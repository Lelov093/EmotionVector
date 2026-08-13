from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import itertools
import json
import random
import re
from typing import Any, Iterable
import unicodedata

from research_foundation.public_mapping_v2 import FAMILY_REVIEW_FIELDS


TARGET_AXIS = "boundary-preserving-over-accommodating"
TARGET_POLES = ("boundary-preserving", "over-accommodating")
ISOLATED_FAMILY_FIELDS = tuple(FAMILY_REVIEW_FIELDS)
SPLITS = ("train", "dev", "test")
TARGET_RATIOS = {"train": 0.50, "dev": 0.25, "test": 0.25}


def stable_digest(*parts: str, length: int = 20) -> str:
    return sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:length]


def content_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


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
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def representation_pairs(
    rows: Iterable[dict[str, Any]],
    axis_id: str = TARGET_AXIS,
    source_revision: str | None = None,
) -> list[dict[str, Any]]:
    """Return only human-accepted, opposite-pole PKU pairs for representation work.

    `same_axis_not_opposite`, partially annotated, rewritten, ambiguous, and
    rejected records are intentionally excluded. Raw text is used only to
    derive hashes and is never returned.
    """
    pairs: list[dict[str, Any]] = []
    for row in rows:
        if row.get("dataset_id") != "pku_safe_rlhf":
            continue
        review = row.get("human_review") or {}
        contrast = review.get("pair_contrast") or {}
        if review.get("mapping_decision") != "accept":
            continue
        if contrast.get("status") != "valid_single_axis" or contrast.get("axis_id") != axis_id:
            continue
        family = review.get("reviewed_family_assignment") or {}
        if any(not isinstance(family.get(field), str) or not family[field] for field in FAMILY_REVIEW_FIELDS):
            raise ValueError(f"{row.get('sample_id')}: accepted representation pair lacks reviewed families")
        annotations = review.get("response_annotations") or []
        if len(annotations) != 2:
            raise ValueError(f"{row.get('sample_id')}: representation pair must have two responses")
        by_response = {annotation.get("response_id"): annotation for annotation in annotations}
        if set(by_response) != {"response_0", "response_1"}:
            raise ValueError(f"{row.get('sample_id')}: response ids must be response_0/response_1")
        observed_poles = {
            (annotation.get("trait_annotation") or {}).get("pole")
            for annotation in annotations
        }
        observed_axes = {
            (annotation.get("trait_annotation") or {}).get("axis_id")
            for annotation in annotations
        }
        if observed_axes != {axis_id} or observed_poles != set(TARGET_POLES):
            raise ValueError(f"{row.get('sample_id')}: valid contrast is not an opposite-pole target pair")
        sample_id = row["sample_id"]
        responses = []
        for response_id in ("response_0", "response_1"):
            annotation = by_response[response_id]
            responses.append(
                {
                    "sample_id": f"{sample_id}__{response_id}",
                    "response_id": response_id,
                    "pole": annotation["trait_annotation"]["pole"],
                    "behavior": annotation["behavior"],
                    "content_sha256": content_sha256(row[response_id]),
                }
            )
        pairs.append(
            {
                "pair_id": "reprpair_" + stable_digest(sample_id),
                "dataset_id": row["dataset_id"],
                "source_revision": source_revision or row["source_family_id"].split("_", 4)[3],
                "source_sample_id": sample_id,
                "source_family_id": row["source_family_id"],
                **{field: family[field] for field in FAMILY_REVIEW_FIELDS},
                "axis_id": axis_id,
                "contrast_status": "valid_single_axis",
                "prompt_sha256": content_sha256(row["prompt"]),
                "pair_content_sha256": row["content_sha256"],
                "responses": responses,
                "_normalized_content_sha256": content_sha256(
                    normalized_text("\n".join([row["prompt"], row["response_0"], row["response_1"]]))
                ),
                "_content_shingles": token_shingles(
                    "\n".join([row["prompt"], row["response_0"], row["response_1"]])
                ),
            }
        )
    return sorted(pairs, key=lambda pair: pair["pair_id"])


def build_family_components(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent = list(range(len(pairs)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[tuple[str, str], int] = {}
    for index, pair in enumerate(pairs):
        for field in ISOLATED_FAMILY_FIELDS:
            token = (field, pair[field])
            union(index, owners.setdefault(token, index))
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, pair in enumerate(pairs):
        groups[find(index)].append(pair)
    components = []
    for group in groups.values():
        pair_ids = sorted(pair["pair_id"] for pair in group)
        components.append(
            {
                "component_id": "reprfamc_" + stable_digest(*pair_ids),
                "pair_ids": pair_ids,
                "pair_count": len(group),
                "response_count": len(group) * 2,
            }
        )
    return sorted(components, key=lambda component: component["component_id"])


def allocate_components(
    components: list[dict[str, Any]], seed: int, minimum_heldout_pairs: int = 5
) -> tuple[dict[str, str], dict[str, int]]:
    if len(components) < len(SPLITS):
        raise ValueError("Fewer family components than required splits")
    total = sum(component["pair_count"] for component in components)
    targets = {split: total * TARGET_RATIOS[split] for split in SPLITS}
    rng = random.Random(seed)
    tie_break = {component["component_id"]: rng.random() for component in components}
    best: tuple[tuple[float, float, float], tuple[str, ...]] | None = None
    for assignment in itertools.product(SPLITS, repeat=len(components)):
        counts = {split: 0 for split in SPLITS}
        for component, split in zip(components, assignment):
            counts[split] += component["pair_count"]
        if counts["dev"] < minimum_heldout_pairs or counts["test"] < minimum_heldout_pairs:
            continue
        if counts["train"] < max(counts["dev"], counts["test"]):
            continue
        ratio_error = sum(abs(counts[split] - targets[split]) for split in SPLITS)
        heldout_imbalance = abs(counts["dev"] - counts["test"])
        deterministic_tie = sum(
            tie_break[component["component_id"]] * (SPLITS.index(split) + 1)
            for component, split in zip(components, assignment)
        )
        score = (ratio_error, heldout_imbalance, deterministic_tie)
        if best is None or score < best[0]:
            best = (score, assignment)
    if best is None:
        raise ValueError("No allocation satisfies the frozen pair-count constraints")
    component_split = {
        component["component_id"]: split
        for component, split in zip(components, best[1])
    }
    pair_split = {
        pair_id: component_split[component["component_id"]]
        for component in components
        for pair_id in component["pair_ids"]
    }
    counts = Counter(pair_split.values())
    return pair_split, {split: counts[split] for split in SPLITS}


def family_overlaps(records: list[dict[str, Any]], field: str) -> dict[str, list[str]]:
    value_splits: dict[str, set[str]] = defaultdict(set)
    for record in records:
        value_splits[record[field]].add(record["split"])
    return {
        value: sorted(splits)
        for value, splits in sorted(value_splits.items())
        if len(splits) > 1
    }


def build_manifest(
    pairs: list[dict[str, Any]],
    pair_split: dict[str, str],
    components: list[dict[str, Any]],
    *,
    created_at: str,
    seed: int,
    license_decision_path: str,
    license_decision_sha256: str,
) -> dict[str, Any]:
    records = [
        {
            **{key: value for key, value in pair.items() if not key.startswith("_")},
            "split": pair_split[pair["pair_id"]],
        }
        for pair in pairs
    ]
    overlaps = {field: family_overlaps(records, field) for field in ISOLATED_FAMILY_FIELDS}
    source_overlap = family_overlaps(records, "source_family_id")
    prompt_splits: dict[str, set[str]] = defaultdict(set)
    content_splits: dict[str, set[str]] = defaultdict(set)
    for record in records:
        prompt_splits[record["prompt_sha256"]].add(record["split"])
        for response in record["responses"]:
            content_splits[response["content_sha256"]].add(record["split"])
    cross_prompt = sorted(key for key, splits in prompt_splits.items() if len(splits) > 1)
    cross_content = sorted(key for key, splits in content_splits.items() if len(splits) > 1)
    normalized_splits: dict[str, set[str]] = defaultdict(set)
    for pair in pairs:
        normalized_splits[pair["_normalized_content_sha256"]].add(pair_split[pair["pair_id"]])
    cross_normalized = sorted(key for key, splits in normalized_splits.items() if len(splits) > 1)
    near_duplicates = []
    for left_index, left in enumerate(pairs):
        for right in pairs[left_index + 1 :]:
            left_split, right_split = pair_split[left["pair_id"]], pair_split[right["pair_id"]]
            if left_split == right_split:
                continue
            similarity = jaccard(left["_content_shingles"], right["_content_shingles"])
            if similarity >= 0.90:
                near_duplicates.append(
                    {
                        "pair_id_a": left["pair_id"],
                        "split_a": left_split,
                        "pair_id_b": right["pair_id"],
                        "split_b": right_split,
                        "token_3gram_jaccard": round(similarity, 6),
                    }
                )
    checks = [
        {"check_id": f"{field}_cross_split", "status": "pass" if not values else "fail"}
        for field, values in overlaps.items()
    ]
    checks.extend(
        [
            {"check_id": "opposite_pole_pair_integrity", "status": "pass"},
            {"check_id": "valid_single_axis_only", "status": "pass"},
            {"check_id": "prompt_hash_cross_split", "status": "pass" if not cross_prompt else "fail"},
            {"check_id": "response_hash_cross_split", "status": "pass" if not cross_content else "fail"},
            {
                "check_id": "normalized_pair_hash_cross_split",
                "status": "pass" if not cross_normalized else "fail",
            },
            {
                "check_id": "token_3gram_near_duplicate_cross_split",
                "status": "pass" if not near_duplicates else "fail",
            },
            {
                "check_id": "source_family_id_cross_split",
                "status": "documented_limitation" if source_overlap else "pass",
            },
        ]
    )
    if any(check["status"] == "fail" for check in checks):
        raise ValueError("Representation split failed a mandatory freeze check")
    pair_counts = Counter(record["split"] for record in records)
    response_counts = {split: pair_counts[split] * 2 for split in SPLITS}
    pole_counts = {
        split: dict(
            sorted(
                Counter(
                    response["pole"]
                    for record in records
                    if record["split"] == split
                    for response in record["responses"]
                ).items()
            )
        )
        for split in SPLITS
    }
    return {
        "manifest_version": "representation_family_split_v2_1",
        "dataset_version": "pku_boundary_representation_pairs_v0_1",
        "created_at": created_at,
        "random_seed": seed,
        "status": "frozen_before_model_execution",
        "axis_scope": [TARGET_AXIS],
        "source_decision": {
            "path": license_decision_path,
            "sha256": license_decision_sha256,
            "hash_basis": "canonical_json_sort_keys_compact_utf8",
            "required_status": "approved_noncommercial_research_use",
        },
        "eligibility_rule": {
            "dataset_id": "pku_safe_rlhf",
            "mapping_decision": "accept",
            "contrast_status": "valid_single_axis",
            "axis_id": TARGET_AXIS,
            "required_poles": list(TARGET_POLES),
            "excluded_as_contrast": [
                "same_axis_not_opposite",
                "insufficient_trait_evidence",
                "ambiguous",
                "multi_axis",
            ],
        },
        "allocation_strategy": {
            "unit": "opposite_pole_source_pair",
            "connected_component_fields": list(ISOLATED_FAMILY_FIELDS),
            "target_ratios": TARGET_RATIOS,
            "minimum_dev_pairs": 5,
            "minimum_test_pairs": 5,
            "component_count": len(components),
            "source_family_policy": (
                "source revision is preserved but model-family values may cross splits; "
                "the dataset does not support source-family generalization claims"
            ),
        },
        "test_access_policy": {
            "frozen": True,
            "frozen_before_model_execution": True,
            "test_use": "single confirmatory opening after train/dev selection is locked",
            "allowed_uses_before_opening": ["schema validation", "hash verification", "count-only audit"],
            "forbidden_uses_before_opening": [
                "layer selection",
                "pooling selection",
                "direction selection",
                "threshold selection",
                "probe hyperparameter selection",
                "rubric revision",
            ],
            "access_log_path": "results/local_artifacts/research_foundation/representation_test_access_log_v0_1.jsonl",
        },
        "records": sorted(records, key=lambda record: record["pair_id"]),
        "components": components,
        "checks": checks,
        "audit": {
            "family_overlaps": overlaps,
            "source_family_overlaps": source_overlap,
            "cross_split_prompt_hashes": cross_prompt,
            "cross_split_response_hashes": cross_content,
            "cross_split_normalized_pair_hashes": cross_normalized,
            "near_duplicate_threshold": {"metric": "token_3gram_jaccard", "threshold": 0.90},
            "near_duplicate_cross_split_pairs": near_duplicates,
        },
        "counts": {
            "pairs": {split: pair_counts[split] for split in SPLITS},
            "responses": response_counts,
            "poles": pole_counts,
        },
        "claim_boundary": (
            "This frozen single-axis pilot supports a family-isolated held-out representation analysis. "
            "Its 26 pairs are below the original confirmatory scale target, do not establish source-family "
            "generalization, and cannot establish causal steering or personality control."
        ),
    }


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def canonical_content_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()
