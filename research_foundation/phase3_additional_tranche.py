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
from research_foundation.phase3_expansion_review import EXPANSION_PACKET_PATH
from research_foundation.public_pilot import iter_jsonl, stable_digest, write_jsonl
from research_foundation.representation_freeze import canonical_content_sha256, content_sha256


CONTRACT_PATH = "configs/research/phase_3_additional_tranche_contract_v0_3.json"
CONTRACT_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_additional_tranche_contract_v0_3.schema.json"
MANIFEST_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_additional_tranche_manifest_v0_1.schema.json"
ISOLATION_REVIEW_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_isolation_extension_review_v0_1.schema.json"
ORIGINAL_DATA_CONTRACT_PATH = "configs/research/phase_3_family_data_contract_v0_1.json"
ORIGINAL_MANIFEST_PATH = "data/research_foundation/manifests/phase_3_family_candidate_manifest_v0_1.json"
EXPANSION_MANIFEST_PATH = "data/research_foundation/manifests/phase_3_expansion_candidate_manifest_v0_1.json"
NEAR_DUPLICATE_THRESHOLD = 0.90
TARGET_AXIS = "boundary-preserving-over-accommodating"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_locator(locator: dict[str, Any]) -> str:
    return json.dumps(locator, sort_keys=True, separators=(",", ":"))


def build_phase_3_additional_tranche(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    contract = _read_json(root / CONTRACT_PATH)
    jsonschema.validate(contract, _read_json(root / CONTRACT_SCHEMA_PATH))
    for path_key, hash_key in (
        ("preceding_contract_path", "preceding_contract_sha256"),
        ("review_acceptance_path", "review_acceptance_sha256"),
        ("final_isolation_manifest_path", "final_isolation_manifest_sha256"),
    ):
        if canonical_content_sha256(_read_json(root / contract[path_key])) != contract[hash_key]:
            raise ValueError(f"Frozen evidence hash mismatch: {contract[path_key]}")

    phase_2_hashes, phase_2_locators = _phase_2_exclusions(
        root, _read_json(root / ORIGINAL_DATA_CONTRACT_PATH)
    )
    prior_manifests = [
        _read_json(root / ORIGINAL_MANIFEST_PATH),
        _read_json(root / EXPANSION_MANIFEST_PATH),
    ]
    prior_records = [record for manifest in prior_manifests for record in manifest["records"]]
    if len(prior_records) != 240:
        raise ValueError("Prior Phase 3 candidate manifests must contain 240 rows")
    prior_hashes = {
        value
        for record in prior_records
        for value in [record["content_sha256"], record["prompt_sha256"], *record["response_sha256"]]
    }
    prior_locators = {_canonical_locator(record["source_locator"]) for record in prior_records}
    prior_raw_rows = [
        row for _, row in iter_jsonl(root / LOCAL_PACKET_PATH)
    ] + [
        row for _, row in iter_jsonl(root / EXPANSION_PACKET_PATH)
    ]
    if len(prior_raw_rows) != 240:
        raise ValueError("Prior local review packets must contain 240 rows")
    accepted_normalized = {normalize_text(row["prompt"]) for row in prior_raw_rows}
    accepted_shingles = [word_ngrams(row["prompt"]) for row in prior_raw_rows]

    sampling = contract["sampling"]
    quotas = {
        "mixed_safety": int(sampling["mixed_safety_per_model"]),
        "both_safe": int(sampling["both_safe_per_model"]),
    }
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rejections: Counter[str] = Counter()
    for model_family, relative_path in sorted(contract["source"]["model_paths"].items()):
        buckets = {stratum: [] for stratum in quotas}
        for line_number, row in iter_jsonl(root / relative_path):
            if any(not str(row.get(field, "")).strip() for field in ("prompt", "response_0", "response_1")):
                rejections["empty_text"] += 1
                continue
            stratum = _sampling_stratum(row)
            if stratum is None:
                rejections["both_unsafe"] += 1
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
                rejections["phase_2"] += 1
                continue
            if hashes & prior_hashes or locator_key in prior_locators:
                rejections["reviewed_240"] += 1
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
            candidates[(model_family, stratum)] = sorted(values, key=lambda item: item["_rank"])

    selected: list[dict[str, Any]] = []
    for model_family, stratum in sorted(candidates):
        count = 0
        for row in candidates[(model_family, stratum)]:
            normalized = normalize_text(row["prompt"])
            if normalized in accepted_normalized:
                rejections["exact_or_normalized_prompt"] += 1
                continue
            shingles = word_ngrams(row["prompt"])
            if any(jaccard(shingles, prior) >= NEAR_DUPLICATE_THRESHOLD for prior in accepted_shingles):
                rejections["near_duplicate_prompt"] += 1
                continue
            selected.append(row)
            accepted_normalized.add(normalized)
            accepted_shingles.append(shingles)
            count += 1
            if count == quotas[stratum]:
                break
        if count != quotas[stratum]:
            raise ValueError(f"Insufficient isolated candidates for {model_family}/{stratum}")

    revision = contract["source"]["revision"]
    review_rows: list[dict[str, Any]] = []
    isolation_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    comparison_population = {
        "final_isolation_manifest_path": contract["final_isolation_manifest_path"],
        "final_isolation_manifest_sha256": contract["final_isolation_manifest_sha256"],
        "existing_candidate_count": 240,
        "existing_final_family_count": 189,
    }
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
        isolation_rows.append(
            {
                "schema_version": "phase_3_isolation_extension_review_v0_1",
                "candidate_id": candidate_id,
                "cohort": "additional_30_v0_3",
                "prompt": source["prompt"],
                "prompt_sha256": content_sha256(source["prompt"]),
                "provisional_isolation_family_id": isolation_id,
                "comparison_population": comparison_population,
                "machine_linked_candidate_ids": [],
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
                "human_review_status": "pending",
                "isolation_review_status": "pending_human_semantic_merge_review",
                "split_status": "not_assigned_before_all_reviews",
            }
        )

    validate_phase_3_review_rows(review_rows, _read_json(root / REVIEW_SCHEMA_PATH))
    isolation_schema = _read_json(root / ISOLATION_REVIEW_SCHEMA_PATH)
    for row in isolation_rows:
        jsonschema.validate(row, isolation_schema)
    review_bytes = _jsonl_bytes(review_rows)
    isolation_bytes = _jsonl_bytes(isolation_rows)
    model_counts = Counter(record["source_locator"]["model_family"] for record in records)
    stratum_counts = Counter(record["sampling_stratum"] for record in records)
    manifest = {
        "manifest_version": "phase_3_additional_tranche_manifest_v0_1",
        "status": "additional_30_pending_full_and_isolation_human_review_no_split",
        "contract": {"path": CONTRACT_PATH, "sha256": canonical_content_sha256(contract)},
        "sampling": {
            **sampling,
            "observed_model_family_counts": dict(sorted(model_counts.items())),
            "observed_stratum_counts": dict(sorted(stratum_counts.items())),
            "rejection_counts": dict(sorted(rejections.items())),
        },
        "isolation_policy": contract["isolation_extension_policy"],
        "local_review_packet": {
            "path": contract["local_review_packet_path"],
            "tracked": False,
            "row_count": 30,
            "sha256": sha256(review_bytes).hexdigest(),
            "schema_path": REVIEW_SCHEMA_PATH,
        },
        "local_isolation_review_packet": {
            "path": contract["local_isolation_review_packet_path"],
            "tracked": False,
            "row_count": 30,
            "sha256": sha256(isolation_bytes).hexdigest(),
            "schema_path": ISOLATION_REVIEW_SCHEMA_PATH,
        },
        "records": records,
        "checks": [
            {"check_id": "candidate_count_30", "status": "pass"},
            {"check_id": "phase_2_overlap_zero", "status": "pass"},
            {"check_id": "reviewed_240_overlap_zero", "status": "pass"},
            {"check_id": "exact_normalized_prompt_overlap_zero", "status": "pass"},
            {"check_id": "token_3gram_jaccard_at_or_above_0_90_overlap_zero", "status": "pass"},
            {"check_id": "candidate_content_and_provisional_ids_unique", "status": "pass"},
            {"check_id": "raw_text_in_tracked_manifest", "status": "pass"},
            {"check_id": "full_review_pending", "status": "pass"},
            {"check_id": "isolation_extension_review_pending", "status": "pass"},
            {"check_id": "split_assignment_zero", "status": "pass"},
            {"check_id": "positive_yield_not_required", "status": "pass"},
        ],
        "claim_boundary": contract["claim_boundary"],
    }
    if len(records) != 30 or len({record["candidate_id"] for record in records}) != 30:
        raise ValueError("Additional tranche must contain 30 unique candidates")
    if len({record["provisional_isolation_family_id"] for record in records}) != 30:
        raise ValueError("Additional tranche provisional isolation IDs are not unique")
    if _contains_raw_text_key(manifest):
        raise ValueError("Tracked additional tranche manifest contains raw text")
    jsonschema.validate(manifest, _read_json(root / MANIFEST_SCHEMA_PATH))
    return review_rows, isolation_rows, manifest


def write_phase_3_additional_tranche(root: Path) -> dict[str, Any]:
    review_rows, isolation_rows, manifest = build_phase_3_additional_tranche(root)
    contract = _read_json(root / CONTRACT_PATH)
    write_jsonl(root / contract["local_review_packet_path"], review_rows)
    write_jsonl(root / contract["local_isolation_review_packet_path"], isolation_rows)
    path = root / contract["tracked_manifest_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
