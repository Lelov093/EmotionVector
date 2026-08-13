from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]


class Phase3IndependentReviewTests(unittest.TestCase):
    def test_amendment_and_packet_preserve_deviation_boundary(self) -> None:
        contract = json.loads((ROOT / "configs/research/phase_3_independent_blind_review_amendment_v0_2.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "data/research_foundation/schemas/phase_3_independent_blind_review_amendment_v0_2.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(contract, schema)
        self.assertFalse(contract["independent_reviewer"]["researcher_01_eligible"])
        self.assertTrue(contract["deviation"]["restricted_condition_key_programmatically_accessed_before_rating_freeze"])
        packet = [json.loads(line) for line in (ROOT / contract["artifacts"]["independent_packet"]).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(packet), 52)
        self.assertEqual(sum(len(item["blind_outputs"]) for item in packet), 780)
        self.assertEqual({item["reviewer_id"] for item in packet}, {"independent_reviewer_01"})

    def test_review_sheet_and_attestation_are_blank(self) -> None:
        contract = json.loads((ROOT / "configs/research/phase_3_independent_blind_review_amendment_v0_2.json").read_text(encoding="utf-8"))
        with (ROOT / contract["artifacts"]["independent_review_sheet"]).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 780)
        self.assertTrue(all(not row["trait_score_0_to_4"] for row in rows))
        attestation = json.loads((ROOT / contract["artifacts"]["reviewer_attestation"]).read_text(encoding="utf-8"))
        self.assertEqual(attestation["status"], "pending_human_signature_before_first_rating")


if __name__ == "__main__":
    unittest.main()
