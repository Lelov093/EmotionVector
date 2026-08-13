from __future__ import annotations

from pathlib import Path
import unittest

import jsonschema

from research_foundation.phase3_readiness import read_json
from research_foundation.representation_freeze import canonical_content_sha256


ROOT = Path(__file__).resolve().parents[1]


class Phase3PreExecutionContractTests(unittest.TestCase):
    def test_blind_review_contract_is_complete_and_condition_blind(self) -> None:
        contract = read_json(ROOT / "configs/research/phase_3_blind_review_contract_v0_1.json")
        schema = read_json(ROOT / "data/research_foundation/schemas/phase_3_blind_review_contract_v0_1.schema.json")
        jsonschema.validate(contract, schema)
        conditions = contract["condition_registry"]["fixed_condition_instances"]
        self.assertEqual(len(conditions), 15)
        self.assertEqual(len(set(conditions)), 15)
        self.assertEqual(sum(value.startswith("random_steering_") for value in conditions), 5)
        self.assertEqual(sum(value.startswith("shuffled_steering_") for value in conditions), 5)
        self.assertEqual(contract["review_design"]["review_rounds"], 1)
        self.assertFalse(contract["review_design"]["blind_ids_encode_condition"])
        self.assertFalse(contract["auxiliary_evaluators"]["may_replace_human_ratings"])

    def test_selection_contract_is_bounded_and_test_blind(self) -> None:
        contract = read_json(ROOT / "configs/research/phase_3_train_dev_selection_contract_v0_1.json")
        schema = read_json(ROOT / "data/research_foundation/schemas/phase_3_train_dev_selection_contract_v0_1.schema.json")
        jsonschema.validate(contract, schema)
        self.assertEqual(contract["steering_selection"]["alpha_candidates"], [1.0, 3.0])
        self.assertEqual(contract["qlora_training"]["checkpoint_candidates"], ["epoch_1", "epoch_2"])
        self.assertFalse(contract["qlora_training"]["hyperparameter_sweep_allowed"])
        self.assertFalse(contract["data_access"]["held_out_test_access_for_selection"])
        self.assertFalse(contract["development_selection_rule"]["test_retuning_allowed"])
        self.assertTrue(contract["future_selection_lock"]["required_before_test_opening"])

    def test_contract_evidence_hashes_match(self) -> None:
        for relative in (
            "configs/research/phase_3_blind_review_contract_v0_1.json",
            "configs/research/phase_3_train_dev_selection_contract_v0_1.json",
        ):
            contract = read_json(ROOT / relative)
            evidence = contract["bound_evidence"]
            for key, path in evidence.items():
                if key.endswith("_path"):
                    expected = evidence[key.removesuffix("_path") + "_sha256"]
                    self.assertEqual(canonical_content_sha256(read_json(ROOT / path)), expected)


if __name__ == "__main__":
    unittest.main()
