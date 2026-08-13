from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from research_foundation.audit import jaccard, normalize_text, word_ngrams
from research_foundation.public_pilot import iter_jsonl, stable_digest, write_jsonl
from research_foundation.representation_freeze import canonical_content_sha256, content_sha256


CONTRACT_PATH = "configs/research/phase_3_family_data_contract_v0_1.json"
REVIEW_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_family_review_v0_1.schema.json"
MANIFEST_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_family_candidate_manifest_v0_1.schema.json"
MAPPING_MANIFEST_PATH = "data/research_foundation/manifests/public_mapping_pilot_v0_2.json"
TARGET_AXIS = "boundary-preserving-over-accommodating"
NEAR_DUPLICATE_THRESHOLD = 0.90
LOCAL_PACKET_PATH = "results/local_artifacts/research_foundation/phase_3/phase_3_family_review_packet_v0_1.jsonl"
FORMAL_REVIEW_PATH = "results/local_artifacts/research_foundation/phase_3/phase_3_family_review_completed_v0_1.jsonl"
REVIEW_ACCEPTANCE_PATH = "results/summaries/phase_3_family_review_acceptance_v0_1.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_locator(locator: dict[str, Any]) -> str:
    return json.dumps(locator, sort_keys=True, separators=(",", ":"))


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
        for row in rows
    )


def _contains_raw_text_key(value: Any) -> bool:
    forbidden = {"prompt", "text", "response_0", "response_1", "output_text"}
    if isinstance(value, dict):
        return bool(forbidden & set(value)) or any(_contains_raw_text_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_text_key(item) for item in value)
    return False


def _source_family_id(model_family: str, revision: str) -> str:
    normalized = model_family.casefold().replace("-", "_")
    return f"pku_safe_rlhf_{revision[:8]}_{normalized}"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_csv_bool(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if normalized not in {"true", "false"}:
        raise ValueError(f"Invalid CSV boolean: {value!r}")
    return normalized == "true"


def _parse_csv_int(value: str) -> int | None:
    return int(value) if value.strip() else None


def _parse_csv_text(value: str) -> str | None:
    return value if value.strip() else None


def _csv_review_projection(row: dict[str, str]) -> dict[str, Any]:
    return {
        "mapping_decision": row["mapping_decision"],
        "response_annotations": [
            {
                "response_id": f"response_{index}",
                "behavior": _parse_csv_text(row[f"response_{index}_behavior"]),
                "pole": _parse_csv_text(row[f"response_{index}_pole"]),
                "task_success": _parse_csv_int(row[f"response_{index}_task_success"]),
                "naturalness": _parse_csv_int(row[f"response_{index}_naturalness"]),
                "useful_alternative": _parse_csv_int(row[f"response_{index}_useful_alternative"]),
                "over_refusal": _parse_csv_int(row[f"response_{index}_over_refusal"]),
                "template_style": _parse_csv_int(row[f"response_{index}_template_style"]),
                "qlora_training_eligible": _parse_csv_bool(row[f"response_{index}_qlora_eligible"]),
            }
            for index in (0, 1)
        ],
        "pair_contrast": row["pair_contrast"],
        "pair_evaluation_eligible": _parse_csv_bool(row["pair_evaluation_eligible"]),
        "reviewed_family_assignment": {
            "task_family_id": row["task_family_id"],
            "scenario_family_id": row["scenario_family_id"],
            "prompt_template_id": row["prompt_template_id"],
            "semantic_cluster_id": row["semantic_cluster_id"],
        },
        "quality_flags": sorted(filter(None, row["quality_flags"].split(";"))),
        "notes": row["notes"],
        "reviewer_id": row["reviewer_id"],
    }


def import_confirmed_phase_3_reviews(
    root: Path,
    prereview_jsonl: Path,
    prereview_csv: Path,
    *,
    reviewer_id: str = "researcher_01",
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    packet_path = root / LOCAL_PACKET_PATH
    packet_hash_before = _file_sha256(packet_path)
    packet_rows = [row for _, row in iter_jsonl(packet_path)]
    prereview_rows = [row for _, row in iter_jsonl(prereview_jsonl)]
    with prereview_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    collections = {
        "original_packet": packet_rows,
        "jsonl_prereview": prereview_rows,
        "csv_cross_check": csv_rows,
    }
    for name, rows in collections.items():
        if len(rows) != 180:
            raise ValueError(f"{name} contains {len(rows)} rows; expected 180")
    packet_by_id = {row["candidate_id"]: row for row in packet_rows}
    prereview_by_id = {row["candidate_id"]: row for row in prereview_rows}
    csv_by_id = {row["candidate_id"]: row for row in csv_rows}
    if any(len(index) != 180 for index in (packet_by_id, prereview_by_id, csv_by_id)):
        raise ValueError("Candidate IDs must be unique in all three inputs")
    if not (set(packet_by_id) == set(prereview_by_id) == set(csv_by_id)):
        raise ValueError("Candidate ID sets differ between packet, JSONL and CSV")

    timestamp = reviewed_at or datetime.now().astimezone().isoformat(timespec="seconds")
    formal_rows: list[dict[str, Any]] = []
    csv_mismatches: list[str] = []
    family_values: dict[str, list[str]] = {
        field: []
        for field in ("task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id")
    }
    for candidate_id in sorted(packet_by_id):
        packet = packet_by_id[candidate_id]
        prereview = prereview_by_id[candidate_id]
        if prereview["content_sha256"] != packet["content_sha256"]:
            raise ValueError(f"{candidate_id}: content hash differs from the original packet")
        if prereview["source_family_id"] != packet["source_family_id"]:
            raise ValueError(f"{candidate_id}: source provenance differs from the original packet")
        proposed = prereview["proposed_human_review"]
        if proposed.get("reviewer_id") != reviewer_id:
            raise ValueError(f"{candidate_id}: reviewer_id is not {reviewer_id}")
        if proposed.get("review_status") != "pending_user_secondary_review":
            raise ValueError(f"{candidate_id}: prereview status is not awaiting user confirmation")

        json_projection = {
            key: proposed[key]
            for key in (
                "mapping_decision", "response_annotations", "pair_contrast",
                "pair_evaluation_eligible", "reviewed_family_assignment",
                "quality_flags", "notes", "reviewer_id",
            )
        }
        json_projection["quality_flags"] = sorted(json_projection["quality_flags"])
        if _csv_review_projection(csv_by_id[candidate_id]) != json_projection:
            csv_mismatches.append(candidate_id)

        family = proposed["reviewed_family_assignment"]
        for field, value in family.items():
            if not isinstance(value, str) or not value or "pending" in value or candidate_id in value:
                raise ValueError(f"{candidate_id}: invalid reviewed family value for {field}")
            family_values[field].append(value)

        formal = json.loads(json.dumps(packet))
        formal["human_review"] = {
            "mapping_decision": proposed["mapping_decision"],
            "reviewer_id": reviewer_id,
            "reviewed_at": timestamp,
            "response_annotations": proposed["response_annotations"],
            "pair_contrast": proposed["pair_contrast"],
            "reviewed_family_assignment": family,
            "pair_evaluation_eligible": proposed["pair_evaluation_eligible"],
            "quality_flags": proposed["quality_flags"],
            "notes": proposed["notes"],
        }
        formal_rows.append(formal)

    if csv_mismatches:
        raise ValueError(f"CSV differs from JSONL for candidates: {csv_mismatches[:10]}")
    for field, values in family_values.items():
        if len(set(values)) == len(values):
            raise ValueError(f"{field}: no family IDs are reused across reviewed candidates")

    schema = _read_json(root / REVIEW_SCHEMA_PATH)
    validate_phase_3_review_rows(formal_rows, schema)
    if any(
        row["human_review"]["pair_evaluation_eligible"]
        and row["human_review"]["pair_contrast"] != "valid_single_axis"
        for row in formal_rows
    ):
        raise ValueError("Only valid_single_axis pairs may be evaluation eligible")

    formal_path = root / FORMAL_REVIEW_PATH
    write_jsonl(formal_path, formal_rows)
    if _file_sha256(packet_path) != packet_hash_before:
        raise RuntimeError("Original Phase 3 review packet changed during import")

    decisions = Counter(row["human_review"]["mapping_decision"] for row in formal_rows)
    contrasts = Counter(row["human_review"]["pair_contrast"] for row in formal_rows)
    eligible_pairs = sum(row["human_review"]["pair_evaluation_eligible"] for row in formal_rows)
    eligible_responses = sum(
        annotation["qlora_training_eligible"]
        for row in formal_rows
        for annotation in row["human_review"]["response_annotations"]
    )
    component_fields = (
        "source_family_id", "task_family_id", "scenario_family_id",
        "prompt_template_id", "semantic_cluster_id",
    )
    parent = list(range(len(formal_rows)))

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
    for index, row in enumerate(formal_rows):
        values = {"source_family_id": row["source_family_id"], **row["human_review"]["reviewed_family_assignment"]}
        for field in component_fields:
            token = (field, values[field])
            if token in owners:
                union(index, owners[token])
            else:
                owners[token] = index
    component_sizes = Counter(find(index) for index in range(len(formal_rows)))
    evaluation_components = {
        find(index)
        for index, row in enumerate(formal_rows)
        if row["human_review"]["pair_evaluation_eligible"]
    }
    qlora_components = {
        find(index)
        for index, row in enumerate(formal_rows)
        if any(item["qlora_training_eligible"] for item in row["human_review"]["response_annotations"])
    }
    summary = {
        "summary_version": "phase_3_family_review_acceptance_v0_1",
        "status": "human_review_complete_pending_family_split_freeze",
        "reviewer_id": reviewer_id,
        "reviewed_at": timestamp,
        "inputs": {
            "original_packet": {"path": LOCAL_PACKET_PATH, "sha256": packet_hash_before, "modified": False},
            "confirmed_jsonl": {"filename": prereview_jsonl.name, "sha256": _file_sha256(prereview_jsonl), "role": "primary"},
            "confirmed_csv": {"filename": prereview_csv.name, "sha256": _file_sha256(prereview_csv), "role": "cross_check"},
        },
        "formal_review": {
            "path": FORMAL_REVIEW_PATH,
            "tracked": False,
            "sha256": _file_sha256(formal_path),
            "row_count": len(formal_rows),
            "schema_path": REVIEW_SCHEMA_PATH,
        },
        "counts": {
            "mapping_decisions": dict(sorted(decisions.items())),
            "pair_contrasts": dict(sorted(contrasts.items())),
            "paired_evaluation_eligible": eligible_pairs,
            "qlora_training_eligible_responses": eligible_responses,
            "unique_families": {field: len(set(values)) for field, values in family_values.items()},
        },
        "family_component_audit": {
            "fields": list(component_fields),
            "component_count": len(component_sizes),
            "largest_component_rows": max(component_sizes.values()),
            "paired_evaluation_component_count": len(evaluation_components),
            "qlora_eligible_pair_component_count": len(qlora_components),
            "allocation_ready": len(component_sizes) >= 3 and len(evaluation_components) >= 2,
            "status": "blocked_single_connected_component" if len(component_sizes) == 1 else "requires_allocation_audit",
            "claim_boundary": (
                "Family IDs are legally formed and reused, but reuse connectivity is a separate split-isolation gate. "
                "Confirmed review values are not altered by this audit."
            ),
        },
        "checks": [
            {"check_id": "all_inputs_have_180_unique_matching_ids", "status": "pass"},
            {"check_id": "jsonl_csv_field_cross_check", "status": "pass", "mismatch_count": 0},
            {"check_id": "original_text_hash_and_provenance_preserved", "status": "pass"},
            {"check_id": "original_packet_unmodified", "status": "pass"},
            {"check_id": "schema_and_completed_review_validation", "status": "pass"},
            {"check_id": "family_ids_nonpending_and_reused", "status": "pass"},
            {
                "check_id": "family_connected_component_allocation_readiness",
                "status": "blocked" if len(component_sizes) == 1 else "requires_allocation_audit",
            },
            {"check_id": "paired_eligibility_valid_single_axis_only", "status": "pass"},
            {"check_id": "same_axis_not_opposite_excluded_from_paired_evaluation", "status": "pass"},
            {"check_id": "qlora_single_response_quality_gates", "status": "pass"},
        ],
        "claim_boundary": (
            "The user confirmed the 180 prereview decisions as the single-researcher human review. "
            "This completes review but does not create a split, authorize model execution, or establish causal evidence."
        ),
    }
    acceptance_path = root / REVIEW_ACCEPTANCE_PATH
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _phase_2_exclusions(root: Path, contract: dict[str, Any]) -> tuple[set[str], set[str]]:
    split_manifest = _read_json(root / contract["phase_2_exclusion_manifest_path"])
    if canonical_content_sha256(split_manifest) != contract["phase_2_exclusion_manifest_sha256"]:
        raise ValueError("Phase 2 exclusion manifest hash does not match the frozen contract")

    excluded_hashes: set[str] = set()
    phase_2_sample_ids: set[str] = set()
    for record in split_manifest["records"]:
        phase_2_sample_ids.add(record["source_sample_id"])
        excluded_hashes.update(
            [record["pair_content_sha256"], record["prompt_sha256"]]
            + [response["content_sha256"] for response in record["responses"]]
        )

    mapping_manifest = _read_json(root / MAPPING_MANIFEST_PATH)
    pku_records = next(
        dataset["records"]
        for dataset in mapping_manifest["datasets"]
        if dataset["dataset_id"] == "pku_safe_rlhf"
    )
    by_sample = {record["sample_id"]: record for record in pku_records}
    missing = sorted(phase_2_sample_ids - set(by_sample))
    if missing:
        raise ValueError(f"Cannot resolve Phase 2 source locators: {missing}")
    excluded_locators = {
        _canonical_locator(by_sample[sample_id]["source_locator"])
        for sample_id in phase_2_sample_ids
    }
    return excluded_hashes, excluded_locators


def _sampling_stratum(row: dict[str, Any]) -> str | None:
    safety = (bool(row["is_response_0_safe"]), bool(row["is_response_1_safe"]))
    if safety == (True, True):
        return "both_safe"
    if safety in {(True, False), (False, True)}:
        return "mixed_safety"
    return None


def blank_phase_3_review() -> dict[str, Any]:
    return {
        "mapping_decision": None,
        "reviewer_id": None,
        "reviewed_at": None,
        "response_annotations": [
            {
                "response_id": response_id,
                "behavior": None,
                "pole": None,
                "task_success": None,
                "naturalness": None,
                "useful_alternative": None,
                "over_refusal": None,
                "template_style": None,
                "qlora_training_eligible": None,
            }
            for response_id in ("response_0", "response_1")
        ],
        "pair_contrast": None,
        "reviewed_family_assignment": {
            "task_family_id": None,
            "scenario_family_id": None,
            "prompt_template_id": None,
            "semantic_cluster_id": None,
        },
        "pair_evaluation_eligible": None,
        "quality_flags": [],
        "notes": "",
    }


def validate_phase_3_review_rows(rows: list[dict[str, Any]], schema: dict[str, Any]) -> None:
    for row in rows:
        jsonschema.validate(row, schema)
        review = row["human_review"]
        annotations = review["response_annotations"]
        if {item["response_id"] for item in annotations} != {"response_0", "response_1"}:
            raise ValueError(f"{row['candidate_id']}: response annotations must cover both responses")
        decision = review["mapping_decision"]
        if decision is None:
            if review["reviewer_id"] is not None or review["reviewed_at"] is not None:
                raise ValueError(f"{row['candidate_id']}: pending review cannot have reviewer provenance")
            continue
        if not review["reviewer_id"] or not review["reviewed_at"]:
            raise ValueError(f"{row['candidate_id']}: completed review requires reviewer provenance")
        if decision == "accept":
            family = review["reviewed_family_assignment"]
            if any(not family[field] for field in family):
                raise ValueError(f"{row['candidate_id']}: accepted review requires all family fields")
            required_annotation_fields = (
                "behavior", "pole", "task_success", "naturalness", "useful_alternative",
                "over_refusal", "template_style", "qlora_training_eligible",
            )
            if any(item[field] is None for item in annotations for field in required_annotation_fields):
                raise ValueError(f"{row['candidate_id']}: accepted review has incomplete annotations")
        if review["pair_evaluation_eligible"] is True:
            poles = {item["pole"] for item in annotations}
            if review["pair_contrast"] != "valid_single_axis" or poles != {
                "boundary-preserving", "over-accommodating"
            }:
                raise ValueError(f"{row['candidate_id']}: evaluation pair is not a valid opposite-pole contrast")
        for item in annotations:
            if item["qlora_training_eligible"] is True:
                if not (
                    decision == "accept"
                    and item["pole"] == "boundary-preserving"
                    and item["task_success"] >= 2
                    and item["naturalness"] >= 2
                    and item["template_style"] == 0
                    and item["over_refusal"] <= 1
                ):
                    raise ValueError(f"{row['candidate_id']}: QLoRA eligibility violates quality gates")


def build_phase_3_family_candidates(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = _read_json(root / CONTRACT_PATH)
    protocol = _read_json(root / contract["protocol_path"])
    source_decision = _read_json(root / contract["source_use_decision_path"])
    if canonical_content_sha256(protocol) != contract["protocol_sha256"]:
        raise ValueError("Phase 3 protocol hash does not match the family data contract")
    if canonical_content_sha256(source_decision) != contract["source_use_decision_sha256"]:
        raise ValueError("Source-use decision hash does not match the family data contract")

    excluded_hashes, excluded_locators = _phase_2_exclusions(root, contract)
    quotas = {
        "mixed_safety": int(contract["sampling"]["mixed_safety_per_model"]),
        "both_safe": int(contract["sampling"]["both_safe_per_model"]),
    }
    candidates_by_bucket: dict[tuple[str, str], list[dict[str, Any]]] = {}
    phase_2_hash_rejections = 0
    phase_2_locator_rejections = 0
    both_unsafe_rejections = 0
    empty_text_rejections = 0
    for model_family, relative_path in sorted(contract["source"]["model_paths"].items()):
        buckets = {stratum: [] for stratum in quotas}
        for line_number, row in iter_jsonl(root / relative_path):
            if any(not str(row.get(field, "")).strip() for field in ("prompt", "response_0", "response_1")):
                empty_text_rejections += 1
                continue
            stratum = _sampling_stratum(row)
            if stratum is None:
                both_unsafe_rejections += 1
                continue
            locator = {
                "model_family": model_family,
                "source_split": "train",
                "lf_record_number": line_number,
            }
            pair_hash = stable_digest(row["prompt"], row["response_0"], row["response_1"])
            row_hashes = {
                pair_hash,
                content_sha256(row["prompt"]),
                content_sha256(row["response_0"]),
                content_sha256(row["response_1"]),
            }
            if row_hashes & excluded_hashes:
                phase_2_hash_rejections += 1
                continue
            if _canonical_locator(locator) in excluded_locators:
                phase_2_locator_rejections += 1
                continue
            buckets[stratum].append(
                {
                    **row,
                    "_model_family": model_family,
                    "_locator": locator,
                    "_stratum": stratum,
                    "_content_sha256": pair_hash,
                    "_rank": stable_digest(
                        contract["sampling"]["seed"], model_family, stratum, line_number, pair_hash
                    ),
                }
            )
        for stratum, values in buckets.items():
            candidates_by_bucket[(model_family, stratum)] = sorted(values, key=lambda item: item["_rank"])

    selected: list[dict[str, Any]] = []
    normalized_prompts: set[str] = set()
    prompt_shingles: list[set[tuple[str, ...]]] = []
    duplicate_rejections = 0
    near_duplicate_rejections = 0
    for bucket in sorted(candidates_by_bucket):
        model_family, stratum = bucket
        bucket_selected = 0
        for row in candidates_by_bucket[bucket]:
            normalized = normalize_text(row["prompt"])
            if normalized in normalized_prompts:
                duplicate_rejections += 1
                continue
            shingles = word_ngrams(row["prompt"])
            if any(jaccard(shingles, prior) >= NEAR_DUPLICATE_THRESHOLD for prior in prompt_shingles):
                near_duplicate_rejections += 1
                continue
            selected.append(row)
            normalized_prompts.add(normalized)
            prompt_shingles.append(shingles)
            bucket_selected += 1
            if bucket_selected == quotas[stratum]:
                break
        if bucket_selected != quotas[stratum]:
            raise ValueError(f"Insufficient unique candidates for {model_family}/{stratum}")

    review_rows: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    revision = contract["source"]["revision"]
    for source in sorted(selected, key=lambda item: item["_content_sha256"]):
        candidate_id = "p3fam_" + source["_content_sha256"][:20]
        proposed = {
            "task_family_id": "safety_helpfulness_preference_pending_human",
            "scenario_family_id": f"pending_human_{candidate_id}",
            "prompt_template_id": "source_prompt_unknown_pending_human",
            "semantic_cluster_id": f"pending_human_{candidate_id}",
            "assignment_status": "machine_proposed_pending_human",
        }
        response_hashes = [content_sha256(source[f"response_{index}"]) for index in (0, 1)]
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
                "proposed_family_assignment": proposed,
                "human_review": blank_phase_3_review(),
            }
        )
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
                "human_review_status": "pending",
                "split_status": "not_assigned_before_human_review",
            }
        )

    review_schema = _read_json(root / REVIEW_SCHEMA_PATH)
    validate_phase_3_review_rows(review_rows, review_schema)
    packet_bytes = _jsonl_bytes(review_rows)
    stratum_counts = Counter(row["sampling_stratum"] for row in manifest_records)
    model_counts = Counter(row["source_locator"]["model_family"] for row in manifest_records)
    candidate_ids = [row["candidate_id"] for row in manifest_records]
    candidate_hashes = [row["content_sha256"] for row in manifest_records]
    selected_locators = {_canonical_locator(row["source_locator"]) for row in manifest_records}
    selected_hashes = {
        value
        for row in manifest_records
        for value in [row["content_sha256"], row["prompt_sha256"], *row["response_sha256"]]
    }
    phase_2_content_overlap = len(selected_hashes & excluded_hashes)
    phase_2_locator_overlap = len(selected_locators & excluded_locators)
    unique_id_and_content_count = min(len(set(candidate_ids)), len(set(candidate_hashes)))
    if phase_2_content_overlap or phase_2_locator_overlap:
        raise ValueError("Selected Phase 3 candidates overlap the frozen Phase 2 exclusion set")
    if unique_id_and_content_count != len(manifest_records):
        raise ValueError("Selected Phase 3 candidates do not have unique IDs and content hashes")
    checks = [
        {"check_id": "candidate_count", "status": "pass", "observed": len(review_rows)},
        {"check_id": "phase_2_content_overlap", "status": "pass", "observed": phase_2_content_overlap},
        {"check_id": "phase_2_source_locator_overlap", "status": "pass", "observed": phase_2_locator_overlap},
        {"check_id": "both_unsafe_selected", "status": "pass", "observed": 0},
        {"check_id": "unique_candidate_and_content_ids", "status": "pass", "observed": unique_id_and_content_count},
        {"check_id": "exact_or_normalized_prompt_duplicates", "status": "pass", "observed": 0},
        {"check_id": "prompt_token_3gram_jaccard_at_or_above_0_90", "status": "pass", "observed": 0},
        {"check_id": "raw_text_in_tracked_manifest", "status": "pass", "observed": 0},
        {"check_id": "split_assignments_before_review", "status": "pass", "observed": 0},
    ]
    manifest = {
        "manifest_version": "phase_3_family_candidate_manifest_v0_1",
        "status": "generated_pending_human_review_no_split",
        "contract": {
            "path": CONTRACT_PATH,
            "sha256": canonical_content_sha256(contract),
            "hash_basis": "canonical_json_sort_keys_compact_utf8",
        },
        "source": contract["source"],
        "phase_2_exclusion": {
            "path": contract["phase_2_exclusion_manifest_path"],
            "sha256": contract["phase_2_exclusion_manifest_sha256"],
            "excluded_pair_count": len(_read_json(root / contract["phase_2_exclusion_manifest_path"])["records"]),
            "content_hash_rejections": phase_2_hash_rejections,
            "source_locator_rejections": phase_2_locator_rejections,
        },
        "sampling": {
            **contract["sampling"],
            "observed_stratum_counts": dict(sorted(stratum_counts.items())),
            "observed_model_family_counts": dict(sorted(model_counts.items())),
            "exact_or_normalized_duplicate_rejections": duplicate_rejections,
            "near_duplicate_rejections": near_duplicate_rejections,
            "both_unsafe_source_rows_excluded": both_unsafe_rejections,
            "empty_prompt_or_response_rows_excluded": empty_text_rejections,
            "near_duplicate_metric": "prompt_token_3gram_jaccard",
            "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
        },
        "axis_scope": [TARGET_AXIS],
        "post_review_targets": contract["post_review_targets"],
        "local_review_packet": {
            "path": contract["local_review_packet_path"],
            "tracked": False,
            "row_count": len(review_rows),
            "sha256": sha256(packet_bytes).hexdigest(),
            "schema_path": REVIEW_SCHEMA_PATH,
        },
        "records": manifest_records,
        "checks": checks,
        "claim_boundary": contract["claim_boundary"],
    }
    raw_text_key_count = int(_contains_raw_text_key(manifest))
    raw_check = next(item for item in checks if item["check_id"] == "raw_text_in_tracked_manifest")
    raw_check["observed"] = raw_text_key_count
    raw_check["status"] = "pass" if raw_text_key_count == 0 else "fail"
    if raw_text_key_count:
        raise ValueError("Tracked Phase 3 manifest contains a raw-text field")
    jsonschema.validate(manifest, _read_json(root / MANIFEST_SCHEMA_PATH))
    return review_rows, manifest


def write_phase_3_family_candidates(root: Path) -> dict[str, Any]:
    review_rows, manifest = build_phase_3_family_candidates(root)
    contract = _read_json(root / CONTRACT_PATH)
    write_jsonl(root / contract["local_review_packet_path"], review_rows)
    manifest_path = root / contract["tracked_manifest_path"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest
