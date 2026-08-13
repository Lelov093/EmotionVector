from __future__ import annotations

import json
from pathlib import Path
import unittest

import jsonschema

from research_foundation.phase3_additional_tranche import (
    CONTRACT_PATH,
    CONTRACT_SCHEMA_PATH,
    MANIFEST_SCHEMA_PATH,
    build_phase_3_additional_tranche,
)


ROOT = Path(__file__).resolve().parents[1]


class Phase3AdditionalTrancheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "data/external/pku_safe_rlhf").exists():
            raise unittest.SkipTest("Git-ignored PKU snapshot is not present")
        cls.review_rows, cls.isolation_rows, cls.manifest = build_phase_3_additional_tranche(ROOT)

    def test_contract_is_bounded_and_keeps_targets(self) -> None:
        contract = json.loads((ROOT / CONTRACT_PATH).read_text(encoding="utf-8"))
        jsonschema.validate(
            contract,
            json.loads((ROOT / CONTRACT_SCHEMA_PATH).read_text(encoding="utf-8")),
        )
        self.assertEqual(contract["sampling"]["candidate_count"], 30)
        self.assertFalse(contract["sampling"]["positive_yield_required"])
        self.assertEqual(contract["unchanged_targets"]["qlora_train_minimum_families"], 40)
        self.assertEqual(contract["unchanged_targets"]["development_minimum_families"], 15)
        self.assertEqual(contract["unchanged_targets"]["held_out_test_minimum_families"], 40)

    def test_tranche_is_balanced_unique_and_pending(self) -> None:
        self.assertEqual(len(self.review_rows), 30)
        self.assertEqual(len(self.isolation_rows), 30)
        self.assertEqual(
            self.manifest["sampling"]["observed_model_family_counts"],
            {"Alpaca-7B": 10, "Alpaca2-7B": 10, "Alpaca3-8B": 10},
        )
        self.assertEqual(self.manifest["sampling"]["observed_stratum_counts"], {"both_safe": 6, "mixed_safety": 24})
        self.assertEqual(len({record["provisional_isolation_family_id"] for record in self.manifest["records"]}), 30)
        self.assertTrue(all(record["human_review_status"] == "pending" for record in self.manifest["records"]))
        self.assertTrue(all(row["human_review"]["decision"] is None for row in self.isolation_rows))

    def test_manifest_has_no_raw_text_and_no_split(self) -> None:
        jsonschema.validate(
            self.manifest,
            json.loads((ROOT / MANIFEST_SCHEMA_PATH).read_text(encoding="utf-8")),
        )
        forbidden = {"prompt", "text", "response_0", "response_1", "output_text"}

        def assert_clean(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for nested in value.values():
                    assert_clean(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_clean(nested)

        assert_clean(self.manifest)
        self.assertTrue(all(record["split_status"] == "not_assigned_before_all_reviews" for record in self.manifest["records"]))


if __name__ == "__main__":
    unittest.main()
