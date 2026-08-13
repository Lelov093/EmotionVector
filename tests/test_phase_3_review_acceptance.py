from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Phase3ReviewAcceptanceTests(unittest.TestCase):
    def test_tracked_acceptance_preserves_review_and_claim_boundaries(self) -> None:
        summary = json.loads(
            (ROOT / "results/summaries/phase_3_family_review_acceptance_v0_1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["status"], "human_review_complete_pending_family_split_freeze")
        self.assertEqual(summary["reviewer_id"], "researcher_01")
        self.assertEqual(summary["formal_review"]["row_count"], 180)
        self.assertFalse(summary["formal_review"]["tracked"])
        self.assertEqual(summary["counts"]["paired_evaluation_eligible"], 64)
        self.assertEqual(summary["counts"]["qlora_training_eligible_responses"], 85)
        mandatory = [
            check for check in summary["checks"]
            if check["check_id"] != "family_connected_component_allocation_readiness"
        ]
        self.assertTrue(all(check["status"] == "pass" for check in mandatory))
        self.assertEqual(summary["family_component_audit"]["component_count"], 1)
        self.assertFalse(summary["family_component_audit"]["allocation_ready"])
        self.assertIn("does not create a split", summary["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
