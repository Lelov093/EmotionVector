from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Phase3AdditionalReviewAcceptanceTests(unittest.TestCase):
    def test_confirmed_counts_and_shortfall_are_frozen(self) -> None:
        summary = json.loads((ROOT / "results/summaries/phase_3_additional_tranche_review_acceptance_v0_1.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["family_counts"]["mapping_decisions"], {"accept": 21, "ambiguous": 2, "reject": 7})
        self.assertEqual(summary["family_counts"]["paired_evaluation_eligible"], 9)
        self.assertEqual(summary["isolation_counts"]["additional_confirm"], 8)
        self.assertEqual(summary["isolation_counts"]["additional_merge"], 22)
        self.assertEqual(summary["isolation_counts"]["final_isolation_families"], 198)
        self.assertEqual(summary["disjoint_gate_audit"]["maximum_qlora_train_families_after_reserving_15_dev_and_40_test"], 37)
        self.assertEqual(summary["disjoint_gate_audit"]["qlora_train_shortfall"], 3)
        self.assertFalse(summary["disjoint_gate_audit"]["meets_40_15_40"])

    def test_v0_2_manifest_is_transitively_closed_and_unsplit(self) -> None:
        manifest = json.loads((ROOT / "data/research_foundation/manifests/phase_3_final_isolation_families_v0_2.json").read_text(encoding="utf-8"))
        records = manifest["records"]
        by_family = Counter(row["final_isolation_family_id"] for row in records)
        self.assertEqual(len(records), 270)
        self.assertEqual(len(by_family), 198)
        self.assertEqual(Counter(by_family.values()), Counter({1: 157, 2: 28, 3: 5, 4: 3, 5: 2, 6: 1, 7: 2}))
        self.assertTrue(all(row["component_size"] == by_family[row["final_isolation_family_id"]] for row in records))
        self.assertTrue(all(row["split_status"] == "not_assigned_pending_authorized_small_supplement" for row in records))


if __name__ == "__main__":
    unittest.main()
