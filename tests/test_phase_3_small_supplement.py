from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest

from research_foundation.phase3_small_supplement import build_small_supplement


ROOT = Path(__file__).resolve().parents[1]


class Phase3SmallSupplementTests(unittest.TestCase):
    def test_contract_preserves_gate_and_bounded_exception(self) -> None:
        contract = json.loads((ROOT / "configs/research/phase_3_small_supplement_contract_v0_4.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["sampling"]["candidate_count"], 12)
        self.assertEqual(contract["unchanged_targets"]["qlora_train_minimum_families"], 40)
        self.assertEqual(contract["unchanged_targets"]["development_minimum_families"], 15)
        self.assertEqual(contract["unchanged_targets"]["held_out_test_minimum_families"], 40)
        self.assertFalse(contract["sampling"]["positive_yield_required"])

    def test_supplement_is_balanced_unique_pending_and_unsplit(self) -> None:
        review, isolation, manifest = build_small_supplement(ROOT)
        self.assertEqual(len(review), 12)
        self.assertEqual(len(isolation), 12)
        self.assertEqual(len({row["candidate_id"] for row in review}), 12)
        self.assertEqual(Counter(row["source_locator"]["model_family"] for row in manifest["records"]), Counter({"Alpaca-7B": 4, "Alpaca2-7B": 4, "Alpaca3-8B": 4}))
        self.assertEqual(Counter(row["sampling_stratum"] for row in manifest["records"]), Counter({"mixed_safety": 9, "both_safe": 3}))
        self.assertTrue(all(row["human_review"]["mapping_decision"] is None for row in review))
        self.assertTrue(all(row["human_review"]["decision"] is None for row in isolation))
        self.assertTrue(all(row["split_status"] == "not_assigned_before_all_reviews" for row in manifest["records"]))

    def test_manifest_contains_no_raw_text(self) -> None:
        manifest = json.loads((ROOT / "data/research_foundation/manifests/phase_3_small_supplement_manifest_v0_1.json").read_text(encoding="utf-8"))
        serialized = json.dumps(manifest)
        self.assertNotIn('"prompt"', serialized)
        self.assertNotIn('"text"', serialized)


if __name__ == "__main__":
    unittest.main()
