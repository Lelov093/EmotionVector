from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import mean
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_blind_review_retest_v2 import quadratic_weighted_kappa


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = average_rank
        start = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        raise ValueError("Correlation inputs must have equal non-zero length")
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sum = sum((a - left_mean) ** 2 for a in left)
    right_sum = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_sum * right_sum)
    return None if denominator == 0 else numerator / denominator


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(average_ranks(left), average_ranks(right))


def ordinal_metrics(
    automatic: list[int], human: list[int], categories: list[int]
) -> dict[str, Any]:
    if len(automatic) != len(human) or not automatic:
        raise ValueError("Ordinal metrics require equal non-empty inputs")
    pairs = list(zip(automatic, human))
    kappa = quadratic_weighted_kappa(pairs, categories)
    correlation = spearman([float(value) for value in automatic], [float(value) for value in human])
    return {
        "n": len(pairs),
        "exact_agreement": round(sum(a == h for a, h in pairs) / len(pairs), 6),
        "mean_absolute_error": round(mean(abs(a - h) for a, h in pairs), 6),
        "spearman_rho": None if correlation is None else round(correlation, 6),
        "quadratic_weighted_kappa": None if kappa is None else round(kappa, 6),
    }


def binary_metrics(automatic: list[bool], human: list[bool]) -> dict[str, Any]:
    if len(automatic) != len(human) or not automatic:
        raise ValueError("Binary metrics require equal non-empty inputs")
    tp = sum(a and h for a, h in zip(automatic, human))
    tn = sum((not a) and (not h) for a, h in zip(automatic, human))
    fp = sum(a and (not h) for a, h in zip(automatic, human))
    fn = sum((not a) and h for a, h in zip(automatic, human))
    positive_n = tp + fn
    negative_n = tn + fp
    sensitivity = tp / positive_n if positive_n else None
    specificity = tn / negative_n if negative_n else None
    balanced = (
        (sensitivity + specificity) / 2
        if sensitivity is not None and specificity is not None
        else None
    )
    return {
        "n": len(automatic),
        "accuracy": round((tp + tn) / len(automatic), 6),
        "balanced_accuracy": None if balanced is None else round(balanced, 6),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "human_positive_n": positive_n,
        "human_negative_n": negative_n,
    }


def preference(left: int, right: int) -> str:
    if left > right:
        return "A"
    if right > left:
        return "B"
    return "tie"


def pairwise_metrics(automatic: list[str], human: list[str]) -> dict[str, Any]:
    if len(automatic) != len(human) or not automatic:
        raise ValueError("Pairwise metrics require equal non-empty inputs")
    non_tie = [(a, h) for a, h in zip(automatic, human) if h != "tie"]
    agreement = (
        sum(a == h for a, h in non_tie) / len(non_tie) if non_tie else None
    )
    return {
        "n": len(automatic),
        "human_non_tie_n": len(non_tie),
        "human_tie_n": len(automatic) - len(non_tie),
        "agreement_on_human_non_ties": None if agreement is None else round(agreement, 6),
        "automatic_choice_counts": dict(sorted(Counter(automatic).items())),
        "human_preference_counts": dict(sorted(Counter(human).items())),
    }


def build_human_index(
    annotations: list[dict[str, Any]],
    key_rows: list[dict[str, Any]],
    review_round: int,
) -> dict[tuple[str, str], dict[str, Any]]:
    mapping = {
        row["blind_output_id"]: (row["artifact_id"], row["condition_id"])
        for row in key_rows
        if row["review_round"] == review_round
    }
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for annotation in annotations:
        if annotation["review_round"] != review_round:
            raise ValueError(f"Unexpected annotation round: {annotation['review_round']}")
        identity = mapping.get(annotation["blind_output_id"])
        if identity is None:
            raise ValueError(f"Missing restricted mapping for {annotation['blind_output_id']}")
        if identity in indexed:
            raise ValueError(f"Duplicate human annotation identity: {identity[0]}")
        indexed[identity] = annotation
    return indexed


def calibrate_heuristic(
    joined: list[tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, Any]:
    ordinal_specs = {
        "trait_expression": ("trait_expression_score", "trait_score", [0, 1, 2, 3, 4], "direct_score_alignment"),
        "response_quality": ("response_quality_score", "task_quality_score", [0, 1, 2, 3, 4], "closest_available_human_dimension"),
        "usefulness": ("usefulness_score", "task_quality_score", [0, 1, 2, 3, 4], "proxy_gap_helpfulness_is_not_identical_to_task_quality"),
        "repetition": ("repetition", "repetition", [0, 1, 2], "direct_after_human_schema_clamp"),
    }
    binary_specs = {
        "over_refusal": ("over_refusal", "over_refusal", "direct_binary_alignment"),
        "sycophancy": ("sycophancy_or_over_accommodation", "sycophancy", "direct_binary_alignment"),
        "verbosity_warning": ("verbosity_conciseness_warning", "verbosity_side_effect", "binary_proxy_any_human_verbosity_side_effect"),
    }
    ordinal_results = {}
    for label, (automatic_field, human_field, categories, alignment) in ordinal_specs.items():
        automatic = [int(heuristic[automatic_field]) for heuristic, _ in joined]
        human = [int(annotation[human_field]) for _, annotation in joined]
        ordinal_results[label] = {
            **ordinal_metrics(automatic, human, categories),
            "alignment": alignment,
        }
    binary_results = {}
    for label, (automatic_field, human_field, alignment) in binary_specs.items():
        automatic = [bool(heuristic[automatic_field]) for heuristic, _ in joined]
        if label == "verbosity_warning":
            human = [annotation[human_field] != "appropriate" for _, annotation in joined]
        else:
            human = [bool(annotation[human_field]) for _, annotation in joined]
        binary_results[label] = {
            **binary_metrics(automatic, human),
            "alignment": alignment,
        }
    return {"ordinal": ordinal_results, "binary": binary_results}


def collect_judge_rows(source_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in source_items:
        external = source.get("external_judge", {})
        if not isinstance(external, dict):
            continue
        for group in external.values():
            if not isinstance(group, list):
                continue
            for row in group:
                if isinstance(row, dict) and isinstance(row.get("llm_judge"), dict):
                    rows.append({"artifact_id": source["review_item_id"], **row})
    return rows


def calibrate_judge(
    judge_rows: list[dict[str, Any]],
    human: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    automatic: list[str] = []
    human_task: list[str] = []
    human_trait: list[str] = []
    models: Counter[str] = Counter()
    fallback_count = 0
    matched = 0
    for row in judge_rows:
        left = human.get((row["artifact_id"], row["condition_a"]))
        right = human.get((row["artifact_id"], row["condition_b"]))
        if left is None or right is None:
            continue
        choice = row["llm_judge"].get("preferred_output")
        if choice not in {"A", "B"}:
            continue
        matched += 1
        automatic.append(choice)
        human_task.append(preference(left["task_quality_score"], right["task_quality_score"]))
        human_trait.append(preference(left["trait_score"], right["trait_score"]))
        models[str(row["llm_judge"].get("model_used", "not_recorded"))] += 1
        fallback_count += int(bool(row["llm_judge"].get("fallback_used")))
    return {
        "matched_pairwise_records": matched,
        "model_counts": dict(sorted(models.items())),
        "fallback_count": fallback_count,
        "against_human_task_quality_preference": pairwise_metrics(automatic, human_task),
        "against_human_trait_preference": pairwise_metrics(automatic, human_trait),
        "construct_warning": "LLM Judge preferred_output is holistic; task-quality and Trait preferences are partial comparison targets, not equivalent gold labels.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate existing heuristic and LLM Judge signals against frozen human annotations.")
    parser.add_argument(
        "--source",
        default="data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl",
    )
    parser.add_argument(
        "--condition-key",
        default="results/local_artifacts/research_foundation/blind_review_pilot_condition_key_v0_2.jsonl",
    )
    parser.add_argument(
        "--round-1",
        default="results/local_artifacts/research_foundation/blind_review_pilot_v0_2_round_1_annotations.jsonl",
    )
    parser.add_argument(
        "--round-2",
        default="results/local_artifacts/research_foundation/blind_review_pilot_v0_2_round_2_annotations.jsonl",
    )
    parser.add_argument(
        "--summary", default="results/summaries/automatic_evaluator_calibration_v0_1.json"
    )
    parser.add_argument(
        "--report", default="results/cards/automatic_evaluator_calibration_v0_1.md"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = ROOT / args.source
    key_path = ROOT / args.condition_key
    round_1_path = ROOT / args.round_1
    round_2_path = ROOT / args.round_2
    source_rows = read_jsonl(source_path)
    key_rows = read_jsonl(key_path)
    round_1 = build_human_index(read_jsonl(round_1_path), key_rows, 1)
    round_2 = build_human_index(read_jsonl(round_2_path), key_rows, 2)
    if set(round_1) != set(round_2) or len(round_1) != 30:
        raise ValueError(f"Human calibration coverage mismatch: r1={len(round_1)}, r2={len(round_2)}")
    source_by_id = {row["review_item_id"]: row for row in source_rows}
    selected_sources = sorted({artifact for artifact, _ in round_1})
    source_subset = [source_by_id[artifact] for artifact in selected_sources]

    joined_by_round: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = {1: [], 2: []}
    for identity in sorted(round_1):
        artifact, condition = identity
        heuristic = source_by_id[artifact]["heuristic_scores"].get(condition)
        if heuristic is None:
            raise ValueError(f"Missing heuristic record for selected output in {artifact}")
        joined_by_round[1].append((heuristic, round_1[identity]))
        joined_by_round[2].append((heuristic, round_2[identity]))

    judge_rows = collect_judge_rows(source_subset)
    round_results = {
        "round_1_primary": {
            "heuristic": calibrate_heuristic(joined_by_round[1]),
            "llm_judge": calibrate_judge(judge_rows, round_1),
        },
        "round_2_accelerated_sensitivity": {
            "heuristic": calibrate_heuristic(joined_by_round[2]),
            "llm_judge": calibrate_judge(judge_rows, round_2),
        },
    }
    primary_trait = round_results["round_1_primary"]["heuristic"]["ordinal"]["trait_expression"]
    primary_quality = round_results["round_1_primary"]["heuristic"]["ordinal"]["response_quality"]
    primary_judge = round_results["round_1_primary"]["llm_judge"]["against_human_task_quality_preference"]
    summary = {
        "schema_version": "automatic_evaluator_calibration_v0_1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "existing_30_output_blind_pilot_only",
        "human_reference": {
            "reviewer_id": "researcher_01",
            "primary_round": 1,
            "sensitivity_round": 2,
            "independent_external_annotation": False,
            "round_2_protocol_compliant_washout": False,
        },
        "coverage": {
            "output_level_pairs": 30,
            "source_review_items": len(selected_sources),
            "llm_judge_pairwise_records": len(judge_rows),
        },
        "evaluator_versions": {
            "heuristic": "not_recorded_in_source_artifact",
            "llm_judge_models": round_results["round_1_primary"]["llm_judge"]["model_counts"],
        },
        "round_results": round_results,
        "allowed_uses": {
            "heuristic": [
                "triage and error-case prioritization",
                "auxiliary sensitivity analysis with human results shown separately",
            ],
            "llm_judge": [
                "exploratory pairwise review aid on matched constructs",
                "disagreement sampling for later human review",
            ],
        },
        "forbidden_uses": [
            "human gold-label replacement",
            "sole model-selection criterion",
            "independent validation claims",
            "automatic proof of Trait control",
            "cross-dataset or cross-model generalization claims",
        ],
        "interpretation": {
            "heuristic_trait": primary_trait,
            "heuristic_response_quality": primary_quality,
            "llm_judge_task_preference": primary_judge,
            "evidence_level": "auxiliary_single_researcher_pilot",
            "no_preregistered_automatic_evaluator_gate": True,
        },
        "evidence": {
            "source_path": args.source,
            "source_sha256": file_sha256(source_path),
            "round_1_annotation_sha256": file_sha256(round_1_path),
            "round_2_annotation_sha256": file_sha256(round_2_path),
            "restricted_condition_key_sha256": file_sha256(key_path),
            "ai_preannotation_used_as_human_reference": False,
            "condition_or_method_fields_emitted": False,
        },
        "claim_boundary": (
            "Calibration is limited to 30 reused outputs and one researcher. Round 2 is an accelerated sensitivity check. "
            "The results define auxiliary uses only and do not validate either evaluator as a human substitute."
        ),
    }
    summary_path = ROOT / args.summary
    report_path = ROOT / args.report
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    heuristic_rows = []
    for label, metrics in round_results["round_1_primary"]["heuristic"]["ordinal"].items():
        heuristic_rows.append(
            f"| {label} | ordinal | {metrics['n']} | exact {metrics['exact_agreement']:.1%}; MAE {metrics['mean_absolute_error']:.3f}; Spearman {metrics['spearman_rho'] if metrics['spearman_rho'] is not None else 'undefined'}; QWK {metrics['quadratic_weighted_kappa'] if metrics['quadratic_weighted_kappa'] is not None else 'undefined'} |"
        )
    for label, metrics in round_results["round_1_primary"]["heuristic"]["binary"].items():
        heuristic_rows.append(
            f"| {label} | binary | {metrics['n']} | accuracy {metrics['accuracy']:.1%}; balanced accuracy {metrics['balanced_accuracy'] if metrics['balanced_accuracy'] is not None else 'undefined'} |"
        )
    judge_task = round_results["round_1_primary"]["llm_judge"]["against_human_task_quality_preference"]
    judge_trait = round_results["round_1_primary"]["llm_judge"]["against_human_trait_preference"]
    report = [
        "# Automatic Evaluator Calibration v0.1",
        "",
        "## Scope",
        "",
        "This is a minimal calibration of already-produced heuristic and LLM Judge signals against the frozen single-researcher blind pilot. Round 1 is the primary reference; accelerated Round 2 is sensitivity evidence only. AI preannotations are excluded from the human reference.",
        "",
        "## Heuristic vs Human Round 1",
        "",
        "| Signal | Type | N | Result |",
        "|---|---|---:|---|",
        *heuristic_rows,
        "",
        "## LLM Judge Pairwise Check",
        "",
        f"- Existing judged pairs: {len(judge_rows)}; matched to the blind pilot: {round_results['round_1_primary']['llm_judge']['matched_pairwise_records']}.",
        f"- Agreement with human task-quality preference on non-ties: {judge_task['agreement_on_human_non_ties'] if judge_task['agreement_on_human_non_ties'] is not None else 'undefined'} (N={judge_task['human_non_tie_n']}; human ties={judge_task['human_tie_n']}).",
        f"- Agreement with human Trait preference on non-ties: {judge_trait['agreement_on_human_non_ties'] if judge_trait['agreement_on_human_non_ties'] is not None else 'undefined'} (N={judge_trait['human_non_tie_n']}; human ties={judge_trait['human_tie_n']}).",
        "- Preferred-output judgments are holistic, so neither comparison is a construct-identical gold-label test.",
        "",
        "## Decision",
        "",
        "- Heuristic: retain only for triage, error sampling and sensitivity analysis; always report human results separately.",
        "- LLM Judge: retain only as an exploratory pairwise review aid and disagreement sampler.",
        "- Neither evaluator may replace human annotation, select a model alone, or establish Trait control.",
        "- No formal automatic-evaluator pass/fail gate is claimed because none was preregistered.",
        "",
        "## Claim Boundary",
        "",
        summary["claim_boundary"],
        "",
    ]
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_level_pairs": 30,
                "llm_judge_pairs": len(judge_rows),
                "heuristic_trait": primary_trait,
                "heuristic_response_quality": primary_quality,
                "llm_judge_task_preference": primary_judge,
                "summary": args.summary,
                "report": args.report,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
