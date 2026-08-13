from __future__ import annotations

import json
from pathlib import Path
import unittest

from research_foundation.phase3_isolation_audit import audit_phase_3_family_isolation_options


ROOT = Path(__file__).resolve().parents[1]


class Phase3IsolationAuditTests(unittest.TestCase):
    def test_no_current_option_can_meet_disjoint_40_15_40_gate(self) -> None:
        result = audit_phase_3_family_isolation_options(ROOT)
        self.assertEqual(result["status"], "no_go_current_180_for_40_15_40_disjoint_split")
        self.assertFalse(any(option["meets_40_15_40_disjoint_gate"] for option in result["options"]))
        self.assertFalse(result["conclusion"]["ownership_field_relaxation_alone_sufficient"])

    def test_candidate_identity_is_only_an_upper_bound_and_still_fails(self) -> None:
        result = audit_phase_3_family_isolation_options(ROOT)
        upper = next(option for option in result["options"] if option["option_id"] == "candidate_identity_upper_bound")
        self.assertEqual(upper["role"], "structural_upper_bound_not_a_family_contract")
        self.assertEqual(upper["component_count"], 180)
        self.assertEqual(upper["evaluation_eligible_components"], 64)
        self.assertEqual(upper["qlora_eligible_components"], 74)
        self.assertEqual(upper["both_role_components"], 62)
        self.assertEqual(upper["maximum_qlora_train_components_after_reserving_15_dev_and_40_test"], 21)
        self.assertEqual(result["conclusion"]["minimum_additional_isolated_qlora_only_components_if_other_yields_hold"], 19)

    def test_tracked_audit_preserves_no_execution_boundary(self) -> None:
        tracked = json.loads(
            (ROOT / "results/summaries/phase_3_family_isolation_options_audit_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(tracked["recommendation"]["decision"], "do_not_freeze_split_from_current_180")
        self.assertTrue(tracked["recommendation"]["requires_user_approval"])
        self.assertIn("does not change confirmed reviews", tracked["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
