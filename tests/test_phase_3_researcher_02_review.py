from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Phase3Researcher02ReviewTests(unittest.TestCase):
    def test_guide_has_all_required_anchors(self) -> None:
        guide = (ROOT / "data/research_foundation/human_review/phase_3_held_out_scoring_guide_v0_3.md").read_text(encoding="utf-8")
        for term in ("Target Trait", "Task quality", "Naturalness", "Refusal appropriateness", "Over-refusal", "Sycophancy", "Alternative quality", "Repetition", "Confidence", "Completion gate"):
            self.assertIn(term, guide)

    def test_researcher_02_sheet_is_complete_and_blank(self) -> None:
        contract = json.loads((ROOT / "configs/research/phase_3_researcher_02_review_contract_v0_3.json").read_text(encoding="utf-8"))
        with (ROOT / contract["artifacts"]["review_sheet"]).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 780)
        self.assertEqual({row["reviewer_id"] for row in rows}, {"researcher_02"})
        self.assertTrue(all(not row["trait_score_0_to_4"] for row in rows))

    def test_compliance_is_user_confirmed_not_reviewer_signed(self) -> None:
        contract = json.loads((ROOT / "configs/research/phase_3_researcher_02_review_contract_v0_3.json").read_text(encoding="utf-8"))
        record = json.loads((ROOT / contract["artifacts"]["compliance_record"]).read_text(encoding="utf-8"))
        self.assertEqual(record["reviewer_id"], "researcher_02")
        self.assertFalse(record["reviewer_signature_recorded"])
        self.assertEqual(set(record["checks"].values()), {"compliant"})


if __name__ == "__main__":
    unittest.main()
