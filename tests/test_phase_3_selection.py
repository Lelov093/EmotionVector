from __future__ import annotations

import json
from pathlib import Path
import unittest

import jsonschema

from research_foundation.phase3_runtime import file_sha256
from research_foundation.phase3_selection import (
    ANNOTATION_SCHEMA,
    FORMAL_ANNOTATIONS,
    FREEZE_MANIFEST,
    LOCK_SCHEMA,
    SELECTION_LOCK,
    SELECTION_SUMMARY,
    SELECTION_SUMMARY_SCHEMA,
    create_selection_lock,
)
from research_foundation.representation_freeze import canonical_content_sha256


ROOT = Path(__file__).resolve().parents[1]


class Phase3SelectionTests(unittest.TestCase):
    def test_formal_review_is_complete_frozen_and_score_preserving(self) -> None:
        rows = [json.loads(line) for line in (ROOT / FORMAL_ANNOTATIONS).read_text(encoding="utf-8").splitlines() if line.strip()]
        schema = json.loads((ROOT / ANNOTATION_SCHEMA).read_text(encoding="utf-8"))
        for row in rows:
            jsonschema.validate(row, schema, format_checker=jsonschema.FormatChecker())
        freeze = json.loads((ROOT / FREEZE_MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 90)
        self.assertEqual(len({row["blind_output_id"] for row in rows}), 90)
        self.assertEqual({row["reviewer_id"] for row in rows}, {"researcher_01"})
        self.assertEqual(file_sha256(ROOT / FORMAL_ANNOTATIONS), freeze["formal_annotations"]["sha256"])
        self.assertFalse(freeze["condition_key_access_at_freeze"])
        self.assertEqual(freeze["validation"]["substantive_score_changes"], 0)
        self.assertEqual(freeze["validation"]["original_output_newlines_restored_from_packet_rows"], 51)

    def test_selection_lock_reports_all_candidates_and_keeps_test_closed(self) -> None:
        lock = json.loads((ROOT / SELECTION_LOCK).read_text(encoding="utf-8"))
        summary = json.loads((ROOT / SELECTION_SUMMARY).read_text(encoding="utf-8"))
        jsonschema.validate(lock, json.loads((ROOT / LOCK_SCHEMA).read_text(encoding="utf-8")), format_checker=jsonschema.FormatChecker())
        jsonschema.validate(summary, json.loads((ROOT / SELECTION_SUMMARY_SCHEMA).read_text(encoding="utf-8")), format_checker=jsonschema.FormatChecker())
        self.assertEqual(len(lock["candidate_results"]), 4)
        self.assertTrue(lock["all_candidates_reported"])
        self.assertEqual(lock["selected_specification"]["target_steering_alpha"], 1.0)
        self.assertEqual(lock["selected_specification"]["qlora_checkpoint_id"], "epoch_1")
        self.assertTrue(lock["quality_gate"]["target_steering_passed"])
        self.assertFalse(lock["quality_gate"]["qlora_passed"])
        self.assertEqual(lock["test_opening_status"], "locked_not_opened")
        self.assertEqual(summary["held_out_test_model_openings"], 0)
        self.assertEqual(canonical_content_sha256(lock), summary["selection_lock_sha256"])

    def test_selection_lock_cannot_be_rebuilt_after_held_out_opening(self) -> None:
        with self.assertRaisesRegex(ValueError, "held-out test access log exists"):
            create_selection_lock(ROOT)


if __name__ == "__main__":
    unittest.main()
