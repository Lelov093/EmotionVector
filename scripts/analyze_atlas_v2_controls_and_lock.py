from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_adapter import (  # noqa: E402
    REQUIRED_CONTROL_IDS,
    create_selection_lock,
    file_sha256,
    load_activation_artifact,
    read_json,
    split_embeddings,
)
from research_foundation.atlas_v2_controls import (  # noqa: E402
    CONTROL_PLAN_PATH,
    continuous_feature_direction,
    control_array_key,
    load_control_artifact,
    load_control_plan,
)
from research_foundation.representation_freeze import canonical_content_sha256  # noqa: E402
from research_foundation.representation_statistics import (  # noqa: E402
    difference_of_means_direction,
    evaluate_named_directions,
    orthogonalize_direction,
)


DETAIL_RESULTS = ROOT / (
    "results/local_artifacts/research_foundation/atlas_v2/"
    "train_dev_candidate_results_v0_1.json"
)
CONTROL_METADATA = ROOT / (
    "results/local_artifacts/research_foundation/atlas_v2/controls/"
    "control_artifact_v0_1.metadata.json"
)
CONTROL_RESULTS = ROOT / (
    "results/local_artifacts/research_foundation/atlas_v2/controls/"
    "control_results_v0_1.json"
)
SELECTION_LOCK = ROOT / (
    "results/local_artifacts/research_foundation/atlas_v2/selection_lock_v0_1.json"
)
TRACKED_SUMMARY = ROOT / "results/summaries/atlas_v2_control_selection_summary_v0_1.json"


def symmetric_auroc(value: float) -> float:
    return max(value, 1.0 - value)


def main() -> int:
    plan = load_control_plan(ROOT)
    selected = plan["preliminary_selection"]
    layer, pooling = selected["layer"], selected["pooling"]
    metadata_path = ROOT / (
        f"results/local_artifacts/research_foundation/atlas_v2/"
        f"train_dev_layer_{layer}_{pooling}.metadata.json"
    )
    target_artifact = load_activation_artifact(
        ROOT, metadata_path, allowed_splits={"train", "dev"}
    )
    control_metadata, control_matrices, token_counts = load_control_artifact(
        ROOT, CONTROL_METADATA
    )
    train_x, train_y, train_ids = split_embeddings(target_artifact, "train")
    dev_x, dev_y, _ = split_embeddings(target_artifact, "dev")
    target_direction = difference_of_means_direction(train_x, train_y.tolist())
    surface_direction = continuous_feature_direction(
        train_x, [token_counts[sample_id] for sample_id in train_ids]
    )
    control_records = sorted(control_metadata["records"], key=lambda item: item["row_index"])
    unrelated_x = control_matrices[control_array_key(layer, pooling)]
    unrelated_y = [1 if item["role"] == "positive" else 0 for item in control_records]
    unrelated_direction = difference_of_means_direction(unrelated_x, unrelated_y)
    orthogonal_direction = orthogonalize_direction(target_direction, surface_direction)
    metrics = evaluate_named_directions(
        dev_x,
        dev_y.tolist(),
        {
            "target_direction": target_direction,
            "surface_style_direction": surface_direction,
            "unrelated_trait_direction": unrelated_direction,
            "orthogonalized_target_direction": orthogonal_direction,
        },
    )
    target_auroc = metrics["target_direction"]["auroc"]
    margin = plan["veto_policy"]["control_auroc_margin"]
    maximum_drop = plan["veto_policy"]["maximum_orthogonalized_auroc_drop"]
    surface_symmetric = symmetric_auroc(metrics["surface_style_direction"]["auroc"])
    unrelated_symmetric = symmetric_auroc(metrics["unrelated_trait_direction"]["auroc"])
    orthogonal_drop = target_auroc - metrics["orthogonalized_target_direction"]["auroc"]
    checks = {
        "surface_below_target_margin": surface_symmetric < target_auroc - margin,
        "unrelated_below_target_margin": unrelated_symmetric < target_auroc - margin,
        "orthogonalized_auroc_drop_within_limit": orthogonal_drop <= maximum_drop,
    }
    gate_status = "pass" if all(checks.values()) else "veto"
    created_at = datetime.now(timezone.utc).isoformat()
    control_payload = {
        "result_version": "atlas_v2_control_results_v0_1",
        "created_at": created_at,
        "control_plan_path": CONTROL_PLAN_PATH,
        "control_plan_sha256": canonical_content_sha256(plan),
        "selected_candidate": {"layer": layer, "pooling": pooling},
        "metrics": metrics,
        "symmetric_control_auroc": {
            "surface_style_direction": surface_symmetric,
            "unrelated_trait_direction": unrelated_symmetric,
        },
        "target_surface_cosine": float(np.dot(target_direction, surface_direction)),
        "target_unrelated_cosine": float(np.dot(target_direction, unrelated_direction)),
        "orthogonalized_auroc_drop": orthogonal_drop,
        "veto_checks": checks,
        "control_gate_status": gate_status,
        "test_opened": False,
        "claim_boundary": (
            "Controls are a conservative post-target-metrics pre-test veto. Passing does not "
            "validate the legacy unrelated Trait axis or establish causal steering."
        ),
    }
    CONTROL_RESULTS.write_text(
        json.dumps(control_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lock = None
    if gate_status == "pass":
        detail = read_json(DETAIL_RESULTS)
        selected_detail = next(
            item
            for item in detail["candidates"]
            if item["candidate_id"] == f"layer_{layer}::{pooling}"
        )
        lock = create_selection_lock(
            ROOT,
            target_artifact,
            activation_metadata_relative_path=metadata_path.relative_to(ROOT).as_posix(),
            candidate_results_sha256=file_sha256(DETAIL_RESULTS),
            control_plan_path=CONTROL_PLAN_PATH,
            control_plan_sha256=canonical_content_sha256(plan),
            control_results_path=CONTROL_RESULTS.relative_to(ROOT).as_posix(),
            control_results_sha256=file_sha256(CONTROL_RESULTS),
            selected_threshold=selected_detail["evidence"]["threshold"],
            probe_regularization_c=1.0,
            completed_control_ids=REQUIRED_CONTROL_IDS,
            locked_at=created_at,
        )
        SELECTION_LOCK.write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    tracked = {
        "summary_version": "atlas_v2_control_selection_summary_v0_1",
        "created_at": created_at,
        "selected_candidate": control_payload["selected_candidate"],
        "control_gate_status": gate_status,
        "metrics": metrics,
        "symmetric_control_auroc": control_payload["symmetric_control_auroc"],
        "orthogonalized_auroc_drop": orthogonal_drop,
        "veto_checks": checks,
        "control_plan_sha256": control_payload["control_plan_sha256"],
        "local_control_results_sha256": file_sha256(CONTROL_RESULTS),
        "selection_lock_created": lock is not None,
        "selection_lock_sha256": canonical_content_sha256(lock) if lock else None,
        "test_opened": False,
        "limitations": [
            "The control plan was frozen after target train/dev metrics were observed.",
            "The legacy calm-agitated source is template-dominated and is only a confound stress-test.",
            "Passing controls does not resolve the two-cluster permutation-resolution limit.",
        ],
        "claim_boundary": control_payload["claim_boundary"],
    }
    TRACKED_SUMMARY.write_text(
        json.dumps(tracked, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(tracked, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
