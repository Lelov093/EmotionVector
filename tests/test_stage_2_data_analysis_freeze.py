from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from research_foundation.representation_freeze import (
    TARGET_AXIS,
    allocate_components,
    build_family_components,
    canonical_content_sha256,
    representation_pairs,
)


ROOT = Path(__file__).resolve().parents[1]


def review_row(status: str = "valid_single_axis") -> dict:
    pole_1 = "over-accommodating" if status == "valid_single_axis" else "boundary-preserving"
    return {
        "sample_id": "pkumap_test",
        "dataset_id": "pku_safe_rlhf",
        "source_family_id": "pku_safe_rlhf_f4b036fc_alpaca_7b",
        "content_sha256": "a" * 64,
        "prompt": "prompt",
        "response_0": "boundary response",
        "response_1": "other response",
        "human_review": {
            "mapping_decision": "accept",
            "pair_contrast": {"status": status, "axis_id": TARGET_AXIS},
            "response_annotations": [
                {
                    "response_id": "response_0",
                    "behavior": "reasonable_refusal",
                    "trait_annotation": {"axis_id": TARGET_AXIS, "pole": "boundary-preserving"},
                },
                {
                    "response_id": "response_1",
                    "behavior": "unsafe_compliance",
                    "trait_annotation": {"axis_id": TARGET_AXIS, "pole": pole_1},
                },
            ],
            "reviewed_family_assignment": {
                "task_family_id": "task",
                "scenario_family_id": "scenario",
                "prompt_template_id": "template",
                "semantic_cluster_id": "semantic",
            },
        },
    }


class Stage2DataAnalysisFreezeTests(unittest.TestCase):
    def test_only_valid_opposite_pole_pairs_are_eligible(self) -> None:
        valid = representation_pairs([review_row()], source_revision="f" * 40)
        invalid = representation_pairs([review_row("same_axis_not_opposite")], source_revision="f" * 40)
        self.assertEqual(len(valid), 1)
        self.assertEqual(invalid, [])
        self.assertEqual({item["pole"] for item in valid[0]["responses"]}, {
            "boundary-preserving", "over-accommodating"
        })
        self.assertNotIn("prompt", valid[0])

    def test_shared_family_values_form_one_component(self) -> None:
        first = representation_pairs([review_row()], source_revision="f" * 40)[0]
        second = deepcopy(first)
        second["pair_id"] = "reprpair_" + "b" * 20
        second["source_sample_id"] = "pkumap_second"
        components = build_family_components([first, second])
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["pair_count"], 2)

    def test_allocation_is_deterministic_and_preserves_heldout_minimum(self) -> None:
        components = [
            {"component_id": f"c{index}", "pair_ids": [f"p{index}_{n}" for n in range(count)], "pair_count": count}
            for index, count in enumerate((8, 7, 8, 3))
        ]
        first, counts = allocate_components(components, seed=20260804)
        second, second_counts = allocate_components(components, seed=20260804)
        self.assertEqual(first, second)
        self.assertEqual(counts, second_counts)
        self.assertEqual(sorted(counts.values()), [7, 8, 11])
        self.assertGreaterEqual(counts["dev"], 5)
        self.assertGreaterEqual(counts["test"], 5)

    def test_tracked_freeze_hashes_and_pair_invariants(self) -> None:
        manifest_path = ROOT / "data/research_foundation/manifests/representation_family_split_v2_1.json"
        freeze = json.loads((ROOT / "data/research_foundation/manifests/representation_family_split_v2_1.freeze.json").read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(canonical_content_sha256(manifest), freeze["manifest_sha256"])
        self.assertTrue(manifest["test_access_policy"]["frozen"])
        self.assertEqual(manifest["status"], "frozen_before_model_execution")
        self.assertEqual(len(manifest["records"]), 26)
        for record in manifest["records"]:
            self.assertEqual(record["contrast_status"], "valid_single_axis")
            self.assertEqual({item["pole"] for item in record["responses"]}, {
                "boundary-preserving", "over-accommodating"
            })
            self.assertNotIn("prompt", record)
            self.assertNotIn("text", record)
            self.assertFalse(any(key.startswith("_") for key in record))

    def test_analysis_plan_keeps_pilot_and_representation_boundaries(self) -> None:
        plan = json.loads((ROOT / "configs/research/representation_atlas_v2_analysis_plan_v0_1.json").read_text(encoding="utf-8"))
        self.assertFalse(plan["sample_size_gate"]["confirmatory_claim_allowed"])
        self.assertEqual(plan["selection_policy"]["test_opening_status"], "not_opened")
        self.assertIn("not causal steering", plan["evidence_target"])
        controls = {item["control_id"] for item in plan["null_and_control_registry"]}
        self.assertIn("shuffled_label_direction", controls)
        self.assertIn("sign_flipped_target_direction", controls)


if __name__ == "__main__":
    unittest.main()
