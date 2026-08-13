from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import jsonschema

from research_foundation.audit import jaccard, normalize_text, word_ngrams
from research_foundation.phase3_data_contract import (
    LOCAL_PACKET_PATH,
    REVIEW_SCHEMA_PATH,
    _contains_raw_text_key,
    _jsonl_bytes,
    _phase_2_exclusions,
    _sampling_stratum,
    _source_family_id,
    blank_phase_3_review,
    validate_phase_3_review_rows,
)
from research_foundation.public_pilot import iter_jsonl, stable_digest, write_jsonl
from research_foundation.representation_freeze import canonical_content_sha256, content_sha256


CONTRACT_PATH = "configs/research/phase_3_isolation_and_expansion_contract_v0_2.json"
CONTRACT_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_isolation_and_expansion_contract_v0_2.schema.json"
MANIFEST_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_expansion_candidate_manifest_v0_1.schema.json"
ISOLATION_MANIFEST_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_provisional_isolation_manifest_v0_1.schema.json"
SEMANTIC_REVIEW_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_isolation_semantic_review_v0_1.schema.json"
EXISTING_MANIFEST_PATH = "data/research_foundation/manifests/phase_3_family_candidate_manifest_v0_1.json"
ISOLATION_MANIFEST_PATH = "data/research_foundation/manifests/phase_3_provisional_isolation_families_v0_1.json"
SEMANTIC_REVIEW_PACKET_PATH = "results/local_artifacts/research_foundation/phase_3/phase_3_isolation_semantic_merge_review_packet_v0_1.jsonl"
NEAR_DUPLICATE_THRESHOLD = 0.90
TARGET_AXIS = "boundary-preserving-over-accommodating"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_locator(locator: dict[str, Any]) -> str:
    return json.dumps(locator, sort_keys=True, separators=(",", ":"))


def build_phase_3_expansion_candidates(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = _read_json(root / CONTRACT_PATH)
    jsonschema.validate(contract, _read_json(root / CONTRACT_SCHEMA_PATH))
    for path_key, hash_key in (
        ("review_acceptance_path", "review_acceptance_sha256"),
        ("isolation_audit_path", "isolation_audit_sha256"),
        ("preceding_data_contract_path", "preceding_data_contract_sha256"),
    ):
        if canonical_content_sha256(_read_json(root / contract[path_key])) != contract[hash_key]:
            raise ValueError(f"Frozen evidence hash mismatch: {contract[path_key]}")

    preceding_contract = _read_json(root / contract["preceding_data_contract_path"])
    phase_2_hashes, phase_2_locators = _phase_2_exclusions(root, preceding_contract)
    existing_manifest = _read_json(root / EXISTING_MANIFEST_PATH)
    existing_hashes = {
        value
        for row in existing_manifest["records"]
        for value in [row["content_sha256"], row["prompt_sha256"], *row["response_sha256"]]
    }
    existing_locators = {
        _canonical_locator(row["source_locator"])
        for row in existing_manifest["records"]
    }
    existing_review_rows = [row for _, row in iter_jsonl(root / LOCAL_PACKET_PATH)]
    if len(existing_review_rows) != 180:
        raise ValueError("Existing Phase 3 review packet no longer contains 180 rows")
    accepted_normalized_prompts = {normalize_text(row["prompt"]) for row in existing_review_rows}
    accepted_shingles = [word_ngrams(row["prompt"]) for row in existing_review_rows]

    sampling = contract["expansion_sampling"]
    quotas = {
        "mixed_safety": int(sampling["mixed_safety_per_model"]),
        "both_safe": int(sampling["both_safe_per_model"]),
    }
    candidates_by_bucket: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rejection_counts: Counter[str] = Counter()
    for model_family, relative_path in sorted(contract["source"]["model_paths"].items()):
        buckets = {stratum: [] for stratum in quotas}
        for line_number, row in iter_jsonl(root / relative_path):
            if any(not str(row.get(field, "")).strip() for field in ("prompt", "response_0", "response_1")):
                rejection_counts["empty_text"] += 1
                continue
            stratum = _sampling_stratum(row)
            if stratum is None:
                rejection_counts["both_unsafe"] += 1
                continue
            locator = {
                "model_family": model_family,
                "source_split": "train",
                "lf_record_number": line_number,
            }
            pair_hash = stable_digest(row["prompt"], row["response_0"], row["response_1"])
            hashes = {
                pair_hash,
                content_sha256(row["prompt"]),
                content_sha256(row["response_0"]),
                content_sha256(row["response_1"]),
            }
            locator_key = _canonical_locator(locator)
            if hashes & phase_2_hashes or locator_key in phase_2_locators:
                rejection_counts["phase_2"] += 1
                continue
            if hashes & existing_hashes or locator_key in existing_locators:
                rejection_counts["existing_180"] += 1
                continue
            buckets[stratum].append(
                {
                    **row,
                    "_model_family": model_family,
                    "_locator": locator,
                    "_stratum": stratum,
                    "_content_sha256": pair_hash,
                    "_rank": stable_digest(
                        sampling["seed"], model_family, stratum, line_number, pair_hash
                    ),
                }
            )
        for stratum, values in buckets.items():
            candidates_by_bucket[(model_family, stratum)] = sorted(values, key=lambda item: item["_rank"])

    selected: list[dict[str, Any]] = []
    for model_family, stratum in sorted(candidates_by_bucket):
        bucket_count = 0
        for row in candidates_by_bucket[(model_family, stratum)]:
            normalized = normalize_text(row["prompt"])
            if normalized in accepted_normalized_prompts:
                rejection_counts["exact_or_normalized_prompt"] += 1
                continue
            shingles = word_ngrams(row["prompt"])
            if any(jaccard(shingles, prior) >= NEAR_DUPLICATE_THRESHOLD for prior in accepted_shingles):
                rejection_counts["near_duplicate_prompt"] += 1
                continue
            selected.append(row)
            accepted_normalized_prompts.add(normalized)
            accepted_shingles.append(shingles)
            bucket_count += 1
            if bucket_count == quotas[stratum]:
                break
        if bucket_count != quotas[stratum]:
            raise ValueError(f"Insufficient isolated expansion candidates for {model_family}/{stratum}")

    revision = contract["source"]["revision"]
    review_rows: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    for source in sorted(selected, key=lambda item: item["_content_sha256"]):
        candidate_id = "p3fam_" + source["_content_sha256"][:20]
        response_hashes = [content_sha256(source[f"response_{index}"]) for index in (0, 1)]
        proposed_family = {
            "task_family_id": "safety_helpfulness_preference_pending_human",
            "scenario_family_id": f"pending_human_{candidate_id}",
            "prompt_template_id": "source_prompt_unknown_pending_human",
            "semantic_cluster_id": f"pending_human_{candidate_id}",
            "assignment_status": "machine_proposed_pending_human",
        }
        review_rows.append(
            {
                "schema_version": "phase_3_family_review_v0_1",
                "dataset_id": "pku_safe_rlhf",
                "candidate_id": candidate_id,
                "source_family_id": _source_family_id(source["_model_family"], revision),
                "source_locator": source["_locator"],
                "content_warning": "Safety research source may contain harmful requests or responses; do not redistribute raw text.",
                "prompt": source["prompt"],
                "responses": [
                    {
                        "response_id": f"response_{index}",
                        "text": source[f"response_{index}"],
                        "content_sha256": response_hashes[index],
                    }
                    for index in (0, 1)
                ],
                "source_labels": {
                    "is_response_0_safe": source["is_response_0_safe"],
                    "is_response_1_safe": source["is_response_1_safe"],
                    "better_response_id": source["better_response_id"],
                    "safer_response_id": source["safer_response_id"],
                    "sampling_stratum": source["_stratum"],
                },
                "content_sha256": source["_content_sha256"],
                "candidate_trait_axes": [TARGET_AXIS],
                "proposed_family_assignment": proposed_family,
                "human_review": blank_phase_3_review(),
            }
        )
        isolation_id = "p3iso_" + stable_digest(candidate_id)[:20]
        manifest_records.append(
            {
                "candidate_id": candidate_id,
                "dataset_id": "pku_safe_rlhf",
                "source_revision": revision,
                "source_family_id": review_rows[-1]["source_family_id"],
                "source_locator": source["_locator"],
                "sampling_stratum": source["_stratum"],
                "prompt_sha256": content_sha256(source["prompt"]),
                "response_sha256": response_hashes,
                "content_sha256": source["_content_sha256"],
                "candidate_trait_axes": [TARGET_AXIS],
                "provisional_isolation_family_id": isolation_id,
                "isolation_review_status": "pending_human_semantic_merge_review",
                "human_review_status": "pending",
                "split_status": "not_assigned_before_all_reviews",
            }
        )

    validate_phase_3_review_rows(review_rows, _read_json(root / REVIEW_SCHEMA_PATH))
    packet_bytes = _jsonl_bytes(review_rows)
    model_counts = Counter(row["source_locator"]["model_family"] for row in manifest_records)
    stratum_counts = Counter(row["sampling_stratum"] for row in manifest_records)
    manifest = {
        "manifest_version": "phase_3_expansion_candidate_manifest_v0_1",
        "status": "expansion_generated_pending_human_review_and_semantic_isolation_review_no_split",
        "contract": {
            "path": CONTRACT_PATH,
            "sha256": canonical_content_sha256(contract),
            "hash_basis": "canonical_json_sort_keys_compact_utf8",
        },
        "sampling": {
            **sampling,
            "observed_model_family_counts": dict(sorted(model_counts.items())),
            "observed_stratum_counts": dict(sorted(stratum_counts.items())),
            "rejection_counts": dict(sorted(rejection_counts.items())),
        },
        "isolation_policy": contract["isolation_policy"],
        "local_review_packet": {
            "path": contract["local_review_packet_path"],
            "tracked": False,
            "row_count": len(review_rows),
            "sha256": sha256(packet_bytes).hexdigest(),
            "schema_path": REVIEW_SCHEMA_PATH,
        },
        "records": manifest_records,
        "checks": [
            {"check_id": "candidate_count_60", "status": "pass"},
            {"check_id": "phase_2_overlap_zero", "status": "pass"},
            {"check_id": "confirmed_180_overlap_zero", "status": "pass"},
            {"check_id": "exact_normalized_prompt_overlap_zero", "status": "pass"},
            {"check_id": "token_3gram_jaccard_at_or_above_0_90_overlap_zero", "status": "pass"},
            {"check_id": "unique_candidate_content_and_provisional_isolation_ids", "status": "pass"},
            {"check_id": "raw_text_in_tracked_manifest", "status": "pass"},
            {"check_id": "human_review_pending", "status": "pass"},
            {"check_id": "semantic_isolation_merge_review_pending", "status": "pass"},
            {"check_id": "split_assignment_zero", "status": "pass"},
        ],
        "claim_boundary": contract["claim_boundary"],
    }
    if len({row["candidate_id"] for row in manifest_records}) != 60:
        raise ValueError("Expansion candidate IDs are not unique")
    if len({row["content_sha256"] for row in manifest_records}) != 60:
        raise ValueError("Expansion content hashes are not unique")
    if len({row["provisional_isolation_family_id"] for row in manifest_records}) != 60:
        raise ValueError("Expansion provisional isolation IDs are unexpectedly merged")
    if _contains_raw_text_key(manifest):
        raise ValueError("Tracked expansion manifest contains raw text")
    jsonschema.validate(manifest, _read_json(root / MANIFEST_SCHEMA_PATH))
    return review_rows, manifest


def build_provisional_isolation_artifacts(
    root: Path,
    expansion_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = _read_json(root / CONTRACT_PATH)
    existing_rows = [row for _, row in iter_jsonl(root / LOCAL_PACKET_PATH)]
    combined = [
        ("confirmed_180", row) for row in existing_rows
    ] + [
        ("expansion_60", row) for row in expansion_rows
    ]
    if len(combined) != 240 or len({row["candidate_id"] for _, row in combined}) != 240:
        raise ValueError("Combined isolation review population must contain 240 unique candidates")

    parent = list(range(len(combined)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    normalized = [normalize_text(row["prompt"]) for _, row in combined]
    shingles = [word_ngrams(row["prompt"]) for _, row in combined]
    for left in range(len(combined)):
        for right in range(left + 1, len(combined)):
            if normalized[left] == normalized[right] or jaccard(shingles[left], shingles[right]) >= NEAR_DUPLICATE_THRESHOLD:
                union(left, right)
    groups: dict[int, list[int]] = {}
    for index in range(len(combined)):
        groups.setdefault(find(index), []).append(index)
    component_ids = {
        root_index: "p3iso_" + stable_digest(
            *sorted(combined[index][1]["candidate_id"] for index in indices)
        )[:20]
        for root_index, indices in groups.items()
    }

    semantic_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, (cohort, row) in enumerate(combined):
        root_index = find(index)
        linked = sorted(
            combined[other][1]["candidate_id"]
            for other in groups[root_index]
            if other != index
        )
        isolation_id = component_ids[root_index]
        semantic_rows.append(
            {
                "schema_version": "phase_3_isolation_semantic_review_v0_1",
                "candidate_id": row["candidate_id"],
                "cohort": cohort,
                "prompt": row["prompt"],
                "prompt_sha256": content_sha256(row["prompt"]),
                "provisional_isolation_family_id": isolation_id,
                "machine_linked_candidate_ids": linked,
                "human_review": {
                    "decision": None,
                    "reviewed_isolation_family_id": None,
                    "merge_with_candidate_ids": [],
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "notes": "",
                },
            }
        )
        records.append(
            {
                "candidate_id": row["candidate_id"],
                "cohort": cohort,
                "prompt_sha256": content_sha256(row["prompt"]),
                "provisional_isolation_family_id": isolation_id,
                "component_size": len(groups[root_index]),
                "machine_linked_candidate_ids": linked,
                "isolation_review_status": "pending_human_semantic_merge_review",
                "split_status": "not_assigned_before_all_reviews",
            }
        )

    semantic_rows.sort(key=lambda row: row["candidate_id"])
    records.sort(key=lambda row: row["candidate_id"])
    semantic_schema = _read_json(root / SEMANTIC_REVIEW_SCHEMA_PATH)
    for row in semantic_rows:
        jsonschema.validate(row, semantic_schema)
    packet_bytes = _jsonl_bytes(semantic_rows)
    manifest = {
        "manifest_version": "phase_3_provisional_isolation_manifest_v0_1",
        "status": "provisional_components_pending_human_semantic_merge_review_no_split",
        "contract": {
            "path": CONTRACT_PATH,
            "sha256": canonical_content_sha256(contract),
        },
        "cohort_counts": {"confirmed_180": 180, "expansion_60": 60},
        "construction": {
            "fields": ["exact_prompt", "normalized_prompt", "prompt_token_3gram_jaccard"],
            "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
            "component_count": len(groups),
            "largest_component_size": max(len(indices) for indices in groups.values()),
            "semantic_model_run": False,
        },
        "local_semantic_review_packet": {
            "path": SEMANTIC_REVIEW_PACKET_PATH,
            "tracked": False,
            "row_count": len(semantic_rows),
            "sha256": sha256(packet_bytes).hexdigest(),
            "schema_path": SEMANTIC_REVIEW_SCHEMA_PATH,
        },
        "records": records,
        "checks": [
            {"check_id": "combined_candidate_count_240", "status": "pass"},
            {"check_id": "candidate_id_unique", "status": "pass"},
            {"check_id": "prompt_hash_unique", "status": "pass"},
            {"check_id": "exact_normalized_component_construction", "status": "pass"},
            {"check_id": "token_3gram_threshold_component_construction", "status": "pass"},
            {"check_id": "human_semantic_merge_review_pending", "status": "pass"},
            {"check_id": "split_assignment_zero", "status": "pass"},
            {"check_id": "raw_text_in_tracked_manifest", "status": "pass"},
        ],
        "claim_boundary": (
            "These are provisional mechanical isolation components. Human semantic merge review is required, "
            "broad family labels remain stratification metadata, and no record has a split assignment."
        ),
    }
    if len({row["prompt_sha256"] for row in records}) != 240:
        raise ValueError("Combined isolation population contains duplicate prompts")
    if _contains_raw_text_key(manifest):
        raise ValueError("Tracked provisional isolation manifest contains raw text")
    jsonschema.validate(manifest, _read_json(root / ISOLATION_MANIFEST_SCHEMA_PATH))
    return semantic_rows, manifest


def write_phase_3_expansion_candidates(root: Path) -> dict[str, Any]:
    rows, manifest = build_phase_3_expansion_candidates(root)
    contract = _read_json(root / CONTRACT_PATH)
    write_jsonl(root / contract["local_review_packet_path"], rows)
    path = root / contract["tracked_manifest_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    semantic_rows, isolation_manifest = build_provisional_isolation_artifacts(root, rows)
    write_jsonl(root / SEMANTIC_REVIEW_PACKET_PATH, semantic_rows)
    isolation_path = root / ISOLATION_MANIFEST_PATH
    isolation_path.parent.mkdir(parents=True, exist_ok=True)
    isolation_path.write_text(
        json.dumps(isolation_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
