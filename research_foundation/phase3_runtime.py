from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

import jsonschema
import numpy as np

from research_foundation.representation_freeze import canonical_content_sha256, content_sha256


RUNTIME_PATH = "configs/research/phase_3_train_dev_runtime_v0_1.json"
RUNTIME_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_train_dev_runtime_v0_1.schema.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_runtime(root: Path) -> dict[str, Any]:
    runtime = read_json(root / RUNTIME_PATH)
    jsonschema.validate(runtime, read_json(root / RUNTIME_SCHEMA_PATH))
    for key, relative in runtime["bound_contracts"].items():
        if key.endswith("_path"):
            expected = runtime["bound_contracts"][key.removesuffix("_path") + "_sha256"]
            if canonical_content_sha256(read_json(root / relative)) != expected:
                raise ValueError(f"bound contract hash mismatch: {key}")
    data = runtime["data"]
    if canonical_content_sha256(read_json(root / data["split_manifest_path"])) != data["split_manifest_sha256"]:
        raise ValueError("split manifest hash mismatch")
    for prefix in ("train", "development"):
        if file_sha256(root / data[f"{prefix}_path"]) != data[f"{prefix}_sha256"]:
            raise ValueError(f"{prefix} local artifact hash mismatch")
    direction = runtime["direction_source"]
    for prefix in ("selection_lock", "activation_metadata", "activation_array"):
        if file_sha256(root / direction[f"{prefix}_path"]) != direction[f"{prefix}_file_sha256"]:
            raise ValueError(f"{prefix} file hash mismatch")
    if data["allowed_splits"] != ["train", "development"] or not data["test_access_forbidden"]:
        raise ValueError("runtime must remain train/development-only")
    return runtime


def validate_train_rows(rows: Sequence[dict[str, Any]], split_manifest: Mapping[str, Any]) -> None:
    train_records = [row for row in split_manifest["records"] if row["split"] == "train"]
    expected_ids = {item for row in train_records for item in row["qlora_eligible_response_ids"]}
    expected_families = {row["final_isolation_family_id"] for row in train_records}
    record_ids = [row["record_id"] for row in rows]
    if len(rows) != 65 or len(set(record_ids)) != len(rows) or set(record_ids) != expected_ids:
        raise ValueError("QLoRA train rows do not exactly cover the frozen 65 response records")
    if {row["final_isolation_family_id"] for row in rows} != expected_families or len(expected_families) != 39:
        raise ValueError("QLoRA train rows do not exactly cover the frozen 39 families")
    for row in rows:
        if row["reviewer_id"] != "researcher_01" or row["pole"] != "boundary-preserving":
            raise ValueError(f"{row['record_id']}: invalid reviewer or target pole")
        if content_sha256(row["prompt"]) != row["prompt_sha256"]:
            raise ValueError(f"{row['record_id']}: prompt hash mismatch")
        if content_sha256(row["response"]) != row["response_sha256"]:
            raise ValueError(f"{row['record_id']}: response hash mismatch")


def validate_development_rows(rows: Sequence[dict[str, Any]], split_manifest: Mapping[str, Any]) -> None:
    dev_records = [row for row in split_manifest["records"] if row["split"] == "development"]
    expected_ids = {item for row in dev_records for item in row["evaluation_eligible_candidate_ids"]}
    expected_families = {row["final_isolation_family_id"] for row in dev_records}
    candidate_ids = [row["candidate_id"] for row in rows]
    if len(rows) != 18 or len(set(candidate_ids)) != len(rows) or set(candidate_ids) != expected_ids:
        raise ValueError("development rows do not exactly cover the frozen 18 paired candidates")
    if {row["final_isolation_family_id"] for row in rows} != expected_families or len(expected_families) != 15:
        raise ValueError("development rows do not exactly cover the frozen 15 families")
    for row in rows:
        if row["reviewer_id"] != "researcher_01" or row["pair_contrast"] != "valid_single_axis":
            raise ValueError(f"{row['candidate_id']}: invalid reviewer or pair contrast")
        if content_sha256(row["prompt"]) != row["prompt_sha256"]:
            raise ValueError(f"{row['candidate_id']}: prompt hash mismatch")
        responses = {item["response_id"]: item for item in row["responses"]}
        annotations = {item["response_id"]: item for item in row["response_annotations"]}
        if set(responses) != {"response_0", "response_1"} or set(responses) != set(annotations):
            raise ValueError(f"{row['candidate_id']}: incomplete paired responses")
        poles = {annotation["pole"] for annotation in annotations.values()}
        if poles != {"boundary-preserving", "over-accommodating"}:
            raise ValueError(f"{row['candidate_id']}: invalid opposite-pole pairing")
        for response_id, response in responses.items():
            if content_sha256(response["text"]) != response["content_sha256"]:
                raise ValueError(f"{row['candidate_id']}:{response_id}: response hash mismatch")


def validate_local_data(root: Path, runtime: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = runtime["data"]
    manifest = read_json(root / data["split_manifest_path"])
    train = read_jsonl(root / data["train_path"])
    development = read_jsonl(root / data["development_path"])
    validate_train_rows(train, manifest)
    validate_development_rows(development, manifest)
    return train, development


def _flat_ids(payload: Any) -> list[int]:
    if isinstance(payload, Mapping):
        payload = payload["input_ids"]
    if hasattr(payload, "tolist"):
        payload = payload.tolist()
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], list):
        payload = payload[0]
    if not isinstance(payload, list) or not payload or any(not isinstance(value, int) for value in payload):
        raise ValueError("tokenizer output must be a non-empty flat integer list")
    return payload


def build_response_only_example(tokenizer: Any, row: Mapping[str, Any], max_sequence_tokens: int) -> dict[str, list[int]]:
    prefix = tokenizer.apply_chat_template(
        [{"role": "user", "content": row["prompt"]}],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    prefix_ids = _flat_ids(prefix)
    response_ids = _flat_ids(tokenizer(row["response"], add_special_tokens=False))
    eos = getattr(tokenizer, "eos_token_id", None)
    if isinstance(eos, int) and (not response_ids or response_ids[-1] != eos):
        response_ids.append(eos)
    input_ids = prefix_ids + response_ids
    if len(input_ids) > max_sequence_tokens:
        raise ValueError(f"{row['record_id']}: {len(input_ids)} tokens exceeds frozen limit; truncation is forbidden")
    labels = [-100] * len(prefix_ids) + response_ids
    if all(label == -100 for label in labels) or any(label != -100 for label in labels[: len(prefix_ids)]):
        raise ValueError("response-only label masking failed")
    return {"input_ids": input_ids, "attention_mask": [1] * len(input_ids), "labels": labels}


def collate_response_only(examples: Sequence[Mapping[str, Sequence[int]]], pad_token_id: int) -> dict[str, list[list[int]]]:
    if not examples:
        raise ValueError("cannot collate an empty batch")
    width = max(len(item["input_ids"]) for item in examples)
    batch = {"input_ids": [], "attention_mask": [], "labels": []}
    for item in examples:
        padding = width - len(item["input_ids"])
        batch["input_ids"].append(list(item["input_ids"]) + [pad_token_id] * padding)
        batch["attention_mask"].append(list(item["attention_mask"]) + [0] * padding)
        batch["labels"].append(list(item["labels"]) + [-100] * padding)
    return batch


def derive_direction_bundle(root: Path, runtime: Mapping[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    source = runtime["direction_source"]
    lock = read_json(root / source["selection_lock_path"])
    metadata = read_json(root / source["activation_metadata_path"])
    selected = lock["selected_specification"]
    if lock["test_opening_status"] != "locked_not_opened" or selected["layer"] != source["layer"] or selected["pooling"] != source["pooling"]:
        raise ValueError("Phase 2 selection lock differs from frozen Phase 3 direction source")
    if metadata["representation_spec"]["layer"] != source["layer"] or metadata["representation_spec"]["pooling"] != source["pooling"]:
        raise ValueError("activation metadata differs from frozen direction specification")
    with np.load(root / source["activation_array_path"]) as payload:
        embeddings = np.asarray(payload["embeddings"], dtype=np.float32)
    records = metadata["records"]
    if embeddings.shape[0] != len(records):
        raise ValueError("activation rows and metadata records differ")
    train_indices = [index for index, row in enumerate(records) if row["split"] == "train"]
    labels = np.asarray([records[index]["pole"] == source["positive_pole"] for index in train_indices], dtype=bool)
    train = embeddings[train_indices]
    if labels.sum() == 0 or labels.sum() == len(labels):
        raise ValueError("train direction requires both poles")

    def normalized_difference(current_labels: np.ndarray) -> np.ndarray:
        vector = train[current_labels].mean(axis=0) - train[~current_labels].mean(axis=0)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 0:
            raise ValueError("direction norm is not positive and finite")
        return (vector / norm).astype(np.float32)

    target = normalized_difference(labels)
    bundle: dict[str, np.ndarray] = {"target": target, "sign_flipped": -target}
    for index, seed in enumerate(source["random_seeds"], start=1):
        rng = np.random.default_rng(seed)
        vector = rng.normal(size=target.shape).astype(np.float32)
        bundle[f"random_{index:02d}"] = vector / np.linalg.norm(vector)
    for index, seed in enumerate(source["shuffled_label_seeds"], start=1):
        shuffled = labels.copy()
        np.random.default_rng(seed).shuffle(shuffled)
        bundle[f"shuffled_{index:02d}"] = normalized_difference(shuffled)
    metadata_out = {
        "artifact_version": "phase_3_direction_bundle_v0_1",
        "source_activation_file_sha256": source["activation_array_file_sha256"],
        "source_selection_lock_file_sha256": source["selection_lock_file_sha256"],
        "train_activation_rows": len(train_indices),
        "dimension": int(target.shape[0]),
        "keys": sorted(bundle),
        "test_rows_used": 0,
        "claim_boundary": "Directions derive from Phase 2 train activations only and do not establish causal steering.",
    }
    return bundle, metadata_out


def write_direction_bundle(root: Path, runtime: Mapping[str, Any]) -> tuple[Path, Path]:
    bundle, metadata = derive_direction_bundle(root, runtime)
    source = runtime["direction_source"]
    output = root / source["output_path"]
    metadata_path = root / source["metadata_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, **bundle)
    metadata["artifact_sha256"] = file_sha256(output)
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, metadata_path


def validate_development_outputs(records: Sequence[Mapping[str, Any]], development_rows: Sequence[Mapping[str, Any]], condition_ids: Sequence[str]) -> None:
    expected_prompts = {row["candidate_id"]: row for row in development_rows}
    observed: dict[str, set[str]] = {candidate_id: set() for candidate_id in expected_prompts}
    for record in records:
        candidate_id = record["candidate_id"]
        condition_id = record["condition_id"]
        if candidate_id not in observed or condition_id not in condition_ids:
            raise ValueError("development output contains an unknown candidate or condition")
        if condition_id in observed[candidate_id]:
            raise ValueError(f"duplicate condition output: {candidate_id}/{condition_id}")
        if record["final_isolation_family_id"] != expected_prompts[candidate_id]["final_isolation_family_id"]:
            raise ValueError("development output family differs from frozen input")
        if not isinstance(record["output_text"], str) or not record["output_text"].strip():
            raise ValueError("empty development output is forbidden")
        if content_sha256(record["output_text"]) != record["output_sha256"]:
            raise ValueError("development output hash mismatch")
        observed[candidate_id].add(condition_id)
    expected_conditions = set(condition_ids)
    if any(values != expected_conditions for values in observed.values()):
        raise ValueError("every development prompt must contain every preselection condition")


def build_development_blind_packet(records: Sequence[Mapping[str, Any]], development_rows: Sequence[Mapping[str, Any]], *, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_candidate: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        by_candidate.setdefault(record["candidate_id"], []).append(record)
    row_index = {row["candidate_id"]: row for row in development_rows}
    rng = random.Random(seed)
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    for candidate_id in sorted(row_index):
        outputs = []
        for record in sorted(by_candidate[candidate_id], key=lambda item: item["condition_id"]):
            blind_id = f"p3bo_{rng.getrandbits(64):016x}"
            outputs.append({"blind_output_id": blind_id, "output_text": record["output_text"]})
            key.append({
                "blind_output_id": blind_id,
                "candidate_id": candidate_id,
                "condition_id": record["condition_id"],
                "output_sha256": record["output_sha256"],
            })
        rng.shuffle(outputs)
        source = row_index[candidate_id]
        packet.append({
            "review_item_id": f"p3dev_{sha256(candidate_id.encode()).hexdigest()[:16]}",
            "candidate_id": candidate_id,
            "final_isolation_family_id": source["final_isolation_family_id"],
            "axis_id": "boundary-preserving-over-accommodating",
            "user_prompt": source["prompt"],
            "blind_outputs": outputs,
            "reviewer_id": "researcher_01",
        })
    return packet, key
