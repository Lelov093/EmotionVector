from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_foundation.public_pilot import (
    build_empathetic_candidates,
    build_pku_candidates,
    validate_completed_review,
)


class PublicMappingPilotTests(unittest.TestCase):
    def test_empathetic_sampling_is_context_stratified_and_manifest_has_no_raw_text(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "train.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "conv_id", "utterance_idx", "context", "prompt", "speaker_idx",
                        "utterance", "selfeval", "tags",
                    ],
                )
                writer.writeheader()
                for conv_id, context in (("c1", "joy"), ("c2", "sad")):
                    writer.writerow({"conv_id": conv_id, "utterance_idx": "1", "context": context,
                                     "prompt": "SECRET_SITUATION", "speaker_idx": "1",
                                     "utterance": "SECRET_USER", "selfeval": "", "tags": ""})
                    writer.writerow({"conv_id": conv_id, "utterance_idx": "2", "context": context,
                                     "prompt": "SECRET_SITUATION", "speaker_idx": "2",
                                     "utterance": "SECRET_RESPONSE", "selfeval": "", "tags": ""})
            review, manifest, summary = build_empathetic_candidates({"train": path}, 7, 1)
        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(summary["context_count"], 2)
        self.assertIn("SECRET_RESPONSE", str(review))
        self.assertNotIn("SECRET_RESPONSE", str(manifest))
        self.assertTrue(all(row["human_review_status"] == "pending" for row in manifest))

    def test_pku_sampling_excludes_both_unsafe_and_preserves_unicode_separator(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "train.jsonl"
            rows = [
                self._pku_row("SECRET_PKU_PROMPT\u2028continued", True, False, "m"),
                self._pku_row("safe prompt", True, True, "s"),
                self._pku_row("unsafe prompt", False, False, "u"),
            ]
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            review, manifest, summary = build_pku_candidates({"Model": path}, 7, 1, 1)
        self.assertEqual(len(review), 2)
        self.assertEqual(summary["selected_stratum_counts"], {"both_safe": 1, "mixed_safety": 1})
        self.assertEqual(summary["excluded_from_pilot"], ["both_unsafe"])
        self.assertNotIn("SECRET_PKU_PROMPT", str(manifest))

    def test_completed_review_validator_requires_human_decisions_and_families(self) -> None:
        row = {
            "dataset_id": "empathetic_dialogues",
            "sample_id": "sample",
            "human_review": {"mapping_decision": None},
        }
        self.assertTrue(validate_completed_review([row]))
        row["human_review"] = {
            "mapping_decision": "accept",
            "primary_trait_axis": "empathetic-detached",
            "task_family_id": "task",
            "scenario_family_id": "scenario",
            "prompt_template_id": "template",
            "semantic_cluster_id": "semantic",
        }
        self.assertEqual(validate_completed_review([row]), [])

    @staticmethod
    def _pku_row(prompt: str, safe0: bool, safe1: bool, suffix: str) -> dict:
        return {
            "prompt": prompt,
            "response_0": f"response zero {suffix}",
            "response_1": f"response one {suffix}",
            "is_response_0_safe": safe0,
            "is_response_1_safe": safe1,
            "better_response_id": 0,
            "safer_response_id": 0 if safe0 else 1,
            "response_0_sha256": f"zero-{suffix}",
            "response_1_sha256": f"one-{suffix}",
        }


if __name__ == "__main__":
    unittest.main()
