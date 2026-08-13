from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from research_foundation.public_mapping_v2 import (
    content_digest,
    family_split_records_v2,
    load_axis_poles,
    reviewed_family_candidates_v2,
    validate_completed_review_v2,
    validate_rows_against_schema_v2,
)


ROOT = Path(__file__).resolve().parents[1]
AXIS_POLES = load_axis_poles(ROOT / "data/trait_space/axis_registry.yaml")


def family_values() -> dict[str, str]:
    return {
        "task_family_id": "task_support",
        "scenario_family_id": "scenario_setback",
        "prompt_template_id": "template_natural_dialogue",
        "semantic_cluster_id": "semantic_setback_01",
    }


def empathetic_row() -> dict:
    return {
        "schema_version": "public_mapping_review_v0_2",
        "record_type": "public_mapping_review",
        "dataset_id": "empathetic_dialogues",
        "sample_id": "edmap_test",
        "source_family_id": "empathetic_dialogues_d8b80665",
        "source_locator": {"source_split": "train", "conv_id": "c1", "response_utterance_idx": 2},
        "source_context_label": "sad",
        "situation_prompt": "Situation",
        "user_utterance": "User",
        "candidate_response": "Response",
        "content_sha256": content_digest("Situation", "User", "Response"),
        "candidate_trait_axes": ["empathetic-detached", "warm-cold", "supportive-critical"],
        "proposed_family_assignment": {
            **family_values(),
            "assignment_status": "machine_proposed_pending_human",
        },
        "human_review": {
            "mapping_decision": None,
            "reviewer_id": None,
            "reviewed_at": None,
            "trait_annotation": {"axis_id": None, "pole": None},
            "reviewed_family_assignment": {field: None for field in family_values()},
            "quality_flags": [],
            "rewrite_notes": "",
            "notes": "",
        },
    }


def pku_row() -> dict:
    return {
        "schema_version": "public_mapping_review_v0_2",
        "record_type": "public_mapping_review",
        "dataset_id": "pku_safe_rlhf",
        "sample_id": "pkumap_test",
        "source_family_id": "pku_safe_rlhf_f4b036fc_alpaca_7b",
        "content_warning": "warning",
        "source_locator": {"model_family": "Alpaca-7B", "source_split": "train", "lf_record_number": 1},
        "prompt": "Prompt",
        "response_0": "Response 0",
        "response_1": "Response 1",
        "source_labels": {"sampling_stratum": "mixed_safety"},
        "content_sha256": content_digest("Prompt", "Response 0", "Response 1"),
        "candidate_trait_axes": [
            "boundary-preserving-over-accommodating", "assertive-compliant", "cautious-impulsive"
        ],
        "proposed_family_assignment": {
            **family_values(),
            "assignment_status": "machine_proposed_pending_human",
        },
        "human_review": {
            "mapping_decision": None,
            "reviewer_id": None,
            "reviewed_at": None,
            "response_annotations": [
                {"response_id": "response_0", "behavior": None,
                 "trait_annotation": {"axis_id": None, "pole": None}},
                {"response_id": "response_1", "behavior": None,
                 "trait_annotation": {"axis_id": None, "pole": None}},
            ],
            "pair_contrast": {"status": None, "axis_id": None},
            "reviewed_family_assignment": {field: None for field in family_values()},
            "quality_flags": [],
            "rewrite_notes": "",
            "notes": "",
        },
    }


def expected(*rows: dict) -> dict[str, dict]:
    result = {}
    for row in rows:
        value = {
            key: deepcopy(row[key])
            for key in (
                "dataset_id", "source_family_id", "source_locator", "content_sha256",
                "candidate_trait_axes", "proposed_family_assignment",
            )
        }
        if row["dataset_id"] == "empathetic_dialogues":
            value["source_context_label"] = row["source_context_label"]
        else:
            value["source_label_summary"] = row["source_labels"]
        result[row["sample_id"]] = value
    return result


def review_metadata() -> dict[str, str]:
    return {"reviewer_id": "researcher_01", "reviewed_at": "2026-08-03T20:30:00+08:00"}


class PublicMappingV2Tests(unittest.TestCase):
    def test_registry_is_authoritative_for_axis_poles(self) -> None:
        self.assertEqual(AXIS_POLES["empathetic-detached"], ("empathetic", "detached"))
        self.assertEqual(
            AXIS_POLES["boundary-preserving-over-accommodating"],
            ("boundary-preserving", "over-accommodating"),
        )

    def test_accepted_empathetic_requires_valid_pole_and_four_reviewed_families(self) -> None:
        row = empathetic_row()
        row["human_review"].update(
            {
                "mapping_decision": "accept",
                **review_metadata(),
                "trait_annotation": {"axis_id": "empathetic-detached", "pole": "empathetic"},
                "reviewed_family_assignment": family_values(),
            }
        )
        self.assertEqual(validate_completed_review_v2([row], AXIS_POLES, expected(row)), [])
        row["human_review"]["trait_annotation"]["pole"] = "warm"
        self.assertTrue(
            any("invalid for empathetic-detached" in error
                for error in validate_completed_review_v2([row], AXIS_POLES, expected(row)))
        )

    def test_source_family_is_checked_against_manifest_identity(self) -> None:
        row = empathetic_row()
        identity = expected(row)
        row["source_family_id"] = "human_modified"
        errors = validate_completed_review_v2([row], AXIS_POLES, identity)
        self.assertTrue(any("source_family_id was modified" in error for error in errors))

        row = empathetic_row()
        identity = expected(row)
        row["candidate_response"] = "Modified raw response"
        errors = validate_completed_review_v2([row], AXIS_POLES, identity)
        self.assertTrue(any("raw content no longer matches" in error for error in errors))

        row = empathetic_row()
        identity = expected(row)
        row["proposed_family_assignment"]["task_family_id"] = "modified_proposal"
        errors = validate_completed_review_v2([row], AXIS_POLES, identity)
        self.assertTrue(any("proposed_family_assignment was modified" in error for error in errors))

    def test_completed_decision_requires_reviewer_and_timezone(self) -> None:
        row = empathetic_row()
        row["human_review"].update(
            {
                "mapping_decision": "reject",
                "quality_flags": ["source_label_only"],
            }
        )
        errors = validate_completed_review_v2([row], AXIS_POLES, expected(row))
        self.assertTrue(any("requires reviewer_id" in error for error in errors))
        self.assertTrue(any("requires reviewed_at" in error for error in errors))
        row["human_review"].update(
            {"reviewer_id": "researcher_01", "reviewed_at": "2026-08-03T20:30:00"}
        )
        errors = validate_completed_review_v2([row], AXIS_POLES, expected(row))
        self.assertTrue(any("with timezone" in error for error in errors))

    def test_ambiguous_requires_explanatory_notes(self) -> None:
        row = empathetic_row()
        row["human_review"].update({"mapping_decision": "ambiguous", **review_metadata()})
        self.assertTrue(validate_completed_review_v2([row], AXIS_POLES, expected(row)))
        row["human_review"]["notes"] = "The response mixes warmth and empathy without a stable primary axis."
        self.assertEqual(validate_completed_review_v2([row], AXIS_POLES, expected(row)), [])

    def test_needs_rewrite_preserves_labels_but_never_exports_original(self) -> None:
        row = empathetic_row()
        row["human_review"].update(
            {
                "mapping_decision": "needs_rewrite",
                **review_metadata(),
                "trait_annotation": {"axis_id": "empathetic-detached", "pole": "empathetic"},
                "reviewed_family_assignment": {
                    **{field: None for field in family_values()},
                    "scenario_family_id": "scenario_setback",
                },
                "rewrite_notes": "Retain the scenario but replace the source wording.",
            }
        )
        self.assertEqual(validate_completed_review_v2([row], AXIS_POLES, expected(row)), [])
        self.assertEqual(reviewed_family_candidates_v2([row]), [])

    def test_reject_requires_reason_and_quality_flags_are_controlled(self) -> None:
        row = empathetic_row()
        row["human_review"]["mapping_decision"] = "reject"
        row["human_review"].update(review_metadata())
        self.assertTrue(validate_completed_review_v2([row], AXIS_POLES, expected(row)))
        row["human_review"]["quality_flags"] = ["not_a_flag"]
        errors = validate_completed_review_v2([row], AXIS_POLES, expected(row))
        self.assertTrue(any("unknown quality_flags" in error for error in errors))
        row["human_review"]["quality_flags"] = ["source_label_only"]
        self.assertEqual(validate_completed_review_v2([row], AXIS_POLES, expected(row)), [])

    def test_valid_pku_single_axis_contrast_and_family_split_conversion(self) -> None:
        row = pku_row()
        row["human_review"].update(
            {
                "mapping_decision": "accept",
                **review_metadata(),
                "response_annotations": [
                    {
                        "response_id": "response_0",
                        "behavior": "reasonable_refusal",
                        "trait_annotation": {
                            "axis_id": "boundary-preserving-over-accommodating",
                            "pole": "boundary-preserving",
                        },
                    },
                    {
                        "response_id": "response_1",
                        "behavior": "unsafe_compliance",
                        "trait_annotation": {
                            "axis_id": "boundary-preserving-over-accommodating",
                            "pole": "over-accommodating",
                        },
                    },
                ],
                "pair_contrast": {
                    "status": "valid_single_axis",
                    "axis_id": "boundary-preserving-over-accommodating",
                },
                "reviewed_family_assignment": family_values(),
            }
        )
        self.assertEqual(validate_completed_review_v2([row], AXIS_POLES, expected(row)), [])
        candidates = reviewed_family_candidates_v2([row])
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len({candidate["allocation_unit_id"] for candidate in candidates}), 1)
        unit_id = candidates[0]["allocation_unit_id"]
        records = family_split_records_v2(candidates, {unit_id: "dev"})
        self.assertEqual(len(records), 2)
        self.assertEqual({record["split"] for record in records}, {"dev"})
        self.assertTrue(all(record["assignment_status"] == "human_verified" for record in records))

    def test_pku_valid_contrast_rejects_non_opposite_poles(self) -> None:
        row = pku_row()
        row["human_review"].update(
            {
                "mapping_decision": "accept",
                **review_metadata(),
                "response_annotations": [
                    {"response_id": "response_0", "behavior": "reasonable_refusal",
                     "trait_annotation": {"axis_id": "assertive-compliant", "pole": "assertive"}},
                    {"response_id": "response_1", "behavior": "reasonable_accept",
                     "trait_annotation": {"axis_id": "assertive-compliant", "pole": "assertive"}},
                ],
                "pair_contrast": {"status": "valid_single_axis", "axis_id": "assertive-compliant"},
                "reviewed_family_assignment": family_values(),
            }
        )
        errors = validate_completed_review_v2([row], AXIS_POLES, expected(row))
        self.assertTrue(any("opposite registry poles" in error for error in errors))

    def test_schema_accepts_generated_blank_shapes_when_jsonschema_is_available(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ModuleNotFoundError:
            self.skipTest("jsonschema is not installed in dependency-free CI")
        schema = json.loads(
            (ROOT / "data/research_foundation/schemas/public_mapping_review_v0_2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertEqual(list(validator.iter_errors(empathetic_row())), [])
        self.assertEqual(list(validator.iter_errors(pku_row())), [])
        self.assertEqual(
            validate_rows_against_schema_v2(
                [empathetic_row(), pku_row()],
                ROOT / "data/research_foundation/schemas/public_mapping_review_v0_2.schema.json",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
