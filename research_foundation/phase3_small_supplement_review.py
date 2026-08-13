from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import jsonschema

from research_foundation.phase3_additional_review import FAMILY_FORMAL as ADDITIONAL_FORMAL
from research_foundation.phase3_data_contract import FORMAL_REVIEW_PATH, REVIEW_SCHEMA_PATH, _file_sha256, validate_phase_3_review_rows
from research_foundation.phase3_expansion_review import EXPANSION_FORMAL_PATH
from research_foundation.phase3_small_supplement import ISOLATION_SCHEMA
from research_foundation.public_pilot import iter_jsonl, write_jsonl


FAMILY_PACKET = "results/local_artifacts/research_foundation/phase_3/phase_3_small_supplement_review_packet_v0_1.jsonl"
ISOLATION_PACKET = "results/local_artifacts/research_foundation/phase_3/phase_3_small_supplement_isolation_review_packet_v0_1.jsonl"
FAMILY_FORMAL = "results/local_artifacts/research_foundation/phase_3/phase_3_small_supplement_family_review_completed_v0_1.jsonl"
ISOLATION_FORMAL = "results/local_artifacts/research_foundation/phase_3/phase_3_small_supplement_isolation_review_completed_v0_1.jsonl"
PRIOR_MANIFEST = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_2.json"
FINAL_MANIFEST = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_3.json"
FINAL_SCHEMA = "data/research_foundation/schemas/phase_3_final_isolation_manifest_v0_3.schema.json"
ACCEPTANCE = "results/summaries/phase_3_small_supplement_review_acceptance_v0_1.json"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [row for _, row in iter_jsonl(path)]


def import_confirmed_small_supplement_reviews(root: Path, family_prereview: Path, isolation_prereview: Path) -> dict[str, Any]:
    reviewer_id = "researcher_01"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    family_packet_path, isolation_packet_path = root / FAMILY_PACKET, root / ISOLATION_PACKET
    packet_hashes = {"family": _file_sha256(family_packet_path), "isolation": _file_sha256(isolation_packet_path)}
    collections = [_rows(path) for path in (family_packet_path, isolation_packet_path, family_prereview, isolation_prereview)]
    if any(len(rows) != 12 or len({row["candidate_id"] for row in rows}) != 12 for rows in collections):
        raise ValueError("Every small-supplement input must contain 12 unique candidates")
    fp, ip, fi, ii = ({row["candidate_id"]: row for row in rows} for rows in collections)
    if not (set(fp) == set(ip) == set(fi) == set(ii)):
        raise ValueError("Small-supplement candidate ID sets differ")

    family_formal = []
    for candidate_id in sorted(fp):
        packet, source = fp[candidate_id], fi[candidate_id]
        if source["content_sha256"] != packet["content_sha256"] or source["source_family_id"] != packet["source_family_id"]:
            raise ValueError(f"{candidate_id}: family identity or provenance changed")
        proposal = source["proposed_human_review"]
        if proposal.get("reviewer_id") != reviewer_id or proposal.get("review_status") != "pending_user_secondary_review":
            raise ValueError(f"{candidate_id}: family proposal is not confirmed researcher_01 input")
        if any(not isinstance(value, str) or not value or "pending" in value for value in proposal["reviewed_family_assignment"].values()):
            raise ValueError(f"{candidate_id}: reviewed family assignment is incomplete")
        row = json.loads(json.dumps(packet))
        row["human_review"] = {key: proposal[key] for key in (
            "mapping_decision", "response_annotations", "pair_contrast", "reviewed_family_assignment",
            "pair_evaluation_eligible", "quality_flags", "notes")}
        row["human_review"].update({"reviewer_id": reviewer_id, "reviewed_at": timestamp})
        family_formal.append(row)
    validate_phase_3_review_rows(family_formal, _json(root / REVIEW_SCHEMA_PATH))
    decisions = Counter(row["human_review"]["mapping_decision"] for row in family_formal)
    contrasts = Counter(row["human_review"]["pair_contrast"] for row in family_formal)
    eligible_responses = sum(annotation["qlora_training_eligible"] for row in family_formal for annotation in row["human_review"]["response_annotations"])
    if decisions != Counter({"accept": 9, "reject": 3}) or contrasts["valid_single_axis"] != 4 or eligible_responses != 5:
        raise ValueError(f"Confirmed family counts differ: {decisions}, {contrasts}, qlora={eligible_responses}")
    if any(row["human_review"]["pair_evaluation_eligible"] != (row["human_review"]["pair_contrast"] == "valid_single_axis") for row in family_formal):
        raise ValueError("Only and all valid_single_axis pairs may be paired-evaluation eligible")

    prior_path = root / PRIOR_MANIFEST
    prior_hash = _file_sha256(prior_path)
    prior = _json(prior_path)
    prior_by_id = {row["candidate_id"]: row for row in prior["records"]}
    all_ids = set(prior_by_id) | set(ip)
    if len(prior_by_id) != 270 or len(all_ids) != 282:
        raise ValueError("The frozen 270 and supplemental 12 populations overlap or are incomplete")
    parent = {candidate_id: candidate_id for candidate_id in all_ids}

    def find(candidate_id: str) -> str:
        while parent[candidate_id] != candidate_id:
            parent[candidate_id] = parent[parent[candidate_id]]
            candidate_id = parent[candidate_id]
        return candidate_id

    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    frozen_groups: dict[str, list[str]] = defaultdict(list)
    for candidate_id, row in prior_by_id.items():
        frozen_groups[row["final_isolation_family_id"]].append(candidate_id)
    for members in frozen_groups.values():
        for member in members[1:]:
            union(members[0], member)

    proposals = {}
    isolation_decisions: Counter[str] = Counter()
    for candidate_id in sorted(ip):
        packet, source = ip[candidate_id], ii[candidate_id]
        if any(source[field] != packet[field] for field in ("cohort", "prompt_sha256", "provisional_isolation_family_id")):
            raise ValueError(f"{candidate_id}: isolation identity changed")
        proposal = source["proposed_human_review"]
        if proposal.get("reviewer_id") != reviewer_id or proposal.get("review_status") != "pending_user_secondary_review":
            raise ValueError(f"{candidate_id}: isolation proposal is not confirmed researcher_01 input")
        decision, references = proposal["decision"], proposal["merge_with_candidate_ids"]
        if decision not in {"confirm", "merge"} or (decision == "confirm" and references) or (decision == "merge" and not references):
            raise ValueError(f"{candidate_id}: invalid isolation decision or merge references")
        for reference in references:
            if reference not in all_ids or reference == candidate_id:
                raise ValueError(f"{candidate_id}: invalid merge reference {reference}")
            union(candidate_id, reference)
        proposals[candidate_id] = proposal
        isolation_decisions[decision] += 1
    if isolation_decisions != Counter({"confirm": 7, "merge": 5}):
        raise ValueError(f"Confirmed isolation counts differ: {isolation_decisions}")

    components: dict[str, list[str]] = defaultdict(list)
    for candidate_id in all_ids:
        components[find(candidate_id)].append(candidate_id)
    if len(components) != 205:
        raise ValueError(f"Expected 205 closure components, found {len(components)}")
    final_ids = {}
    canonicalized = 0
    for members in components.values():
        frozen_ids = {prior_by_id[x]["final_isolation_family_id"] for x in members if x in prior_by_id}
        proposed_ids = {proposals[x]["reviewed_isolation_family_id"] for x in members if x in proposals}
        if len(frozen_ids) > 1 or (not frozen_ids and len(proposed_ids) != 1):
            raise ValueError(f"Inconsistent isolation IDs in component: {sorted(members)}")
        final_id = next(iter(frozen_ids or proposed_ids))
        canonicalized += sum(proposals[x]["reviewed_isolation_family_id"] != final_id for x in members if x in proposals)
        for member in members:
            final_ids[member] = final_id
    if len(set(final_ids.values())) != 205:
        raise ValueError("Different components reuse a canonical isolation ID")
    members_by_family: dict[str, list[str]] = defaultdict(list)
    for candidate_id, family_id in final_ids.items():
        members_by_family[family_id].append(candidate_id)

    isolation_formal = []
    for candidate_id in sorted(ip):
        row = json.loads(json.dumps(ip[candidate_id]))
        family_id = final_ids[candidate_id]
        row["human_review"] = {"decision": proposals[candidate_id]["decision"], "reviewed_isolation_family_id": family_id,
            "merge_with_candidate_ids": sorted(x for x in members_by_family[family_id] if x != candidate_id),
            "reviewer_id": reviewer_id, "reviewed_at": timestamp, "notes": proposals[candidate_id]["notes"]}
        jsonschema.validate(row, _json(root / ISOLATION_SCHEMA))
        isolation_formal.append(row)

    family_formal_path, isolation_formal_path = root / FAMILY_FORMAL, root / ISOLATION_FORMAL
    write_jsonl(family_formal_path, family_formal)
    write_jsonl(isolation_formal_path, isolation_formal)
    if _file_sha256(family_packet_path) != packet_hashes["family"] or _file_sha256(isolation_packet_path) != packet_hashes["isolation"] or _file_sha256(prior_path) != prior_hash:
        raise RuntimeError("A frozen packet or isolation manifest changed during import")

    records = []
    for candidate_id in sorted(all_ids):
        source = prior_by_id.get(candidate_id, ip.get(candidate_id))
        family_id = final_ids[candidate_id]
        records.append({"candidate_id": candidate_id, "cohort": source["cohort"], "prompt_sha256": source["prompt_sha256"],
            "final_isolation_family_id": family_id, "component_size": len(members_by_family[family_id]),
            "review_decision": source["review_decision"] if candidate_id in prior_by_id else proposals[candidate_id]["decision"],
            "split_status": "not_assigned_40_15_40_blocked_shortfall_1"})
    sizes = Counter(len(members) for members in members_by_family.values())
    manifest = {
        "manifest_version": "phase_3_final_isolation_manifest_v0_3", "status": "review_complete_40_15_40_blocked_shortfall_1_no_split",
        "reviewer_id": reviewer_id, "reviewed_at": timestamp,
        "formal_reviews": {"prior_270": {"path": PRIOR_MANIFEST, "sha256": prior_hash, "row_count": 270},
                           "supplemental_12": {"path": ISOLATION_FORMAL, "tracked": False, "sha256": _file_sha256(isolation_formal_path), "row_count": 12}},
        "counts": {"candidate_count": 282, "supplemental_confirm": 7, "supplemental_merge": 5, "supplemental_exclude": 0,
                   "merged_components": sum(size > 1 for size in sizes.elements()), "final_isolation_families": 205,
                   "component_size_distribution": dict(sorted(sizes.items())), "supplemental_ids_canonicalized_to_frozen_family_id": canonicalized},
        "records": records,
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "candidate_count_282", "identity_hash_text_and_provenance_preserved", "original_packets_unmodified",
            "frozen_v0_2_manifest_unmodified", "merge_references_valid", "transitive_closure_complete",
            "canonical_frozen_family_ids_preserved", "family_id_unique_across_components", "schema_valid", "split_assignment_zero")],
        "claim_boundary": "All 282 reviewed candidates are transitively closed, but the unchanged 40/15/40 gate remains one train family short. No split, model run, training result, or causal evidence is created."
    }
    jsonschema.validate(manifest, _json(root / FINAL_SCHEMA))
    (root / FINAL_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    review_paths = (FORMAL_REVIEW_PATH, EXPANSION_FORMAL_PATH, ADDITIONAL_FORMAL)
    reviews = [row for path in review_paths for row in _rows(root / path)] + family_formal
    if len(reviews) != 282:
        raise ValueError("Formal family review population must contain 282 records")
    evaluation = {final_ids[row["candidate_id"]] for row in reviews if row["human_review"]["pair_evaluation_eligible"]}
    qlora = {final_ids[row["candidate_id"]] for row in reviews if any(x["qlora_training_eligible"] for x in row["human_review"]["response_annotations"])}
    evaluation_only, qlora_only, both = evaluation - qlora, qlora - evaluation, evaluation & qlora
    maximum_train = len(qlora) - max(0, 55 - len(evaluation_only))
    feasible = len(evaluation) >= 55 and maximum_train >= 40
    if feasible or maximum_train != 39:
        raise ValueError("Unexpected final 40/15/40 recomputation")
    summary = {
        "summary_version": "phase_3_small_supplement_review_acceptance_v0_1",
        "status": "reviews_complete_40_15_40_blocked_shortfall_1_no_split", "reviewer_id": reviewer_id, "reviewed_at": timestamp,
        "inputs": {"family_prereview": {"filename": family_prereview.name, "sha256": _file_sha256(family_prereview)},
                   "isolation_prereview": {"filename": isolation_prereview.name, "sha256": _file_sha256(isolation_prereview)},
                   "family_packet": {"path": FAMILY_PACKET, "sha256": packet_hashes["family"], "modified": False},
                   "isolation_packet": {"path": ISOLATION_PACKET, "sha256": packet_hashes["isolation"], "modified": False},
                   "prior_final_isolation_manifest": {"path": PRIOR_MANIFEST, "sha256": prior_hash, "modified": False}},
        "formal_reviews": {"family": {"path": FAMILY_FORMAL, "tracked": False, "sha256": _file_sha256(family_formal_path), "row_count": 12},
                           "isolation": {"path": ISOLATION_FORMAL, "tracked": False, "sha256": _file_sha256(isolation_formal_path), "row_count": 12}},
        "family_counts": {"mapping_decisions": dict(sorted(decisions.items())), "pair_contrasts": dict(sorted(contrasts.items())),
                          "paired_evaluation_eligible": sum(row["human_review"]["pair_evaluation_eligible"] for row in family_formal),
                          "qlora_training_eligible_responses": eligible_responses},
        "isolation_counts": manifest["counts"],
        "disjoint_gate_audit": {"evaluation_eligible_families": len(evaluation), "qlora_eligible_families": len(qlora),
            "both_role_families": len(both), "evaluation_only_families": len(evaluation_only), "qlora_only_families": len(qlora_only),
            "maximum_qlora_train_families_after_reserving_15_dev_and_40_test": maximum_train,
            "qlora_train_shortfall": 1, "meets_40_15_40": False},
        "decision": {"outcome": "blocked_shortfall_1", "split_created": False, "model_execution_authorized": False,
                     "automatic_expansion_allowed": False},
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "all_12_input_ids_complete", "raw_packet_identity_hash_text_and_provenance_preserved", "family_schema_and_eligibility_valid",
            "isolation_schema_and_relations_valid", "merge_transitive_closure_and_canonical_ids", "split_not_created")]
                  + [{"check_id": "disjoint_40_15_40_feasibility", "status": "blocked_shortfall_1"}],
        "claim_boundary": "The confirmed supplemental review improves the maximum disjoint allocation to 39/15/40, not 40/15/40. The frozen gate remains unmet; no split or model execution is authorized."
    }
    (root / ACCEPTANCE).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
