from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import jsonschema

from research_foundation.phase3_data_contract import (
    FORMAL_REVIEW_PATH,
    REVIEW_SCHEMA_PATH,
    _file_sha256,
    validate_phase_3_review_rows,
)
from research_foundation.phase3_expansion import (
    ISOLATION_MANIFEST_PATH,
    SEMANTIC_REVIEW_PACKET_PATH,
)
from research_foundation.public_pilot import iter_jsonl, write_jsonl


EXPANSION_PACKET_PATH = "results/local_artifacts/research_foundation/phase_3/phase_3_family_expansion_review_packet_v0_1.jsonl"
EXPANSION_FORMAL_PATH = "results/local_artifacts/research_foundation/phase_3/phase_3_family_expansion_review_completed_v0_1.jsonl"
ISOLATION_FORMAL_PATH = "results/local_artifacts/research_foundation/phase_3/phase_3_isolation_semantic_merge_review_completed_v0_1.jsonl"
FINAL_ISOLATION_MANIFEST_PATH = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_1.json"
FINAL_ISOLATION_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_final_isolation_manifest_v0_1.schema.json"
ACCEPTANCE_PATH = "results/summaries/phase_3_expansion_and_isolation_review_acceptance_v0_1.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [row for _, row in iter_jsonl(path)]


def _validated_proposed_review(candidate_id: str, proposed: dict[str, Any], reviewer_id: str) -> dict[str, Any]:
    if proposed.get("reviewer_id") != reviewer_id:
        raise ValueError(f"{candidate_id}: reviewer_id is not {reviewer_id}")
    if proposed.get("review_status") != "pending_user_secondary_review":
        raise ValueError(f"{candidate_id}: result was not awaiting user confirmation")
    return proposed


def import_confirmed_expansion_and_isolation_reviews(
    root: Path,
    expansion_prereview_path: Path,
    isolation_prereview_path: Path,
    *,
    reviewer_id: str = "researcher_01",
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    expansion_packet_path = root / EXPANSION_PACKET_PATH
    isolation_packet_path = root / SEMANTIC_REVIEW_PACKET_PATH
    expansion_packet_hash = _file_sha256(expansion_packet_path)
    isolation_packet_hash = _file_sha256(isolation_packet_path)
    expansion_packet = _rows(expansion_packet_path)
    isolation_packet = _rows(isolation_packet_path)
    expansion_prereview = _rows(expansion_prereview_path)
    isolation_prereview = _rows(isolation_prereview_path)
    for label, rows, expected in (
        ("expansion packet", expansion_packet, 60),
        ("expansion prereview", expansion_prereview, 60),
        ("isolation packet", isolation_packet, 240),
        ("isolation prereview", isolation_prereview, 240),
    ):
        if len(rows) != expected or len({row["candidate_id"] for row in rows}) != expected:
            raise ValueError(f"{label} must contain {expected} unique candidate IDs")
    expansion_packet_by_id = {row["candidate_id"]: row for row in expansion_packet}
    expansion_prereview_by_id = {row["candidate_id"]: row for row in expansion_prereview}
    isolation_packet_by_id = {row["candidate_id"]: row for row in isolation_packet}
    isolation_prereview_by_id = {row["candidate_id"]: row for row in isolation_prereview}
    if set(expansion_packet_by_id) != set(expansion_prereview_by_id):
        raise ValueError("Expansion candidate ID sets differ")
    if set(isolation_packet_by_id) != set(isolation_prereview_by_id):
        raise ValueError("Isolation candidate ID sets differ")

    timestamp = reviewed_at or datetime.now().astimezone().isoformat(timespec="seconds")
    expansion_formal: list[dict[str, Any]] = []
    for candidate_id in sorted(expansion_packet_by_id):
        packet = expansion_packet_by_id[candidate_id]
        prereview = expansion_prereview_by_id[candidate_id]
        if prereview["content_sha256"] != packet["content_sha256"]:
            raise ValueError(f"{candidate_id}: expansion content hash changed")
        if prereview["source_family_id"] != packet["source_family_id"]:
            raise ValueError(f"{candidate_id}: expansion provenance changed")
        proposed = _validated_proposed_review(candidate_id, prereview["proposed_human_review"], reviewer_id)
        family = proposed["reviewed_family_assignment"]
        if any(not value or "pending" in value for value in family.values()):
            raise ValueError(f"{candidate_id}: expansion family assignment is incomplete")
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
        expansion_formal.append(formal)
    review_schema = _read_json(root / REVIEW_SCHEMA_PATH)
    validate_phase_3_review_rows(expansion_formal, review_schema)
    expansion_decisions = Counter(row["human_review"]["mapping_decision"] for row in expansion_formal)
    if expansion_decisions != Counter({"accept": 43, "ambiguous": 1, "reject": 16}):
        raise ValueError(f"Unexpected expansion decision counts: {expansion_decisions}")

    parent = {candidate_id: candidate_id for candidate_id in isolation_packet_by_id}

    def find(candidate_id: str) -> str:
        while parent[candidate_id] != candidate_id:
            parent[candidate_id] = parent[parent[candidate_id]]
            candidate_id = parent[candidate_id]
        return candidate_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    isolation_decisions: Counter[str] = Counter()
    proposed_by_id: dict[str, dict[str, Any]] = {}
    for candidate_id, prereview in isolation_prereview_by_id.items():
        packet = isolation_packet_by_id[candidate_id]
        for field in ("cohort", "prompt_sha256", "provisional_isolation_family_id"):
            if prereview[field] != packet[field]:
                raise ValueError(f"{candidate_id}: isolation {field} changed")
        proposed = _validated_proposed_review(candidate_id, prereview["proposed_human_review"], reviewer_id)
        decision = proposed["decision"]
        if decision not in {"confirm", "merge"}:
            raise ValueError(f"{candidate_id}: unsupported confirmed isolation decision {decision}")
        isolation_decisions[decision] += 1
        proposed_by_id[candidate_id] = proposed
        references = proposed["merge_with_candidate_ids"]
        if decision == "confirm" and references:
            raise ValueError(f"{candidate_id}: confirm decision cannot contain merge references")
        if decision == "merge" and not references:
            raise ValueError(f"{candidate_id}: merge decision requires references")
        for reference in references:
            if reference not in parent or reference == candidate_id:
                raise ValueError(f"{candidate_id}: invalid merge reference {reference}")
            union(candidate_id, reference)
    if isolation_decisions != Counter({"confirm": 158, "merge": 82}):
        raise ValueError(f"Unexpected isolation decision counts: {isolation_decisions}")

    components: dict[str, list[str]] = defaultdict(list)
    for candidate_id in parent:
        components[find(candidate_id)].append(candidate_id)
    merged_components = [members for members in components.values() if len(members) > 1]
    component_size_distribution = Counter(len(members) for members in components.values())
    if len(components) != 189 or len(merged_components) != 31:
        raise ValueError(
            f"Unexpected transitive closure: {len(components)} families, {len(merged_components)} merge groups"
        )
    final_id_by_candidate: dict[str, str] = {}
    for members in components.values():
        proposed_ids = {
            proposed_by_id[candidate_id]["reviewed_isolation_family_id"]
            for candidate_id in members
        }
        if len(proposed_ids) != 1:
            raise ValueError(f"Merge group does not use one isolation ID: {sorted(members)}")
        final_id = next(iter(proposed_ids))
        if not isinstance(final_id, str) or not final_id.startswith("p3iso_") or len(final_id) != 26:
            raise ValueError(f"Invalid reviewed isolation family ID: {final_id}")
        for candidate_id in members:
            final_id_by_candidate[candidate_id] = final_id
    if len(set(final_id_by_candidate.values())) != 189:
        raise ValueError("Different transitive components reuse an isolation family ID")

    isolation_formal: list[dict[str, Any]] = []
    final_records: list[dict[str, Any]] = []
    for candidate_id in sorted(isolation_packet_by_id):
        packet = isolation_packet_by_id[candidate_id]
        proposed = proposed_by_id[candidate_id]
        members = sorted(
            member for member, family_id in final_id_by_candidate.items()
            if family_id == final_id_by_candidate[candidate_id]
        )
        formal = json.loads(json.dumps(packet))
        formal["human_review"] = {
            "decision": proposed["decision"],
            "reviewed_isolation_family_id": final_id_by_candidate[candidate_id],
            "merge_with_candidate_ids": [member for member in members if member != candidate_id],
            "reviewer_id": reviewer_id,
            "reviewed_at": timestamp,
            "notes": proposed["notes"],
        }
        isolation_formal.append(formal)
        final_records.append(
            {
                "candidate_id": candidate_id,
                "cohort": packet["cohort"],
                "prompt_sha256": packet["prompt_sha256"],
                "final_isolation_family_id": final_id_by_candidate[candidate_id],
                "component_size": len(members),
                "review_decision": proposed["decision"],
                "split_status": "not_assigned_pending_40_15_40_feasibility",
            }
        )
    isolation_schema = _read_json(root / "data/research_foundation/schemas/phase_3_isolation_semantic_review_v0_1.schema.json")
    for row in isolation_formal:
        jsonschema.validate(row, isolation_schema)

    expansion_formal_path = root / EXPANSION_FORMAL_PATH
    isolation_formal_path = root / ISOLATION_FORMAL_PATH
    write_jsonl(expansion_formal_path, expansion_formal)
    write_jsonl(isolation_formal_path, isolation_formal)
    if _file_sha256(expansion_packet_path) != expansion_packet_hash:
        raise RuntimeError("Original expansion packet changed during import")
    if _file_sha256(isolation_packet_path) != isolation_packet_hash:
        raise RuntimeError("Original isolation packet changed during import")

    final_manifest = {
        "manifest_version": "phase_3_final_isolation_manifest_v0_1",
        "status": "human_semantic_merge_review_complete_no_split",
        "reviewer_id": reviewer_id,
        "reviewed_at": timestamp,
        "formal_review": {
            "path": ISOLATION_FORMAL_PATH,
            "tracked": False,
            "sha256": _file_sha256(isolation_formal_path),
            "row_count": 240,
        },
        "counts": {
            "confirm": 158,
            "merge": 82,
            "exclude": 0,
            "merged_components": 31,
            "final_isolation_families": 189,
            "component_size_distribution": dict(sorted(component_size_distribution.items())),
        },
        "records": final_records,
        "checks": [
            {"check_id": "candidate_count_240", "status": "pass"},
            {"check_id": "identity_hash_and_cohort_preserved", "status": "pass"},
            {"check_id": "original_packet_unmodified", "status": "pass"},
            {"check_id": "merge_references_valid", "status": "pass"},
            {"check_id": "transitive_closure_complete", "status": "pass"},
            {"check_id": "one_family_id_per_component", "status": "pass"},
            {"check_id": "family_id_unique_across_components", "status": "pass"},
            {"check_id": "schema_valid", "status": "pass"},
            {"check_id": "split_assignment_zero", "status": "pass"},
        ],
        "claim_boundary": (
            "Human semantic merge review is complete and transitively closed. This manifest contains no raw text "
            "and does not assign a split or establish model evidence."
        ),
    }
    jsonschema.validate(final_manifest, _read_json(root / FINAL_ISOLATION_SCHEMA_PATH))
    final_manifest_path = root / FINAL_ISOLATION_MANIFEST_PATH
    final_manifest_path.write_text(json.dumps(final_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    original_formal = _rows(root / FORMAL_REVIEW_PATH)
    all_reviews = original_formal + expansion_formal
    if len(all_reviews) != 240 or set(final_id_by_candidate) != {row["candidate_id"] for row in all_reviews}:
        raise ValueError("Eligibility and isolation populations do not match")
    evaluation_families: set[str] = set()
    qlora_families: set[str] = set()
    for row in all_reviews:
        family_id = final_id_by_candidate[row["candidate_id"]]
        review = row["human_review"]
        if review["pair_evaluation_eligible"]:
            evaluation_families.add(family_id)
        if any(item["qlora_training_eligible"] for item in review["response_annotations"]):
            qlora_families.add(family_id)
    evaluation_only = evaluation_families - qlora_families
    qlora_only = qlora_families - evaluation_families
    both = evaluation_families & qlora_families
    maximum_train_after_heldout = len(qlora_families) - max(0, 55 - len(evaluation_only))
    feasible = len(evaluation_families) >= 55 and maximum_train_after_heldout >= 40
    if feasible:
        raise ValueError("Unexpected feasible split; acceptance status must be reviewed before writing")

    summary = {
        "summary_version": "phase_3_expansion_and_isolation_review_acceptance_v0_1",
        "status": "reviews_complete_no_go_240_for_disjoint_40_15_40",
        "reviewer_id": reviewer_id,
        "reviewed_at": timestamp,
        "inputs": {
            "expansion_prereview": {"filename": expansion_prereview_path.name, "sha256": _file_sha256(expansion_prereview_path)},
            "isolation_prereview": {"filename": isolation_prereview_path.name, "sha256": _file_sha256(isolation_prereview_path)},
            "expansion_packet": {"path": EXPANSION_PACKET_PATH, "sha256": expansion_packet_hash, "modified": False},
            "isolation_packet": {"path": SEMANTIC_REVIEW_PACKET_PATH, "sha256": isolation_packet_hash, "modified": False},
        },
        "formal_reviews": {
            "expansion": {"path": EXPANSION_FORMAL_PATH, "tracked": False, "sha256": _file_sha256(expansion_formal_path), "row_count": 60},
            "isolation": {"path": ISOLATION_FORMAL_PATH, "tracked": False, "sha256": _file_sha256(isolation_formal_path), "row_count": 240},
        },
        "expansion_counts": {
            "mapping_decisions": dict(sorted(expansion_decisions.items())),
            "pair_contrasts": dict(sorted(Counter(row["human_review"]["pair_contrast"] for row in expansion_formal).items())),
            "paired_evaluation_eligible": sum(row["human_review"]["pair_evaluation_eligible"] for row in expansion_formal),
            "qlora_training_eligible_responses": sum(
                item["qlora_training_eligible"]
                for row in expansion_formal
                for item in row["human_review"]["response_annotations"]
            ),
        },
        "isolation_counts": final_manifest["counts"],
        "disjoint_gate_audit": {
            "evaluation_eligible_families": len(evaluation_families),
            "qlora_eligible_families": len(qlora_families),
            "both_role_families": len(both),
            "evaluation_only_families": len(evaluation_only),
            "qlora_only_families": len(qlora_only),
            "maximum_qlora_train_families_after_reserving_15_dev_and_40_test": maximum_train_after_heldout,
            "qlora_train_shortfall": max(0, 40 - maximum_train_after_heldout),
            "meets_40_15_40": feasible,
        },
        "checks": [
            {"check_id": "all_input_counts_and_ids_complete", "status": "pass"},
            {"check_id": "raw_packet_identity_hash_text_and_provenance_preserved", "status": "pass"},
            {"check_id": "expansion_review_schema_and_eligibility_valid", "status": "pass"},
            {"check_id": "isolation_review_schema_valid", "status": "pass"},
            {"check_id": "merge_transitive_closure_and_uniform_ids", "status": "pass"},
            {"check_id": "split_not_created", "status": "pass"},
            {"check_id": "disjoint_40_15_40_feasibility", "status": "blocked"},
        ],
        "claim_boundary": (
            "Both user-confirmed reviews are formally accepted. The final 189 isolation families still cannot "
            "support the disjoint 40/15/40 allocation, so no split or model execution is authorized."
        ),
    }
    acceptance_path = root / ACCEPTANCE_PATH
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
