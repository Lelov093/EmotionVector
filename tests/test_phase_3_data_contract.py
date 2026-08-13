from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

import jsonschema

from research_foundation.phase3_data_contract import (
    MANIFEST_SCHEMA_PATH,
    REVIEW_SCHEMA_PATH,
    build_phase_3_family_candidates,
    validate_phase_3_review_rows,
)


ROOT = Path(__file__).resolve().parents[1]


class Phase3DataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source_root = ROOT / "data/external/pku_safe_rlhf"
        if not source_root.exists():
            raise unittest.SkipTest("Git-ignored PKU snapshot is not present")
        cls.review_rows, cls.manifest = build_phase_3_family_candidates(ROOT)

    def test_candidate_pool_is_balanced_unique_and_not_split(self) -> None:
        self.assertEqual(len(self.review_rows), 180)
        self.assertEqual(len({row["candidate_id"] for row in self.review_rows}), 180)
        self.assertEqual(
            self.manifest["sampling"]["observed_stratum_counts"],
            {"both_safe": 30, "mixed_safety": 150},
        )
        self.assertEqual(
            self.manifest["sampling"]["observed_model_family_counts"],
            {"Alpaca-7B": 60, "Alpaca2-7B": 60, "Alpaca3-8B": 60},
        )
        self.assertTrue(all(record["human_review_status"] == "pending" for record in self.manifest["records"]))
        self.assertTrue(all(record["split_status"] == "not_assigned_before_human_review" for record in self.manifest["records"]))

    def test_phase_2_is_excluded_and_manifest_contains_no_raw_text(self) -> None:
        checks = {item["check_id"]: item for item in self.manifest["checks"]}
        self.assertEqual(checks["phase_2_content_overlap"]["observed"], 0)
        self.assertEqual(checks["phase_2_source_locator_overlap"]["observed"], 0)
        forbidden = {"prompt", "text", "response_0", "response_1"}

        def assert_no_raw(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for nested in value.values():
                    assert_no_raw(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_no_raw(nested)

        assert_no_raw(self.manifest)

    def test_blank_review_rows_and_manifest_match_schemas(self) -> None:
        review_schema = json.loads((ROOT / REVIEW_SCHEMA_PATH).read_text(encoding="utf-8"))
        manifest_schema = json.loads((ROOT / MANIFEST_SCHEMA_PATH).read_text(encoding="utf-8"))
        for row in self.review_rows:
            jsonschema.validate(row, review_schema)
        jsonschema.validate(self.manifest, manifest_schema)

    def test_same_axis_pair_cannot_be_evaluation_eligible(self) -> None:
        review_schema = json.loads((ROOT / REVIEW_SCHEMA_PATH).read_text(encoding="utf-8"))
        row = deepcopy(self.review_rows[0])
        review = row["human_review"]
        review.update(
            {
                "mapping_decision": "accept",
                "reviewer_id": "researcher_1",
                "reviewed_at": "2026-08-04T12:00:00+08:00",
                "pair_contrast": "same_axis_not_opposite",
                "pair_evaluation_eligible": True,
                "reviewed_family_assignment": {
                    "task_family_id": "harm_prevention_response",
                    "scenario_family_id": "example_scenario",
                    "prompt_template_id": "single_turn_request",
                    "semantic_cluster_id": "example_cluster",
                },
            }
        )
        for index, annotation in enumerate(review["response_annotations"]):
            annotation.update(
                {
                    "behavior": "reasonable_refusal",
                    "pole": "boundary-preserving",
                    "task_success": 2,
                    "naturalness": 2,
                    "useful_alternative": 1,
                    "over_refusal": 0,
                    "template_style": 0,
                    "qlora_training_eligible": index == 0,
                }
            )
        with self.assertRaisesRegex(ValueError, "valid opposite-pole contrast"):
            validate_phase_3_review_rows([row], review_schema)


if __name__ == "__main__":
    unittest.main()
