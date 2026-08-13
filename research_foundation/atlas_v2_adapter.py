from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any, Iterable, Sequence

import jsonschema
import numpy as np

from research_foundation.representation_freeze import (
    canonical_content_sha256,
    stable_digest,
)
from research_foundation.representation_statistics import (
    ProjectionPair,
    analyze_projection_pairs,
    cosine_similarity,
    difference_of_means_direction,
    empirical_null_comparison,
    evaluate_named_directions,
    fit_linear_probe,
    paired_difference_direction,
    project_embeddings,
    random_isotropic_directions,
    random_label_probe_selectivity,
    shuffled_label_directions,
    sign_flipped_direction,
    training_threshold,
)


DATASET_MANIFEST_PATH = (
    "data/research_foundation/manifests/representation_family_split_v2_1.json"
)
ANALYSIS_PLAN_PATH = "configs/research/representation_atlas_v2_analysis_plan_v0_1.json"
RUNTIME_CONFIG_PATH = "configs/research/representation_atlas_v2_runtime_v0_1.json"
ACTIVATION_SCHEMA_PATH = (
    "data/research_foundation/schemas/atlas_v2_activation_artifact_v0_1.schema.json"
)
SELECTION_LOCK_SCHEMA_PATH = (
    "data/research_foundation/schemas/atlas_v2_selection_lock_v0_1.schema.json"
)
TEST_ACCESS_SCHEMA_PATH = (
    "data/research_foundation/schemas/atlas_v2_test_access_event_v0_1.schema.json"
)
POSITIVE_POLE = "boundary-preserving"
NEGATIVE_POLE = "over-accommodating"
REQUIRED_CONTROL_IDS = (
    "orthogonalized_target_direction",
    "random_isotropic_direction",
    "shuffled_label_direction",
    "sign_flipped_target_direction",
    "surface_style_direction",
    "unrelated_trait_direction",
)


@dataclass(frozen=True)
class ActivationArtifact:
    metadata_path: Path
    metadata: dict[str, Any]
    embeddings: np.ndarray
    dataset_manifest: dict[str, Any]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_schema(instance: dict[str, Any], schema_path: Path) -> None:
    schema = read_json(schema_path)
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(instance)


def _resolve_local_array_path(root: Path, relative_path: str) -> Path:
    _validate_local_artifact_relative_path(relative_path)
    candidate = (root / relative_path).resolve()
    allowed_root = (root / "results/local_artifacts").resolve()
    if candidate != allowed_root and allowed_root not in candidate.parents:
        raise ValueError("activation array must remain under results/local_artifacts")
    if not candidate.is_file():
        raise ValueError(f"activation array does not exist: {relative_path}")
    return candidate


def _validate_local_artifact_relative_path(relative_path: str) -> None:
    parsed = PurePosixPath(relative_path)
    if (
        parsed.is_absolute()
        or ".." in parsed.parts
        or not relative_path.startswith("results/local_artifacts/")
        or parsed.as_posix() != relative_path
    ):
        raise ValueError("artifact path must be a normalized path under results/local_artifacts")


def _dataset_response_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for pair in manifest["records"]:
        family_id = f"{pair['task_family_id']}::{pair['scenario_family_id']}"
        for response in pair["responses"]:
            sample_id = response["sample_id"]
            if sample_id in index:
                raise ValueError(f"duplicate sample in dataset manifest: {sample_id}")
            index[sample_id] = {
                "pair_id": pair["pair_id"],
                "split": pair["split"],
                "pole": response["pole"],
                "family_id": family_id,
            }
    return index


def load_activation_artifact(
    root: Path,
    metadata_path: Path,
    *,
    allowed_splits: Iterable[str],
    test_access_event: dict[str, Any] | None = None,
) -> ActivationArtifact:
    root = root.resolve()
    metadata_path = metadata_path.resolve()
    metadata = read_json(metadata_path)
    validate_schema(metadata, root / ACTIVATION_SCHEMA_PATH)
    allowed = set(allowed_splits)
    observed_splits = set(metadata["splits"])
    if not observed_splits <= allowed:
        raise ValueError(
            f"activation artifact contains unauthorized splits: {sorted(observed_splits - allowed)}"
        )
    if "test" in observed_splits:
        if observed_splits != {"test"}:
            raise ValueError("test activations must be isolated in a test-only artifact")
        if test_access_event is None:
            raise ValueError("test activation access requires a recorded test-opening event")
        validate_schema(test_access_event, root / TEST_ACCESS_SCHEMA_PATH)
        if test_access_event["dataset_manifest_sha256"] != metadata["dataset"]["manifest_sha256"]:
            raise ValueError("test-opening event dataset hash does not match activation metadata")
        if test_access_event["model"] != metadata["model"]:
            raise ValueError("test-opening event model does not match activation metadata")
        if test_access_event["representation_spec"] != metadata["representation_spec"]:
            raise ValueError("test-opening event representation specification mismatch")
        if test_access_event["planned_test_activation_path"] != metadata["array_artifact"]["path"]:
            raise ValueError("test-opening event planned path does not match activation metadata")
    dataset_path = root / metadata["dataset"]["manifest_path"]
    dataset_manifest = read_json(dataset_path)
    dataset_sha = canonical_content_sha256(dataset_manifest)
    if metadata["dataset"]["manifest_sha256"] != dataset_sha:
        raise ValueError("activation metadata dataset hash mismatch")
    analysis_plan = read_json(root / metadata["analysis_plan"]["path"])
    if metadata["analysis_plan"]["sha256"] != canonical_content_sha256(analysis_plan):
        raise ValueError("activation metadata analysis-plan hash mismatch")
    runtime_config = read_json(root / metadata["runtime_config"]["path"])
    if metadata["runtime_config"]["sha256"] != canonical_content_sha256(runtime_config):
        raise ValueError("activation metadata runtime-config hash mismatch")
    array_path = _resolve_local_array_path(root, metadata["array_artifact"]["path"])
    if metadata["array_artifact"]["sha256"] != file_sha256(array_path):
        raise ValueError("activation array hash mismatch")
    with np.load(array_path, allow_pickle=False) as payload:
        key = metadata["array_artifact"]["embedding_key"]
        if key not in payload.files:
            raise ValueError(f"activation array is missing key: {key}")
        embeddings = np.asarray(payload[key])
    spec = metadata["representation_spec"]
    if embeddings.ndim != 2:
        raise ValueError("embeddings must be a two-dimensional array")
    if embeddings.shape != (len(metadata["records"]), spec["dimension"]):
        raise ValueError("embedding shape does not match activation metadata")
    if str(embeddings.dtype) != spec["array_dtype"]:
        raise ValueError("embedding dtype does not match activation metadata")
    if not np.isfinite(embeddings).all():
        raise ValueError("embeddings contain a non-finite value")
    records = metadata["records"]
    row_indices = [record["row_index"] for record in records]
    if sorted(row_indices) != list(range(len(records))):
        raise ValueError("activation row_index values must cover every row exactly once")
    if len({record["sample_id"] for record in records}) != len(records):
        raise ValueError("activation sample_id values must be unique")
    dataset_index = _dataset_response_index(dataset_manifest)
    expected_sample_ids = {
        sample_id
        for sample_id, record in dataset_index.items()
        if record["split"] in observed_splits
    }
    observed_sample_ids = {record["sample_id"] for record in records}
    if observed_sample_ids != expected_sample_ids:
        missing = sorted(expected_sample_ids - observed_sample_ids)
        extra = sorted(observed_sample_ids - expected_sample_ids)
        raise ValueError(
            f"activation sample coverage mismatch; missing={missing[:3]} extra={extra[:3]}"
        )
    for record in records:
        expected = dataset_index.get(record["sample_id"])
        if expected is None:
            raise ValueError(f"unknown activation sample_id: {record['sample_id']}")
        for field in ("pair_id", "split", "pole"):
            if record[field] != expected[field]:
                raise ValueError(
                    f"{record['sample_id']}: activation {field} does not match frozen dataset"
                )
    return ActivationArtifact(metadata_path, metadata, embeddings, dataset_manifest)


def _record_rows(artifact: ActivationArtifact) -> dict[str, tuple[dict[str, Any], np.ndarray]]:
    return {
        record["sample_id"]: (record, artifact.embeddings[record["row_index"]])
        for record in artifact.metadata["records"]
    }


def split_embeddings(
    artifact: ActivationArtifact, split: str
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rows = _record_rows(artifact)
    selected = [
        (record, embedding)
        for record, embedding in rows.values()
        if record["split"] == split
    ]
    if not selected:
        raise ValueError(f"activation artifact does not contain split: {split}")
    embeddings = np.stack([embedding for _, embedding in selected])
    labels = np.asarray(
        [1 if record["pole"] == POSITIVE_POLE else 0 for record, _ in selected],
        dtype=np.int64,
    )
    sample_ids = [record["sample_id"] for record, _ in selected]
    return embeddings, labels, sample_ids


def projection_pairs_for_split(
    artifact: ActivationArtifact, direction: Sequence[float], split: str
) -> list[ProjectionPair]:
    dataset_pairs = {
        pair["pair_id"]: pair
        for pair in artifact.dataset_manifest["records"]
        if pair["split"] == split
    }
    rows = _record_rows(artifact)
    result = []
    for pair_id, pair in sorted(dataset_pairs.items()):
        by_pole = {response["pole"]: response["sample_id"] for response in pair["responses"]}
        if set(by_pole) != {POSITIVE_POLE, NEGATIVE_POLE}:
            raise ValueError(f"{pair_id}: frozen pair is not opposite-pole complete")
        try:
            positive = rows[by_pole[POSITIVE_POLE]][1]
            negative = rows[by_pole[NEGATIVE_POLE]][1]
        except KeyError as exc:
            raise ValueError(f"{pair_id}: activation pair is incomplete") from exc
        scores = project_embeddings(np.stack([positive, negative]), direction)
        result.append(
            ProjectionPair(
                pair_id=pair_id,
                positive_score=float(scores[0]),
                negative_score=float(scores[1]),
                family_id=f"{pair['task_family_id']}::{pair['scenario_family_id']}",
            )
        )
    return result


def build_train_dev_evidence(
    artifact: ActivationArtifact,
    *,
    seed: int,
    random_direction_count: int = 20,
    shuffled_direction_count: int = 20,
    random_label_draws: int = 20,
    bootstrap_iterations: int = 5000,
    permutation_iterations: int = 10000,
) -> dict[str, Any]:
    if set(artifact.metadata["splits"]) != {"train", "dev"}:
        raise ValueError("train/dev evidence requires exactly train and dev activation rows")
    train_x, train_y, _ = split_embeddings(artifact, "train")
    dev_x, dev_y, _ = split_embeddings(artifact, "dev")
    direction = difference_of_means_direction(train_x, train_y.tolist())
    rows = _record_rows(artifact)
    positive_train = []
    negative_train = []
    for pair in artifact.dataset_manifest["records"]:
        if pair["split"] != "train":
            continue
        by_pole = {response["pole"]: response["sample_id"] for response in pair["responses"]}
        positive_train.append(rows[by_pole[POSITIVE_POLE]][1])
        negative_train.append(rows[by_pole[NEGATIVE_POLE]][1])
    paired_direction = paired_difference_direction(
        np.stack(positive_train), np.stack(negative_train)
    )
    train_pairs = projection_pairs_for_split(artifact, direction, "train")
    dev_pairs = projection_pairs_for_split(artifact, direction, "dev")
    threshold = training_threshold(train_pairs)
    dev_analysis = analyze_projection_pairs(
        dev_pairs,
        threshold=threshold,
        bootstrap_iterations=bootstrap_iterations,
        permutation_iterations=permutation_iterations,
        seed=seed,
    )
    random_directions = random_isotropic_directions(
        train_x.shape[1], random_direction_count, seed=seed + 1
    )
    shuffled_directions = shuffled_label_directions(
        train_x,
        train_y.tolist(),
        count=shuffled_direction_count,
        seed=seed + 2,
    )
    random_metrics = [
        evaluate_named_directions(dev_x, dev_y.tolist(), {"random": item})["random"]
        for item in random_directions
    ]
    shuffled_metrics = [
        evaluate_named_directions(dev_x, dev_y.tolist(), {"shuffled": item})["shuffled"]
        for item in shuffled_directions
    ]
    sign_flip_metric = evaluate_named_directions(
        dev_x,
        dev_y.tolist(),
        {"sign_flipped_target_direction": sign_flipped_direction(direction)},
    )["sign_flipped_target_direction"]
    logistic = fit_linear_probe(
        train_x,
        train_y.tolist(),
        dev_x,
        dev_y.tolist(),
        probe_id="l2_logistic_regression",
        regularization_c=1.0,
        seed=seed + 3,
    )
    svm = fit_linear_probe(
        train_x,
        train_y.tolist(),
        dev_x,
        dev_y.tolist(),
        probe_id="linear_svm",
        regularization_c=1.0,
        seed=seed + 4,
    )
    selectivity = random_label_probe_selectivity(
        train_x,
        train_y.tolist(),
        dev_x,
        dev_y.tolist(),
        probe_id="l2_logistic_regression",
        regularization_c=1.0,
        draws=random_label_draws,
        seed=seed + 5,
    )
    return {
        "evidence_scope": "train_dev_only",
        "representation_spec": artifact.metadata["representation_spec"],
        "direction": direction.tolist(),
        "direction_equivalence_cosine": cosine_similarity(direction, paired_direction),
        "threshold": threshold,
        "dev_analysis": dev_analysis,
        "null_distributions": {
            "random_isotropic_direction": random_metrics,
            "shuffled_label_direction": shuffled_metrics,
        },
        "null_comparisons": {
            "random_isotropic_auroc": empirical_null_comparison(
                dev_analysis["auroc"], [item["auroc"] for item in random_metrics]
            ),
            "shuffled_label_auroc": empirical_null_comparison(
                dev_analysis["auroc"], [item["auroc"] for item in shuffled_metrics]
            ),
        },
        "available_controls": {
            "sign_flipped_target_direction": sign_flip_metric,
        },
        "probes": {
            "l2_logistic_regression": logistic,
            "linear_svm": svm,
            "random_label_selectivity": selectivity,
        },
        "required_external_controls_not_fabricated": [
            "orthogonalized_target_direction",
            "surface_style_direction",
            "unrelated_trait_direction",
        ],
        "test_opened": False,
        "claim_boundary": (
            "This evidence uses train/dev activations only. It cannot be reported as held-out test "
            "evidence and does not establish causal steering."
        ),
    }


def create_selection_lock(
    root: Path,
    artifact: ActivationArtifact,
    *,
    activation_metadata_relative_path: str,
    candidate_results_sha256: str,
    control_plan_path: str,
    control_plan_sha256: str,
    control_results_path: str,
    control_results_sha256: str,
    selected_threshold: float,
    probe_regularization_c: float,
    completed_control_ids: Sequence[str],
    locked_at: str,
) -> dict[str, Any]:
    if set(artifact.metadata["splits"]) != {"train", "dev"}:
        raise ValueError("selection lock can only be created from train/dev activations")
    if tuple(sorted(completed_control_ids)) != REQUIRED_CONTROL_IDS:
        raise ValueError("selection lock requires the complete frozen control registry")
    if re.fullmatch(r"[a-f0-9]{64}", candidate_results_sha256) is None:
        raise ValueError("candidate_results_sha256 must be a SHA-256 digest")
    for name, digest in (
        ("control_plan_sha256", control_plan_sha256),
        ("control_results_sha256", control_results_sha256),
    ):
        if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError(f"{name} must be a SHA-256 digest")
    if not math.isfinite(selected_threshold) or not math.isfinite(probe_regularization_c):
        raise ValueError("selected threshold and probe regularization must be finite")
    if probe_regularization_c <= 0:
        raise ValueError("probe regularization must be positive")
    _validate_local_artifact_relative_path(activation_metadata_relative_path)
    _validate_local_artifact_relative_path(control_results_path)
    plan = read_json(root / ANALYSIS_PLAN_PATH)
    spec = artifact.metadata["representation_spec"]
    lock = {
        "selection_lock_version": "atlas_v2_selection_lock_v0_1",
        "locked_at": locked_at,
        "dataset_manifest_sha256": canonical_content_sha256(artifact.dataset_manifest),
        "analysis_plan_sha256": canonical_content_sha256(plan),
        "activation_metadata_path": activation_metadata_relative_path,
        "activation_metadata_sha256": canonical_content_sha256(artifact.metadata),
        "selection_source_splits": ["train", "dev"],
        "selected_specification": {
            "layer": spec["layer"],
            "pooling": spec["pooling"],
            "threshold": float(selected_threshold),
            "probe_regularization_c": float(probe_regularization_c),
            "direction_method": "difference_of_means",
        },
        "candidate_results_sha256": candidate_results_sha256,
        "all_candidates_reported": True,
        "control_plan_path": control_plan_path,
        "control_plan_sha256": control_plan_sha256,
        "control_results_path": control_results_path,
        "control_results_sha256": control_results_sha256,
        "control_gate_status": "pass",
        "control_registry_complete": list(REQUIRED_CONTROL_IDS),
        "test_opening_status": "locked_not_opened",
        "claim_boundary": (
            "This lock records train/dev-only selection. It does not open test, authorize a model "
            "run, or establish representation evidence."
        ),
    }
    validate_schema(lock, root / SELECTION_LOCK_SCHEMA_PATH)
    return lock


def build_test_access_event(
    root: Path,
    selection_lock: dict[str, Any],
    *,
    selection_lock_path: str,
    planned_test_activation_path: str,
    model: dict[str, Any],
    representation_spec: dict[str, Any],
    prior_events: Sequence[dict[str, Any]],
    opened_at: str,
    operator_id: str,
) -> dict[str, Any]:
    validate_schema(selection_lock, root / SELECTION_LOCK_SCHEMA_PATH)
    if prior_events:
        raise ValueError("frozen test has already been opened; a second opening is forbidden")
    selected = selection_lock["selected_specification"]
    if (representation_spec["layer"], representation_spec["pooling"]) != (
        selected["layer"],
        selected["pooling"],
    ):
        raise ValueError("planned test representation specification differs from selection lock")
    _validate_local_artifact_relative_path(planned_test_activation_path)
    lock_sha = canonical_content_sha256(selection_lock)
    event = {
        "event_version": "atlas_v2_test_access_event_v0_1",
        "event_id": "testopen_"
        + stable_digest(lock_sha, planned_test_activation_path, opened_at, operator_id),
        "opened_at": opened_at,
        "operator_id": operator_id,
        "dataset_manifest_sha256": selection_lock["dataset_manifest_sha256"],
        "selection_lock_path": selection_lock_path,
        "selection_lock_sha256": lock_sha,
        "planned_test_activation_path": planned_test_activation_path,
        "model": model,
        "representation_spec": representation_spec,
        "opening_reason": "single_confirmatory_opening_after_train_dev_lock",
        "prior_opening_count": 0,
        "irreversible_warning_acknowledged": True,
        "claim_boundary": (
            "This event must be recorded before test activation extraction or analysis. It does "
            "not itself run a model or establish a positive result."
        ),
    }
    validate_schema(event, root / TEST_ACCESS_SCHEMA_PATH)
    return event
