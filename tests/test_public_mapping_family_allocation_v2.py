from __future__ import annotations

import unittest

from scripts.build_public_mapping_family_allocation_v2 import (
    allocate_components,
    build_family_components,
    jaccard,
    normalized_text,
)


def candidate(sample_id: str, unit: str, task: str, scenario: str, template: str, semantic: str) -> dict:
    return {
        "sample_id": sample_id,
        "source_sample_id": sample_id,
        "response_id": None,
        "axis_id": "warm-cold",
        "pole": "warm",
        "allocation_unit_id": unit,
        "source_family_id": "source_a",
        "task_family_id": task,
        "scenario_family_id": scenario,
        "prompt_template_id": template,
        "semantic_cluster_id": semantic,
        "assignment_status": "human_verified",
    }


class PublicMappingFamilyAllocationV2Tests(unittest.TestCase):
    def test_shared_family_value_forms_one_component(self) -> None:
        rows = [
            candidate("a", "u1", "task_shared", "s1", "t1", "m1"),
            candidate("b", "u2", "task_shared", "s2", "t2", "m2"),
            candidate("c", "u3", "task_other", "s3", "t3", "m3"),
        ]
        components = build_family_components(rows)
        self.assertEqual(sorted(component["candidate_count"] for component in components), [1, 2])

    def test_allocation_is_deterministic_and_keeps_splits_nonempty(self) -> None:
        components = [
            {"component_id": f"c{index}", "allocation_unit_ids": [f"u{index}"], "candidate_count": count}
            for index, count in enumerate((39, 22, 18, 17, 16), start=1)
        ]
        first, counts = allocate_components(components, seed=20260803)
        second, _ = allocate_components(components, seed=20260803)
        self.assertEqual(first, second)
        self.assertTrue(all(counts[split] > 0 for split in ("train", "dev", "test")))
        self.assertEqual(sum(counts.values()), 112)

    def test_normalization_and_jaccard_are_stable(self) -> None:
        self.assertEqual(normalized_text("  Hello,  WORLD! "), "hello world")
        self.assertEqual(jaccard({("a",), ("b",)}, {("b",), ("c",)}), 1 / 3)


if __name__ == "__main__":
    unittest.main()
