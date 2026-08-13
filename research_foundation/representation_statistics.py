from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import itertools
import math
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC


@dataclass(frozen=True)
class ProjectionPair:
    pair_id: str
    positive_score: float
    negative_score: float
    family_id: str

    @property
    def difference(self) -> float:
        return float(self.positive_score - self.negative_score)


def _finite_vector(values: Sequence[float], name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains a non-finite value")
    return array


def _matrix(values: Sequence[Sequence[float]] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] == 0:
        raise ValueError(f"{name} must be a non-empty two-dimensional array")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains a non-finite value")
    return array


def paired_differences(pairs: Sequence[ProjectionPair]) -> np.ndarray:
    if not pairs:
        raise ValueError("at least one projection pair is required")
    if len({pair.pair_id for pair in pairs}) != len(pairs):
        raise ValueError("pair_id values must be unique")
    return _finite_vector([pair.difference for pair in pairs], "paired differences")


def standardized_paired_effect_size(differences: Sequence[float]) -> dict[str, Any]:
    values = _finite_vector(differences, "differences")
    mean_difference = float(values.mean())
    if len(values) < 2:
        return {
            "metric": "cohens_dz",
            "n": int(len(values)),
            "estimate": None,
            "mean_difference": mean_difference,
            "sd_difference": None,
            "reason": "fewer_than_two_pairs",
        }
    sd_difference = float(values.std(ddof=1))
    if math.isclose(sd_difference, 0.0, abs_tol=1e-15):
        return {
            "metric": "cohens_dz",
            "n": int(len(values)),
            "estimate": None,
            "mean_difference": mean_difference,
            "sd_difference": sd_difference,
            "reason": "zero_difference_variance",
        }
    return {
        "metric": "cohens_dz",
        "n": int(len(values)),
        "estimate": mean_difference / sd_difference,
        "mean_difference": mean_difference,
        "sd_difference": sd_difference,
        "reason": None,
    }


def training_threshold(pairs: Sequence[ProjectionPair]) -> float:
    if not pairs:
        raise ValueError("training pairs are required")
    positive = _finite_vector([pair.positive_score for pair in pairs], "positive scores")
    negative = _finite_vector([pair.negative_score for pair in pairs], "negative scores")
    return float((positive.mean() + negative.mean()) / 2.0)


def classification_metrics(
    pairs: Sequence[ProjectionPair], threshold: float
) -> dict[str, Any]:
    if not pairs:
        raise ValueError("evaluation pairs are required")
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    scores = np.asarray(
        [score for pair in pairs for score in (pair.positive_score, pair.negative_score)],
        dtype=np.float64,
    )
    labels = np.asarray([label for _ in pairs for label in (1, 0)], dtype=np.int64)
    predictions = (scores >= threshold).astype(np.int64)
    pairwise_correct = sum(pair.positive_score > pair.negative_score for pair in pairs)
    return {
        "sample_count": int(len(scores)),
        "pair_count": len(pairs),
        "threshold": float(threshold),
        "auroc": float(roc_auc_score(labels, scores)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "pairwise_accuracy": pairwise_correct / len(pairs),
    }


def _clustered_differences(
    differences: Sequence[float], cluster_ids: Sequence[str]
) -> dict[str, np.ndarray]:
    values = _finite_vector(differences, "differences")
    if len(values) != len(cluster_ids):
        raise ValueError("cluster_ids must align with differences")
    if any(not isinstance(cluster_id, str) or not cluster_id for cluster_id in cluster_ids):
        raise ValueError("cluster_ids must be non-empty strings")
    grouped: dict[str, list[float]] = defaultdict(list)
    for cluster_id, value in zip(cluster_ids, values, strict=True):
        grouped[cluster_id].append(float(value))
    return {cluster_id: np.asarray(items, dtype=np.float64) for cluster_id, items in grouped.items()}


def paired_cluster_bootstrap(
    differences: Sequence[float],
    cluster_ids: Sequence[str],
    *,
    iterations: int,
    seed: int,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    if iterations < 100:
        raise ValueError("bootstrap iterations must be at least 100")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    grouped = _clustered_differences(differences, cluster_ids)
    cluster_names = sorted(grouped)
    if len(cluster_names) < 2:
        return {
            "method": "cluster_bootstrap_cohens_dz",
            "iterations": iterations,
            "valid_iterations": 0,
            "cluster_count": len(cluster_names),
            "lower": None,
            "upper": None,
            "level": confidence_level,
            "reason": "fewer_than_two_clusters",
        }
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        selected = rng.integers(0, len(cluster_names), size=len(cluster_names))
        sample = np.concatenate([grouped[cluster_names[index]] for index in selected])
        effect = standardized_paired_effect_size(sample.tolist())["estimate"]
        if effect is not None and math.isfinite(effect):
            estimates.append(float(effect))
    alpha = (1.0 - confidence_level) / 2.0
    lower = float(np.quantile(estimates, alpha)) if estimates else None
    upper = float(np.quantile(estimates, 1.0 - alpha)) if estimates else None
    return {
        "method": "cluster_bootstrap_cohens_dz",
        "iterations": iterations,
        "valid_iterations": len(estimates),
        "cluster_count": len(cluster_names),
        "lower": lower,
        "upper": upper,
        "level": confidence_level,
        "reason": None if estimates else "all_resamples_have_zero_variance",
    }


def paired_cluster_permutation_test(
    differences: Sequence[float],
    cluster_ids: Sequence[str],
    *,
    iterations: int,
    seed: int,
    exact_cluster_limit: int = 16,
) -> dict[str, Any]:
    if iterations < 100:
        raise ValueError("permutation iterations must be at least 100")
    grouped = _clustered_differences(differences, cluster_ids)
    cluster_names = sorted(grouped)
    observed_signed = float(np.concatenate([grouped[name] for name in cluster_names]).mean())
    observed = abs(observed_signed)

    def statistic(signs: Sequence[int]) -> float:
        permuted = np.concatenate(
            [grouped[name] * sign for name, sign in zip(cluster_names, signs, strict=True)]
        )
        return abs(float(permuted.mean()))

    tolerance = 1e-15
    if len(cluster_names) <= exact_cluster_limit:
        all_signs = itertools.product((-1, 1), repeat=len(cluster_names))
        statistics = [statistic(signs) for signs in all_signs]
        extreme = sum(value >= observed - tolerance for value in statistics)
        p_value = extreme / len(statistics)
        return {
            "method": "exact_cluster_sign_flip",
            "alternative": "two_sided",
            "observed_mean_difference": observed_signed,
            "cluster_count": len(cluster_names),
            "permutations": len(statistics),
            "p_value": p_value,
            "seed": None,
        }
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(iterations):
        signs = rng.choice((-1, 1), size=len(cluster_names))
        extreme += statistic(signs) >= observed - tolerance
    return {
        "method": "monte_carlo_cluster_sign_flip",
        "alternative": "two_sided",
        "observed_mean_difference": observed_signed,
        "cluster_count": len(cluster_names),
        "permutations": iterations,
        "p_value": (extreme + 1) / (iterations + 1),
        "seed": seed,
    }


def analyze_projection_pairs(
    pairs: Sequence[ProjectionPair],
    *,
    threshold: float,
    bootstrap_iterations: int,
    permutation_iterations: int,
    seed: int,
) -> dict[str, Any]:
    differences = paired_differences(pairs)
    clusters = [pair.family_id for pair in pairs]
    effect = standardized_paired_effect_size(differences.tolist())
    bootstrap = paired_cluster_bootstrap(
        differences.tolist(), clusters, iterations=bootstrap_iterations, seed=seed
    )
    return {
        "effect_size": effect["estimate"],
        "effect_size_detail": effect,
        "effect_size_ci": {
            "lower": bootstrap["lower"],
            "upper": bootstrap["upper"],
            "level": bootstrap["level"],
        },
        **classification_metrics(pairs, threshold),
        "paired_bootstrap": bootstrap,
        "permutation": paired_cluster_permutation_test(
            differences.tolist(), clusters, iterations=permutation_iterations, seed=seed
        ),
    }


def l2_normalize(vector: Sequence[float] | np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float64)
    if array.ndim != 1 or not np.isfinite(array).all():
        raise ValueError("direction must be a finite one-dimensional vector")
    norm = float(np.linalg.norm(array))
    if math.isclose(norm, 0.0, abs_tol=1e-15):
        raise ValueError("zero vector cannot define a direction")
    return array / norm


def difference_of_means_direction(
    embeddings: Sequence[Sequence[float]] | np.ndarray,
    labels: Sequence[int],
) -> np.ndarray:
    matrix = _matrix(embeddings, "embeddings")
    label_array = np.asarray(labels, dtype=np.int64)
    if label_array.shape != (matrix.shape[0],) or set(label_array.tolist()) != {0, 1}:
        raise ValueError("labels must align with embeddings and contain both binary classes")
    return l2_normalize(matrix[label_array == 1].mean(axis=0) - matrix[label_array == 0].mean(axis=0))


def paired_difference_direction(
    positive_embeddings: Sequence[Sequence[float]] | np.ndarray,
    negative_embeddings: Sequence[Sequence[float]] | np.ndarray,
) -> np.ndarray:
    positive = _matrix(positive_embeddings, "positive_embeddings")
    negative = _matrix(negative_embeddings, "negative_embeddings")
    if positive.shape != negative.shape:
        raise ValueError("positive and negative embeddings must have the same shape")
    return l2_normalize((positive - negative).mean(axis=0))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    return float(np.dot(l2_normalize(left), l2_normalize(right)))


def orthogonalize_direction(
    target: Sequence[float], nuisance: Sequence[float]
) -> np.ndarray:
    target_unit = l2_normalize(target)
    nuisance_unit = l2_normalize(nuisance)
    residual = target_unit - float(np.dot(target_unit, nuisance_unit)) * nuisance_unit
    return l2_normalize(residual)


def sign_flipped_direction(target: Sequence[float]) -> np.ndarray:
    return -l2_normalize(target)


def random_isotropic_directions(dimension: int, count: int, seed: int) -> list[np.ndarray]:
    if dimension < 2:
        raise ValueError("direction dimension must be at least two")
    if count < 1:
        raise ValueError("at least one random direction is required")
    rng = np.random.default_rng(seed)
    return [l2_normalize(rng.normal(size=dimension)) for _ in range(count)]


def shuffled_label_directions(
    embeddings: Sequence[Sequence[float]] | np.ndarray,
    labels: Sequence[int],
    *,
    count: int,
    seed: int,
) -> list[np.ndarray]:
    matrix = _matrix(embeddings, "embeddings")
    label_array = np.asarray(labels, dtype=np.int64)
    if label_array.shape != (matrix.shape[0],) or set(label_array.tolist()) != {0, 1}:
        raise ValueError("labels must align with embeddings and contain both binary classes")
    if count < 1:
        raise ValueError("at least one shuffled direction is required")
    rng = np.random.default_rng(seed)
    directions = []
    attempts = 0
    while len(directions) < count:
        attempts += 1
        if attempts > count * 100:
            raise ValueError("could not construct the requested shuffled-label directions")
        shuffled = rng.permutation(label_array)
        if np.array_equal(shuffled, label_array):
            continue
        try:
            directions.append(difference_of_means_direction(matrix, shuffled.tolist()))
        except ValueError as exc:
            if "zero vector" not in str(exc):
                raise
    return directions


def project_embeddings(
    embeddings: Sequence[Sequence[float]] | np.ndarray, direction: Sequence[float]
) -> np.ndarray:
    matrix = _matrix(embeddings, "embeddings")
    unit = l2_normalize(direction)
    if matrix.shape[1] != len(unit):
        raise ValueError("embedding and direction dimensions do not match")
    return matrix @ unit


def empirical_null_comparison(target_value: float, null_values: Sequence[float]) -> dict[str, Any]:
    if not math.isfinite(target_value):
        raise ValueError("target_value must be finite")
    null = _finite_vector(null_values, "null_values")
    extreme = int(np.sum(np.abs(null) >= abs(target_value)))
    percentile = float(np.mean(null < target_value))
    return {
        "target_value": float(target_value),
        "null_count": int(len(null)),
        "null_mean": float(null.mean()),
        "null_sd": float(null.std(ddof=1)) if len(null) > 1 else None,
        "two_sided_empirical_p": (extreme + 1) / (len(null) + 1),
        "target_percentile": percentile,
    }


def _binary_labels(labels: Sequence[int], expected_length: int, name: str) -> np.ndarray:
    array = np.asarray(labels, dtype=np.int64)
    if array.shape != (expected_length,) or set(array.tolist()) != {0, 1}:
        raise ValueError(f"{name} must align with rows and contain both binary classes")
    return array


def fit_linear_probe(
    train_embeddings: Sequence[Sequence[float]] | np.ndarray,
    train_labels: Sequence[int],
    eval_embeddings: Sequence[Sequence[float]] | np.ndarray,
    eval_labels: Sequence[int],
    *,
    probe_id: str,
    regularization_c: float,
    seed: int,
) -> dict[str, Any]:
    train = _matrix(train_embeddings, "train_embeddings")
    evaluation = _matrix(eval_embeddings, "eval_embeddings")
    if train.shape[1] != evaluation.shape[1]:
        raise ValueError("train and evaluation embedding dimensions differ")
    train_y = _binary_labels(train_labels, train.shape[0], "train_labels")
    eval_y = _binary_labels(eval_labels, evaluation.shape[0], "eval_labels")
    if regularization_c <= 0:
        raise ValueError("regularization_c must be positive")
    if probe_id == "l2_logistic_regression":
        estimator = LogisticRegression(
            C=regularization_c,
            solver="liblinear",
            random_state=seed,
        )
    elif probe_id == "linear_svm":
        estimator = LinearSVC(C=regularization_c, random_state=seed)
    else:
        raise ValueError(f"unsupported probe_id: {probe_id}")
    pipeline = make_pipeline(StandardScaler(), estimator)
    pipeline.fit(train, train_y)
    scores = np.asarray(pipeline.decision_function(evaluation), dtype=np.float64)
    predictions = np.asarray(pipeline.predict(evaluation), dtype=np.int64)
    return {
        "probe_id": probe_id,
        "regularization_c": float(regularization_c),
        "seed": seed,
        "train_count": int(train.shape[0]),
        "eval_count": int(evaluation.shape[0]),
        "auroc": float(roc_auc_score(eval_y, scores)),
        "balanced_accuracy": float(balanced_accuracy_score(eval_y, predictions)),
    }


def random_label_probe_selectivity(
    train_embeddings: Sequence[Sequence[float]] | np.ndarray,
    train_labels: Sequence[int],
    eval_embeddings: Sequence[Sequence[float]] | np.ndarray,
    eval_labels: Sequence[int],
    *,
    probe_id: str,
    regularization_c: float,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    if draws < 20:
        raise ValueError("random-label selectivity requires at least 20 draws")
    train = _matrix(train_embeddings, "train_embeddings")
    train_y = _binary_labels(train_labels, train.shape[0], "train_labels")
    real = fit_linear_probe(
        train,
        train_y.tolist(),
        eval_embeddings,
        eval_labels,
        probe_id=probe_id,
        regularization_c=regularization_c,
        seed=seed,
    )
    rng = np.random.default_rng(seed)
    null_balanced_accuracy = []
    null_auroc = []
    for draw in range(draws):
        shuffled = rng.permutation(train_y)
        while np.array_equal(shuffled, train_y):
            shuffled = rng.permutation(train_y)
        result = fit_linear_probe(
            train,
            shuffled.tolist(),
            eval_embeddings,
            eval_labels,
            probe_id=probe_id,
            regularization_c=regularization_c,
            seed=seed + draw + 1,
        )
        null_balanced_accuracy.append(result["balanced_accuracy"])
        null_auroc.append(result["auroc"])
    balanced_null = np.asarray(null_balanced_accuracy, dtype=np.float64)
    auroc_null = np.asarray(null_auroc, dtype=np.float64)
    return {
        "probe_id": probe_id,
        "draws": draws,
        "seed": seed,
        "real": real,
        "random_label_null": {
            "balanced_accuracy": null_balanced_accuracy,
            "auroc": null_auroc,
        },
        "selectivity": {
            "balanced_accuracy_delta": real["balanced_accuracy"] - float(balanced_null.mean()),
            "auroc_delta": real["auroc"] - float(auroc_null.mean()),
            "balanced_accuracy_empirical_p": (
                int(np.sum(balanced_null >= real["balanced_accuracy"])) + 1
            ) / (draws + 1),
            "auroc_empirical_p": (
                int(np.sum(auroc_null >= real["auroc"])) + 1
            ) / (draws + 1),
        },
    }


def evaluate_named_directions(
    embeddings: Sequence[Sequence[float]] | np.ndarray,
    labels: Sequence[int],
    directions: Mapping[str, Sequence[float]],
) -> dict[str, dict[str, float]]:
    matrix = _matrix(embeddings, "embeddings")
    label_array = _binary_labels(labels, matrix.shape[0], "labels")
    results = {}
    for control_id, direction in directions.items():
        scores = project_embeddings(matrix, direction)
        results[control_id] = {
            "auroc": float(roc_auc_score(label_array, scores)),
            "mean_positive_projection": float(scores[label_array == 1].mean()),
            "mean_negative_projection": float(scores[label_array == 0].mean()),
            "projection_margin": float(
                scores[label_array == 1].mean() - scores[label_array == 0].mean()
            ),
        }
    return results
