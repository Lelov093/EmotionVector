from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import (
    RUNTIME_PATH,
    file_sha256,
    load_runtime,
    read_jsonl,
    validate_development_outputs,
    validate_local_data,
)
from research_foundation.representation_freeze import canonical_content_sha256


OUTPUT = "results/summaries/phase_3_train_dev_execution_v0_1.json"
SCHEMA = "data/research_foundation/schemas/phase_3_train_dev_execution_v0_1.schema.json"
NOTICE = "results/summaries/phase_3_model_gpu_execution_notice_v0_1.json"


def artifact(root: Path, relative: str) -> dict:
    path = root / relative
    return {"path": relative, "sha256": file_sha256(path), "bytes": path.stat().st_size, "tracked": False}


def main() -> int:
    runtime = load_runtime(ROOT)
    _, development = validate_local_data(ROOT, runtime)
    generation = runtime["development_generation"]
    outputs = read_jsonl(ROOT / generation["output_path"])
    packet = read_jsonl(ROOT / generation["blind_packet_path"])
    key = read_jsonl(ROOT / generation["condition_key_path"])
    validate_development_outputs(outputs, development, generation["candidate_condition_ids"])
    training = json.loads((ROOT / runtime["qlora"]["training_summary_path"]).read_text(encoding="utf-8"))
    notice = json.loads((ROOT / NOTICE).read_text(encoding="utf-8"))

    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in outputs:
        grouped[(row["candidate_id"], row["output_sha256"])].append(row["condition_id"])
    exact_pairs: Counter[tuple[str, str]] = Counter()
    duplicate_groups = 0
    affected_prompts: set[str] = set()
    for (candidate_id, _), conditions in grouped.items():
        if len(conditions) < 2:
            continue
        duplicate_groups += 1
        affected_prompts.add(candidate_id)
        ordered = sorted(conditions)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                exact_pairs[(left, right)] += 1
    condition_counts = Counter(row["condition_id"] for row in outputs)
    artifacts = {
        "training_summary": artifact(ROOT, runtime["qlora"]["training_summary_path"]),
        "direction_bundle": artifact(ROOT, runtime["direction_source"]["output_path"]),
        "direction_metadata": artifact(ROOT, runtime["direction_source"]["metadata_path"]),
        "development_outputs": artifact(ROOT, generation["output_path"]),
        "blind_packet": artifact(ROOT, generation["blind_packet_path"]),
        "restricted_condition_key": artifact(ROOT, generation["condition_key_path"]),
    }
    test_log = ROOT / "results/local_artifacts/research_foundation/phase_3/phase_3_test_access_log_v0_1.jsonl"
    summary = {
        "summary_version": "phase_3_train_dev_execution_v0_1",
        "status": "train_and_development_candidates_complete_pending_condition_blind_human_review",
        "runtime": {"path": RUNTIME_PATH, "sha256": canonical_content_sha256(runtime)},
        "notice": {"path": NOTICE, "sha256": canonical_content_sha256(notice), "notified_at": notice["notified_at"]},
        "training": {
            "train_rows": training["train_rows"],
            "train_families": training["train_families"],
            "checkpoint_ids": [item["checkpoint_id"] for item in training["epochs"]],
            "mean_loss_by_checkpoint": {item["checkpoint_id"]: item["mean_loss"] for item in training["epochs"]},
            "elapsed_seconds": training["elapsed_seconds"],
            "peak_allocated_bytes": training["cuda"]["peak_allocated_bytes"],
            "peak_reserved_bytes": training["cuda"]["peak_reserved_bytes"],
            "quality_selected": False,
        },
        "development_generation": {
            "development_pairs": len(development),
            "development_families": len({row["final_isolation_family_id"] for row in development}),
            "condition_outputs": len(outputs),
            "condition_counts": dict(sorted(condition_counts.items())),
            "unique_output_hashes": len({row["output_sha256"] for row in outputs}),
            "exact_duplicate_groups": duplicate_groups,
            "prompts_with_cross_condition_exact_match": len(affected_prompts),
            "cross_condition_exact_match_counts": {f"{left}|{right}": count for (left, right), count in sorted(exact_pairs.items())},
            "automatic_quality_or_trait_scores_computed": False,
        },
        "blind_review": {
            "packet_items": len(packet),
            "blind_outputs": len(key),
            "unique_blind_ids": len({row["blind_output_id"] for row in key}),
            "human_annotations_completed": 0,
            "condition_key_tracked": False,
        },
        "test_boundary": {
            "held_out_test_access_log_exists": test_log.exists(),
            "held_out_test_model_openings": 0,
            "phase_2_opened_test_reused": False,
        },
        "artifacts": artifacts,
        "claim_boundary": "QLoRA training and development candidate generation completed as bounded pipeline evidence. No checkpoint or alpha is selected, human outcome evidence is pending, test remains unopened, and causal or superiority claims are unsupported.",
    }
    jsonschema.validate(summary, json.loads((ROOT / SCHEMA).read_text(encoding="utf-8")))
    (ROOT / OUTPUT).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "outputs": len(outputs), "human_annotations": 0, "test_openings": 0, "output": OUTPUT}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
