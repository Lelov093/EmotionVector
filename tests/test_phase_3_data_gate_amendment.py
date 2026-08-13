from __future__ import annotations

import json
from pathlib import Path
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]


class Phase3DataGateAmendmentTests(unittest.TestCase):
    def test_amendment_is_explicit_post_review_and_schema_valid(self) -> None:
        amendment = json.loads((ROOT / "configs/research/phase_3_data_gate_amendment_v0_1.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "data/research_foundation/schemas/phase_3_data_gate_amendment_v0_1.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(amendment, schema)
        self.assertFalse(amendment["original_gate"]["passed"])
        self.assertEqual(amendment["original_gate"]["qlora_train_families"], 40)
        self.assertTrue(amendment["amended_gate"]["passed"])
        self.assertEqual(amendment["amended_gate"]["qlora_train_families"], 39)
        self.assertIn("after", amendment["timing_disclosure"])
        self.assertFalse(amendment["decision"]["additional_candidate_expansion_allowed"])
        self.assertFalse(amendment["decision"]["model_or_gpu_execution_authorized"])

    def test_acceptance_does_not_rewrite_original_gate_result(self) -> None:
        result = json.loads((ROOT / "results/summaries/phase_3_data_gate_amendment_acceptance_v0_1.json").read_text(encoding="utf-8"))
        self.assertFalse(result["gate_accounting"]["original_40_15_40_passed"])
        self.assertTrue(result["gate_accounting"]["amended_39_15_40_passed"])
        self.assertEqual(result["observed_population"]["maximum_train_after_reserving_15_dev_and_40_test"], 39)
        self.assertFalse(result["model_or_gpu_execution_authorized"])


if __name__ == "__main__":
    unittest.main()
