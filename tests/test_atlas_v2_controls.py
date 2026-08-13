from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from research_foundation.atlas_v2_controls import (
    continuous_feature_direction,
    load_control_plan,
    load_unrelated_train_rows,
)


ROOT = Path(__file__).resolve().parents[1]


class AtlasV2ControlTests(unittest.TestCase):
    def test_control_plan_discloses_timing_and_freezes_conservative_veto(self) -> None:
        plan = load_control_plan(ROOT)
        self.assertIn("after_train_dev_target_metrics", plan["timing_disclosure"])
        self.assertEqual(plan["preliminary_selection"]["layer"], 24)
        self.assertEqual(plan["preliminary_selection"]["pooling"], "last_response_token")
        self.assertEqual(plan["veto_policy"]["control_auroc_margin"], 0.05)
        self.assertEqual(plan["veto_policy"]["maximum_orthogonalized_auroc_drop"], 0.10)

    def test_unrelated_control_uses_only_six_balanced_legacy_train_pairs(self) -> None:
        plan = load_control_plan(ROOT)
        rows = load_unrelated_train_rows(ROOT, plan)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({row.pair_id for row in rows}), 6)
        self.assertEqual(sum(row.pole == "positive" for row in rows), 6)
        self.assertEqual(sum(row.pole == "negative" for row in rows), 6)
        self.assertEqual({row.split for row in rows}, {"control_train"})

    def test_surface_direction_is_normalized_feature_covariance(self) -> None:
        embeddings = np.asarray(
            [[-2.0, 1.0], [-1.0, -1.0], [1.0, -1.0], [2.0, 1.0]]
        )
        direction = continuous_feature_direction(embeddings, [1, 2, 3, 4])
        self.assertAlmostEqual(float(np.linalg.norm(direction)), 1.0)
        self.assertGreater(direction[0], 0.99)
        with self.assertRaisesRegex(ValueError, "zero variance"):
            continuous_feature_direction(embeddings, [1, 1, 1, 1])

    def test_tracked_control_summary_passes_but_keeps_test_closed(self) -> None:
        import json

        summary = json.loads(
            (ROOT / "results/summaries/atlas_v2_control_selection_summary_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(summary["control_gate_status"], "pass")
        self.assertTrue(summary["selection_lock_created"])
        self.assertTrue(all(summary["veto_checks"].values()))
        self.assertFalse(summary["test_opened"])


if __name__ == "__main__":
    unittest.main()
