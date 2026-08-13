from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema

from research_foundation.phase3_runtime import file_sha256, read_json, read_jsonl
from research_foundation.representation_freeze import canonical_content_sha256, content_sha256


RUNTIME_PATH = "configs/research/phase_3_held_out_runtime_v0_1.json"
RUNTIME_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_held_out_runtime_v0_1.schema.json"

CONDITION_IDS = [
    "base",
    "prompt_only",
    "target_steering",
    "sign_flipped_steering",
    *[f"random_steering_{index:02d}" for index in range(1, 6)],
    *[f"shuffled_steering_{index:02d}" for index in range(1, 6)],
    "qlora",
]


def _validate_bound_evidence(root: Path, runtime: Mapping[str, Any]) -> None:
    evidence = runtime["bound_evidence"]
    for key, relative in evidence.items():
        if not key.endswith("_path"):
            continue
        expected = evidence[key.removesuffix("_path") + "_sha256"]
        if canonical_content_sha256(read_json(root / relative)) != expected:
            raise ValueError(f"held-out runtime evidence hash mismatch: {key}")


def _validate_selected_assets(root: Path, runtime: Mapping[str, Any]) -> None:
    selection = read_json(root / runtime["bound_evidence"]["selection_lock_path"])
    selected = selection["selected_specification"]
    if selected["target_steering_alpha"] != 1.0 or selected["qlora_checkpoint_id"] != "epoch_1":
        raise ValueError("held-out runtime differs from the frozen train/dev selection")
    if selection["quality_gate"]["qlora_passed"]:
        raise ValueError("QLoRA epoch 1 must remain a failed-quality-gate fallback")
    if selection["test_opening_status"] != "locked_not_opened":
        raise ValueError("selection lock no longer records an unopened test")

    direction = runtime["direction_bundle"]
    if file_sha256(root / direction["path"]) != direction["sha256"]:
        raise ValueError("direction bundle hash mismatch")
    if file_sha256(root / direction["metadata_path"]) != direction["metadata_file_sha256"]:
        raise ValueError("direction bundle metadata hash mismatch")
    metadata = read_json(root / direction["metadata_path"])
    if metadata["test_rows_used"] != 0 or metadata["keys"] != sorted(direction["required_vector_keys"]):
        raise ValueError("direction bundle is incomplete or used test rows")

    adapter = runtime["qlora_adapter"]
    summary_path = root / adapter["training_summary_path"]
    if file_sha256(summary_path) != adapter["training_summary_file_sha256"]:
        raise ValueError("QLoRA training summary hash mismatch")
    training = read_json(summary_path)
    epoch = next((item for item in training["epochs"] if item["checkpoint_id"] == "epoch_1"), None)
    if epoch is None or epoch["adapter_path"] != adapter["adapter_path"]:
        raise ValueError("selected QLoRA epoch 1 adapter is missing from the training summary")
    for artifact in epoch["artifact_manifest"]:
        if file_sha256(root / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"QLoRA adapter artifact hash mismatch: {artifact['path']}")


def load_held_out_runtime(root: Path, *, require_unopened: bool = True) -> dict[str, Any]:
    runtime = read_json(root / RUNTIME_PATH)
    jsonschema.validate(runtime, read_json(root / RUNTIME_SCHEMA_PATH))
    _validate_bound_evidence(root, runtime)
    _validate_selected_assets(root, runtime)
    registry = runtime["condition_registry"]
    if registry["condition_ids"] != CONDITION_IDS or registry["expected_output_count"] != 52 * len(CONDITION_IDS):
        raise ValueError("held-out condition registry is not the frozen 15-condition matrix")
    access_log = root / runtime["test_data"]["access_log_path"]
    if require_unopened and access_log.exists():
        raise ValueError("Phase 3 held-out test is no longer unopened")
    return runtime


def prompt_only_user_content(runtime: Mapping[str, Any], user_prompt: str) -> str:
    return f"{runtime['prompt_only']['instruction']}\n\n{user_prompt}"


def validate_access_event(root: Path, runtime: Mapping[str, Any]) -> dict[str, Any]:
    access_log = root / runtime["test_data"]["access_log_path"]
    events = read_jsonl(access_log)
    if len(events) != 1:
        raise ValueError("held-out execution requires exactly one access event")
    event = events[0]
    jsonschema.validate(
        event,
        read_json(root / runtime["test_data"]["access_event_schema_path"]),
        format_checker=jsonschema.FormatChecker(),
    )
    if event["runtime_sha256"] != canonical_content_sha256(dict(runtime)):
        raise ValueError("test access event runtime hash mismatch")
    if event["test_freeze_sha256"] != runtime["bound_evidence"]["test_freeze_sha256"]:
        raise ValueError("test access event freeze hash mismatch")
    if event["selection_lock_sha256"] != runtime["bound_evidence"]["selection_lock_sha256"]:
        raise ValueError("test access event selection-lock hash mismatch")
    notice_path = root / event["notice_path"]
    if canonical_content_sha256(read_json(notice_path)) != event["notice_sha256"]:
        raise ValueError("test access event notice hash mismatch")
    return event


def create_access_event(
    root: Path,
    runtime: Mapping[str, Any],
    *,
    authorization_reference: str,
    opened_at: str | None = None,
) -> dict[str, Any]:
    if not authorization_reference.strip():
        raise ValueError("an explicit user authorization reference is required")
    notice_path = root / runtime["execution_gate"]["held_out_model_gpu_notice_path"]
    if not notice_path.exists():
        raise FileNotFoundError("held-out model/GPU notice must exist before test opening")
    notice = read_json(notice_path)
    runtime_sha = canonical_content_sha256(dict(runtime))
    if notice.get("runtime_path") != RUNTIME_PATH or notice.get("runtime_sha256") != runtime_sha:
        raise ValueError("held-out model/GPU notice does not bind the frozen runtime")
    event = {
        "event_version": "phase_3_test_access_event_v0_1",
        "opened_at": opened_at or datetime.now().astimezone().isoformat(),
        "authorization_reference": authorization_reference.strip(),
        "runtime_sha256": runtime_sha,
        "test_freeze_sha256": runtime["bound_evidence"]["test_freeze_sha256"],
        "selection_lock_sha256": runtime["bound_evidence"]["selection_lock_sha256"],
        "notice_path": runtime["execution_gate"]["held_out_model_gpu_notice_path"],
        "notice_sha256": canonical_content_sha256(notice),
        "model_opening_number": 1,
        "claim_boundary": "This event irreversibly records the single Phase 3 held-out opening. It authorizes no retuning, selective omission, repeat opening, or confirmatory causal claim.",
    }
    jsonschema.validate(
        event,
        read_json(root / runtime["test_data"]["access_event_schema_path"]),
        format_checker=jsonschema.FormatChecker(),
    )
    return event


def write_access_event(
    root: Path,
    runtime: Mapping[str, Any],
    *,
    authorization_reference: str,
    opened_at: str | None = None,
) -> Path:
    event = create_access_event(
        root,
        runtime,
        authorization_reference=authorization_reference,
        opened_at=opened_at,
    )
    path = root / runtime["test_data"]["access_log_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return path


def load_held_out_pairs_after_opening(root: Path, runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_access_event(root, runtime)
    data = runtime["test_data"]
    path = root / data["pair_artifact_path"]
    if file_sha256(path) != data["pair_artifact_sha256"]:
        raise ValueError("held-out pair artifact hash mismatch")
    rows = read_jsonl(path)
    if len(rows) != data["pair_count"]:
        raise ValueError("held-out pair count differs from the frozen runtime")
    families = {row["final_isolation_family_id"] for row in rows}
    if len(families) != data["family_count"]:
        raise ValueError("held-out family count differs from the frozen runtime")
    for row in rows:
        if row.get("pair_contrast") != "valid_single_axis" or content_sha256(row["prompt"]) != row["prompt_sha256"]:
            raise ValueError(f"{row.get('candidate_id', 'unknown')}: invalid frozen held-out pair")
    return rows


def validate_test_outputs(
    records: Sequence[Mapping[str, Any]],
    held_out_rows: Sequence[Mapping[str, Any]],
    condition_ids: Sequence[str] = CONDITION_IDS,
) -> None:
    expected = {row["candidate_id"]: row for row in held_out_rows}
    observed = {candidate_id: set() for candidate_id in expected}
    for record in records:
        candidate_id = record["candidate_id"]
        condition_id = record["condition_id"]
        if candidate_id not in expected or condition_id not in condition_ids:
            raise ValueError("test output contains an unknown candidate or condition")
        if condition_id in observed[candidate_id]:
            raise ValueError(f"duplicate test output: {candidate_id}/{condition_id}")
        if record["final_isolation_family_id"] != expected[candidate_id]["final_isolation_family_id"]:
            raise ValueError("test output family differs from the frozen input")
        if record.get("prompt_sha256") != expected[candidate_id].get("prompt_sha256"):
            raise ValueError("test output prompt differs from the frozen input")
        if not str(record["output_text"]).strip() or content_sha256(record["output_text"]) != record["output_sha256"]:
            raise ValueError("test output is empty or has a hash mismatch")
        observed[candidate_id].add(condition_id)
    required = set(condition_ids)
    if len(records) != len(expected) * len(required) or any(values != required for values in observed.values()):
        raise ValueError("every held-out prompt must contain all 15 frozen conditions")


def build_test_blind_packet(
    records: Sequence[Mapping[str, Any]],
    held_out_rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from research_foundation.phase3_runtime import build_development_blind_packet

    packet, key = build_development_blind_packet(records, held_out_rows, seed=seed)
    for item in packet:
        item["review_item_id"] = item["review_item_id"].replace("p3dev_", "p3test_")
    return packet, key
