from __future__ import annotations

from pathlib import Path
import unittest

from research_foundation.phase3_readiness import audit_phase_3_readiness, read_json


ROOT = Path(__file__).resolve().parents[1]


class Phase3ReadinessTests(unittest.TestCase):
    def test_protocol_freezes_limited_single_axis_comparison(self) -> None:
        protocol = read_json(ROOT / "configs/research/phase_3_limited_fair_comparison_protocol_v0_1.json")
        self.assertEqual(protocol["research_scope"]["axis_ids"], ["boundary-preserving-over-accommodating"])
        self.assertEqual(protocol["evidence_basis"]["confirmatory_steering_gate"], "no_go")
        self.assertEqual(protocol["research_scope"]["study_role"], "limited_nonconfirmatory_fair_method_comparison")
        self.assertIn("qlora", protocol["conditions"])
        self.assertIn("random_steering", protocol["conditions"])
        self.assertTrue(protocol["acceptance"]["positive_result_required"] is False)

    def test_current_readiness_rejects_legacy_assets_and_model_execution(self) -> None:
        audit = audit_phase_3_readiness(ROOT)
        self.assertEqual(audit["execution_status"], "phase_3_limited_nonconfirmatory_comparison_complete")
        self.assertTrue(audit["model_or_gpu_run"])
        self.assertTrue(audit["gates"]["new_qlora_training_data_ready"])
        self.assertTrue(audit["gates"]["human_review_ready"])
        self.assertTrue(audit["gates"]["family_isolated_data_count_gate_passed_under_amended_39_15_40"])
        self.assertTrue(audit["gates"]["family_leakage_audit_passed"])
        self.assertTrue(audit["gates"]["new_development_ready"])
        self.assertTrue(audit["gates"]["new_held_out_test_ready"])
        self.assertTrue(audit["gates"]["blind_review_contract_ready"])
        self.assertTrue(audit["gates"]["train_dev_selection_contract_ready"])
        self.assertTrue(audit["gates"]["train_dev_runtime_ready"])
        self.assertTrue(audit["gates"]["model_gpu_notice_completed"])
        self.assertTrue(audit["gates"]["qlora_training_complete"])
        self.assertTrue(audit["gates"]["development_candidate_generation_complete"])
        self.assertTrue(audit["gates"]["development_human_review_complete"])
        self.assertTrue(audit["gates"]["train_dev_selection_lock_frozen"])
        self.assertTrue(audit["gates"]["held_out_runtime_frozen"])
        self.assertTrue(audit["gates"]["held_out_model_gpu_notice_issued"])
        self.assertTrue(audit["gates"]["held_out_condition_generation_complete"])
        self.assertTrue(audit["gates"]["independent_review_amendment_frozen"])
        self.assertTrue(audit["gates"]["researcher_02_review_materials_ready"])
        self.assertTrue(audit["gates"]["held_out_human_review_frozen"])
        self.assertTrue(audit["gates"]["held_out_nonconfirmatory_analysis_complete"])
        review = audit["current_candidate_assets"]["phase_3_researcher_02_review"]
        self.assertEqual(review["reviewer_id"], "researcher_02")
        self.assertEqual(review["required_ratings"], 780)
        self.assertEqual(review["ratings_completed"], 780)
        self.assertFalse(review["reviewer_signature_recorded"])
        self.assertFalse(review["condition_key_access_at_freeze"])
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_candidates"]["count"], 180)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_candidates"]["completed_human_reviews"], 180)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_candidates"]["split_assignments"], 0)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_candidates"]["family_component_count"], 1)
        self.assertFalse(audit["current_candidate_assets"]["phase_3_family_candidates"]["family_allocation_ready"])
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_family_candidates"]["isolation_options_status"],
            "no_go_current_180_for_40_15_40_disjoint_split",
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_family_candidates"][
                "identity_upper_bound_train_after_heldout"
            ],
            21,
        )
        self.assertEqual(audit["current_candidate_assets"]["phase_3_expansion_candidates"]["count"], 60)
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_expansion_candidates"]["completed_human_reviews"],
            60,
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_provisional_isolation"]["candidate_count"],
            240,
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_provisional_isolation"]["completed_semantic_merge_reviews"],
            0,
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_final_isolation"]["final_family_count"],
            189,
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_final_isolation"]["merged_component_count"],
            31,
        )
        self.assertFalse(
            audit["current_candidate_assets"]["phase_3_final_isolation"]["disjoint_40_15_40_ready"]
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_final_isolation"]["qlora_train_shortfall"],
            11,
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_additional_tranche"]["candidate_count"],
            30,
        )
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_additional_tranche"]["completed_human_reviews"],
            30,
        )
        self.assertEqual(audit["current_candidate_assets"]["phase_3_final_isolation_v2"]["candidate_count"], 270)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_final_isolation_v2"]["final_family_count"], 198)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_final_isolation_v2"]["qlora_train_shortfall"], 3)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_small_supplement"]["candidate_count"], 12)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_small_supplement"]["completed_human_reviews"], 12)
        self.assertEqual(
            audit["current_candidate_assets"]["phase_3_additional_tranche"]["completed_isolation_reviews"],
            30,
        )
        self.assertEqual(audit["current_candidate_assets"]["phase_3_small_supplement"]["completed_isolation_reviews"], 12)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_final_isolation_v3"]["candidate_count"], 282)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_final_isolation_v3"]["final_family_count"], 205)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_final_isolation_v3"]["qlora_train_shortfall"], 1)
        self.assertFalse(audit["current_candidate_assets"]["phase_3_data_gate_amendment"]["original_40_15_40_passed"])
        self.assertTrue(audit["current_candidate_assets"]["phase_3_data_gate_amendment"]["amended_39_15_40_passed"])
        self.assertFalse(audit["current_candidate_assets"]["phase_3_data_gate_amendment"]["additional_candidate_expansion_allowed"])
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_split"]["train_families"], 39)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_split"]["development_families"], 15)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_family_split"]["held_out_test_families"], 40)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_test_once"]["model_execution_openings"], 0)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_held_out_runtime"]["condition_count"], 15)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_held_out_runtime"]["expected_output_count"], 780)
        self.assertFalse(audit["current_candidate_assets"]["phase_3_held_out_runtime"]["selected_qlora_quality_gate_passed"])
        self.assertEqual(audit["current_candidate_assets"]["phase_3_held_out_runtime"]["test_openings"], 1)
        self.assertEqual(audit["current_candidate_assets"]["phase_3_held_out_runtime"]["condition_outputs"], 780)
        self.assertEqual(audit["current_candidate_assets"]["cleaned_sft_candidates"]["count"], 2)
        self.assertEqual(audit["current_candidate_assets"]["review_ready_items"]["completed_human_reviews"], 0)
        self.assertEqual(
            audit["legacy_assets"]["legacy_steering_config"]["unsupported_axes"],
            ["calm-agitated", "cautious-impulsive"],
        )
        v2 = next(item for item in audit["legacy_assets"]["forbidden_sft"] if "v0_2" in item["path"])
        self.assertEqual(v2["template_phrase_hits"]["the_request_asks_me_to"], 84)
        self.assertEqual(v2["template_phrase_hits"]["if_you_want_i_can_help"], 84)


if __name__ == "__main__":
    unittest.main()
