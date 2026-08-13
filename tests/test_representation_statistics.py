from __future__ import annotations

import json
from pathlib import Path
import unittest

import jsonschema
import numpy as np

from research_foundation.representation_statistics import (
    ProjectionPair,
    analyze_projection_pairs,
    classification_metrics,
    cosine_similarity,
    difference_of_means_direction,
    empirical_null_comparison,
    evaluate_named_directions,
    fit_linear_probe,
    orthogonalize_direction,
    paired_cluster_bootstrap,
    paired_cluster_permutation_test,
    paired_difference_direction,
    random_isotropic_directions,
    random_label_probe_selectivity,
    sign_flipped_direction,
    shuffled_label_directions,
    standardized_paired_effect_size,
    training_threshold,
)


ROOT = Path(__file__).resolve().parents[1]


def projection_pairs() -> list[ProjectionPair]:
    return [
        ProjectionPair("p1", 1.4, -0.3, "family_a"),
        ProjectionPair("p2", 1.1, -0.1, "family_a"),
        ProjectionPair("p3", 0.9, -0.6, "family_b"),
        ProjectionPair("p4", 1.8, 0.2, "family_c"),
        ProjectionPair("p5", 1.0, -0.2, "family_d"),
    ]


class RepresentationStatisticsTests(unittest.TestCase):
    def test_effect_size_and_classification_metrics(self) -> None:
        effect = standardized_paired_effect_size([1.0, 2.0, 3.0])
        self.assertAlmostEqual(effect["estimate"], 2.0)
        pairs = projection_pairs()
        threshold = training_threshold(pairs)
        metrics = classification_metrics(pairs, threshold)
        self.assertEqual(metrics["auroc"], 1.0)
        self.assertEqual(metrics["balanced_accuracy"], 1.0)
        self.assertEqual(metrics["pairwise_accuracy"], 1.0)

    def test_cluster_bootstrap_is_deterministic(self) -> None:
        differences = [1.0, 1.5, 2.0, 2.5]
        clusters = ["a", "b", "c", "d"]
        first = paired_cluster_bootstrap(
            differences, clusters, iterations=500, seed=20260804
        )
        second = paired_cluster_bootstrap(
            differences, clusters, iterations=500, seed=20260804
        )
        self.assertEqual(first, second)
        self.assertGreater(first["valid_iterations"], 0)
        self.assertLess(first["lower"], first["upper"])

    def test_cluster_permutation_uses_exact_sign_flips_for_small_cluster_count(self) -> None:
        result = paired_cluster_permutation_test(
            [1.0, 1.5, 2.0], ["a", "b", "c"], iterations=1000, seed=7
        )
        self.assertEqual(result["method"], "exact_cluster_sign_flip")
        self.assertEqual(result["permutations"], 8)
        self.assertEqual(result["p_value"], 0.25)

    def test_paired_and_difference_of_means_directions_are_equivalent(self) -> None:
        positive = np.asarray([[2.0, 1.0], [3.0, 0.0], [2.0, -1.0]])
        negative = np.asarray([[-1.0, 1.0], [0.0, 0.0], [-1.0, -1.0]])
        embeddings = np.vstack([positive, negative])
        labels = [1, 1, 1, 0, 0, 0]
        dom = difference_of_means_direction(embeddings, labels)
        paired = paired_difference_direction(positive, negative)
        self.assertAlmostEqual(cosine_similarity(dom, paired), 1.0, places=12)

    def test_random_shuffled_orthogonal_and_sign_controls(self) -> None:
        random_first = random_isotropic_directions(4, 20, seed=11)
        random_second = random_isotropic_directions(4, 20, seed=11)
        self.assertEqual(len(random_first), 20)
        np.testing.assert_allclose(random_first, random_second)
        self.assertTrue(all(np.isclose(np.linalg.norm(item), 1.0) for item in random_first))

        embeddings = np.asarray([
            [2.0, 0.1], [1.5, -0.2], [1.0, 0.3], [-2.0, -0.1], [-1.5, 0.2], [-1.0, -0.3]
        ])
        shuffled_first = shuffled_label_directions(
            embeddings, [1, 1, 1, 0, 0, 0], count=20, seed=13
        )
        shuffled_second = shuffled_label_directions(
            embeddings, [1, 1, 1, 0, 0, 0], count=20, seed=13
        )
        np.testing.assert_allclose(shuffled_first, shuffled_second)

        orthogonal = orthogonalize_direction([1.0, 1.0], [1.0, 0.0])
        self.assertAlmostEqual(float(np.dot(orthogonal, [1.0, 0.0])), 0.0, places=12)
        target = difference_of_means_direction(embeddings, [1, 1, 1, 0, 0, 0])
        controls = evaluate_named_directions(
            embeddings,
            [1, 1, 1, 0, 0, 0],
            {
                "target": target,
                "sign_flipped_target_direction": sign_flipped_direction(target),
            },
        )
        self.assertEqual(controls["target"]["auroc"], 1.0)
        self.assertEqual(controls["sign_flipped_target_direction"]["auroc"], 0.0)

    def test_empirical_null_uses_finite_sample_correction(self) -> None:
        comparison = empirical_null_comparison(2.0, [-0.5, 0.0, 0.5, 1.0])
        self.assertEqual(comparison["two_sided_empirical_p"], 0.2)
        self.assertEqual(comparison["target_percentile"], 1.0)

    def test_random_label_probe_selectivity_detects_strong_linear_signal(self) -> None:
        rng = np.random.default_rng(17)
        train_labels = np.asarray([0] * 40 + [1] * 40)
        eval_labels = np.asarray([0] * 20 + [1] * 20)
        train = rng.normal(scale=0.4, size=(80, 5))
        evaluation = rng.normal(scale=0.4, size=(40, 5))
        train[:, 0] += np.where(train_labels == 1, 2.0, -2.0)
        evaluation[:, 0] += np.where(eval_labels == 1, 2.0, -2.0)
        result = random_label_probe_selectivity(
            train,
            train_labels.tolist(),
            evaluation,
            eval_labels.tolist(),
            probe_id="l2_logistic_regression",
            regularization_c=1.0,
            draws=20,
            seed=19,
        )
        self.assertEqual(result["real"]["balanced_accuracy"], 1.0)
        self.assertGreater(result["selectivity"]["balanced_accuracy_delta"], 0.3)
        self.assertLessEqual(result["selectivity"]["balanced_accuracy_empirical_p"], 2 / 21)
        svm = fit_linear_probe(
            train,
            train_labels.tolist(),
            evaluation,
            eval_labels.tolist(),
            probe_id="linear_svm",
            regularization_c=1.0,
            seed=19,
        )
        self.assertEqual(svm["balanced_accuracy"], 1.0)

    def test_projection_analysis_can_fill_frozen_axis_result_schema(self) -> None:
        pairs = projection_pairs()
        analysis = analyze_projection_pairs(
            pairs,
            threshold=0.5,
            bootstrap_iterations=500,
            permutation_iterations=1000,
            seed=23,
        )
        axis_result = {
            "axis_id": "boundary-preserving-over-accommodating",
            "split": "test",
            **analysis,
            "null_distributions": [{"control_id": "random"}, {"control_id": "shuffled"}],
            "controls": [
                {"control_id": "surface"},
                {"control_id": "unrelated"},
                {"control_id": "orthogonal"},
                {"control_id": "sign_flipped"},
            ],
            "probes": [{"probe_id": "logistic"}, {"probe_id": "linear_svm"}],
            "status": "pilot_signal",
            "limitations": ["synthetic fixture only"],
        }
        result = {
            "schema_version": "representation_atlas_v2_result_v0_1",
            "analysis_plan_version": "representation_atlas_v2_analysis_plan_v0_1",
            "dataset_manifest_sha256": "a" * 64,
            "model": {"model_id": "fixture", "revision": "fixture", "dtype": "float32", "quantization": None},
            "selection": {
                "selected_layer": 1,
                "selected_pooling": "fixture",
                "selected_threshold": 0.5,
                "selection_splits": ["train", "dev"],
                "locked_before_test": True,
            },
            "axis_results": [axis_result],
            "test_access": {
                "opened_at": "2026-08-04T00:00:00+08:00",
                "opening_reason": "single_confirmatory_opening_after_train_dev_lock",
                "access_log_sha256": "b" * 64,
            },
            "negative_results_retained": True,
            "evidence_type": "representation_evidence_only",
            "claim_boundary": "synthetic schema fixture",
        }
        schema = json.loads(
            (ROOT / "data/research_foundation/schemas/representation_atlas_v2_result.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(result)

    def test_zero_variance_effect_is_explicitly_undefined(self) -> None:
        result = standardized_paired_effect_size([1.0, 1.0, 1.0])
        self.assertIsNone(result["estimate"])
        self.assertEqual(result["reason"], "zero_difference_variance")


if __name__ == "__main__":
    unittest.main()
