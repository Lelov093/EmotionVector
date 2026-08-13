from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_adapter import (  # noqa: E402
    file_sha256,
    load_activation_artifact,
    projection_pairs_for_split,
    read_json,
    split_embeddings,
    validate_schema,
)
from research_foundation.atlas_v2_controls import (  # noqa: E402
    continuous_feature_direction,
    control_array_key,
    load_control_artifact,
)
from research_foundation.atlas_v2_extraction import load_test_runtime_config  # noqa: E402
from research_foundation.representation_freeze import canonical_content_sha256  # noqa: E402
from research_foundation.representation_statistics import (  # noqa: E402
    analyze_projection_pairs,
    difference_of_means_direction,
    empirical_null_comparison,
    evaluate_named_directions,
    fit_linear_probe,
    orthogonalize_direction,
    random_isotropic_directions,
    random_label_probe_selectivity,
    shuffled_label_directions,
    sign_flipped_direction,
)


LOCK_PATH = ROOT / "results/local_artifacts/research_foundation/atlas_v2/selection_lock_v0_1.json"
ACCESS_LOG = ROOT / "results/local_artifacts/research_foundation/representation_test_access_log_v0_1.jsonl"
CONTROL_METADATA = ROOT / "results/local_artifacts/research_foundation/atlas_v2/controls/control_artifact_v0_1.metadata.json"
RESULT_PATH = ROOT / "results/summaries/atlas_v2_frozen_test_result_v0_1.json"
RESULT_SCHEMA = ROOT / "data/research_foundation/schemas/representation_atlas_v2_result.schema.json"


def main() -> int:
    runtime = load_test_runtime_config(ROOT)
    lock = read_json(LOCK_PATH)
    events = [json.loads(line) for line in ACCESS_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(events) != 1:
        raise ValueError("frozen test analysis requires exactly one access event")
    event = events[0]
    if event["selection_lock_sha256"] != canonical_content_sha256(lock):
        raise ValueError("access event does not bind the current selection lock")
    spec = lock["selected_specification"]
    frozen_spec = runtime["representation_specification"]
    if (spec["layer"], spec["pooling"]) != (frozen_spec["layer"], frozen_spec["pooling"]):
        raise ValueError("selection lock and frozen test runtime differ")

    train_artifact = load_activation_artifact(
        ROOT, ROOT / lock["activation_metadata_path"], allowed_splits={"train", "dev"}
    )
    test_artifact = load_activation_artifact(
        ROOT,
        ROOT / runtime["artifact_policy"]["metadata_path"],
        allowed_splits={"test"},
        test_access_event=event,
    )
    train_x, train_y, train_ids = split_embeddings(train_artifact, "train")
    test_x, test_y, _ = split_embeddings(test_artifact, "test")
    target_direction = difference_of_means_direction(train_x, train_y.tolist())
    pairs = projection_pairs_for_split(test_artifact, target_direction, "test")
    analysis = analyze_projection_pairs(
        pairs,
        threshold=spec["threshold"],
        bootstrap_iterations=runtime["analysis"]["bootstrap_iterations"],
        permutation_iterations=runtime["analysis"]["permutation_iterations"],
        seed=runtime["analysis"]["seed"],
    )

    control_metadata, control_matrices, token_counts = load_control_artifact(ROOT, CONTROL_METADATA)
    surface_direction = continuous_feature_direction(
        train_x, [token_counts[sample_id] for sample_id in train_ids]
    )
    control_rows = sorted(control_metadata["records"], key=lambda item: item["row_index"])
    unrelated_x = control_matrices[control_array_key(spec["layer"], spec["pooling"])]
    unrelated_y = [1 if item["role"] == "positive" else 0 for item in control_rows]
    unrelated_direction = difference_of_means_direction(unrelated_x, unrelated_y)
    named_controls = evaluate_named_directions(
        test_x,
        test_y.tolist(),
        {
            "sign_flipped_target_direction": sign_flipped_direction(target_direction),
            "surface_style_direction": surface_direction,
            "unrelated_trait_direction": unrelated_direction,
            "orthogonalized_target_direction": orthogonalize_direction(target_direction, surface_direction),
        },
    )

    seed = runtime["analysis"]["seed"]
    random_dirs = random_isotropic_directions(test_x.shape[1], 20, seed=seed + 1)
    shuffled_dirs = shuffled_label_directions(train_x, train_y.tolist(), count=20, seed=seed + 2)
    random_metrics = [evaluate_named_directions(test_x, test_y.tolist(), {"null": direction})["null"] for direction in random_dirs]
    shuffled_metrics = [evaluate_named_directions(test_x, test_y.tolist(), {"null": direction})["null"] for direction in shuffled_dirs]
    nulls = [
        {
            "control_id": "random_isotropic_direction",
            "draw_count": 20,
            "auroc_values": [item["auroc"] for item in random_metrics],
            "comparison": empirical_null_comparison(analysis["auroc"], [item["auroc"] for item in random_metrics]),
        },
        {
            "control_id": "shuffled_label_direction",
            "draw_count": 20,
            "auroc_values": [item["auroc"] for item in shuffled_metrics],
            "comparison": empirical_null_comparison(analysis["auroc"], [item["auroc"] for item in shuffled_metrics]),
        },
    ]
    probes = [
        fit_linear_probe(train_x, train_y.tolist(), test_x, test_y.tolist(), probe_id="l2_logistic_regression", regularization_c=spec["probe_regularization_c"], seed=seed + 3),
        fit_linear_probe(train_x, train_y.tolist(), test_x, test_y.tolist(), probe_id="linear_svm", regularization_c=spec["probe_regularization_c"], seed=seed + 4),
        random_label_probe_selectivity(train_x, train_y.tolist(), test_x, test_y.tolist(), probe_id="l2_logistic_regression", regularization_c=spec["probe_regularization_c"], draws=20, seed=seed + 5),
    ]
    axis_result = {
        "axis_id": "boundary-preserving-over-accommodating",
        "split": "test",
        "pair_count": len(pairs),
        "effect_size": analysis["effect_size"],
        "effect_size_ci": analysis["effect_size_ci"],
        "auroc": analysis["auroc"],
        "balanced_accuracy": analysis["balanced_accuracy"],
        "pairwise_accuracy": analysis["pairwise_accuracy"],
        "permutation": analysis["permutation"],
        "paired_bootstrap": analysis["paired_bootstrap"],
        "null_distributions": nulls,
        "controls": [{"control_id": key, **value} for key, value in named_controls.items()],
        "probes": probes,
        "status": "exploratory",
        "limitations": [
            "The frozen test contains only seven pairs and is a pilot, not confirmatory-scale evidence.",
            "Family-cluster permutation resolution is limited by the small number of independent clusters.",
            "The unrelated direction is a template-dominated legacy confound stress-test only.",
            "The control plan was frozen after target train/dev metrics were observed.",
        ],
    }
    result = {
        "schema_version": "representation_atlas_v2_result_v0_1",
        "analysis_plan_version": "representation_atlas_v2_analysis_plan_v0_1",
        "dataset_manifest_sha256": event["dataset_manifest_sha256"],
        "model": event["model"],
        "selection": {
            "selected_layer": spec["layer"],
            "selected_pooling": spec["pooling"],
            "selected_threshold": spec["threshold"],
            "selection_splits": ["train", "dev"],
            "locked_before_test": True,
        },
        "axis_results": [axis_result],
        "test_access": {
            "opened_at": event["opened_at"],
            "opening_reason": event["opening_reason"],
            "access_log_sha256": file_sha256(ACCESS_LOG),
        },
        "negative_results_retained": True,
        "evidence_type": "representation_evidence_only",
        "claim_boundary": (
            "Single-axis held-out pilot representation evidence only. The sample size forbids a "
            "confirmatory claim, and no intervention was performed, so causal steering is untested."
        ),
    }
    validate_schema(result, RESULT_SCHEMA)
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": axis_result["status"],
        "pair_count": axis_result["pair_count"],
        "effect_size": axis_result["effect_size"],
        "effect_size_ci": axis_result["effect_size_ci"],
        "auroc": axis_result["auroc"],
        "balanced_accuracy": axis_result["balanced_accuracy"],
        "pairwise_accuracy": axis_result["pairwise_accuracy"],
        "permutation": axis_result["permutation"],
        "null_comparisons": {item["control_id"]: item["comparison"] for item in nulls},
        "controls": named_controls,
        "probes": probes,
        "result_path": RESULT_PATH.relative_to(ROOT).as_posix(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
