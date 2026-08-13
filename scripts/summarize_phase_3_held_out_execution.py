from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_test_runtime import (
    RUNTIME_PATH,
    load_held_out_pairs_after_opening,
    load_held_out_runtime,
    validate_test_outputs,
)
from research_foundation.phase3_runtime import read_jsonl
from research_foundation.representation_freeze import canonical_content_sha256


OUTPUT = "results/summaries/phase_3_held_out_execution_v0_1.json"
SCHEMA = "data/research_foundation/schemas/phase_3_held_out_execution_v0_1.schema.json"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": file_sha256(path), "tracked": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize completed Phase 3 held-out generation without scoring outputs.")
    parser.add_argument("--initial-timeout-recovery", action="store_true")
    args = parser.parse_args()
    runtime = load_held_out_runtime(ROOT, require_unopened=False)
    held_out = load_held_out_pairs_after_opening(ROOT, runtime)
    paths = {name: ROOT / runtime["artifacts"][key] for name, key in (
        ("candidate_outputs", "candidate_outputs_path"),
        ("blind_packet", "blind_packet_path"),
    )}
    paths["access_log"] = ROOT / runtime["test_data"]["access_log_path"]
    outputs = read_jsonl(paths["candidate_outputs"])
    packet = read_jsonl(paths["blind_packet"])
    validate_test_outputs(outputs, held_out, runtime["condition_registry"]["condition_ids"])
    condition_counts = Counter(row["condition_id"] for row in outputs)
    by_candidate: dict[str, dict[str, str]] = defaultdict(dict)
    for row in outputs:
        by_candidate[row["candidate_id"]][row["condition_id"]] = row["output_sha256"]
    candidates_with_duplicates = sum(len(set(values.values())) < len(values) for values in by_candidate.values())
    exact = {
        "base_vs_target": sum(values["base"] == values["target_steering"] for values in by_candidate.values()),
        "target_vs_sign_flipped": sum(values["target_steering"] == values["sign_flipped_steering"] for values in by_candidate.values()),
        "base_vs_prompt_only": sum(values["base"] == values["prompt_only"] for values in by_candidate.values()),
        "base_vs_qlora": sum(values["base"] == values["qlora"] for values in by_candidate.values()),
    }
    packet_ids = {output["blind_output_id"] for item in packet for output in item["blind_outputs"]}
    if len(packet) != 52 or len(packet_ids) != 780:
        raise ValueError("held-out blind packet coverage mismatch")
    if set(packet[0]) != {"review_item_id", "candidate_id", "final_isolation_family_id", "axis_id", "user_prompt", "blind_outputs", "reviewer_id"}:
        raise ValueError("held-out reviewer packet fields differ from the frozen blind contract")
    if any(set(output) != {"blind_output_id", "output_text"} for item in packet for output in item["blind_outputs"]):
        raise ValueError("held-out reviewer output fields leak condition metadata")
    access_events = read_jsonl(paths["access_log"])
    if len(access_events) != 1:
        raise ValueError("held-out execution must retain exactly one access event")
    generated_times = sorted(row["generated_at"] for row in outputs)
    summary = {
        "summary_version": "phase_3_held_out_execution_v0_1",
        "status": "held_out_candidates_complete_blinding_deviation_pending_user_decision",
        "runtime": {"path": RUNTIME_PATH, "sha256": canonical_content_sha256(runtime)},
        "access": {"event_count": 1, "model_opening_number": access_events[0]["model_opening_number"], "event_created_before_pair_read": True},
        "execution": {
            "environment": ".venv/Scripts/python.exe",
            "model_or_gpu_run": True,
            "training_run": False,
            "external_llm_or_judge_run": False,
            "generation_seconds_sum": sum(float(row["generation_seconds"]) for row in outputs),
            "first_output_completed_at": generated_times[0],
            "last_output_completed_at": generated_times[-1],
            "operational_recovery": {
                "initial_launch_timed_out_before_any_output_artifact": args.initial_timeout_recovery,
                "continued_under_same_access_event": args.initial_timeout_recovery,
                "runtime_or_condition_change": False,
            },
        },
        "artifacts": {name: artifact(path) for name, path in paths.items()},
        "generation": {
            "held_out_families": 40,
            "held_out_pairs": 52,
            "condition_count": 15,
            "condition_outputs": len(outputs),
            "condition_counts": dict(sorted(condition_counts.items())),
            "unique_output_hashes": len({row["output_sha256"] for row in outputs}),
            "candidates_with_any_exact_cross_condition_match": candidates_with_duplicates,
            "selected_exact_match_diagnostics": exact,
            "automatic_quality_or_trait_scores_computed": False,
        },
        "blind_review": {
            "packet_items": len(packet),
            "blind_outputs": len(packet_ids),
            "unique_blind_ids": len(packet_ids),
            "condition_identity_fields_present": False,
            "human_annotations_completed": 0,
            "restricted_condition_key_was_programmatically_read_before_rating_freeze": True,
            "per_item_condition_mapping_exposed_to_human_reviewer": False,
            "condition_level_exact_match_diagnostics_disclosed_before_rating_freeze": True,
            "strict_pre_rating_nonaccess_claim_available": False,
            "restricted_condition_key_artifact_exists": (ROOT / runtime["artifacts"]["condition_key_path"]).exists(),
        },
        "test_boundary": {
            "test_openings": 1,
            "all_conditions_complete_before_packet": True,
            "test_retuning_or_selective_rerun": False,
            "qlora_epoch_1_remains_failed_quality_gate_fallback": True,
        },
        "claim_boundary": "The single held-out opening generated a complete 15-condition packet, but post-generation automation accessed the restricted key and disclosed aggregate condition-level exact-match diagnostics before human rating freeze. Per-item mappings were not disclosed and outputs remain unscored, but strict preregistered pre-rating nonaccess cannot be claimed; user direction is required before evaluation continues.",
    }
    jsonschema.validate(summary, json.loads((ROOT / SCHEMA).read_text(encoding="utf-8")))
    output = ROOT / OUTPUT
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "outputs": len(outputs), "blind_outputs": len(packet_ids), "test_openings": 1}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
