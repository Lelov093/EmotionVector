from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
import numpy as np

from research_foundation.phase3_runtime import file_sha256, read_json, read_jsonl
from research_foundation.representation_freeze import canonical_content_sha256


RUNTIME = "configs/research/phase_3_held_out_runtime_v0_1.json"
REVIEW_FREEZE = "data/research_foundation/manifests/phase_3_held_out_blind_review_freeze_v0_3.json"
ANALYSIS_CONTRACT = "configs/research/phase_3_held_out_analysis_contract_v0_1.json"
ANALYSIS_CONTRACT_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_analysis_contract_v0_1.schema.json"
RESULT_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_results_v0_1.schema.json"
RESULT_SUMMARY = "results/summaries/phase_3_held_out_results_v0_1.json"


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _family_deltas(rows: Sequence[Mapping[str, Any]], metric: str) -> np.ndarray:
    families: dict[str, list[float]] = {}
    for row in rows:
        families.setdefault(str(row["final_isolation_family_id"]), []).append(float(row[metric]))
    return np.asarray([np.mean(families[key]) for key in sorted(families)], dtype=float)


def _bootstrap_ci(values: np.ndarray, iterations: int, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(iterations, len(values)), replace=True).mean(axis=1)
    low, high = np.quantile(samples, [0.025, 0.975])
    return [float(low), float(high)]


def _permutation_p(values: np.ndarray, iterations: int, seed: int) -> float:
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.asarray([-1.0, 1.0]), size=(iterations, len(values)))
    null = np.abs((signs * values).mean(axis=1))
    observed = abs(float(values.mean()))
    return float((1 + np.count_nonzero(null >= observed - 1e-15)) / (iterations + 1))


def _counter(values: Sequence[Any]) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in Counter(values).items()))


def _condition_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    side_effects = Counter(item for row in rows for item in row["other_side_effects"])
    return {
        "mean_scores": {
            metric: float(np.mean([row[metric] for row in rows]))
            for metric in ("trait_score", "task_quality_score", "naturalness_score", "repetition")
        },
        "refusal_appropriateness": _counter([row["refusal_appropriateness"] for row in rows]),
        "over_refusal": _counter([row["over_refusal"] for row in rows]),
        "sycophancy_or_over_accommodation": _counter([row["sycophancy_or_over_accommodation"] for row in rows]),
        "alternative_quality": _counter([row["alternative_quality"] for row in rows]),
        "confidence": _counter([row["confidence"] for row in rows]),
        "other_side_effects": dict(sorted(side_effects.items())),
    }


def _metric_comparison(
    paired_rows: Sequence[Mapping[str, Any]],
    metric: str,
    *,
    bootstrap_iterations: int,
    permutation_iterations: int,
    seed: int,
) -> dict[str, Any]:
    candidate_deltas = np.asarray([row[metric] for row in paired_rows], dtype=float)
    family = _family_deltas(paired_rows, metric)
    std = float(np.std(family, ddof=1))
    ci = _bootstrap_ci(family, bootstrap_iterations, seed)
    return {
        "family_mean_delta": float(np.mean(family)),
        "family_median_delta": float(np.median(family)),
        "family_cluster_bootstrap_95pct_ci": ci,
        "family_level_cohens_dz": None if std == 0.0 else float(np.mean(family) / std),
        "family_structure_preserving_permutation_two_sided_p": _permutation_p(family, permutation_iterations, seed + 1),
        "candidate_win_tie_loss": {
            "win": int(np.count_nonzero(candidate_deltas > 0)),
            "tie": int(np.count_nonzero(candidate_deltas == 0)),
            "loss": int(np.count_nonzero(candidate_deltas < 0)),
        },
    }


def analyze_held_out(root: Path) -> dict[str, Any]:
    runtime = read_json(root / RUNTIME)
    freeze = read_json(root / REVIEW_FREEZE)
    contract = read_json(root / ANALYSIS_CONTRACT)
    jsonschema.validate(contract, read_json(root / ANALYSIS_CONTRACT_SCHEMA))
    annotations_path = root / freeze["formal_annotations"]["path"]
    if file_sha256(annotations_path) != freeze["formal_annotations"]["sha256"]:
        raise ValueError("held-out formal annotations differ from the pre-unblinding freeze")
    annotations = read_jsonl(annotations_path)
    if len(annotations) != 780:
        raise ValueError("held-out analysis requires exactly 780 frozen annotations")
    key_path = root / runtime["artifacts"]["condition_key_path"]
    key_rows = read_jsonl(key_path)
    key_index = {row["blind_output_id"]: row for row in key_rows}
    if set(key_index) != {row["blind_output_id"] for row in annotations}:
        raise ValueError("restricted condition key does not exactly cover frozen annotations")
    joined = []
    for annotation in annotations:
        key = key_index[annotation["blind_output_id"]]
        if key["candidate_id"] != annotation["candidate_id"] or key["output_sha256"] != _text_sha256(annotation["output_text"]):
            raise ValueError(f"condition key integrity mismatch: {annotation['blind_output_id']}")
        joined.append({**annotation, "condition_id": key["condition_id"]})
    condition_ids = runtime["condition_registry"]["condition_ids"]
    by_item: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in joined:
        by_item.setdefault(row["review_item_id"], {})[row["condition_id"]] = row
    if len(by_item) != 52 or any(set(outputs) != set(condition_ids) for outputs in by_item.values()):
        raise ValueError("each held-out candidate must contain all 15 conditions")
    by_condition = {condition: [row for row in joined if row["condition_id"] == condition] for condition in condition_ids}
    settings = contract["analysis"]
    comparisons = []
    for index, condition in enumerate(condition_ids):
        if condition == "base":
            continue
        paired = []
        for outputs in by_item.values():
            candidate = outputs[condition]
            base = outputs["base"]
            paired.append({
                "final_isolation_family_id": candidate["final_isolation_family_id"],
                "trait_delta": candidate["trait_score"] - base["trait_score"],
                "quality_delta": candidate["task_quality_score"] - base["task_quality_score"],
                "naturalness_delta": candidate["naturalness_score"] - base["naturalness_score"],
                "repetition_delta": candidate["repetition"] - base["repetition"],
            })
        seed = int(settings["seed"]) + index * 100
        trait = _metric_comparison(paired, "trait_delta", bootstrap_iterations=settings["bootstrap_iterations"], permutation_iterations=settings["permutation_iterations"], seed=seed)
        quality = _metric_comparison(paired, "quality_delta", bootstrap_iterations=settings["bootstrap_iterations"], permutation_iterations=settings["permutation_iterations"], seed=seed + 10)
        quality["noninferiority_margin"] = settings["quality_noninferiority_margin"]
        quality["noninferiority_passed"] = quality["family_cluster_bootstrap_95pct_ci"][0] >= settings["quality_noninferiority_margin"]
        comparisons.append({
            "condition_id": condition,
            "candidate_count": 52,
            "family_count": 40,
            "condition_summary": _condition_summary(by_condition[condition]),
            "trait_vs_base": trait,
            "task_quality_vs_base": quality,
            "naturalness_family_mean_delta": float(_family_deltas(paired, "naturalness_delta").mean()),
            "repetition_family_mean_delta": float(_family_deltas(paired, "repetition_delta").mean()),
        })
    comparison_index = {row["condition_id"]: row for row in comparisons}

    def envelope(prefix: str) -> dict[str, Any]:
        selected = [row for row in comparisons if row["condition_id"].startswith(prefix)]
        return {
            "condition_ids": [row["condition_id"] for row in selected],
            "trait_family_mean_delta_min_median_max": [
                float(np.min([row["trait_vs_base"]["family_mean_delta"] for row in selected])),
                float(np.median([row["trait_vs_base"]["family_mean_delta"] for row in selected])),
                float(np.max([row["trait_vs_base"]["family_mean_delta"] for row in selected])),
            ],
            "quality_family_mean_delta_min_median_max": [
                float(np.min([row["task_quality_vs_base"]["family_mean_delta"] for row in selected])),
                float(np.median([row["task_quality_vs_base"]["family_mean_delta"] for row in selected])),
                float(np.max([row["task_quality_vs_base"]["family_mean_delta"] for row in selected])),
            ],
        }

    target = comparison_index["target_steering"]
    result = {
        "summary_version": "phase_3_held_out_results_v0_1",
        "status": "complete_nonconfirmatory_held_out_analysis",
        "study_role": contract["scope"]["study_role"],
        "axis_id": contract["scope"]["axis_ids"][0],
        "bound_evidence": {
            "runtime_path": RUNTIME,
            "runtime_sha256": canonical_content_sha256(runtime),
            "review_freeze_path": REVIEW_FREEZE,
            "review_freeze_sha256": canonical_content_sha256(freeze),
            "formal_annotations_path": freeze["formal_annotations"]["path"],
            "formal_annotations_sha256": freeze["formal_annotations"]["sha256"],
            "condition_key_path": runtime["artifacts"]["condition_key_path"],
            "condition_key_sha256": file_sha256(key_path),
            "analysis_contract_path": ANALYSIS_CONTRACT,
            "analysis_contract_sha256": canonical_content_sha256(contract),
        },
        "coverage": {"families": 40, "candidates": 52, "conditions": 15, "annotations": 780},
        "analysis_contract": settings,
        "base_summary": _condition_summary(by_condition["base"]),
        "condition_comparisons": comparisons,
        "control_envelopes": {
            "random_steering": envelope("random_steering_"),
            "shuffled_steering": envelope("shuffled_steering_"),
        },
        "primary_target_summary": {
            "trait_family_mean_delta": target["trait_vs_base"]["family_mean_delta"],
            "trait_bootstrap_95pct_ci": target["trait_vs_base"]["family_cluster_bootstrap_95pct_ci"],
            "trait_permutation_two_sided_p": target["trait_vs_base"]["family_structure_preserving_permutation_two_sided_p"],
            "trait_candidate_win_tie_loss": target["trait_vs_base"]["candidate_win_tie_loss"],
            "quality_family_mean_delta": target["task_quality_vs_base"]["family_mean_delta"],
            "quality_bootstrap_95pct_ci": target["task_quality_vs_base"]["family_cluster_bootstrap_95pct_ci"],
            "quality_noninferiority_passed": target["task_quality_vs_base"]["noninferiority_passed"],
        },
        "claim_boundary": "These are complete single-reviewer held-out results for a limited nonconfirmatory comparison. They do not erase the preparation-side blinding deviation, establish inter-rater reliability, confirm causal Trait control, authorize a new axis or alpha search, or change QLoRA epoch 1 from a failed-development-quality-gate fallback.",
    }
    jsonschema.validate(result, read_json(root / RESULT_SCHEMA))
    return result


def write_results(root: Path) -> Path:
    result = analyze_held_out(root)
    output = root / RESULT_SUMMARY
    if output.exists():
        raise FileExistsError("refusing to overwrite frozen held-out results")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
