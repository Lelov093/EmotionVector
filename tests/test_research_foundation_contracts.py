from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "data/research_foundation/schemas"


class ResearchFoundationContractTests(unittest.TestCase):
    def test_schema_files_are_valid_json_and_draft_2020_12(self) -> None:
        schemas = sorted(SCHEMA_DIR.glob("*.schema.json"))
        self.assertEqual(len(schemas), 52)
        for path in schemas:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_split_contract_requires_all_family_isolation_fields(self) -> None:
        payload = json.loads((SCHEMA_DIR / "family_split_v2.schema.json").read_text(encoding="utf-8"))
        record_required = payload["properties"]["records"]["items"]["required"]
        expected = {
            "source_family_id",
            "task_family_id",
            "scenario_family_id",
            "prompt_template_id",
            "semantic_cluster_id",
        }
        self.assertTrue(expected.issubset(record_required))

    def test_blind_review_item_cannot_contain_condition_or_auxiliary_scores(self) -> None:
        payload = json.loads((SCHEMA_DIR / "blind_evaluation_v2.schema.json").read_text(encoding="utf-8"))
        review_item = payload["$defs"]["review_item"]
        self.assertFalse(review_item["additionalProperties"])
        properties = set(review_item["properties"])
        self.assertFalse({"condition_id", "heuristic_scores", "external_judge"} & properties)

    def test_current_provenance_hashes_and_counts_match_files(self) -> None:
        from research_foundation.audit import file_sha256, read_jsonl

        manifest = json.loads(
            (ROOT / "data/research_foundation/manifests/current_dataset_provenance_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        for entry in manifest["entries"]:
            path = ROOT / entry["path"]
            self.assertEqual(file_sha256(path), entry["sha256"], entry["dataset_id"])
            self.assertEqual(len(read_jsonl(path)), entry["row_count"], entry["dataset_id"])

    def test_public_candidates_have_scoped_use_decisions_and_current_mapping_status(self) -> None:
        registry = json.loads(
            (ROOT / "data/research_foundation/manifests/public_dataset_candidates_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            registry["download_status"],
            "downloaded_raw_human_mapping_review_complete_scoped_use_approved",
        )
        expected_mapping_status = {
            "empathetic_dialogues": "schema_v0_2_human_review_complete_not_representation_ready",
            "pku_safe_rlhf": "schema_v0_2_human_review_complete_representation_subset_frozen",
        }
        for candidate in registry["candidates"]:
            self.assertEqual(candidate["license_review_status"], "approved_noncommercial_research_use")
            self.assertEqual(
                candidate["mapping_status"],
                expected_mapping_status[candidate["dataset_id"]],
            )
            self.assertEqual(
                candidate["license_decision_path"],
                "data/research_foundation/manifests/public_dataset_use_decisions_v0_1.json",
            )
            self.assertEqual(
                candidate["pilot_manifest_path"],
                "data/research_foundation/manifests/public_mapping_pilot_v0_2.json",
            )
            self.assertEqual(
                candidate["historical_pilot_manifest_path"],
                "data/research_foundation/manifests/public_mapping_pilot_v0_1.json",
            )
            self.assertTrue(candidate["local_snapshot_path"].startswith("data/external/"))

    def test_public_mapping_manifest_is_pending_and_contains_no_raw_text(self) -> None:
        manifest = json.loads(
            (ROOT / "data/research_foundation/manifests/public_mapping_pilot_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            manifest["status"], "candidate_packets_prepared_pending_single_researcher_review"
        )
        self.assertEqual(manifest["formal_split_status"], "not_created")
        self.assertEqual(manifest["human_review_status"], "not_started")
        counts = {dataset["dataset_id"]: len(dataset["records"]) for dataset in manifest["datasets"]}
        self.assertEqual(counts, {"empathetic_dialogues": 64, "pku_safe_rlhf": 60})
        forbidden = {
            "prompt", "response_0", "response_1", "candidate_response",
            "user_utterance", "situation_prompt", "output_text",
        }

        def assert_clean(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for nested in value.values():
                    assert_clean(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_clean(nested)

        assert_clean(manifest)
        for dataset in manifest["datasets"]:
            for record in dataset["records"]:
                self.assertEqual(
                    record["proposed_family_assignment"]["assignment_status"],
                    "machine_proposed_pending_human",
                )
                self.assertEqual(record["human_review_status"], "pending")

    def test_public_mapping_v2_manifest_is_pending_and_source_family_is_not_human_editable(self) -> None:
        manifest = json.loads(
            (ROOT / "data/research_foundation/manifests/public_mapping_pilot_v0_2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            manifest["status"], "v0_2_blank_packets_prepared_pending_single_researcher_review"
        )
        self.assertEqual(manifest["formal_split_status"], "not_created")
        self.assertEqual(manifest["human_review_status"], "not_started")
        self.assertEqual(
            manifest["historical_predecessor"]["manifest"],
            "data/research_foundation/manifests/public_mapping_pilot_v0_1.json",
        )
        counts = {dataset["dataset_id"]: len(dataset["records"]) for dataset in manifest["datasets"]}
        self.assertEqual(counts, {"empathetic_dialogues": 64, "pku_safe_rlhf": 60})
        for dataset in manifest["datasets"]:
            for record in dataset["records"]:
                self.assertTrue(record["source_family_id"])
                self.assertNotIn("source_family_id", record["proposed_family_assignment"])
                self.assertEqual(record["human_review_status"], "pending")

    def test_download_manifest_hashes_and_parser_findings_match_files(self) -> None:
        from research_foundation.audit import file_sha256

        manifest = json.loads(
            (ROOT / "data/research_foundation/manifests/public_dataset_downloads_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        if not (ROOT / manifest["download_root"]).exists():
            self.skipTest("Git-ignored public dataset snapshots are not present in this environment")
        self.assertEqual(len(manifest["datasets"]), 2)
        for dataset in manifest["datasets"]:
            for entry in dataset["files"]:
                path = ROOT / entry["path"]
                self.assertTrue(path.exists(), entry["path"])
                self.assertEqual(file_sha256(path), entry["sha256"], entry["path"])
                if entry["role"] == "extracted_split":
                    with path.open(encoding="utf-8", newline="") as handle:
                        self.assertEqual(sum(1 for _ in csv.DictReader(handle)), entry["rows"])
                if entry["role"].startswith("source_split"):
                    physical = valid = invalid = 0
                    with path.open("r", encoding="utf-8") as handle:
                        for line in handle:
                            if not line.strip():
                                continue
                            physical += 1
                            try:
                                json.loads(line)
                                valid += 1
                            except json.JSONDecodeError:
                                invalid += 1
                    self.assertEqual(physical, entry["physical_nonempty_lines"], entry["path"])
                    self.assertEqual(valid, entry["valid_json_objects"], entry["path"])
                    self.assertEqual(invalid, entry["invalid_lines"], entry["path"])
        pku = next(dataset for dataset in manifest["datasets"] if dataset["dataset_id"] == "pku_safe_rlhf")
        self.assertEqual(pku["quality_summary"]["invalid_lines"], 0)
        self.assertEqual(pku["quality_summary"]["jsonl_boundary"], "LF_or_CRLF_only")

    def test_jsonl_reader_does_not_split_unicode_separators_inside_strings(self) -> None:
        from tempfile import TemporaryDirectory

        from research_foundation.audit import read_jsonl

        with TemporaryDirectory() as directory:
            path = Path(directory) / "unicode-separator.jsonl"
            path.write_text('{"text":"left\u2028right"}\n{"text":"next"}\n', encoding="utf-8")
            rows = read_jsonl(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "left\u2028right")


if __name__ == "__main__":
    unittest.main()
