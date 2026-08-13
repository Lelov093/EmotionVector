from __future__ import annotations

from pathlib import Path
import unittest

from research_foundation.phase3_heldout_analysis import analyze_held_out


ROOT = Path(__file__).resolve().parents[1]


class Phase3HeldOutAnalysisTests(unittest.TestCase):
    def test_complete_frozen_analysis_covers_all_conditions(self) -> None:
        result = analyze_held_out(ROOT)
        self.assertEqual(result["coverage"], {"families": 40, "candidates": 52, "conditions": 15, "annotations": 780})
        self.assertEqual(len(result["condition_comparisons"]), 14)
        self.assertEqual(len(result["control_envelopes"]["random_steering"]["condition_ids"]), 5)
        self.assertEqual(len(result["control_envelopes"]["shuffled_steering"]["condition_ids"]), 5)
        for comparison in result["condition_comparisons"]:
            self.assertEqual(sum(comparison["trait_vs_base"]["candidate_win_tie_loss"].values()), 52)
            self.assertEqual(comparison["family_count"], 40)

    def test_qlora_claim_remains_failed_quality_gate_fallback(self) -> None:
        result = analyze_held_out(ROOT)
        self.assertIn("failed-development-quality-gate fallback", result["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
