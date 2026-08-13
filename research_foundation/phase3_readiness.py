from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from research_foundation.representation_freeze import canonical_content_sha256


PROTOCOL_PATH = "configs/research/phase_3_limited_fair_comparison_protocol_v0_1.json"
PROTOCOL_SCHEMA_PATH = "data/research_foundation/schemas/phase_3_limited_fair_comparison_protocol_v0_1.schema.json"
LEGACY_STEERING_CONFIG = "configs/experiments/steering_qwen3_4b.phase_c_batch2.yaml"
V3_CANDIDATES = "data/post_training/boundary_preserving_cleaned_sft_candidates_v0_3.jsonl"
V3_REVIEW = "data/post_training/boundary_preserving_human_review_ready_v0_3.jsonl"
V3_EVAL = "data/post_training/boundary_preserving_cleaned_eval_pairs_v0_3.jsonl"
PHASE3_CANDIDATE_MANIFEST = "data/research_foundation/manifests/phase_3_family_candidate_manifest_v0_1.json"
PHASE3_REVIEW_ACCEPTANCE = "results/summaries/phase_3_family_review_acceptance_v0_1.json"
PHASE3_ISOLATION_AUDIT = "results/summaries/phase_3_family_isolation_options_audit_v0_1.json"
PHASE3_EXPANSION_MANIFEST = "data/research_foundation/manifests/phase_3_expansion_candidate_manifest_v0_1.json"
PHASE3_PROVISIONAL_ISOLATION = "data/research_foundation/manifests/phase_3_provisional_isolation_families_v0_1.json"
PHASE3_FINAL_ISOLATION = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_1.json"
PHASE3_EXPANSION_ACCEPTANCE = "results/summaries/phase_3_expansion_and_isolation_review_acceptance_v0_1.json"
PHASE3_ADDITIONAL_TRANCHE = "data/research_foundation/manifests/phase_3_additional_tranche_manifest_v0_1.json"
PHASE3_ADDITIONAL_ACCEPTANCE = "results/summaries/phase_3_additional_tranche_review_acceptance_v0_1.json"
PHASE3_FINAL_ISOLATION_V2 = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_2.json"
PHASE3_SMALL_SUPPLEMENT = "data/research_foundation/manifests/phase_3_small_supplement_manifest_v0_1.json"
PHASE3_SMALL_SUPPLEMENT_ACCEPTANCE = "results/summaries/phase_3_small_supplement_review_acceptance_v0_1.json"
PHASE3_FINAL_ISOLATION_V3 = "data/research_foundation/manifests/phase_3_final_isolation_families_v0_3.json"
PHASE3_DATA_GATE_AMENDMENT = "configs/research/phase_3_data_gate_amendment_v0_1.json"
PHASE3_DATA_GATE_AMENDMENT_SCHEMA = "data/research_foundation/schemas/phase_3_data_gate_amendment_v0_1.schema.json"
PHASE3_DATA_GATE_ACCEPTANCE = "results/summaries/phase_3_data_gate_amendment_acceptance_v0_1.json"
PHASE3_FAMILY_SPLIT = "data/research_foundation/manifests/phase_3_family_split_v0_1.json"
PHASE3_TEST_FREEZE = "data/research_foundation/manifests/phase_3_held_out_test_freeze_v0_1.json"
PHASE3_TEST_ONCE = "configs/research/phase_3_test_once_contract_v0_1.json"
PHASE3_SPLIT_LEAKAGE_AUDIT = "results/summaries/phase_3_family_split_leakage_audit_v0_1.json"
PHASE3_BLIND_REVIEW_CONTRACT = "configs/research/phase_3_blind_review_contract_v0_1.json"
PHASE3_BLIND_REVIEW_SCHEMA = "data/research_foundation/schemas/phase_3_blind_review_contract_v0_1.schema.json"
PHASE3_SELECTION_CONTRACT = "configs/research/phase_3_train_dev_selection_contract_v0_1.json"
PHASE3_SELECTION_SCHEMA = "data/research_foundation/schemas/phase_3_train_dev_selection_contract_v0_1.schema.json"
PHASE3_TRAIN_DEV_RUNTIME = "configs/research/phase_3_train_dev_runtime_v0_1.json"
PHASE3_TRAIN_DEV_RUNTIME_SCHEMA = "data/research_foundation/schemas/phase_3_train_dev_runtime_v0_1.schema.json"
PHASE3_MODEL_GPU_NOTICE = "results/summaries/phase_3_model_gpu_execution_notice_v0_1.json"
PHASE3_TRAIN_DEV_EXECUTION = "results/summaries/phase_3_train_dev_execution_v0_1.json"
PHASE3_TRAIN_DEV_EXECUTION_SCHEMA = "data/research_foundation/schemas/phase_3_train_dev_execution_v0_1.schema.json"
PHASE3_DEV_REVIEW_FREEZE = "data/research_foundation/manifests/phase_3_development_blind_review_freeze_v0_1.json"
PHASE3_SELECTION_SUMMARY = "results/summaries/phase_3_train_dev_selection_v0_1.json"
PHASE3_SELECTION_LOCK = "results/local_artifacts/research_foundation/phase_3/phase_3_train_dev_selection_lock_v0_1.json"
PHASE3_HELD_OUT_RUNTIME = "configs/research/phase_3_held_out_runtime_v0_1.json"
PHASE3_HELD_OUT_NOTICE = "results/summaries/phase_3_held_out_model_gpu_execution_notice_v0_1.json"
PHASE3_HELD_OUT_EXECUTION = "results/summaries/phase_3_held_out_execution_v0_1.json"
PHASE3_HELD_OUT_EXECUTION_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_execution_v0_1.schema.json"
PHASE3_INDEPENDENT_REVIEW_AMENDMENT = "configs/research/phase_3_independent_blind_review_amendment_v0_2.json"
PHASE3_INDEPENDENT_REVIEW_AMENDMENT_SCHEMA = "data/research_foundation/schemas/phase_3_independent_blind_review_amendment_v0_2.schema.json"
PHASE3_RESEARCHER_02_REVIEW_CONTRACT = "configs/research/phase_3_researcher_02_review_contract_v0_3.json"
PHASE3_RESEARCHER_02_REVIEW_CONTRACT_SCHEMA = "data/research_foundation/schemas/phase_3_researcher_02_review_contract_v0_3.schema.json"
PHASE3_HELD_OUT_REVIEW_FREEZE = "data/research_foundation/manifests/phase_3_held_out_blind_review_freeze_v0_3.json"
PHASE3_HELD_OUT_ANALYSIS_CONTRACT = "configs/research/phase_3_held_out_analysis_contract_v0_1.json"
PHASE3_HELD_OUT_ANALYSIS_CONTRACT_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_analysis_contract_v0_1.schema.json"
PHASE3_HELD_OUT_RESULTS = "results/summaries/phase_3_held_out_results_v0_1.json"
PHASE3_HELD_OUT_RESULTS_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_results_v0_1.schema.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_phase_3_readiness(root: Path) -> dict[str, Any]:
    protocol = read_json(root / PROTOCOL_PATH)
    jsonschema.validate(protocol, read_json(root / PROTOCOL_SCHEMA_PATH))
    acceptance_path = root / protocol["evidence_basis"]["phase_2_acceptance_path"]
    acceptance_hash_matches = canonical_content_sha256(read_json(acceptance_path)) == protocol["evidence_basis"]["phase_2_acceptance_sha256"]
    if not acceptance_hash_matches:
        raise ValueError("Phase 3 protocol does not bind the current Phase 2 acceptance")

    legacy_datasets = []
    for relative in protocol["data_gates"]["legacy_sft_forbidden"]:
        path = root / relative
        rows = read_jsonl(path)
        responses = [str(row.get("response", "")) for row in rows]
        legacy_datasets.append(
            {
                "path": relative,
                "sha256": file_sha256(path),
                "row_count": len(rows),
                "template_phrase_hits": {
                    "the_request_asks_me_to": sum(
                        "the request asks me to" in value.lower() for value in responses
                    ),
                    "if_you_want_i_can_help": sum(
                        "if you want, i can help" in value.lower() for value in responses
                    ),
                },
                "phase_3_training_allowed": False,
            }
        )

    candidates = read_jsonl(root / V3_CANDIDATES)
    review_items = read_jsonl(root / V3_REVIEW)
    eval_pairs = read_jsonl(root / V3_EVAL)
    phase3_candidates = read_json(root / PHASE3_CANDIDATE_MANIFEST)
    phase3_review = read_json(root / PHASE3_REVIEW_ACCEPTANCE)
    phase3_isolation = read_json(root / PHASE3_ISOLATION_AUDIT)
    phase3_expansion = read_json(root / PHASE3_EXPANSION_MANIFEST)
    provisional_isolation = read_json(root / PHASE3_PROVISIONAL_ISOLATION)
    final_isolation = read_json(root / PHASE3_FINAL_ISOLATION)
    expansion_acceptance = read_json(root / PHASE3_EXPANSION_ACCEPTANCE)
    additional_tranche = read_json(root / PHASE3_ADDITIONAL_TRANCHE)
    additional_acceptance = read_json(root / PHASE3_ADDITIONAL_ACCEPTANCE)
    final_isolation_v2 = read_json(root / PHASE3_FINAL_ISOLATION_V2)
    small_supplement = read_json(root / PHASE3_SMALL_SUPPLEMENT)
    small_supplement_acceptance = read_json(root / PHASE3_SMALL_SUPPLEMENT_ACCEPTANCE)
    final_isolation_v3 = read_json(root / PHASE3_FINAL_ISOLATION_V3)
    data_gate_amendment = read_json(root / PHASE3_DATA_GATE_AMENDMENT)
    jsonschema.validate(data_gate_amendment, read_json(root / PHASE3_DATA_GATE_AMENDMENT_SCHEMA))
    data_gate_acceptance = read_json(root / PHASE3_DATA_GATE_ACCEPTANCE)
    family_split = read_json(root / PHASE3_FAMILY_SPLIT)
    test_freeze = read_json(root / PHASE3_TEST_FREEZE)
    test_once = read_json(root / PHASE3_TEST_ONCE)
    split_leakage = read_json(root / PHASE3_SPLIT_LEAKAGE_AUDIT)
    blind_review_contract = read_json(root / PHASE3_BLIND_REVIEW_CONTRACT)
    selection_contract = read_json(root / PHASE3_SELECTION_CONTRACT)
    jsonschema.validate(blind_review_contract, read_json(root / PHASE3_BLIND_REVIEW_SCHEMA))
    jsonschema.validate(selection_contract, read_json(root / PHASE3_SELECTION_SCHEMA))
    train_dev_runtime = read_json(root / PHASE3_TRAIN_DEV_RUNTIME)
    train_dev_execution = read_json(root / PHASE3_TRAIN_DEV_EXECUTION)
    model_gpu_notice = read_json(root / PHASE3_MODEL_GPU_NOTICE)
    jsonschema.validate(train_dev_runtime, read_json(root / PHASE3_TRAIN_DEV_RUNTIME_SCHEMA))
    jsonschema.validate(train_dev_execution, read_json(root / PHASE3_TRAIN_DEV_EXECUTION_SCHEMA))
    if canonical_content_sha256(train_dev_runtime) != model_gpu_notice["runtime_sha256"]:
        raise ValueError("Phase 3 model/GPU notice does not bind the frozen runtime")
    if canonical_content_sha256(train_dev_runtime) != train_dev_execution["runtime"]["sha256"]:
        raise ValueError("Phase 3 execution summary does not bind the frozen runtime")
    development_review_freeze = read_json(root / PHASE3_DEV_REVIEW_FREEZE)
    selection_summary = read_json(root / PHASE3_SELECTION_SUMMARY)
    if file_sha256(root / development_review_freeze["formal_annotations"]["path"]) != development_review_freeze["formal_annotations"]["sha256"]:
        raise ValueError("Phase 3 frozen development annotations hash mismatch")
    selection_lock = read_json(root / PHASE3_SELECTION_LOCK)
    if canonical_content_sha256(selection_lock) != selection_summary["selection_lock_sha256"]:
        raise ValueError("Phase 3 train/dev selection lock hash mismatch")
    from research_foundation.phase3_test_runtime import load_held_out_runtime

    held_out_runtime = load_held_out_runtime(root, require_unopened=False)
    held_out_notice = read_json(root / PHASE3_HELD_OUT_NOTICE)
    if held_out_notice["runtime_path"] != PHASE3_HELD_OUT_RUNTIME or held_out_notice["runtime_sha256"] != canonical_content_sha256(held_out_runtime):
        raise ValueError("Phase 3 held-out model/GPU notice does not bind the frozen runtime")
    held_out_execution = read_json(root / PHASE3_HELD_OUT_EXECUTION)
    jsonschema.validate(held_out_execution, read_json(root / PHASE3_HELD_OUT_EXECUTION_SCHEMA))
    if held_out_execution["runtime"]["sha256"] != canonical_content_sha256(held_out_runtime):
        raise ValueError("Phase 3 held-out execution summary does not bind the frozen runtime")
    independent_amendment = read_json(root / PHASE3_INDEPENDENT_REVIEW_AMENDMENT)
    jsonschema.validate(independent_amendment, read_json(root / PHASE3_INDEPENDENT_REVIEW_AMENDMENT_SCHEMA))
    for key, relative in independent_amendment["bound_evidence"].items():
        if key.endswith("_path") and canonical_content_sha256(read_json(root / relative)) != independent_amendment["bound_evidence"][key.removesuffix("_path") + "_sha256"]:
            raise ValueError(f"Phase 3 independent-review amendment evidence mismatch: {key}")
    researcher_02_contract = read_json(root / PHASE3_RESEARCHER_02_REVIEW_CONTRACT)
    jsonschema.validate(
        researcher_02_contract,
        read_json(root / PHASE3_RESEARCHER_02_REVIEW_CONTRACT_SCHEMA),
    )
    researcher_02_compliance = read_json(root / researcher_02_contract["artifacts"]["compliance_record"])
    held_out_review_freeze = read_json(root / PHASE3_HELD_OUT_REVIEW_FREEZE)
    formal_held_out_annotations = root / held_out_review_freeze["formal_annotations"]["path"]
    if file_sha256(formal_held_out_annotations) != held_out_review_freeze["formal_annotations"]["sha256"]:
        raise ValueError("Phase 3 held-out formal annotations hash mismatch")
    held_out_analysis_contract = read_json(root / PHASE3_HELD_OUT_ANALYSIS_CONTRACT)
    jsonschema.validate(
        held_out_analysis_contract,
        read_json(root / PHASE3_HELD_OUT_ANALYSIS_CONTRACT_SCHEMA),
    )
    held_out_results = read_json(root / PHASE3_HELD_OUT_RESULTS)
    jsonschema.validate(held_out_results, read_json(root / PHASE3_HELD_OUT_RESULTS_SCHEMA))
    if held_out_results["bound_evidence"]["formal_annotations_sha256"] != held_out_review_freeze["formal_annotations"]["sha256"]:
        raise ValueError("Phase 3 held-out results do not bind the frozen annotations")
    if held_out_results["bound_evidence"]["analysis_contract_sha256"] != canonical_content_sha256(held_out_analysis_contract):
        raise ValueError("Phase 3 held-out results do not bind the analysis contract")
    for contract_name, contract in (
        ("blind review", blind_review_contract),
        ("train/dev selection", selection_contract),
    ):
        evidence = contract["bound_evidence"]
        for key, value in evidence.items():
            if not key.endswith("_path"):
                continue
            hash_key = key.removesuffix("_path") + "_sha256"
            if canonical_content_sha256(read_json(root / value)) != evidence[hash_key]:
                raise ValueError(f"Phase 3 {contract_name} contract evidence hash mismatch: {key}")
    for path_key, hash_key in (
        ("review_acceptance_path", "review_acceptance_sha256"),
        ("final_isolation_manifest_path", "final_isolation_manifest_sha256"),
    ):
        if canonical_content_sha256(read_json(root / data_gate_amendment["bound_evidence"][path_key])) != data_gate_amendment["bound_evidence"][hash_key]:
            raise ValueError(f"Phase 3 data-gate amendment evidence hash mismatch: {path_key}")
    reviewed_items = sum(
        bool(row.get("human_review", {}).get("reviewer")) for row in review_items
    )
    legacy_steering = yaml.safe_load((root / LEGACY_STEERING_CONFIG).read_text(encoding="utf-8"))
    allowed_axes = set(protocol["research_scope"]["axis_ids"])
    unsupported_legacy_axes = sorted(set(legacy_steering["axes"]) - allowed_axes)
    gates = {
        "phase_2_acceptance_bound": acceptance_hash_matches,
        "protocol_schema_valid": True,
        "single_supported_axis_only": protocol["research_scope"]["axis_ids"]
        == ["boundary-preserving-over-accommodating"],
        "family_isolated_data_count_gate_passed_under_amended_39_15_40": data_gate_acceptance["gate_accounting"]["amended_39_15_40_passed"],
        "new_qlora_training_data_ready": family_split["counts"]["train_families"] == 39,
        "human_review_ready": True,
        "family_leakage_audit_passed": set(split_leakage["blocking_leakage_counts"].values()) == {0},
        "new_development_ready": family_split["counts"]["development_families"] == 15,
        "new_held_out_test_ready": (
            family_split["counts"]["held_out_test_families"] == 40
            and test_freeze["access_state"]["model_execution_openings"] == 0
        ),
        "blind_review_contract_ready": True,
        "train_dev_selection_contract_ready": True,
        "train_dev_runtime_ready": True,
        "model_gpu_notice_completed": True,
        "qlora_training_complete": train_dev_execution["training"]["checkpoint_ids"] == ["epoch_1", "epoch_2"],
        "development_candidate_generation_complete": train_dev_execution["development_generation"]["condition_outputs"] == 90,
        "development_human_review_complete": development_review_freeze["formal_annotations"]["row_count"] == 90,
        "train_dev_selection_lock_frozen": selection_lock["test_opening_status"] == "locked_not_opened",
        "held_out_runtime_frozen": (
            len(held_out_runtime["condition_registry"]["condition_ids"]) == 15
            and held_out_runtime["condition_registry"]["expected_output_count"] == 780
        ),
        "held_out_model_gpu_notice_issued": (
            held_out_notice["authorization_state"]["model_test_openings_at_notice"] == 0
            and held_out_notice["authorization_state"]["fresh_user_authorization_required"]
        ),
        "held_out_condition_generation_complete": (
            held_out_execution["generation"]["condition_outputs"] == 780
            and held_out_execution["blind_review"]["blind_outputs"] == 780
            and held_out_execution["access"]["event_count"] == 1
        ),
        "independent_review_amendment_frozen": (
            not independent_amendment["independent_reviewer"]["researcher_01_eligible"]
            and independent_amendment["review_contract"]["required_ratings"] == 780
        ),
        "researcher_02_review_materials_ready": (
            researcher_02_contract["reviewer"]["reviewer_id"] == "researcher_02"
            and researcher_02_contract["scoring"]["required_rows"] == 780
            and (root / researcher_02_contract["scoring"]["guide_path"]).is_file()
            and (root / researcher_02_contract["artifacts"]["review_packet"]).is_file()
            and (root / researcher_02_contract["artifacts"]["review_sheet"]).is_file()
            and researcher_02_compliance["reviewer_id"] == "researcher_02"
            and not researcher_02_compliance["reviewer_signature_recorded"]
            and set(researcher_02_compliance["checks"].values()) == {"compliant"}
        ),
        "held_out_human_review_frozen": (
            held_out_review_freeze["formal_annotations"]["row_count"] == 780
            and held_out_review_freeze["validation"]["unique_blind_outputs"] == 780
            and not held_out_review_freeze["condition_key_access_at_freeze"]
        ),
        "held_out_nonconfirmatory_analysis_complete": (
            held_out_results["status"] == "complete_nonconfirmatory_held_out_analysis"
            and len(held_out_results["condition_comparisons"]) == 14
        ),
    }
    return {
        "summary_version": "phase_3_readiness_audit_v0_1",
        "protocol_path": PROTOCOL_PATH,
        "protocol_sha256": canonical_content_sha256(protocol),
        "phase_2_acceptance_sha256": canonical_content_sha256(read_json(acceptance_path)),
        "study_role": protocol["research_scope"]["study_role"],
        "confirmatory_steering_gate": protocol["evidence_basis"]["confirmatory_steering_gate"],
        "legacy_assets": {
            "forbidden_sft": legacy_datasets,
            "legacy_steering_config": {
                "path": LEGACY_STEERING_CONFIG,
                "axes": legacy_steering["axes"],
                "unsupported_axes": unsupported_legacy_axes,
                "phase_3_evidence_reuse_allowed": False,
            },
        },
        "current_candidate_assets": {
            "phase_3_family_candidates": {
                "path": PHASE3_CANDIDATE_MANIFEST,
                "count": len(phase3_candidates["records"]),
                "completed_human_reviews": phase3_review["formal_review"]["row_count"],
                "split_assignments": sum(
                    record["split_status"] != "not_assigned_before_human_review"
                    for record in phase3_candidates["records"]
                ),
                "status": phase3_candidates["status"],
                "review_acceptance_path": PHASE3_REVIEW_ACCEPTANCE,
                "family_component_count": phase3_review["family_component_audit"]["component_count"],
                "family_allocation_ready": phase3_review["family_component_audit"]["allocation_ready"],
                "isolation_options_audit_path": PHASE3_ISOLATION_AUDIT,
                "isolation_options_status": phase3_isolation["status"],
                "identity_upper_bound_train_after_heldout": phase3_isolation["conclusion"][
                    "maximum_train_after_heldout_reservation"
                ],
            },
            "phase_3_expansion_candidates": {
                "path": PHASE3_EXPANSION_MANIFEST,
                "count": len(phase3_expansion["records"]),
                "completed_human_reviews": expansion_acceptance["formal_reviews"]["expansion"]["row_count"],
                "status": phase3_expansion["status"],
                "review_acceptance_path": PHASE3_EXPANSION_ACCEPTANCE,
            },
            "phase_3_provisional_isolation": {
                "path": PHASE3_PROVISIONAL_ISOLATION,
                "candidate_count": len(provisional_isolation["records"]),
                "provisional_component_count": provisional_isolation["construction"]["component_count"],
                "completed_semantic_merge_reviews": sum(
                    record["isolation_review_status"] != "pending_human_semantic_merge_review"
                    for record in provisional_isolation["records"]
                ),
                "status": provisional_isolation["status"],
            },
            "phase_3_final_isolation": {
                "path": PHASE3_FINAL_ISOLATION,
                "candidate_count": len(final_isolation["records"]),
                "final_family_count": final_isolation["counts"]["final_isolation_families"],
                "merged_component_count": final_isolation["counts"]["merged_components"],
                "status": final_isolation["status"],
                "disjoint_40_15_40_ready": expansion_acceptance["disjoint_gate_audit"]["meets_40_15_40"],
                "qlora_train_shortfall": expansion_acceptance["disjoint_gate_audit"]["qlora_train_shortfall"],
            },
            "phase_3_additional_tranche": {
                "path": PHASE3_ADDITIONAL_TRANCHE,
                "candidate_count": len(additional_tranche["records"]),
                "completed_human_reviews": additional_acceptance["formal_reviews"]["family"]["row_count"],
                "completed_isolation_reviews": additional_acceptance["formal_reviews"]["isolation"]["row_count"],
                "status": additional_acceptance["status"],
                "review_acceptance_path": PHASE3_ADDITIONAL_ACCEPTANCE,
            },
            "phase_3_final_isolation_v2": {
                "path": PHASE3_FINAL_ISOLATION_V2,
                "candidate_count": len(final_isolation_v2["records"]),
                "final_family_count": final_isolation_v2["counts"]["final_isolation_families"],
                "merged_component_count": final_isolation_v2["counts"]["merged_components"],
                "disjoint_40_15_40_ready": additional_acceptance["disjoint_gate_audit"]["meets_40_15_40"],
                "qlora_train_shortfall": additional_acceptance["disjoint_gate_audit"]["qlora_train_shortfall"],
                "status": final_isolation_v2["status"],
            },
            "phase_3_small_supplement": {
                "path": PHASE3_SMALL_SUPPLEMENT,
                "candidate_count": len(small_supplement["records"]),
                "completed_human_reviews": small_supplement_acceptance["formal_reviews"]["family"]["row_count"],
                "completed_isolation_reviews": small_supplement_acceptance["formal_reviews"]["isolation"]["row_count"],
                "status": small_supplement_acceptance["status"],
                "review_acceptance_path": PHASE3_SMALL_SUPPLEMENT_ACCEPTANCE,
            },
            "phase_3_final_isolation_v3": {
                "path": PHASE3_FINAL_ISOLATION_V3,
                "candidate_count": len(final_isolation_v3["records"]),
                "final_family_count": final_isolation_v3["counts"]["final_isolation_families"],
                "merged_component_count": final_isolation_v3["counts"]["merged_components"],
                "disjoint_40_15_40_ready": small_supplement_acceptance["disjoint_gate_audit"]["meets_40_15_40"],
                "qlora_train_shortfall": small_supplement_acceptance["disjoint_gate_audit"]["qlora_train_shortfall"],
                "status": final_isolation_v3["status"],
            },
            "phase_3_data_gate_amendment": {
                "path": PHASE3_DATA_GATE_AMENDMENT,
                "acceptance_path": PHASE3_DATA_GATE_ACCEPTANCE,
                "original_40_15_40_passed": data_gate_acceptance["gate_accounting"]["original_40_15_40_passed"],
                "amended_39_15_40_passed": data_gate_acceptance["gate_accounting"]["amended_39_15_40_passed"],
                "additional_candidate_expansion_allowed": data_gate_amendment["decision"]["additional_candidate_expansion_allowed"],
                "split_created_at_amendment_time": False,
            },
            "phase_3_family_split": {
                "path": PHASE3_FAMILY_SPLIT,
                "status": family_split["status"],
                "train_families": family_split["counts"]["train_families"],
                "development_families": family_split["counts"]["development_families"],
                "held_out_test_families": family_split["counts"]["held_out_test_families"],
                "leakage_audit_path": PHASE3_SPLIT_LEAKAGE_AUDIT,
                "leakage_audit_status": split_leakage["status"],
            },
            "phase_3_test_once": {
                "freeze_path": PHASE3_TEST_FREEZE,
                "contract_path": PHASE3_TEST_ONCE,
                "freeze_status": test_freeze["status"],
                "contract_status": test_once["status"],
                "model_execution_openings": test_freeze["access_state"]["model_execution_openings"],
            },
            "phase_3_pre_execution_contracts": {
                "blind_review_contract_path": PHASE3_BLIND_REVIEW_CONTRACT,
                "blind_review_contract_status": blind_review_contract["status"],
                "selection_contract_path": PHASE3_SELECTION_CONTRACT,
                "selection_contract_status": selection_contract["status"],
                "future_selection_lock_created": False,
            },
            "phase_3_train_dev_execution": {
                "runtime_path": PHASE3_TRAIN_DEV_RUNTIME,
                "notice_path": PHASE3_MODEL_GPU_NOTICE,
                "execution_summary_path": PHASE3_TRAIN_DEV_EXECUTION,
                "status": train_dev_execution["status"],
                "qlora_checkpoints": train_dev_execution["training"]["checkpoint_ids"],
                "development_condition_outputs": train_dev_execution["development_generation"]["condition_outputs"],
                "human_annotations_completed": train_dev_execution["blind_review"]["human_annotations_completed"],
            },
            "phase_3_train_dev_selection": {
                "review_freeze_path": PHASE3_DEV_REVIEW_FREEZE,
                "formal_annotation_rows": development_review_freeze["formal_annotations"]["row_count"],
                "selection_summary_path": PHASE3_SELECTION_SUMMARY,
                "selection_lock_path": PHASE3_SELECTION_LOCK,
                "selected_specification": selection_summary["selected_specification"],
                "quality_gate": selection_summary["quality_gate"],
                "held_out_test_model_openings": selection_summary["held_out_test_model_openings"],
            },
            "phase_3_held_out_runtime": {
                "runtime_path": PHASE3_HELD_OUT_RUNTIME,
                "runtime_sha256": canonical_content_sha256(held_out_runtime),
                "status": held_out_runtime["status"],
                "condition_count": len(held_out_runtime["condition_registry"]["condition_ids"]),
                "expected_output_count": held_out_runtime["condition_registry"]["expected_output_count"],
                "selected_target_alpha": held_out_runtime["selected_methods"]["target_steering_alpha"],
                "selected_qlora_checkpoint": held_out_runtime["selected_methods"]["qlora_checkpoint_id"],
                "selected_qlora_quality_gate_passed": held_out_runtime["selected_methods"]["qlora_quality_gate_passed"],
                "fresh_notice_and_user_authorization_required": held_out_runtime["execution_gate"]["fresh_user_authorization_required_after_notice"],
                "notice_path": PHASE3_HELD_OUT_NOTICE,
                "notice_status": held_out_notice["notice_status"],
                "execution_summary_path": PHASE3_HELD_OUT_EXECUTION,
                "execution_status": held_out_execution["status"],
                "test_openings": held_out_execution["access"]["event_count"],
                "condition_outputs": held_out_execution["generation"]["condition_outputs"],
                "blind_outputs": held_out_execution["blind_review"]["blind_outputs"],
                "human_annotations_completed": held_out_execution["blind_review"]["human_annotations_completed"],
            },
            "phase_3_independent_review": {
                "amendment_path": PHASE3_INDEPENDENT_REVIEW_AMENDMENT,
                "status": independent_amendment["status"],
                "reviewer_id": independent_amendment["independent_reviewer"]["reviewer_id"],
                "required_ratings": independent_amendment["review_contract"]["required_ratings"],
                "route_status": "superseded_by_researcher_02_review_contract_v0_3",
                "ratings_completed": 0
            },
            "phase_3_researcher_02_review": {
                "contract_path": PHASE3_RESEARCHER_02_REVIEW_CONTRACT,
                "status": researcher_02_contract["status"],
                "reviewer_id": researcher_02_contract["reviewer"]["reviewer_id"],
                "scoring_guide_path": researcher_02_contract["scoring"]["guide_path"],
                "review_packet_path": researcher_02_contract["artifacts"]["review_packet"],
                "review_sheet_path": researcher_02_contract["artifacts"]["review_sheet"],
                "compliance_source": researcher_02_contract["compliance_record_policy"]["source"],
                "reviewer_signature_recorded": researcher_02_compliance["reviewer_signature_recorded"],
                "required_ratings": researcher_02_contract["scoring"]["required_rows"],
                "ratings_completed": held_out_review_freeze["formal_annotations"]["row_count"],
                "review_freeze_path": PHASE3_HELD_OUT_REVIEW_FREEZE,
                "formal_annotations_sha256": held_out_review_freeze["formal_annotations"]["sha256"],
                "condition_key_access_at_freeze": held_out_review_freeze["condition_key_access_at_freeze"],
            },
            "phase_3_held_out_results": {
                "analysis_contract_path": PHASE3_HELD_OUT_ANALYSIS_CONTRACT,
                "results_path": PHASE3_HELD_OUT_RESULTS,
                "status": held_out_results["status"],
                "condition_comparisons": len(held_out_results["condition_comparisons"]),
                "primary_target_summary": held_out_results["primary_target_summary"],
            },
            "cleaned_sft_candidates": {
                "path": V3_CANDIDATES,
                "count": len(candidates),
                "human_approved_count": sum(row.get("human_annotated") is True for row in candidates),
                "minimum_required": protocol["data_gates"]["qlora_train"]["minimum_human_approved_families"],
            },
            "review_ready_items": {
                "path": V3_REVIEW,
                "count": len(review_items),
                "completed_human_reviews": reviewed_items,
            },
            "cleaned_eval_pairs": {
                "path": V3_EVAL,
                "count": len(eval_pairs),
                "human_annotated_count": sum(row.get("human_annotated") is True for row in eval_pairs),
            },
        },
        "gates": gates,
        "execution_status": "phase_3_limited_nonconfirmatory_comparison_complete",
        "model_or_gpu_run": True,
        "phase_3_completion_estimate": 1.0,
        "next_required_block": "stop_or_separately_authorize_phase_4_external_validity_decision",
        "claim_boundary": (
            "The original 40/15/40 gate failed by one train family. After observing that result, the researcher "
            "explicitly amended the data-count standard to 39/15/40 and stopped further expansion. The amended "
            "count gate passes. A deterministic family-isolated 39/15/40 split, zero-blocker leakage audit, and unopened "
            "test-once, condition-blind review, and bounded train/dev selection contracts are frozen. Advance model/GPU "
            "notice was recorded, the fixed two-epoch QLoRA run completed, and all 90 condition-blind development candidates "
            "were generated without opening test. The 90 ratings were frozen before restricted unblinding; alpha 1 and QLoRA "
            "epoch 1 are locked by the preregistered rule, while QLoRA fails the dev quality margin. Under the single held-out "
            "opening, all 780 outputs and a condition-blind packet were generated for 40 families and 52 pairs. No human held-out "
            "ratings or outcome statistics exist yet. Post-generation automation accessed the restricted condition key and disclosed "
            "aggregate condition-level exact-match diagnostics before rating freeze; per-item mappings were not disclosed, but strict "
            "pre-rating nonaccess cannot be claimed. The user designated researcher_02 for the amended independent-human review route; "
            "the scoring guide, packet, blank 780-row sheet and user-confirmed compliance record are prepared without a personal-name "
            "or signature field. That record must not be described as a reviewer-signed attestation. The submitted 780 ratings were "
            "validated and frozen before this workflow accessed the condition key. Based on the user's provenance statement, AI preliminary "
            "judgments were auxiliary and researcher_02 reviewed and owns every final rating. The frozen nonconfirmatory analysis finds no "
            "credible target-specific steering improvement and a large harmful QLoRA effect. The single-rater design and prior preparation-side "
            "blinding deviation remain limitations. The Phase 3 bounded comparison is complete, while the confirmatory steering "
            "gate remains No-Go."
        ),
    }
