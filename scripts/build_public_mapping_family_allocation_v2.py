from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import itertools
import json
from pathlib import Path
import random
import re
import sys
import unicodedata
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.public_mapping_v2 import (  # noqa: E402
    FAMILY_REVIEW_FIELDS,
    expected_identity_index,
    family_split_records_v2,
    load_axis_poles,
    read_jsonl,
    reviewed_family_candidates_v2,
    validate_completed_review_v2,
    validate_rows_against_schema_v2,
)


ISOLATED_FAMILY_FIELDS = (
    "task_family_id",
    "scenario_family_id",
    "prompt_template_id",
    "semantic_cluster_id",
)
SPLITS = ("train", "dev", "test")
TARGET_RATIOS = {"train": 0.70, "dev": 0.15, "test": 0.15}


def timestamp_with_timezone() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stable_digest(*parts: str, length: int = 20) -> str:
    return sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:length]


def build_family_components(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unit_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        unit_rows[candidate["allocation_unit_id"]].append(candidate)
    unit_ids = sorted(unit_rows)
    unit_index = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    parent = list(range(len(unit_ids)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    family_owner: dict[tuple[str, str], int] = {}
    for unit_id in unit_ids:
        index = unit_index[unit_id]
        representative = unit_rows[unit_id][0]
        for field in ISOLATED_FAMILY_FIELDS:
            token = (field, representative[field])
            previous = family_owner.setdefault(token, index)
            union(index, previous)

    grouped: dict[int, list[str]] = defaultdict(list)
    for unit_id in unit_ids:
        grouped[find(unit_index[unit_id])].append(unit_id)
    components: list[dict[str, Any]] = []
    for component_units in grouped.values():
        sorted_units = sorted(component_units)
        rows = [row for unit_id in sorted_units for row in unit_rows[unit_id]]
        components.append(
            {
                "component_id": "famc_" + stable_digest(*sorted_units),
                "allocation_unit_ids": sorted_units,
                "candidate_count": len(rows),
                "source_sample_count": len({row["source_sample_id"] for row in rows}),
                "axis_counts": dict(sorted(Counter(row["axis_id"] for row in rows).items())),
                "pole_counts": dict(sorted(Counter(row["pole"] for row in rows).items())),
            }
        )
    return sorted(components, key=lambda item: item["component_id"])


def allocate_components(
    components: list[dict[str, Any]], seed: int
) -> tuple[dict[str, str], dict[str, int]]:
    if len(components) < len(SPLITS):
        raise ValueError("Fewer family components than required non-empty splits")
    total = sum(component["candidate_count"] for component in components)
    target = {split: total * TARGET_RATIOS[split] for split in SPLITS}
    rng = random.Random(seed)
    tie_break = {component["component_id"]: rng.random() for component in components}
    best: tuple[tuple[float, float, float], tuple[str, ...]] | None = None
    for assignment in itertools.product(SPLITS, repeat=len(components)):
        counts = {split: 0 for split in SPLITS}
        for component, split in zip(components, assignment):
            counts[split] += component["candidate_count"]
        if any(counts[split] == 0 for split in SPLITS):
            continue
        ratio_error = sum(abs(counts[split] - target[split]) for split in SPLITS)
        largest_error = max(abs(counts[split] - target[split]) for split in SPLITS)
        train_not_largest = float(counts["train"] < max(counts["dev"], counts["test"]))
        deterministic_tie = sum(
            tie_break[component["component_id"]] * (SPLITS.index(split) + 1)
            for component, split in zip(components, assignment)
        )
        score = (train_not_largest, ratio_error, largest_error + deterministic_tie * 1e-6)
        if best is None or score < best[0]:
            best = (score, assignment)
    if best is None:
        raise ValueError("No non-empty component allocation was found")
    assignment = best[1]
    component_split = {
        component["component_id"]: split
        for component, split in zip(components, assignment)
    }
    unit_split = {
        unit_id: component_split[component["component_id"]]
        for component in components
        for unit_id in component["allocation_unit_ids"]
    }
    counts = {split: 0 for split in SPLITS}
    for component in components:
        counts[component_split[component["component_id"]]] += component["candidate_count"]
    return unit_split, counts


def normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def token_shingles(value: str, width: int = 3) -> set[tuple[str, ...]]:
    tokens = normalized_text(value).split()
    if not tokens:
        return set()
    if len(tokens) < width:
        return {tuple(tokens)}
    return {tuple(tokens[index : index + width]) for index in range(len(tokens) - width + 1)}


def jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def candidate_text(candidate: dict[str, Any], review_by_id: dict[str, dict[str, Any]]) -> str:
    source = review_by_id[candidate["source_sample_id"]]
    if source["dataset_id"] == "empathetic_dialogues":
        return "\n".join(
            [source["situation_prompt"], source["user_utterance"], source["candidate_response"]]
        )
    response_id = candidate["response_id"]
    if response_id not in {"response_0", "response_1"}:
        raise ValueError(f"Invalid PKU response_id: {response_id}")
    return "\n".join([source["prompt"], source[response_id]])


def overlap_values_by_split(
    candidates: list[dict[str, Any]], unit_split: dict[str, str], field: str
) -> dict[str, list[str]]:
    value_splits: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        value_splits[candidate[field]].add(unit_split[candidate["allocation_unit_id"]])
    return {
        value: sorted(splits)
        for value, splits in sorted(value_splits.items())
        if len(splits) > 1
    }


def build_leakage_audit(
    candidates: list[dict[str, Any]],
    unit_split: dict[str, str],
    review_by_id: dict[str, dict[str, Any]],
    evidence_path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fingerprints: list[dict[str, Any]] = []
    for candidate in candidates:
        raw = candidate_text(candidate, review_by_id)
        normalized = normalized_text(raw)
        fingerprints.append(
            {
                "sample_id": candidate["sample_id"],
                "source_sample_id": candidate["source_sample_id"],
                "split": unit_split[candidate["allocation_unit_id"]],
                "exact_sha256": sha256(raw.encode("utf-8")).hexdigest(),
                "normalized_sha256": sha256(normalized.encode("utf-8")).hexdigest(),
                "shingles": token_shingles(raw),
            }
        )

    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_splits: dict[str, set[str]] = defaultdict(set)
    for item in fingerprints:
        exact_groups[item["exact_sha256"]].append(item)
        normalized_groups[item["normalized_sha256"]].append(item)
        source_splits[item["source_sample_id"]].add(item["split"])
    exact_cross_split = [
        {"sample_ids": sorted(row["sample_id"] for row in group), "splits": sorted({row["split"] for row in group})}
        for group in exact_groups.values()
        if len({row["split"] for row in group}) > 1
    ]
    normalized_cross_split = [
        {"sample_ids": sorted(row["sample_id"] for row in group), "splits": sorted({row["split"] for row in group})}
        for group in normalized_groups.values()
        if len({row["split"] for row in group}) > 1
    ]
    source_sample_cross_split = {
        sample_id: sorted(splits)
        for sample_id, splits in sorted(source_splits.items())
        if len(splits) > 1
    }
    near_duplicate_pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(fingerprints):
        for right in fingerprints[left_index + 1 :]:
            if left["split"] == right["split"]:
                continue
            similarity = jaccard(left["shingles"], right["shingles"])
            if similarity >= 0.90:
                near_duplicate_pairs.append(
                    {
                        "sample_id_a": left["sample_id"],
                        "split_a": left["split"],
                        "sample_id_b": right["sample_id"],
                        "split_b": right["split"],
                        "token_3gram_jaccard": round(similarity, 6),
                    }
                )

    family_overlaps = {
        field: overlap_values_by_split(candidates, unit_split, field)
        for field in ("source_family_id", *ISOLATED_FAMILY_FIELDS)
    }
    split_axis_counts: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
    split_pole_counts: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
    for candidate in candidates:
        split = unit_split[candidate["allocation_unit_id"]]
        split_axis_counts[split][candidate["axis_id"]] += 1
        split_pole_counts[split][f"{candidate['axis_id']}::{candidate['pole']}"] += 1
    all_axes = sorted({candidate["axis_id"] for candidate in candidates})
    missing_axes = {
        split: sorted(set(all_axes) - set(split_axis_counts[split])) for split in SPLITS
    }

    checks: list[dict[str, Any]] = []

    def add(check_id: str, status: str) -> None:
        checks.append({"check_id": check_id, "status": status, "evidence_path": evidence_path})

    add("exact_content_hash_cross_split", "pass" if not exact_cross_split else "fail")
    add("normalized_content_hash_cross_split", "pass" if not normalized_cross_split else "fail")
    add("token_3gram_near_duplicate_cross_split", "pass" if not near_duplicate_pairs else "fail")
    add("source_sample_cross_split", "pass" if not source_sample_cross_split else "fail")
    for field in ISOLATED_FAMILY_FIELDS:
        add(f"{field}_cross_split", "pass" if not family_overlaps[field] else "fail")
    add(
        "source_family_id_cross_split",
        "pass" if not family_overlaps["source_family_id"] else "human_review_required",
    )
    add(
        "axis_coverage_all_splits",
        "pass" if all(not missing_axes[split] for split in SPLITS) else "human_review_required",
    )
    audit = {
        "schema_version": "public_mapping_family_leakage_audit_v0_1",
        "created_at": timestamp_with_timezone(),
        "candidate_count": len(candidates),
        "checks": checks,
        "exact_cross_split_groups": exact_cross_split,
        "normalized_cross_split_groups": normalized_cross_split,
        "near_duplicate_threshold": {"metric": "token_3gram_jaccard", "threshold": 0.90},
        "near_duplicate_cross_split_pairs": near_duplicate_pairs,
        "source_sample_cross_split": source_sample_cross_split,
        "family_overlaps": family_overlaps,
        "axis_counts_by_split": {
            split: dict(sorted(split_axis_counts[split].items())) for split in SPLITS
        },
        "pole_counts_by_split": {
            split: dict(sorted(split_pole_counts[split].items())) for split in SPLITS
        },
        "missing_axes_by_split": missing_axes,
        "content_policy": "Raw prompts and responses were hashed in memory and are not emitted.",
    }
    return audit, checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a family-connected allocation candidate and leakage evidence from completed v0.2 reviews."
    )
    parser.add_argument("--reviews", nargs="+", required=True)
    parser.add_argument(
        "--mapping-manifest",
        default="data/research_foundation/manifests/public_mapping_pilot_v0_2.json",
    )
    parser.add_argument("--axis-registry", default="data/trait_space/axis_registry.yaml")
    parser.add_argument(
        "--review-schema",
        default="data/research_foundation/schemas/public_mapping_review_v0_2.schema.json",
    )
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--allocation-manifest", required=True)
    parser.add_argument("--leakage-evidence", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping_manifest = json.loads((ROOT / args.mapping_manifest).read_text(encoding="utf-8"))
    rows = [row for value in args.reviews for row in read_jsonl(ROOT / value)]
    errors = validate_rows_against_schema_v2(rows, ROOT / args.review_schema)
    errors.extend(
        validate_completed_review_v2(
            rows,
            load_axis_poles(ROOT / args.axis_registry),
            expected_identity_index(mapping_manifest),
        )
    )
    if errors:
        raise ValueError(f"Review validation failed with {len(errors)} errors; no allocation was written")
    candidates = reviewed_family_candidates_v2(rows)
    if not candidates:
        raise ValueError("No accepted human-reviewed candidates are available")
    components = build_family_components(candidates)
    unit_split, split_counts = allocate_components(components, args.seed)
    review_by_id = {row["sample_id"]: row for row in rows}
    audit, checks = build_leakage_audit(
        candidates, unit_split, review_by_id, args.leakage_evidence
    )
    component_split = {
        component["component_id"]: unit_split[component["allocation_unit_ids"][0]]
        for component in components
    }
    allocation_units = []
    candidate_by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        candidate_by_unit[candidate["allocation_unit_id"]].append(candidate)
    component_by_unit = {
        unit_id: component["component_id"]
        for component in components
        for unit_id in component["allocation_unit_ids"]
    }
    for unit_id in sorted(candidate_by_unit):
        representative = candidate_by_unit[unit_id][0]
        allocation_units.append(
            {
                "allocation_unit_id": unit_id,
                "component_id": component_by_unit[unit_id],
                "split": unit_split[unit_id],
                "candidate_count": len(candidate_by_unit[unit_id]),
                "source_family_id": representative["source_family_id"],
                **{field: representative[field] for field in FAMILY_REVIEW_FIELDS},
            }
        )
    manifest = {
        "manifest_version": "public_mapping_family_allocation_v0_1",
        "dataset_version": "public_mapping_family_split_v2_candidate",
        "created_at": timestamp_with_timezone(),
        "random_seed": args.seed,
        "allocation_strategy": {
            "atomic_unit": "five_family_tuple",
            "connected_component_fields": list(ISOLATED_FAMILY_FIELDS),
            "target_ratios": TARGET_RATIOS,
            "source_family_policy": (
                "provenance_preserved_but_not_component_isolated; isolating source_family_id collapses "
                "the pilot to two components and prevents a three-way split"
            ),
        },
        "test_access_policy": {
            "frozen": False,
            "allowed_uses": [
                "split feasibility review",
                "family leakage audit",
                "eligibility pilot analysis",
            ],
            "forbidden_uses": [
                "frozen independent test evaluation",
                "model selection",
                "training without a separate data card and approval",
                "Trait gold-label claims",
            ],
            "access_log_path": "results/local_artifacts/research_foundation/public_mapping_family_split_v2_access_log.jsonl",
        },
        "components": [
            {**component, "split": component_split[component["component_id"]]}
            for component in components
        ],
        "allocation_units": allocation_units,
        "split_candidate_counts": split_counts,
        "leakage_checks": checks,
        "human_review_status": "complete",
        "candidate_status": "generated_not_frozen",
    }
    allocation_path = ROOT / args.allocation_manifest
    evidence_path = ROOT / args.leakage_evidence
    allocation_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    allocation_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "review_rows": len(rows),
                "accepted_candidates": len(candidates),
                "allocation_units": len(allocation_units),
                "family_components": len(components),
                "split_candidate_counts": split_counts,
                "check_status_counts": dict(Counter(check["status"] for check in checks)),
                "allocation_manifest": args.allocation_manifest,
                "leakage_evidence": args.leakage_evidence,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
