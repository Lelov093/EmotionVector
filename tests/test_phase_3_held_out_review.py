from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from research_foundation.phase3_heldout_review import build_formal_annotations


ROOT = Path(__file__).resolve().parents[1]
REVIEW_SHEET = (
    ROOT
    / "results/local_artifacts/research_foundation/phase_3/"
    "phase_3_researcher_02_test_blind_review_sheet_v0_3_scored.csv"
)


class Phase3HeldOutReviewTests(unittest.TestCase):
    def test_scored_submission_builds_780_schema_valid_annotations(self) -> None:
        source = REVIEW_SHEET
        if not source.exists():
            self.skipTest("gitignored reviewer submission is not available")
        formal, validation = build_formal_annotations(ROOT, source)
        self.assertEqual(len(formal), 780)
        self.assertEqual(validation["unique_blind_outputs"], 780)
        self.assertEqual(validation["unique_review_items"], 52)
        self.assertEqual(validation["unique_families"], 40)
        self.assertEqual({row["reviewer_id"] for row in formal}, {"researcher_02"})

    def test_rejects_changed_frozen_identity(self) -> None:
        source = REVIEW_SHEET
        if not source.exists():
            self.skipTest("gitignored reviewer submission is not available")
        with source.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            fields = list(rows[0])
        rows[0]["candidate_id"] = "changed"
        with tempfile.TemporaryDirectory(dir=ROOT / "results" / "local_artifacts") as directory:
            changed = Path(directory) / "changed.csv"
            with changed.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "frozen content differs"):
                build_formal_annotations(ROOT, changed)


if __name__ == "__main__":
    unittest.main()
