from __future__ import annotations

import unittest

from scripts.analyze_blind_review_retest_v2 import exact_agreement, quadratic_weighted_kappa


class BlindReviewRetestMetricsTests(unittest.TestCase):
    def test_exact_agreement(self) -> None:
        self.assertEqual(exact_agreement([(1, 1), (2, 1), (0, 0), (3, 3)]), 0.75)

    def test_quadratic_weighted_kappa_is_one_for_perfect_agreement(self) -> None:
        value = quadratic_weighted_kappa([(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)], [0, 1, 2, 3, 4])
        self.assertAlmostEqual(value or 0.0, 1.0)

    def test_quadratic_weighted_kappa_is_undefined_without_expected_variation(self) -> None:
        self.assertIsNone(quadratic_weighted_kappa([(2, 2), (2, 2)], [0, 1, 2, 3, 4]))


if __name__ == "__main__":
    unittest.main()
