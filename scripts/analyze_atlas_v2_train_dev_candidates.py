from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_adapter import (  # noqa: E402
    ANALYSIS_PLAN_PATH,
    DATASET_MANIFEST_PATH,
    RUNTIME_CONFIG_PATH,
    build_train_dev_evidence,
    load_activation_artifact,
    read_json,
    file_sha256,
)
from research_foundation.representation_freeze import canonical_content_sha256  # noqa: E402


OUTPUT = ROOT / (
    "results/local_artifacts/research_foundation/atlas_v2/"
    "train_dev_candidate_results_v0_1.json"
)
TRACKED_SUMMARY = ROOT / "results/summaries/atlas_v2_train_dev_candidate_summary_v0_1.json"


def main() -> int:
    runtime = read_json(ROOT / RUNTIME_CONFIG_PATH)
    artifact_root = ROOT / runtime["artifact_policy"]["root"]
    candidates = []
    missing = []
    for layer in runtime["candidate_specifications"]["layers"]:
        for pooling in runtime["candidate_specifications"]["pooling"]:
            metadata_path = artifact_root / f"train_dev_layer_{layer}_{pooling}.metadata.json"
            if not metadata_path.is_file():
                missing.append(metadata_path.relative_to(ROOT).as_posix())
                continue
            artifact = load_activation_artifact(
                ROOT, metadata_path, allowed_splits={"train", "dev"}
            )
            evidence = build_train_dev_evidence(
                artifact,
                seed=20260804,
                random_direction_count=20,
                shuffled_direction_count=20,
                random_label_draws=20,
                bootstrap_iterations=5000,
                permutation_iterations=10000,
            )
            candidates.append(
                {
                    "candidate_id": f"layer_{layer}::{pooling}",
                    "activation_metadata_path": metadata_path.relative_to(ROOT).as_posix(),
                    "activation_metadata_sha256": canonical_content_sha256(artifact.metadata),
                    "evidence": evidence,
                }
            )
    if missing:
        raise ValueError(f"candidate activation artifacts are missing: {missing}")
    expected_count = len(runtime["candidate_specifications"]["layers"]) * len(
        runtime["candidate_specifications"]["pooling"]
    )
    if len(candidates) != expected_count:
        raise ValueError("candidate result count differs from frozen runtime grid")
    payload = {
        "result_version": "atlas_v2_train_dev_candidate_results_v0_1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_config_path": RUNTIME_CONFIG_PATH,
        "runtime_config_sha256": canonical_content_sha256(runtime),
        "selection_source_splits": ["train", "dev"],
        "candidate_count": len(candidates),
        "all_candidates_reported": True,
        "candidates": candidates,
        "selection_status": "blocked_pending_external_controls",
        "missing_controls": [
            "surface_style_direction",
            "unrelated_trait_direction",
            "orthogonalized_target_direction",
        ],
        "test_opened": False,
        "claim_boundary": (
            "All frozen train/dev candidates are reported. No specification is selected until "
            "the external control artifacts are defined and evaluated. These results are not "
            "held-out test evidence or causal steering evidence."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tracked_candidates = []
    for candidate in candidates:
        evidence = candidate["evidence"]
        analysis = evidence["dev_analysis"]
        tracked_candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "activation_metadata_sha256": candidate["activation_metadata_sha256"],
                "direction_equivalence_cosine": evidence["direction_equivalence_cosine"],
                "dev_effect_size": analysis["effect_size"],
                "dev_effect_size_ci": analysis["effect_size_ci"],
                "dev_auroc": analysis["auroc"],
                "dev_balanced_accuracy": analysis["balanced_accuracy"],
                "dev_pairwise_accuracy": analysis["pairwise_accuracy"],
                "permutation": analysis["permutation"],
                "null_comparisons": evidence["null_comparisons"],
                "probe_selectivity": evidence["probes"]["random_label_selectivity"]["selectivity"],
            }
        )
    tracked_summary = {
        "summary_version": "atlas_v2_train_dev_candidate_summary_v0_1",
        "created_at": payload["created_at"],
        "model": {
            "model_id": runtime["model"]["model_id"],
            "revision": runtime["model"]["revision"],
            "dtype": runtime["model"]["load_dtype"],
            "quantization": runtime["model"]["quantization"],
        },
        "runtime_config_sha256": payload["runtime_config_sha256"],
        "dataset_manifest_sha256": canonical_content_sha256(
            read_json(ROOT / DATASET_MANIFEST_PATH)
        ),
        "analysis_plan_sha256": canonical_content_sha256(
            read_json(ROOT / ANALYSIS_PLAN_PATH)
        ),
        "local_detailed_results_sha256": file_sha256(OUTPUT),
        "selection_source_splits": ["train", "dev"],
        "sample_counts": {"train": 22, "dev": 16},
        "candidate_count": len(tracked_candidates),
        "all_candidates_reported": True,
        "candidates": tracked_candidates,
        "selection_status": payload["selection_status"],
        "missing_controls": payload["missing_controls"],
        "test_opened": False,
        "limitations": [
            "Dev contains only eight pairs and too few independent family clusters for a low-resolution permutation test.",
            "The minimum observed exact cluster sign-flip p-value is 0.5 for this dev family structure.",
            "Surface-style, unrelated-trait, and nuisance-orthogonalized controls are not yet available.",
            "Quantized runtime is an execution constraint and not a methodological contribution.",
        ],
        "claim_boundary": payload["claim_boundary"],
    }
    TRACKED_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    TRACKED_SUMMARY.write_text(
        json.dumps(tracked_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "status": payload["selection_status"],
        "candidate_count": len(candidates),
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "tracked_summary": TRACKED_SUMMARY.relative_to(ROOT).as_posix(),
        "test_opened": False,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "dev_auroc": candidate["evidence"]["dev_analysis"]["auroc"],
                "dev_balanced_accuracy": candidate["evidence"]["dev_analysis"]["balanced_accuracy"],
                "effect_size": candidate["evidence"]["dev_analysis"]["effect_size"],
                "permutation_p": candidate["evidence"]["dev_analysis"]["permutation"]["p_value"],
                "probe_selectivity_balanced_accuracy_delta": candidate["evidence"]["probes"]["random_label_selectivity"]["selectivity"]["balanced_accuracy_delta"],
            }
            for candidate in candidates
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
