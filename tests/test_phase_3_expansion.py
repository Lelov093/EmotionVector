from __future__ import annotations

import json
from pathlib import Path
import unittest

import jsonschema

from research_foundation.phase3_expansion import (
    CONTRACT_PATH,
    CONTRACT_SCHEMA_PATH,
    MANIFEST_SCHEMA_PATH,
    build_phase_3_expansion_candidates,
    build_provisional_isolation_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


class Phase3ExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "data/external/pku_safe_rlhf").exists():
            raise unittest.SkipTest("Git-ignored PKU snapshot is not present")
        cls.rows, cls.manifest = build_phase_3_expansion_candidates(ROOT)
        cls.semantic_rows, cls.isolation_manifest = build_provisional_isolation_artifacts(ROOT, cls.rows)

    def test_contract_revises_ownership_without_lowering_targets(self) -> None:
        contract = json.loads((ROOT / CONTRACT_PATH).read_text(encoding="utf-8"))
        schema = json.loads((ROOT / CONTRACT_SCHEMA_PATH).read_text(encoding="utf-8"))
        jsonschema.validate(contract, schema)
        self.assertEqual(contract["isolation_policy"]["strict_split_ownership_field"], "isolation_family_id")
        self.assertFalse(contract["isolation_policy"]["broad_fields_are_automatic_union_keys"])
        self.assertTrue(contract["isolation_policy"]["human_semantic_merge_review_required_before_split"])
        self.assertEqual(contract["unchanged_post_review_targets"]["qlora_train_minimum_families"], 40)
        self.assertEqual(contract["unchanged_post_review_targets"]["development_minimum_families"], 15)
        self.assertEqual(contract["unchanged_post_review_targets"]["held_out_test_minimum_families"], 40)

    def test_expansion_is_balanced_pending_and_unique(self) -> None:
        self.assertEqual(len(self.rows), 60)
        self.assertEqual(
            self.manifest["sampling"]["observed_model_family_counts"],
            {"Alpaca-7B": 20, "Alpaca2-7B": 20, "Alpaca3-8B": 20},
        )
        self.assertEqual(self.manifest["sampling"]["observed_stratum_counts"], {"both_safe": 15, "mixed_safety": 45})
        self.assertEqual(len({record["provisional_isolation_family_id"] for record in self.manifest["records"]}), 60)
        self.assertTrue(all(record["human_review_status"] == "pending" for record in self.manifest["records"]))
        self.assertTrue(all(record["split_status"] == "not_assigned_before_all_reviews" for record in self.manifest["records"]))

    def test_tracked_manifest_has_no_raw_text_and_matches_schema(self) -> None:
        schema = json.loads((ROOT / MANIFEST_SCHEMA_PATH).read_text(encoding="utf-8"))
        jsonschema.validate(self.manifest, schema)
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

    def test_provisional_isolation_covers_all_240_and_requires_human_merge_review(self) -> None:
        self.assertEqual(len(self.semantic_rows), 240)
        self.assertEqual(len(self.isolation_manifest["records"]), 240)
        self.assertEqual(self.isolation_manifest["construction"]["component_count"], 240)
        self.assertEqual(self.isolation_manifest["construction"]["largest_component_size"], 1)
        self.assertFalse(self.isolation_manifest["construction"]["semantic_model_run"])
        self.assertTrue(all(row["human_review"]["decision"] is None for row in self.semantic_rows))
        self.assertTrue(
            all(
                row["isolation_review_status"] == "pending_human_semantic_merge_review"
                for row in self.isolation_manifest["records"]
            )
        )


if __name__ == "__main__":
    unittest.main()
