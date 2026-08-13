from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from research_foundation.representation_freeze import canonical_content_sha256


ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Phase3SplitFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.split = json.loads((ROOT / "data/research_foundation/manifests/phase_3_family_split_v0_1.json").read_text(encoding="utf-8"))
        self.freeze = json.loads((ROOT / "data/research_foundation/manifests/phase_3_held_out_test_freeze_v0_1.json").read_text(encoding="utf-8"))
        self.test_once = json.loads((ROOT / "configs/research/phase_3_test_once_contract_v0_1.json").read_text(encoding="utf-8"))
        self.audit = json.loads((ROOT / "results/summaries/phase_3_family_split_leakage_audit_v0_1.json").read_text(encoding="utf-8"))

    def test_split_is_exact_disjoint_and_eligibility_safe(self) -> None:
        records = self.split["records"]
        by_split = {name: [row for row in records if row["split"] == name] for name in ("train", "development", "held_out_test", "not_selected_ineligible")}
        self.assertEqual({name: len(rows) for name, rows in by_split.items()}, {"train": 39, "development": 15, "held_out_test": 40, "not_selected_ineligible": 111})
        self.assertEqual(len({row["final_isolation_family_id"] for row in records}), 205)
        self.assertTrue(all(row["qlora_eligible_response_ids"] for row in by_split["train"]))
        self.assertTrue(all(row["evaluation_eligible_candidate_ids"] for row in by_split["development"] + by_split["held_out_test"]))
        candidate_sets = [{candidate for row in by_split[name] for candidate in row["candidate_ids"]} for name in ("train", "development", "held_out_test")]
        self.assertFalse(candidate_sets[0] & candidate_sets[1])
        self.assertFalse(candidate_sets[0] & candidate_sets[2])
        self.assertFalse(candidate_sets[1] & candidate_sets[2])

    def test_local_artifacts_are_hash_bound_and_not_tracked(self) -> None:
        expected_counts = {"train": 65, "development": 18, "held_out_test": 52}
        for name, metadata in self.split["local_artifacts"].items():
            path = ROOT / metadata["path"]
            self.assertTrue(path.exists())
            self.assertFalse(metadata["tracked"])
            self.assertEqual(metadata["row_count"], expected_counts[name])
            self.assertEqual(metadata["sha256"], file_sha256(path))

    def test_test_freeze_preserves_preopening_state_and_current_single_event(self) -> None:
        self.assertEqual(len(self.freeze["test_family_ids"]), 40)
        self.assertEqual(len(self.freeze["test_candidate_ids"]), 52)
        self.assertEqual(self.freeze["access_state"]["model_execution_openings"], 0)
        self.assertFalse(self.freeze["access_state"]["access_log_exists"])
        access_log = ROOT / self.freeze["access_state"]["access_log_path"]
        self.assertFalse(self.freeze["access_state"]["access_log_exists"])
        self.assertEqual(self.freeze["access_state"]["model_execution_openings"], 0)
        self.assertTrue(access_log.exists())
        events = [line for line in access_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(events), 1)
        self.assertEqual(self.test_once["split_manifest"]["sha256"], canonical_content_sha256(self.split))
        self.assertEqual(self.test_once["test_freeze"]["sha256"], canonical_content_sha256(self.freeze))
        self.assertTrue(self.test_once["access_policy"]["single_model_test_opening"])

    def test_leakage_audit_has_zero_blockers_and_reports_stratifier_overlap(self) -> None:
        self.assertEqual(set(self.audit["blocking_leakage_counts"].values()), {0})
        self.assertLess(self.audit["maximum_cross_split_prompt_token_3gram_jaccard"], 0.9)
        self.assertEqual(self.audit["semantic_isolation_evidence"]["status"], "pass")
        self.assertGreater(self.audit["broad_family_stratifier_overlap_nonblocking"]["task_family_id"]["train_vs_held_out_test"], 0)
        self.assertIn("stratifiers", self.audit["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
