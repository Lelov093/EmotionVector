from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Phase3SmallSupplementReviewAcceptanceTests(unittest.TestCase):
    def test_review_counts_and_gate_shortfall_are_frozen(self) -> None:
        result = json.loads((ROOT / "results/summaries/phase_3_small_supplement_review_acceptance_v0_1.json").read_text(encoding="utf-8"))
        self.assertEqual(result["family_counts"]["mapping_decisions"], {"accept": 9, "reject": 3})
        self.assertEqual(result["family_counts"]["paired_evaluation_eligible"], 4)
        self.assertEqual(result["family_counts"]["qlora_training_eligible_responses"], 5)
        self.assertEqual(result["isolation_counts"]["supplemental_confirm"], 7)
        self.assertEqual(result["isolation_counts"]["supplemental_merge"], 5)
        self.assertEqual(result["disjoint_gate_audit"]["maximum_qlora_train_families_after_reserving_15_dev_and_40_test"], 39)
        self.assertEqual(result["disjoint_gate_audit"]["qlora_train_shortfall"], 1)
        self.assertFalse(result["disjoint_gate_audit"]["meets_40_15_40"])
        self.assertFalse(result["decision"]["split_created"])

    def test_final_282_manifest_is_closed_canonical_and_unsplit(self) -> None:
        manifest = json.loads((ROOT / "data/research_foundation/manifests/phase_3_final_isolation_families_v0_3.json").read_text(encoding="utf-8"))
        records = manifest["records"]
        by_family = Counter(row["final_isolation_family_id"] for row in records)
        self.assertEqual(len(records), 282)
        self.assertEqual(len(by_family), 205)
        self.assertEqual(Counter(by_family.values()), Counter({1: 162, 2: 29, 3: 6, 4: 2, 5: 3, 7: 3}))
        self.assertTrue(all(row["component_size"] == by_family[row["final_isolation_family_id"]] for row in records))
        self.assertTrue(all(row["split_status"] == "not_assigned_40_15_40_blocked_shortfall_1" for row in records))
        self.assertEqual(manifest["counts"]["supplemental_ids_canonicalized_to_frozen_family_id"], 0)


if __name__ == "__main__":
    unittest.main()
