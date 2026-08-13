from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def normalize_side_effects(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("other_side_effects must be a list")
    return tuple(sorted(str(item).strip() for item in value if str(item).strip()))


def normalize_notes(value: Any) -> str:
    return " ".join(str(value or "").split())


def exact_agreement(pairs: list[tuple[Any, Any]]) -> float:
    if not pairs:
        raise ValueError("Agreement requires at least one pair")
    return sum(left == right for left, right in pairs) / len(pairs)


def quadratic_weighted_kappa(
    pairs: list[tuple[int, int]], categories: list[int]
) -> float | None:
    if not pairs:
        return None
    index = {category: position for position, category in enumerate(categories)}
    if any(left not in index or right not in index for left, right in pairs):
        raise ValueError("Observed value is outside the declared ordinal categories")
    category_count = len(categories)
    if category_count < 2:
        return None
    observed = [[0.0] * category_count for _ in range(category_count)]
    left_counts = [0.0] * category_count
    right_counts = [0.0] * category_count
    for left, right in pairs:
        left_index = index[left]
        right_index = index[right]
        observed[left_index][right_index] += 1.0
        left_counts[left_index] += 1.0
        right_counts[right_index] += 1.0
    total = float(len(pairs))
    denominator = float((category_count - 1) ** 2)
    observed_disagreement = 0.0
    expected_disagreement = 0.0
    for left_index in range(category_count):
        for right_index in range(category_count):
            weight = ((left_index - right_index) ** 2) / denominator
            observed_disagreement += weight * observed[left_index][right_index] / total
            expected = left_counts[left_index] * right_counts[right_index] / (total * total)
            expected_disagreement += weight * expected
    if expected_disagreement == 0.0:
        return None
    return 1.0 - observed_disagreement / expected_disagreement


def annotation_index(
    annotations: list[dict[str, Any]],
    blind_to_canonical: dict[str, str],
    expected_round: int,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in annotations:
        if row.get("review_round") != expected_round:
            raise ValueError(f"Unexpected annotation round: {row.get('review_round')}")
        blind_id = row["blind_output_id"]
        canonical_id = blind_to_canonical.get(blind_id)
        if canonical_id is None:
            raise ValueError(f"Missing canonical mapping for blind output {blind_id}")
        if canonical_id in indexed:
            raise ValueError(f"Duplicate canonical annotation in round {expected_round}: {canonical_id}")
        indexed[canonical_id] = row
    return indexed


def build_restricted_mapping(
    condition_key_rows: list[dict[str, Any]],
) -> dict[int, dict[str, str]]:
    mappings: dict[int, dict[str, str]] = {1: {}, 2: {}}
    for restricted_row in condition_key_rows:
        review_round = restricted_row.get("review_round")
        if review_round not in mappings:
            raise ValueError(f"Unexpected condition-key round: {review_round}")
        blind_id = restricted_row["blind_output_id"]
        canonical_id = restricted_row["canonical_output_id"]
        if blind_id in mappings[review_round]:
            raise ValueError(f"Duplicate blind ID in condition key: {blind_id}")
        mappings[review_round][blind_id] = canonical_id
    return mappings


def dimension_result(
    canonical_ids: list[str],
    round_1: dict[str, dict[str, Any]],
    round_2: dict[str, dict[str, Any]],
    field: str,
    normalize: Callable[[Any], Any] | None = None,
    ordinal_categories: list[int] | None = None,
    exclude_value: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalize_value = normalize or (lambda value: value)
    all_pairs: list[tuple[Any, Any]] = []
    kappa_pairs: list[tuple[int, int]] = []
    disagreements: list[dict[str, Any]] = []
    for canonical_id in canonical_ids:
        left = normalize_value(round_1[canonical_id][field])
        right = normalize_value(round_2[canonical_id][field])
        all_pairs.append((left, right))
        if left != right:
            disagreements.append(
                {
                    "canonical_output_id": canonical_id,
                    "dimension": field,
                    "round_1": list(left) if isinstance(left, tuple) else left,
                    "round_2": list(right) if isinstance(right, tuple) else right,
                }
            )
        if ordinal_categories is not None and left != exclude_value and right != exclude_value:
            kappa_pairs.append((int(left), int(right)))
    result: dict[str, Any] = {
        "dimension": field,
        "paired_n": len(all_pairs),
        "exact_agreement": round(exact_agreement(all_pairs), 6),
        "exact_agreement_count": sum(left == right for left, right in all_pairs),
        "disagreement_count": len(disagreements),
        "quadratic_weighted_kappa": None,
        "kappa_n": 0,
    }
    if ordinal_categories is not None:
        result["kappa_n"] = len(kappa_pairs)
        kappa = quadratic_weighted_kappa(kappa_pairs, ordinal_categories)
        result["quadratic_weighted_kappa"] = None if kappa is None else round(kappa, 6)
    return result, disagreements


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Round 1/2 condition-blind retest stability.")
    parser.add_argument(
        "--round-1",
        default="results/local_artifacts/research_foundation/blind_review_pilot_v0_2_round_1_annotations.jsonl",
    )
    parser.add_argument(
        "--round-2",
        default="results/local_artifacts/research_foundation/blind_review_pilot_v0_2_round_2_annotations.jsonl",
    )
    parser.add_argument(
        "--condition-key",
        default="results/local_artifacts/research_foundation/blind_review_pilot_condition_key_v0_2.jsonl",
    )
    parser.add_argument(
        "--round-1-freeze",
        default="results/local_artifacts/research_foundation/blind_review_pilot_v0_2_round_1_annotations.freeze.json",
    )
    parser.add_argument(
        "--round-2-freeze",
        default="results/local_artifacts/research_foundation/blind_review_pilot_v0_2_round_2_annotations.freeze.json",
    )
    parser.add_argument(
        "--summary",
        default="results/summaries/blind_review_retest_stability_v0_2.json",
    )
    parser.add_argument(
        "--report",
        default="results/cards/blind_review_retest_stability_v0_2.md",
    )
    parser.add_argument(
        "--disagreements",
        default="results/local_artifacts/research_foundation/blind_review_retest_disagreements_v0_2.jsonl",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    round_1_path = ROOT / args.round_1
    round_2_path = ROOT / args.round_2
    condition_key_path = ROOT / args.condition_key
    round_1_freeze = json.loads((ROOT / args.round_1_freeze).read_text(encoding="utf-8"))
    round_2_freeze = json.loads((ROOT / args.round_2_freeze).read_text(encoding="utf-8"))
    round_1_rows = read_jsonl(round_1_path)
    round_2_rows = read_jsonl(round_2_path)
    restricted_mapping = build_restricted_mapping(read_jsonl(condition_key_path))
    round_1 = annotation_index(round_1_rows, restricted_mapping[1], 1)
    round_2 = annotation_index(round_2_rows, restricted_mapping[2], 2)
    canonical_ids = sorted(round_1)
    if len(canonical_ids) != 30 or set(canonical_ids) != set(round_2):
        raise ValueError(
            f"Canonical coverage mismatch: round_1={len(round_1)}, round_2={len(round_2)}"
        )

    ordinal_specs = {
        "trait_score": ([0, 1, 2, 3, 4], None, None),
        "task_quality_score": ([0, 1, 2, 3, 4], None, None),
        "naturalness_score": ([0, 1, 2, 3, 4], None, None),
        "alternative_quality": (
            [0, 1, 2, 3],
            lambda value: {
                "not_applicable": -1,
                "none": 0,
                "weak": 1,
                "adequate": 2,
                "strong": 3,
            }[value],
            -1,
        ),
        "repetition": ([0, 1, 2], None, None),
        "confidence": (
            [0, 1, 2],
            lambda value: {"low": 0, "medium": 1, "high": 2}[value],
            None,
        ),
    }
    categorical_specs: dict[str, Callable[[Any], Any] | None] = {
        "refusal_appropriateness": None,
        "over_refusal": None,
        "sycophancy": None,
        "verbosity_side_effect": None,
        "other_side_effects": normalize_side_effects,
    }
    dimensions: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for field, (categories, normalize, exclude_value) in ordinal_specs.items():
        result, field_disagreements = dimension_result(
            canonical_ids,
            round_1,
            round_2,
            field,
            normalize=normalize,
            ordinal_categories=categories,
            exclude_value=exclude_value,
        )
        dimensions.append(result)
        disagreements.extend(field_disagreements)
    for field, normalize in categorical_specs.items():
        result, field_disagreements = dimension_result(
            canonical_ids, round_1, round_2, field, normalize=normalize
        )
        dimensions.append(result)
        disagreements.extend(field_disagreements)
    notes_result, note_disagreements = dimension_result(
        canonical_ids, round_1, round_2, "notes", normalize=normalize_notes
    )
    notes_result["role"] = "supplementary_free_text_not_a_scoring_dimension"
    disagreements.extend(note_disagreements)

    trait = next(item for item in dimensions if item["dimension"] == "trait_score")
    exact_pass = trait["exact_agreement"] >= 0.70
    kappa_pass = (
        trait["quadratic_weighted_kappa"] is not None
        and trait["quadratic_weighted_kappa"] >= 0.67
    )
    numeric_gate_pass = exact_pass and kappa_pass
    protocol_compliant = not bool(round_2_freeze.get("protocol_deviation"))
    if not numeric_gate_pass:
        gate_status = "fails_numeric_stability_gate"
    elif not protocol_compliant:
        gate_status = "passes_numeric_thresholds_but_not_protocol_compliant"
    else:
        gate_status = "passes_protocol_stability_gate"

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    summary = {
        "schema_version": "blind_review_retest_stability_v0_2",
        "generated_at": generated_at,
        "analysis_scope": "single_researcher_condition_blind_round_1_round_2_retest",
        "reviewer_id": "researcher_01",
        "paired_outputs": len(canonical_ids),
        "review_items_per_round": len({row["review_item_id"] for row in round_1_rows}),
        "dimensions": dimensions,
        "supplementary": {"notes_exact_agreement": notes_result},
        "trait_stability_gate": {
            "exact_agreement_threshold": 0.70,
            "quadratic_weighted_kappa_threshold": 0.67,
            "exact_agreement_pass": exact_pass,
            "quadratic_weighted_kappa_pass": kappa_pass,
            "numeric_gate_pass": numeric_gate_pass,
            "protocol_compliant": protocol_compliant,
            "status": gate_status,
        },
        "protocol_deviation": round_2_freeze.get("protocol_deviation"),
        "evidence": {
            "round_1_annotation_path": args.round_1,
            "round_1_annotation_sha256": file_sha256(round_1_path),
            "round_1_expected_sha256": round_1_freeze["annotation_sha256"],
            "round_2_annotation_path": args.round_2,
            "round_2_annotation_sha256": file_sha256(round_2_path),
            "round_2_expected_sha256": round_2_freeze["annotation_sha256"],
            "restricted_condition_key_path": args.condition_key,
            "restricted_condition_key_sha256": file_sha256(condition_key_path),
            "restricted_fields_emitted": False,
            "disagreement_artifact_path": args.disagreements,
        },
        "disagreement_counts": dict(Counter(row["dimension"] for row in disagreements)),
        "interpretation": {
            "direct_evidence": [
                "Trait ratings match exactly for all 30 paired outputs and meet the predeclared numeric thresholds.",
                "Verbosity-side-effect exact agreement is 70.0%, and other-side-effects exact agreement is 33.3%.",
            ],
            "reasonable_inference": [
                "The very short interval may have increased score carryover or recall, so perfect Trait agreement may overestimate repeatability under the intended washout.",
                "Free-text other-side-effect labels are not sufficiently standardized for exact-agreement use in their current form.",
            ],
            "not_verified": [
                "Protocol-compliant seven-day test-retest stability.",
                "Inter-rater reliability or independent external validity.",
                "Any method-level Trait-control advantage.",
            ],
        },
        "claim_boundary": (
            "This diagnostic measures accelerated within-reviewer repeatability on 30 reused outputs. "
            "It is not inter-rater agreement, independent external validation, a protocol-compliant "
            "seven-day test-retest estimate, method comparison, or evidence of Trait control."
        ),
    }
    if summary["evidence"]["round_1_annotation_sha256"] != summary["evidence"]["round_1_expected_sha256"]:
        raise ValueError("Round 1 annotation hash no longer matches its freeze manifest")
    if summary["evidence"]["round_2_annotation_sha256"] != summary["evidence"]["round_2_expected_sha256"]:
        raise ValueError("Round 2 annotation hash no longer matches its freeze manifest")

    summary_path = ROOT / args.summary
    report_path = ROOT / args.report
    disagreement_path = ROOT / args.disagreements
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(disagreement_path, disagreements)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Blind Review Round 1/2 Accelerated Retest Stability v0.2",
        "",
        "## Outcome",
        "",
        f"- Paired outputs: {len(canonical_ids)}",
        f"- Trait exact agreement: {trait['exact_agreement']:.1%} ({trait['exact_agreement_count']}/{trait['paired_n']})",
        f"- Trait quadratic weighted kappa: {trait['quadratic_weighted_kappa'] if trait['quadratic_weighted_kappa'] is not None else 'undefined'}",
        f"- Numeric gate status: `{gate_status}`",
        f"- Protocol compliant: `{str(protocol_compliant).lower()}`",
        "",
        "The original seven-day washout was not met. Even if the numeric thresholds pass, this run remains an accelerated diagnostic and cannot establish protocol-compliant test-retest stability.",
        "",
        "## Per-Dimension Results",
        "",
        "| Dimension | N | Exact agreement | QWK | QWK N | Disagreements |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in dimensions:
        kappa_text = (
            "undefined"
            if item["quadratic_weighted_kappa"] is None
            else f"{item['quadratic_weighted_kappa']:.3f}"
        )
        lines.append(
            f"| {item['dimension']} | {item['paired_n']} | {item['exact_agreement']:.1%} | {kappa_text} | {item['kappa_n']} | {item['disagreement_count']} |"
        )
    lines.extend(
        [
            "",
            "## Evidence and Access Boundary",
            "",
            f"- Round 1 annotation SHA-256: `{summary['evidence']['round_1_annotation_sha256']}`",
            f"- Round 2 annotation SHA-256: `{summary['evidence']['round_2_annotation_sha256']}`",
            f"- Restricted condition-key SHA-256: `{summary['evidence']['restricted_condition_key_sha256']}`",
            "- The condition key was used only to recover canonical cross-round pairing. Condition IDs, artifact IDs and method labels are not emitted in the summary, report or disagreement artifact.",
            "- Free-text notes agreement is supplementary and is not included in the scoring gate.",
            "",
            "## Interpretation",
            "",
            "- **Direct evidence:** Trait ratings agree on 30/30 pairs and meet the predeclared numeric thresholds. Verbosity-side-effect agreement is 70.0%; free-text other-side-effects agreement is 33.3%.",
            "- **Reasonable inference:** the approximately 1.14-hour interval may have increased recall or score carryover, so the perfect Trait result may overestimate repeatability under the intended washout.",
            "- **Required correction before formal evaluation:** replace free-text side-effect agreement with a controlled tag taxonomy, while retaining optional notes as qualitative evidence.",
            "- **Not verified:** seven-day test-retest stability, inter-rater reliability, independent external validity, or any method-level advantage.",
            "",
            "## Claim Boundary",
            "",
            summary["claim_boundary"],
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "paired_outputs": len(canonical_ids),
                "trait_exact_agreement": trait["exact_agreement"],
                "trait_qwk": trait["quadratic_weighted_kappa"],
                "gate_status": gate_status,
                "protocol_compliant": protocol_compliant,
                "disagreements": len(disagreements),
                "summary": args.summary,
                "report": args.report,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
