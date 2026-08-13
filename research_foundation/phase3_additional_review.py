from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import jsonschema

from research_foundation.phase3_additional_tranche import ISOLATION_REVIEW_SCHEMA_PATH
from research_foundation.phase3_data_contract import FORMAL_REVIEW_PATH, REVIEW_SCHEMA_PATH, _file_sha256, validate_phase_3_review_rows
from research_foundation.phase3_expansion_review import EXPANSION_FORMAL_PATH, FINAL_ISOLATION_MANIFEST_PATH
from research_foundation.public_pilot import iter_jsonl, write_jsonl


FAMILY_PACKET = "results/local_artifacts/research_foundation/phase_3/phase_3_additional_tranche_review_packet_v0_1.jsonl"
ISOLATION_PACKET = "results/local_artifacts/research_foundation/phase_3/phase_3_additional_tranche_isolation_review_packet_v0_1.jsonl"
FAMILY_FORMAL = "results/local_artifacts/research_foundation/phase_3/phase_3_additional_tranche_family_review_completed_v0_1.jsonl"
ISOLATION_FORMAL = "results/local_artifacts/research_foundation/phase_3/phase_3_additional_tranche_isolation_review_completed_v0_1.jsonl"
FINAL_MANIFEST = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_2.json"
FINAL_SCHEMA = "data/research_foundation/schemas/phase_3_final_isolation_manifest_v0_2.schema.json"
ACCEPTANCE = "results/summaries/phase_3_additional_tranche_review_acceptance_v0_1.json"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [row for _, row in iter_jsonl(path)]


def import_confirmed_additional_reviews(root: Path, family_prereview: Path, isolation_prereview: Path) -> dict[str, Any]:
    reviewer_id = "researcher_01"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    packet_paths = {"family": root / FAMILY_PACKET, "isolation": root / ISOLATION_PACKET}
    packet_hashes = {name: _file_sha256(path) for name, path in packet_paths.items()}
    family_packet, isolation_packet = _rows(packet_paths["family"]), _rows(packet_paths["isolation"])
    family_input, isolation_input = _rows(family_prereview), _rows(isolation_prereview)
    groups = [family_packet, isolation_packet, family_input, isolation_input]
    if any(len(rows) != 30 or len({row["candidate_id"] for row in rows}) != 30 for rows in groups):
        raise ValueError("Every additional-tranche input must contain 30 unique candidates")
    fp, ip, fi, ii = ({row["candidate_id"]: row for row in rows} for rows in groups)
    if not (set(fp) == set(ip) == set(fi) == set(ii)):
        raise ValueError("Additional-tranche candidate ID sets differ")

    family_formal = []
    for candidate_id in sorted(fp):
        packet, source = fp[candidate_id], fi[candidate_id]
        if source["content_sha256"] != packet["content_sha256"] or source["source_family_id"] != packet["source_family_id"]:
            raise ValueError(f"{candidate_id}: family identity or provenance changed")
        proposal = source["proposed_human_review"]
        if proposal.get("reviewer_id") != reviewer_id or proposal.get("review_status") != "pending_user_secondary_review":
            raise ValueError(f"{candidate_id}: family prereview is not the confirmed researcher_01 proposal")
        if any(not value or "pending" in value for value in proposal["reviewed_family_assignment"].values()):
            raise ValueError(f"{candidate_id}: family assignment is incomplete")
        row = json.loads(json.dumps(packet))
        row["human_review"] = {key: proposal[key] for key in (
            "mapping_decision", "response_annotations", "pair_contrast", "reviewed_family_assignment",
            "pair_evaluation_eligible", "quality_flags", "notes"
        )}
        row["human_review"].update({"reviewer_id": reviewer_id, "reviewed_at": timestamp})
        family_formal.append(row)
    validate_phase_3_review_rows(family_formal, _json(root / REVIEW_SCHEMA_PATH))
    decisions = Counter(row["human_review"]["mapping_decision"] for row in family_formal)
    contrasts = Counter(row["human_review"]["pair_contrast"] for row in family_formal)
    if decisions != Counter({"accept": 21, "ambiguous": 2, "reject": 7}) or contrasts["valid_single_axis"] != 9:
        raise ValueError(f"Confirmed family counts differ: {decisions}, {contrasts}")
    if any(row["human_review"]["pair_evaluation_eligible"] != (row["human_review"]["pair_contrast"] == "valid_single_axis") for row in family_formal):
        raise ValueError("Only valid_single_axis may be paired-evaluation eligible")

    old_path = root / FINAL_ISOLATION_MANIFEST_PATH
    old_hash = _file_sha256(old_path)
    old = _json(old_path)
    old_by_id = {row["candidate_id"]: row for row in old["records"]}
    all_ids = set(old_by_id) | set(ip)
    if len(old_by_id) != 240 or len(all_ids) != 270:
        raise ValueError("The frozen 240 and additional 30 populations are not disjoint")
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
    for candidate_id, row in old_by_id.items():
        frozen_groups[row["final_isolation_family_id"]].append(candidate_id)
    for members in frozen_groups.values():
        for member in members[1:]:
            union(members[0], member)

    proposals: dict[str, dict[str, Any]] = {}
    isolation_decisions: Counter[str] = Counter()
    for candidate_id in sorted(ip):
        packet, source = ip[candidate_id], ii[candidate_id]
        if any(source[field] != packet[field] for field in ("cohort", "prompt_sha256", "provisional_isolation_family_id")):
            raise ValueError(f"{candidate_id}: isolation identity changed")
        proposal = source["proposed_human_review"]
        if proposal.get("reviewer_id") != reviewer_id or proposal.get("review_status") != "pending_user_secondary_review":
            raise ValueError(f"{candidate_id}: isolation prereview is not the confirmed researcher_01 proposal")
        decision, references = proposal["decision"], proposal["merge_with_candidate_ids"]
        if decision not in {"confirm", "merge"} or (decision == "confirm" and references) or (decision == "merge" and not references):
            raise ValueError(f"{candidate_id}: invalid isolation decision or references")
        for reference in references:
            if reference not in all_ids or reference == candidate_id:
                raise ValueError(f"{candidate_id}: invalid merge reference {reference}")
            union(candidate_id, reference)
        isolation_decisions[decision] += 1
        proposals[candidate_id] = proposal
    if isolation_decisions != Counter({"confirm": 8, "merge": 22}):
        raise ValueError(f"Confirmed isolation counts differ: {isolation_decisions}")

    components: dict[str, list[str]] = defaultdict(list)
    for candidate_id in all_ids:
        components[find(candidate_id)].append(candidate_id)
    if len(components) != 198:
        raise ValueError(f"Expected 198 final isolation families, found {len(components)}")
    final_ids: dict[str, str] = {}
    canonicalized = 0
    for members in components.values():
        frozen_ids = {old_by_id[x]["final_isolation_family_id"] for x in members if x in old_by_id}
        proposed_ids = {proposals[x]["reviewed_isolation_family_id"] for x in members if x in proposals}
        if len(frozen_ids) > 1 or (not frozen_ids and len(proposed_ids) != 1):
            raise ValueError(f"Component has inconsistent family IDs: {sorted(members)}")
        final_id = next(iter(frozen_ids or proposed_ids))
        canonicalized += sum(proposals[x]["reviewed_isolation_family_id"] != final_id for x in members if x in proposals)
        for member in members:
            final_ids[member] = final_id
    if len(set(final_ids.values())) != 198:
        raise ValueError("Different components reuse a final p3iso ID")
    members_by_family: dict[str, list[str]] = defaultdict(list)
    for candidate_id, family_id in final_ids.items():
        members_by_family[family_id].append(candidate_id)

    isolation_formal = []
    for candidate_id in sorted(ip):
        row = json.loads(json.dumps(ip[candidate_id]))
        family_id = final_ids[candidate_id]
        row["human_review"] = {
            "decision": proposals[candidate_id]["decision"],
            "reviewed_isolation_family_id": family_id,
            "merge_with_candidate_ids": sorted(x for x in members_by_family[family_id] if x != candidate_id),
            "reviewer_id": reviewer_id,
            "reviewed_at": timestamp,
            "notes": proposals[candidate_id]["notes"],
        }
        jsonschema.validate(row, _json(root / ISOLATION_REVIEW_SCHEMA_PATH))
        isolation_formal.append(row)

    family_formal_path, isolation_formal_path = root / FAMILY_FORMAL, root / ISOLATION_FORMAL
    write_jsonl(family_formal_path, family_formal)
    write_jsonl(isolation_formal_path, isolation_formal)
    if any(_file_sha256(packet_paths[name]) != packet_hashes[name] for name in packet_paths) or _file_sha256(old_path) != old_hash:
        raise RuntimeError("A frozen packet or manifest changed during import")

    records = []
    for candidate_id in sorted(all_ids):
        source = old_by_id.get(candidate_id, ip.get(candidate_id))
        family_id = final_ids[candidate_id]
        records.append({
            "candidate_id": candidate_id, "cohort": source["cohort"], "prompt_sha256": source["prompt_sha256"],
            "final_isolation_family_id": family_id, "component_size": len(members_by_family[family_id]),
            "review_decision": source["review_decision"] if candidate_id in old_by_id else proposals[candidate_id]["decision"],
            "split_status": "not_assigned_pending_authorized_small_supplement",
        })
    sizes = Counter(len(members) for members in members_by_family.values())
    manifest = {
        "manifest_version": "phase_3_final_isolation_manifest_v0_2", "status": "additional_30_review_complete_no_split",
        "reviewer_id": reviewer_id, "reviewed_at": timestamp,
        "formal_reviews": {"prior_240": old["formal_review"], "additional_30": {"path": ISOLATION_FORMAL, "tracked": False, "sha256": _file_sha256(isolation_formal_path), "row_count": 30}},
        "counts": {"candidate_count": 270, "additional_confirm": 8, "additional_merge": 22, "additional_exclude": 0,
                   "merged_components": sum(size > 1 for size in sizes.elements()), "final_isolation_families": 198,
                   "component_size_distribution": dict(sorted(sizes.items())), "additional_ids_canonicalized_to_frozen_family_id": canonicalized},
        "records": records,
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "candidate_count_270", "identity_hash_text_and_provenance_preserved", "original_packets_unmodified",
            "frozen_v0_1_manifest_unmodified", "merge_references_valid", "transitive_closure_complete",
            "one_family_id_per_component", "family_id_unique_across_components", "schema_valid", "split_assignment_zero")],
        "claim_boundary": "The confirmed additional 30 are transitively closed with the frozen 240. No split, model run, training result, or causal evidence is created.",
    }
    jsonschema.validate(manifest, _json(root / FINAL_SCHEMA))
    (root / FINAL_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    reviews = _rows(root / FORMAL_REVIEW_PATH) + _rows(root / EXPANSION_FORMAL_PATH) + family_formal
    evaluation = {final_ids[row["candidate_id"]] for row in reviews if row["human_review"]["pair_evaluation_eligible"]}
    qlora = {final_ids[row["candidate_id"]] for row in reviews if any(x["qlora_training_eligible"] for x in row["human_review"]["response_annotations"])}
    evaluation_only, qlora_only, both = evaluation - qlora, qlora - evaluation, evaluation & qlora
    maximum_train = len(qlora) - max(0, 55 - len(evaluation_only))
    feasible = len(evaluation) >= 55 and maximum_train >= 40
    if feasible or maximum_train != 37:
        raise ValueError("Unexpected 40/15/40 recomputation")
    summary = {
        "summary_version": "phase_3_additional_tranche_review_acceptance_v0_1",
        "status": "review_complete_shortfall_3_pending_user_authorized_small_supplement", "reviewer_id": reviewer_id, "reviewed_at": timestamp,
        "inputs": {"family_prereview": {"filename": family_prereview.name, "sha256": _file_sha256(family_prereview)},
                   "isolation_prereview": {"filename": isolation_prereview.name, "sha256": _file_sha256(isolation_prereview)},
                   "family_packet": {"path": FAMILY_PACKET, "sha256": packet_hashes["family"], "modified": False},
                   "isolation_packet": {"path": ISOLATION_PACKET, "sha256": packet_hashes["isolation"], "modified": False}},
        "formal_reviews": {"family": {"path": FAMILY_FORMAL, "tracked": False, "sha256": _file_sha256(family_formal_path), "row_count": 30},
                           "isolation": {"path": ISOLATION_FORMAL, "tracked": False, "sha256": _file_sha256(isolation_formal_path), "row_count": 30}},
        "family_counts": {"mapping_decisions": dict(sorted(decisions.items())), "pair_contrasts": dict(sorted(contrasts.items())),
                          "paired_evaluation_eligible": sum(row["human_review"]["pair_evaluation_eligible"] for row in family_formal),
                          "qlora_training_eligible_responses": sum(x["qlora_training_eligible"] for row in family_formal for x in row["human_review"]["response_annotations"])},
        "isolation_counts": manifest["counts"],
        "disjoint_gate_audit": {"evaluation_eligible_families": len(evaluation), "qlora_eligible_families": len(qlora),
                                "both_role_families": len(both), "evaluation_only_families": len(evaluation_only), "qlora_only_families": len(qlora_only),
                                "maximum_qlora_train_families_after_reserving_15_dev_and_40_test": maximum_train,
                                "qlora_train_shortfall": 3, "meets_40_15_40": False},
        "decision": {"outcome": "one_user_authorized_bounded_supplement", "split_created": False, "model_execution_authorized": False,
                     "automatic_expansion_allowed": False, "authorized_supplement_candidate_count": 12},
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "all_30_input_ids_complete", "raw_packet_identity_hash_text_and_provenance_preserved", "family_schema_and_eligibility_valid",
            "isolation_schema_and_relations_valid", "merge_transitive_closure_and_canonical_ids", "split_not_created")]
                  + [{"check_id": "disjoint_40_15_40_feasibility", "status": "blocked_shortfall_3"}],
        "claim_boundary": "The confirmed 30 improve the maximum disjoint allocation to 37/15/40, not 40/15/40. The user authorized one small bounded supplement; no automatic open-ended expansion or model execution is authorized.",
    }
    (root / ACCEPTANCE).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
