from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from research_foundation.audit import audit_dataset, cross_split_near_duplicates, normalize_text


class ResearchFoundationAuditTests(unittest.TestCase):
    def test_normalize_text_is_case_and_punctuation_insensitive(self) -> None:
        self.assertEqual(normalize_text("Hello,  WORLD!"), "hello world")

    def test_audit_detects_cross_split_prompt_and_family_leakage(self) -> None:
        rows = [
            {"id": "a", "split": "train", "user_prompt": "Same prompt!", "task_family_id": "task-a"},
            {"id": "b", "split": "test", "user_prompt": "same prompt", "task_family_id": "task-a"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixture.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            result = audit_dataset(
                root,
                {
                    "dataset_id": "fixture",
                    "path": "fixture.jsonl",
                    "id_field": "id",
                    "split_field": "split",
                    "text_fields": ["user_prompt"],
                    "legacy_group_fields": [],
                    "known_template_phrases": [],
                    "formal_use_status": "fixture",
                },
            )
        blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
        self.assertIn("exact_text_leakage_across_splits", blocker_ids)
        self.assertIn("family_or_group_leakage_across_splits", blocker_ids)
        self.assertEqual(len(result["family_leaks"]["task_family_id"]), 1)

    def test_near_duplicate_check_excludes_exact_duplicates(self) -> None:
        rows = [
            {"split": "train", "text": "alpha beta gamma delta epsilon"},
            {"split": "test", "text": "alpha beta gamma delta epsilon"},
            {"split": "test", "text": "alpha beta gamma delta epsilon zeta"},
        ]
        result = cross_split_near_duplicates(rows, "text", "split", threshold=0.7)
        self.assertEqual(result["count"], 1)

    def test_template_phrase_is_reported_as_direct_blocker(self) -> None:
        rows = [
            {"id": "a", "split": "train", "response": "Fixed phrase one"},
            {"id": "b", "split": "test", "response": "Fixed phrase two"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixture.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            result = audit_dataset(
                root,
                {
                    "dataset_id": "fixture",
                    "path": "fixture.jsonl",
                    "id_field": "id",
                    "split_field": "split",
                    "text_fields": ["response"],
                    "legacy_group_fields": [],
                    "known_template_phrases": ["Fixed phrase"],
                    "template_blocker_min_rows": 2,
                    "formal_use_status": "fixture",
                },
            )
        blockers = {blocker["blocker_id"]: blocker for blocker in result["blockers"]}
        self.assertEqual(blockers["repeated_template_phrase"]["evidence_level"], "direct")


if __name__ == "__main__":
    unittest.main()
