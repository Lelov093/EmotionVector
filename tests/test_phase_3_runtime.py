from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from research_foundation.phase3_runtime import (
    build_development_blind_packet,
    build_response_only_example,
    collate_response_only,
    derive_direction_bundle,
    load_runtime,
    validate_development_outputs,
    validate_local_data,
)
from research_foundation.representation_freeze import content_sha256


ROOT = Path(__file__).resolve().parents[1]


class FakeTokenizer:
    eos_token_id = 99

    def apply_chat_template(self, messages, **kwargs):
        return [10, 11, 12]

    def __call__(self, text, **kwargs):
        return {"input_ids": [20 + index for index, _ in enumerate(text.split())]}


class Phase3RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = load_runtime(ROOT)
        cls.train, cls.development = validate_local_data(ROOT, cls.runtime)

    def test_runtime_binds_exact_local_train_and_development_data(self) -> None:
        self.assertEqual(len(self.train), 65)
        self.assertEqual(len({row["final_isolation_family_id"] for row in self.train}), 39)
        self.assertEqual(len(self.development), 18)
        self.assertEqual(len({row["final_isolation_family_id"] for row in self.development}), 15)
        self.assertTrue(self.runtime["data"]["test_access_forbidden"])

    def test_response_only_masking_and_padding(self) -> None:
        row = {"record_id": "r1", "prompt": "one prompt", "response": "two response tokens"}
        example = build_response_only_example(FakeTokenizer(), row, 20)
        self.assertEqual(example["labels"][:3], [-100, -100, -100])
        self.assertTrue(all(label != -100 for label in example["labels"][3:]))
        batch = collate_response_only([example, {k: v[:-1] for k, v in example.items()}], 0)
        self.assertEqual(batch["labels"][1][-1], -100)
        self.assertEqual(batch["attention_mask"][1][-1], 0)

    def test_overlength_training_example_is_rejected_not_truncated(self) -> None:
        row = {"record_id": "r1", "prompt": "p", "response": "one two three"}
        with self.assertRaisesRegex(ValueError, "truncation is forbidden"):
            build_response_only_example(FakeTokenizer(), row, 4)

    def test_direction_bundle_uses_train_only_and_is_deterministic(self) -> None:
        first, metadata = derive_direction_bundle(ROOT, self.runtime)
        second, _ = derive_direction_bundle(ROOT, self.runtime)
        self.assertEqual(metadata["test_rows_used"], 0)
        self.assertEqual(set(first), {"target", "sign_flipped", *{f"random_{i:02d}" for i in range(1, 6)}, *{f"shuffled_{i:02d}" for i in range(1, 6)}})
        self.assertTrue(np.allclose(first["target"], -first["sign_flipped"]))
        for key in first:
            self.assertAlmostEqual(float(np.linalg.norm(first[key])), 1.0, places=5)
            self.assertTrue(np.array_equal(first[key], second[key]))

    def test_development_outputs_require_every_candidate_condition(self) -> None:
        conditions = self.runtime["development_generation"]["candidate_condition_ids"]
        records = []
        for row in self.development:
            for condition in conditions:
                output = f"output {row['candidate_id']} {condition}"
                records.append({
                    "candidate_id": row["candidate_id"],
                    "final_isolation_family_id": row["final_isolation_family_id"],
                    "condition_id": condition,
                    "output_text": output,
                    "output_sha256": content_sha256(output),
                })
        validate_development_outputs(records, self.development, conditions)
        with self.assertRaisesRegex(ValueError, "every development prompt"):
            validate_development_outputs(records[:-1], self.development, conditions)
        packet, key = build_development_blind_packet(records, self.development, seed=7)
        self.assertEqual(len(packet), 18)
        self.assertEqual(len(key), 90)
        self.assertNotIn("condition_id", str(packet))
        self.assertEqual(len({item["blind_output_id"] for item in key}), 90)

    def test_tracked_execution_summary_keeps_test_closed_and_results_unselected(self) -> None:
        import json

        summary = json.loads((ROOT / "results/summaries/phase_3_train_dev_execution_v0_1.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["development_generation"]["condition_outputs"], 90)
        self.assertEqual(summary["blind_review"]["human_annotations_completed"], 0)
        self.assertFalse(summary["training"]["quality_selected"])
        self.assertFalse(summary["test_boundary"]["held_out_test_access_log_exists"])
        self.assertEqual(summary["test_boundary"]["held_out_test_model_openings"], 0)


if __name__ == "__main__":
    unittest.main()
