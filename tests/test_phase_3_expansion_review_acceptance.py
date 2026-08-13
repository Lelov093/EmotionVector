from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Phase3ExpansionReviewAcceptanceTests(unittest.TestCase):
    def test_acceptance_counts_and_disjoint_gate_are_frozen(self) -> None:
        summary = json.loads(
            (ROOT / "results/summaries/phase_3_expansion_and_isolation_review_acceptance_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(summary["expansion_counts"]["mapping_decisions"], {"accept": 43, "ambiguous": 1, "reject": 16})
        self.assertEqual(summary["isolation_counts"]["confirm"], 158)
        self.assertEqual(summary["isolation_counts"]["merge"], 82)
        self.assertEqual(summary["isolation_counts"]["merged_components"], 31)
        self.assertEqual(summary["isolation_counts"]["final_isolation_families"], 189)
        self.assertFalse(summary["disjoint_gate_audit"]["meets_40_15_40"])
        self.assertEqual(summary["disjoint_gate_audit"]["maximum_qlora_train_families_after_reserving_15_dev_and_40_test"], 29)
        self.assertEqual(summary["disjoint_gate_audit"]["qlora_train_shortfall"], 11)

    def test_final_manifest_has_uniform_transitively_closed_families(self) -> None:
        manifest = json.loads(
            (ROOT / "data/research_foundation/manifests/phase_3_final_isolation_families_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        records = manifest["records"]
        self.assertEqual(len(records), 240)
        by_family = Counter(record["final_isolation_family_id"] for record in records)
        self.assertEqual(len(by_family), 189)
        self.assertEqual(sum(size > 1 for size in by_family.values()), 31)
        self.assertTrue(all(record["component_size"] == by_family[record["final_isolation_family_id"]] for record in records))
        self.assertEqual(Counter(by_family.values()), Counter({1: 158, 2: 21, 3: 6, 5: 2, 6: 2}))
        self.assertTrue(all(record["split_status"] == "not_assigned_pending_40_15_40_feasibility" for record in records))


if __name__ == "__main__":
    unittest.main()
