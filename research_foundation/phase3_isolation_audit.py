from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from research_foundation.phase3_data_contract import FORMAL_REVIEW_PATH, REVIEW_ACCEPTANCE_PATH
from research_foundation.public_pilot import iter_jsonl


OUTPUT_PATH = "results/summaries/phase_3_family_isolation_options_audit_v0_1.json"
FAMILY_FIELDS = (
    "source_family_id",
    "task_family_id",
    "scenario_family_id",
    "prompt_template_id",
    "semantic_cluster_id",
)
OPTIONS = (
    ("frozen_five_field_component", FAMILY_FIELDS, "current_frozen_contract"),
    (
        "scenario_semantic_template_component",
        ("scenario_family_id", "semantic_cluster_id", "prompt_template_id"),
        "diagnostic_only",
    ),
    (
        "scenario_semantic_component",
        ("scenario_family_id", "semantic_cluster_id"),
        "diagnostic_only",
    ),
    ("semantic_component", ("semantic_cluster_id",), "diagnostic_only"),
    ("prompt_template_component", ("prompt_template_id",), "diagnostic_only"),
    ("candidate_identity_upper_bound", (), "structural_upper_bound_not_a_family_contract"),
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _family_values(row: dict[str, Any]) -> dict[str, str]:
    return {
        "source_family_id": row["source_family_id"],
        **row["human_review"]["reviewed_family_assignment"],
    }


def _components(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[int]:
    if not fields:
        return list(range(len(rows)))
    parent = list(range(len(rows)))

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
    for index, row in enumerate(rows):
        values = _family_values(row)
        for field in fields:
            token = (field, values[field])
            if token in owners:
                union(index, owners[token])
            else:
                owners[token] = index
    return [find(index) for index in range(len(rows))]


def _option_audit(rows: list[dict[str, Any]], option: tuple[str, tuple[str, ...], str]) -> dict[str, Any]:
    option_id, fields, role = option
    roots = _components(rows, fields)
    all_components = set(roots)
    evaluation = {
        roots[index]
        for index, row in enumerate(rows)
        if row["human_review"]["pair_evaluation_eligible"]
    }
    qlora = {
        roots[index]
        for index, row in enumerate(rows)
        if any(
            annotation["qlora_training_eligible"]
            for annotation in row["human_review"]["response_annotations"]
        )
    }
    both = evaluation & qlora
    evaluation_only = evaluation - qlora
    qlora_only = qlora - evaluation
    heldout_required = 15 + 40
    qlora_components_consumed_by_heldout = max(0, heldout_required - len(evaluation_only))
    maximum_train_after_heldout = max(0, len(qlora) - qlora_components_consumed_by_heldout)
    sizes = Counter(roots)
    feasible = len(evaluation) >= heldout_required and maximum_train_after_heldout >= 40
    return {
        "option_id": option_id,
        "role": role,
        "ownership_fields": list(fields),
        "component_count": len(all_components),
        "largest_component_rows": max(sizes.values()),
        "evaluation_eligible_components": len(evaluation),
        "qlora_eligible_components": len(qlora),
        "both_role_components": len(both),
        "evaluation_only_components": len(evaluation_only),
        "qlora_only_components": len(qlora_only),
        "maximum_qlora_train_components_after_reserving_15_dev_and_40_test": maximum_train_after_heldout,
        "meets_40_15_40_disjoint_gate": feasible,
    }


def audit_phase_3_family_isolation_options(root: Path) -> dict[str, Any]:
    acceptance = _read_json(root / REVIEW_ACCEPTANCE_PATH)
    rows = [row for _, row in iter_jsonl(root / FORMAL_REVIEW_PATH)]
    if len(rows) != acceptance["formal_review"]["row_count"]:
        raise ValueError("Formal review count does not match tracked acceptance")
    options = [_option_audit(rows, option) for option in OPTIONS]
    upper_bound = next(option for option in options if option["option_id"] == "candidate_identity_upper_bound")
    minimum_additional_qlora_only = max(
        0,
        40 - upper_bound["maximum_qlora_train_components_after_reserving_15_dev_and_40_test"],
    )
    if any(option["meets_40_15_40_disjoint_gate"] for option in options):
        raise ValueError("Unexpected feasible option; audit recommendation must be reviewed")
    return {
        "audit_version": "phase_3_family_isolation_options_audit_v0_1",
        "status": "no_go_current_180_for_40_15_40_disjoint_split",
        "review_acceptance": {
            "path": REVIEW_ACCEPTANCE_PATH,
            "formal_review_sha256": acceptance["formal_review"]["sha256"],
            "row_count": len(rows),
        },
        "frozen_targets": {
            "qlora_train_minimum_families": 40,
            "development_minimum_families": 15,
            "held_out_test_minimum_families": 40,
            "required_disjoint_family_components": 95,
        },
        "observed_role_yield": {
            "evaluation_eligible_pairs": acceptance["counts"]["paired_evaluation_eligible"],
            "qlora_eligible_responses": acceptance["counts"]["qlora_training_eligible_responses"],
            "qlora_eligible_pairs": upper_bound["qlora_eligible_components"],
        },
        "options": options,
        "conclusion": {
            "frozen_contract_component_count": options[0]["component_count"],
            "identity_upper_bound_evaluation_components": upper_bound["evaluation_eligible_components"],
            "identity_upper_bound_qlora_components": upper_bound["qlora_eligible_components"],
            "identity_upper_bound_overlap_components": upper_bound["both_role_components"],
            "maximum_train_after_heldout_reservation": upper_bound[
                "maximum_qlora_train_components_after_reserving_15_dev_and_40_test"
            ],
            "minimum_additional_isolated_qlora_only_components_if_other_yields_hold": minimum_additional_qlora_only,
            "ownership_field_relaxation_alone_sufficient": False,
        },
        "recommendation": {
            "decision": "do_not_freeze_split_from_current_180",
            "preferred_route": (
                "Preserve the confirmed review, define a new granular isolation_family_id from prompt-intent and "
                "exact/normalized/near-duplicate connectivity, retain source/task/scenario/template/semantic fields "
                "as provenance or stratification controls, and review an additional targeted candidate tranche."
            ),
            "minimum_expansion_note": (
                "Even candidate identity gives only 21 QLoRA-train components after reserving 55 evaluation "
                "components; at least 19 additional isolated QLoRA-only eligible components are mathematically "
                "required, and a larger candidate tranche is needed because review yield is below 100%."
            ),
            "requires_user_approval": True,
        },
        "claim_boundary": (
            "This CPU-only structural audit compares allocation feasibility. It does not change confirmed reviews, "
            "revise the frozen isolation contract, create a split, run semantic embeddings, or authorize model work."
        ),
    }


def write_phase_3_family_isolation_options_audit(root: Path) -> dict[str, Any]:
    result = audit_phase_3_family_isolation_options(root)
    path = root / OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
