from __future__ import annotations

import unittest

from scripts.calibrate_automatic_evaluators_v2 import (
    binary_metrics,
    ordinal_metrics,
    pairwise_metrics,
    preference,
    spearman,
)


class AutomaticEvaluatorCalibrationV2Tests(unittest.TestCase):
    def test_spearman_handles_ties(self) -> None:
        self.assertAlmostEqual(spearman([1, 1, 2, 3], [1, 1, 2, 3]) or 0.0, 1.0)

    def test_ordinal_metrics_perfect_alignment(self) -> None:
        result = ordinal_metrics([0, 1, 2, 3, 4], [0, 1, 2, 3, 4], [0, 1, 2, 3, 4])
        self.assertEqual(result["exact_agreement"], 1.0)
        self.assertEqual(result["mean_absolute_error"], 0.0)
        self.assertEqual(result["quadratic_weighted_kappa"], 1.0)

    def test_binary_balanced_accuracy(self) -> None:
        result = binary_metrics([True, False, True, False], [True, False, False, True])
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["balanced_accuracy"], 0.5)

    def test_pairwise_excludes_human_ties_from_agreement(self) -> None:
        result = pairwise_metrics(["A", "B", "A"], ["A", "tie", "B"])
        self.assertEqual(result["human_non_tie_n"], 2)
        self.assertEqual(result["agreement_on_human_non_ties"], 0.5)
        self.assertEqual(preference(3, 3), "tie")


if __name__ == "__main__":
    unittest.main()
