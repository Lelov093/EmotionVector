from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import jsonschema

from research_foundation.audit import jaccard, normalize_text, word_ngrams
from research_foundation.phase3_additional_review import FAMILY_FORMAL as ADDITIONAL_FORMAL
from research_foundation.phase3_data_contract import (
    FORMAL_REVIEW_PATH, _contains_raw_text_key, _file_sha256, _phase_2_exclusions,
)
from research_foundation.phase3_expansion_review import EXPANSION_FORMAL_PATH
from research_foundation.phase3_small_supplement_review import FAMILY_FORMAL as SUPPLEMENTAL_FORMAL
from research_foundation.public_pilot import iter_jsonl, stable_digest, write_jsonl
from research_foundation.representation_freeze import canonical_content_sha256


CONTRACT_PATH = "configs/research/phase_3_family_split_contract_v0_1.json"
CONTRACT_SCHEMA = "data/research_foundation/schemas/phase_3_family_split_contract_v0_1.schema.json"
SPLIT_SCHEMA = "data/research_foundation/schemas/phase_3_family_split_v0_1.schema.json"
FREEZE_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_test_freeze_v0_1.schema.json"
TEST_ONCE_SCHEMA = "data/research_foundation/schemas/phase_3_test_once_contract_v0_1.schema.json"
ORIGINAL_DATA_CONTRACT = "configs/research/phase_3_family_data_contract_v0_1.json"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [row for _, row in iter_jsonl(path)]


def _list_sha256(values: list[str]) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def _locator_key(locator: dict[str, Any]) -> str:
    return json.dumps(locator, sort_keys=True, separators=(",", ":"))


def build_phase_3_split_freeze(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = _json(root / CONTRACT_PATH)
    jsonschema.validate(contract, _json(root / CONTRACT_SCHEMA))
    for path_key, hash_key in (
        ("data_gate_amendment_path", "data_gate_amendment_sha256"),
        ("data_gate_acceptance_path", "data_gate_acceptance_sha256"),
        ("final_isolation_manifest_path", "final_isolation_manifest_sha256"),
    ):
        path = root / contract["bound_evidence"][path_key]
        if canonical_content_sha256(_json(path)) != contract["bound_evidence"][hash_key]:
            raise ValueError(f"Frozen split evidence hash mismatch: {path_key}")

    final_isolation = _json(root / contract["bound_evidence"]["final_isolation_manifest_path"])
    isolation_by_candidate = {row["candidate_id"]: row for row in final_isolation["records"]}
    review_paths = (FORMAL_REVIEW_PATH, EXPANSION_FORMAL_PATH, ADDITIONAL_FORMAL, SUPPLEMENTAL_FORMAL)
    reviews = [row for path in review_paths for row in _rows(root / path)]
    review_by_id = {row["candidate_id"]: row for row in reviews}
    if len(reviews) != 282 or len(review_by_id) != 282 or set(review_by_id) != set(isolation_by_candidate):
        raise ValueError("The formal review and final isolation populations must match at 282 candidates")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate_id, review in review_by_id.items():
        by_family[isolation_by_candidate[candidate_id]["final_isolation_family_id"]].append(review)
    if len(by_family) != 205:
        raise ValueError("Final split population must contain 205 isolation families")

    evaluation_families = {
        family_id for family_id, rows in by_family.items()
        if any(row["human_review"]["pair_evaluation_eligible"] for row in rows)
    }
    qlora_families = {
        family_id for family_id, rows in by_family.items()
        if any(annotation["qlora_training_eligible"] for row in rows for annotation in row["human_review"]["response_annotations"])
    }
    evaluation_only = evaluation_families - qlora_families
    dual_role = evaluation_families & qlora_families
    qlora_only = qlora_families - evaluation_families
    if (len(evaluation_families), len(qlora_families), len(evaluation_only), len(dual_role), len(qlora_only)) != (80, 92, 2, 78, 14):
        raise ValueError("Frozen eligibility-family counts changed")

    seed = contract["seed"]
    reserved_evaluation = set(evaluation_only)
    reserved_evaluation.update(sorted(dual_role, key=lambda family_id: stable_digest(seed, "reserve_eval", family_id))[:53])
    train_families = qlora_families - reserved_evaluation
    ranked_evaluation = sorted(reserved_evaluation, key=lambda family_id: stable_digest(seed, "eval_split", family_id))
    test_families = set(ranked_evaluation[:40])
    development_families = set(ranked_evaluation[40:])
    assigned = train_families | development_families | test_families
    if (len(train_families), len(development_families), len(test_families), len(assigned)) != (39, 15, 40, 94):
        raise ValueError("Deterministic allocation did not produce 39/15/40 disjoint families")

    split_by_family = {
        family_id: (
            "train" if family_id in train_families else
            "development" if family_id in development_families else
            "held_out_test" if family_id in test_families else
            "not_selected_ineligible"
        )
        for family_id in by_family
    }
    train_rows: list[dict[str, Any]] = []
    development_rows: list[dict[str, Any]] = []
    test_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for family_id in sorted(by_family):
        family_reviews = sorted(by_family[family_id], key=lambda row: row["candidate_id"])
        split = split_by_family[family_id]
        evaluation_candidate_ids = sorted(
            row["candidate_id"] for row in family_reviews if row["human_review"]["pair_evaluation_eligible"]
        )
        qlora_response_ids = sorted(
            f"{row['candidate_id']}:{annotation['response_id']}"
            for row in family_reviews
            for annotation in row["human_review"]["response_annotations"]
            if annotation["qlora_training_eligible"]
        )
        records.append({
            "final_isolation_family_id": family_id,
            "candidate_ids": [row["candidate_id"] for row in family_reviews],
            "component_size": len(family_reviews),
            "evaluation_eligible_candidate_ids": evaluation_candidate_ids,
            "qlora_eligible_response_ids": qlora_response_ids,
            "source_model_families": sorted({row["source_locator"]["model_family"] for row in family_reviews}),
            "cohorts": sorted({isolation_by_candidate[row["candidate_id"]]["cohort"] for row in family_reviews}),
            "split": split,
        })
        if split == "train":
            if not qlora_response_ids:
                raise ValueError(f"Train family has no eligible response: {family_id}")
            for row in family_reviews:
                annotation_by_id = {item["response_id"]: item for item in row["human_review"]["response_annotations"]}
                for response in row["responses"]:
                    annotation = annotation_by_id[response["response_id"]]
                    if annotation["qlora_training_eligible"]:
                        train_rows.append({
                            "record_id": f"{row['candidate_id']}:{response['response_id']}",
                            "final_isolation_family_id": family_id,
                            "candidate_id": row["candidate_id"],
                            "source_family_id": row["source_family_id"],
                            "source_locator": row["source_locator"],
                            "prompt": row["prompt"],
                            "prompt_sha256": isolation_by_candidate[row["candidate_id"]]["prompt_sha256"],
                            "response_id": response["response_id"],
                            "response": response["text"],
                            "response_sha256": response["content_sha256"],
                            "behavior": annotation["behavior"],
                            "pole": annotation["pole"],
                            "reviewer_id": row["human_review"]["reviewer_id"],
                            "reviewed_at": row["human_review"]["reviewed_at"],
                        })
        elif split in {"development", "held_out_test"}:
            target = development_rows if split == "development" else test_rows
            if not evaluation_candidate_ids:
                raise ValueError(f"Evaluation family has no eligible pair: {family_id}")
            for row in family_reviews:
                if row["human_review"]["pair_evaluation_eligible"]:
                    if row["human_review"]["pair_contrast"] != "valid_single_axis":
                        raise ValueError("Non-valid pair entered evaluation materialization")
                    target.append({
                        "candidate_id": row["candidate_id"],
                        "final_isolation_family_id": family_id,
                        "source_family_id": row["source_family_id"],
                        "source_locator": row["source_locator"],
                        "prompt": row["prompt"],
                        "prompt_sha256": isolation_by_candidate[row["candidate_id"]]["prompt_sha256"],
                        "responses": row["responses"],
                        "response_annotations": row["human_review"]["response_annotations"],
                        "pair_contrast": row["human_review"]["pair_contrast"],
                        "reviewed_family_assignment": row["human_review"]["reviewed_family_assignment"],
                        "reviewer_id": row["human_review"]["reviewer_id"],
                        "reviewed_at": row["human_review"]["reviewed_at"],
                    })

    outputs = contract["outputs"]
    local_paths = {
        "train": root / outputs["local_train_rows"],
        "development": root / outputs["local_development_pairs"],
        "held_out_test": root / outputs["local_held_out_test_pairs"],
    }
    write_jsonl(local_paths["train"], sorted(train_rows, key=lambda row: row["record_id"]))
    write_jsonl(local_paths["development"], sorted(development_rows, key=lambda row: row["candidate_id"]))
    write_jsonl(local_paths["held_out_test"], sorted(test_rows, key=lambda row: row["candidate_id"]))
    local_artifacts = {
        name: {"path": str(path.relative_to(root)).replace("\\", "/"), "tracked": False, "sha256": _file_sha256(path), "row_count": len(rows)}
        for (name, path), rows in zip(local_paths.items(), (train_rows, development_rows, test_rows))
    }

    split_manifest = {
        "manifest_version": "phase_3_family_split_v0_1",
        "status": "family_isolated_39_15_40_split_frozen",
        "contract": {"path": CONTRACT_PATH, "sha256": canonical_content_sha256(contract)},
        "counts": {
            "total_isolation_families": 205,
            "assigned_families": 94,
            "train_families": 39,
            "development_families": 15,
            "held_out_test_families": 40,
            "not_selected_ineligible_families": 111,
            "train_response_rows": len(train_rows),
            "development_pair_rows": len(development_rows),
            "held_out_test_pair_rows": len(test_rows),
        },
        "local_artifacts": local_artifacts,
        "records": records,
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "all_205_isolation_families_covered", "assigned_family_counts_39_15_40", "split_family_sets_disjoint",
            "train_family_qlora_eligibility", "development_family_pair_eligibility", "test_family_pair_eligibility",
            "same_axis_not_opposite_excluded_from_eval", "one_split_per_isolation_family", "raw_text_absent_from_tracked_manifest",
            "local_artifact_hashes_recorded", "allocation_deterministic_and_label_content_blind")],
        "claim_boundary": "This tracked manifest freezes family ownership and local raw artifact hashes under the amended 39/15/40 standard. It is data infrastructure, not model or causal steering evidence.",
    }
    if _contains_raw_text_key(split_manifest):
        raise ValueError("Tracked Phase 3 split manifest contains raw text")
    jsonschema.validate(split_manifest, _json(root / SPLIT_SCHEMA))

    split_path = root / outputs["tracked_split_manifest"]
    split_path.parent.mkdir(parents=True, exist_ok=True)
    split_path.write_text(json.dumps(split_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    split_hash = canonical_content_sha256(split_manifest)
    test_family_ids = sorted(test_families)
    test_candidate_ids = sorted(row["candidate_id"] for row in test_rows)
    access_log = root / outputs["local_test_access_log"]
    if access_log.exists():
        raise ValueError("Phase 3 model test-access log already exists before freeze construction")
    test_freeze = {
        "freeze_version": "phase_3_held_out_test_freeze_v0_1",
        "status": "held_out_test_frozen_unopened_for_model_execution",
        "split_manifest": {"path": outputs["tracked_split_manifest"], "sha256": split_hash},
        "test_family_ids": test_family_ids,
        "test_family_ids_sha256": _list_sha256(test_family_ids),
        "test_candidate_ids": test_candidate_ids,
        "test_candidate_ids_sha256": _list_sha256(test_candidate_ids),
        "local_test_artifact": local_artifacts["held_out_test"],
        "access_state": {"model_execution_openings": 0, "access_log_path": outputs["local_test_access_log"], "access_log_exists": False},
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "test_family_count_40", "test_family_ids_unique", "test_candidate_ids_frozen", "local_test_hash_frozen",
            "model_test_opening_zero", "phase_2_test_reuse_zero")],
        "claim_boundary": "The held-out prompt/pair identities and local artifact are frozen. Human source mapping review preceded this freeze, but no Phase 3 condition output or model test execution has occurred.",
    }
    jsonschema.validate(test_freeze, _json(root / FREEZE_SCHEMA))
    freeze_path = root / outputs["tracked_test_freeze"]
    freeze_path.write_text(json.dumps(test_freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    test_once = {
        "contract_version": "phase_3_test_once_contract_v0_1",
        "status": "frozen_before_model_or_test_execution",
        "split_manifest": {"path": outputs["tracked_split_manifest"], "sha256": split_hash},
        "test_freeze": {"path": outputs["tracked_test_freeze"], "sha256": canonical_content_sha256(test_freeze)},
        "access_policy": {
            "single_model_test_opening": True,
            "exclusive_create_access_log": True,
            "access_log_path": outputs["local_test_access_log"],
            "opening_requires_frozen_train_dev_selection_lock": True,
            "opening_requires_model_gpu_execution_notice": True,
            "condition_outputs_must_be_complete_before_unblinding": True,
        },
        "forbidden_uses": [
            "alpha_selection", "qlora_checkpoint_selection", "prompt_revision", "method_ranking_before_final_evaluation",
            "test_retuning", "selective_condition_omission", "phase_2_opened_test_reuse",
        ],
        "required_preconditions": [
            "family_split_leakage_audit_passed", "blind_review_contract_frozen", "all_method_conditions_frozen",
            "train_dev_selection_lock_frozen", "user_notified_before_model_or_gpu_execution",
        ],
        "claim_boundary": "This contract guards a future single model-test opening. Creating it does not open the test, authorize model/GPU use, or supply confirmatory causal evidence.",
    }
    jsonschema.validate(test_once, _json(root / TEST_ONCE_SCHEMA))
    (root / outputs["tracked_test_once_contract"]).write_text(json.dumps(test_once, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assigned_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for family_id in assigned:
        assigned_candidates[split_by_family[family_id]].extend(by_family[family_id])
    split_names = ("train", "development", "held_out_test")
    pair_names = (("train", "development"), ("train", "held_out_test"), ("development", "held_out_test"))
    family_overlap = {f"{left}_vs_{right}": len(
        {isolation_by_candidate[row["candidate_id"]]["final_isolation_family_id"] for row in assigned_candidates[left]}
        & {isolation_by_candidate[row["candidate_id"]]["final_isolation_family_id"] for row in assigned_candidates[right]}
    ) for left, right in pair_names}
    candidate_overlap = {f"{left}_vs_{right}": len(
        {row["candidate_id"] for row in assigned_candidates[left]} & {row["candidate_id"] for row in assigned_candidates[right]}
    ) for left, right in pair_names}
    hashes_by_split: dict[str, set[str]] = {}
    locators_by_split: dict[str, set[str]] = {}
    normalized_by_split: dict[str, set[str]] = {}
    shingles_by_split: dict[str, list[tuple[str, set[tuple[str, ...]]]]] = {}
    for split_name in split_names:
        rows = assigned_candidates[split_name]
        hashes_by_split[split_name] = {
            value for row in rows for value in [row["content_sha256"], isolation_by_candidate[row["candidate_id"]]["prompt_sha256"], *[response["content_sha256"] for response in row["responses"]]]
        }
        locators_by_split[split_name] = {_locator_key(row["source_locator"]) for row in rows}
        normalized_by_split[split_name] = {normalize_text(row["prompt"]) for row in rows}
        shingles_by_split[split_name] = [(row["candidate_id"], word_ngrams(row["prompt"])) for row in rows]
    hash_overlap = {f"{left}_vs_{right}": len(hashes_by_split[left] & hashes_by_split[right]) for left, right in pair_names}
    locator_overlap = {f"{left}_vs_{right}": len(locators_by_split[left] & locators_by_split[right]) for left, right in pair_names}
    normalized_overlap = {f"{left}_vs_{right}": len(normalized_by_split[left] & normalized_by_split[right]) for left, right in pair_names}
    maximum_jaccard = 0.0
    maximum_jaccard_pair: list[str] = []
    for left, right in pair_names:
        for left_id, left_ngrams in shingles_by_split[left]:
            for right_id, right_ngrams in shingles_by_split[right]:
                score = jaccard(left_ngrams, right_ngrams)
                if score > maximum_jaccard:
                    maximum_jaccard = score
                    maximum_jaccard_pair = [left, left_id, right, right_id]
    phase_2_hashes, phase_2_locators = _phase_2_exclusions(root, _json(root / ORIGINAL_DATA_CONTRACT))
    selected_hashes = set().union(*(hashes_by_split[name] for name in split_names))
    selected_locators = set().union(*(locators_by_split[name] for name in split_names))
    family_fields = ("task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id")
    broad_family_overlap = {}
    for field in family_fields:
        values = {
            split_name: {row["human_review"]["reviewed_family_assignment"][field] for row in assigned_candidates[split_name]}
            for split_name in split_names
        }
        broad_family_overlap[field] = {
            f"{left}_vs_{right}": len(values[left] & values[right]) for left, right in pair_names
        }
    blocking_counts = {
        "family_id_cross_split_overlap": sum(family_overlap.values()),
        "candidate_id_cross_split_overlap": sum(candidate_overlap.values()),
        "content_prompt_response_hash_cross_split_overlap": sum(hash_overlap.values()),
        "source_locator_cross_split_overlap": sum(locator_overlap.values()),
        "normalized_prompt_cross_split_overlap": sum(normalized_overlap.values()),
        "phase_2_content_hash_overlap": len(selected_hashes & phase_2_hashes),
        "phase_2_source_locator_overlap": len(selected_locators & phase_2_locators),
        "prompt_token_3gram_jaccard_at_or_above_0_90": int(maximum_jaccard >= contract["leakage_policy"]["cross_split_prompt_token_3gram_jaccard_threshold"]),
    }
    if any(blocking_counts.values()):
        raise ValueError(f"Phase 3 split leakage blockers detected: {blocking_counts}")
    audit = {
        "summary_version": "phase_3_family_split_leakage_audit_v0_1",
        "status": "passed_family_isolated_39_15_40_split_no_model_execution",
        "split_manifest": {"path": outputs["tracked_split_manifest"], "sha256": split_hash},
        "test_freeze": {"path": outputs["tracked_test_freeze"], "sha256": canonical_content_sha256(test_freeze)},
        "test_once_contract": {"path": outputs["tracked_test_once_contract"], "sha256": canonical_content_sha256(test_once)},
        "counts": split_manifest["counts"],
        "blocking_leakage_counts": blocking_counts,
        "maximum_cross_split_prompt_token_3gram_jaccard": maximum_jaccard,
        "maximum_cross_split_prompt_token_3gram_jaccard_pair": maximum_jaccard_pair,
        "semantic_isolation_evidence": {
            "final_manifest_path": contract["bound_evidence"]["final_isolation_manifest_path"],
            "human_reviewed_transitive_components": 205,
            "status": "pass",
        },
        "broad_family_stratifier_overlap_nonblocking": broad_family_overlap,
        "checks": [{"check_id": check, "status": "pass"} for check in (
            "strict_isolation_family_overlap_zero", "candidate_and_source_overlap_zero", "content_hash_overlap_zero",
            "normalized_prompt_overlap_zero", "token_3gram_threshold_pass", "phase_2_overlap_zero",
            "human_semantic_closure_bound", "test_family_count_40", "test_access_openings_zero")],
        "claim_boundary": "Leakage checks pass under final_isolation_family_id ownership. Broad reviewed task/scenario/template/semantic fields intentionally remain overlapping stratifiers under contract v0.2 and are reported rather than misrepresented as independent ownership units. No model or test execution occurred.",
    }
    (root / outputs["tracked_leakage_audit"]).write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return split_manifest, test_freeze, test_once, audit


def write_phase_3_split_freeze(root: Path) -> dict[str, Any]:
    split, freeze, test_once, audit = build_phase_3_split_freeze(root)
    return {
        "status": audit["status"],
        "split_counts": split["counts"],
        "test_access_state": freeze["access_state"],
        "test_once_status": test_once["status"],
        "model_or_gpu_run": False,
    }
