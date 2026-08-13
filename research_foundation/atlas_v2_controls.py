from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from research_foundation.atlas_v2_adapter import file_sha256, read_json, validate_schema
from research_foundation.atlas_v2_extraction import FrozenTextRow, _flat_token_ids
from research_foundation.representation_statistics import l2_normalize


CONTROL_PLAN_PATH = "configs/research/representation_atlas_v2_control_plan_v0_1.json"
CONTROL_PLAN_SCHEMA_PATH = "data/research_foundation/schemas/atlas_v2_control_plan_v0_1.schema.json"
CONTROL_ROOT = "results/local_artifacts/research_foundation/atlas_v2/controls"


def load_control_plan(root: Path) -> dict[str, Any]:
    plan = read_json(root / CONTROL_PLAN_PATH)
    validate_schema(plan, root / CONTROL_PLAN_SCHEMA_PATH)
    summary = read_json(root / plan["candidate_summary"]["path"])
    from research_foundation.representation_freeze import canonical_content_sha256

    if canonical_content_sha256(summary) != plan["candidate_summary"]["sha256"]:
        raise ValueError("control plan candidate-summary hash mismatch")
    source_path = root / plan["unrelated_control"]["source_path"]
    if file_sha256(source_path) != plan["unrelated_control"]["source_sha256"]:
        raise ValueError("control plan unrelated-source hash mismatch")
    return plan


def load_unrelated_train_rows(root: Path, plan: dict[str, Any]) -> list[FrozenTextRow]:
    source_path = root / plan["unrelated_control"]["source_path"]
    records = [
        json.loads(line)
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [
        row
        for row in records
        if row.get("axis_id") == plan["unrelated_control"]["axis_id"]
        and row.get("split") == plan["unrelated_control"]["fit_split"]
    ]
    pair_ids = {row["pair_id"] for row in selected}
    if len(pair_ids) != plan["unrelated_control"]["pair_count"]:
        raise ValueError("unrelated control pair count differs from frozen plan")
    roles = [row["positive_negative_pair_role"] for row in selected]
    if roles.count("positive") != roles.count("negative") or len(selected) != 2 * len(pair_ids):
        raise ValueError("unrelated control train pairs are incomplete or imbalanced")
    if any(row.get("quality_flags") != ["approved"] for row in selected):
        raise ValueError("unrelated control contains a non-approved legacy row")
    return [
        FrozenTextRow(
            sample_id=row["sample_id"],
            pair_id=row["pair_id"],
            split="control_train",
            pole=row["positive_negative_pair_role"],
            prompt=plan["unrelated_control"]["input_prompt"],
            response=row["text"],
        )
        for row in selected
    ]


def response_token_counts(tokenizer: Any, rows: Sequence[FrozenTextRow]) -> dict[str, int]:
    counts = {}
    for row in rows:
        token_ids = _flat_token_ids(
            tokenizer(row.response, add_special_tokens=False), "surface response"
        )
        if not token_ids:
            raise ValueError(f"{row.sample_id}: response has no tokens")
        counts[row.sample_id] = len(token_ids)
    return counts


def continuous_feature_direction(
    embeddings: np.ndarray, feature_values: Sequence[float]
) -> np.ndarray:
    matrix = np.asarray(embeddings, dtype=np.float64)
    values = np.asarray(feature_values, dtype=np.float64)
    if matrix.ndim != 2 or values.shape != (matrix.shape[0],):
        raise ValueError("surface feature values must align with activation rows")
    centered_values = values - values.mean()
    if np.isclose(np.linalg.norm(centered_values), 0.0):
        raise ValueError("surface feature has zero variance")
    centered_matrix = matrix - matrix.mean(axis=0, keepdims=True)
    return l2_normalize(centered_matrix.T @ centered_values)


def control_array_key(layer: int, pooling: str) -> str:
    return f"layer_{layer}__{pooling}"


def write_control_artifact(
    root: Path,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    rows: Sequence[FrozenTextRow],
    matrices: dict[tuple[int, str], np.ndarray],
    target_token_counts: dict[str, int],
) -> Path:
    from research_foundation.representation_freeze import canonical_content_sha256

    output_root = root / CONTROL_ROOT
    output_root.mkdir(parents=True, exist_ok=True)
    array_path = output_root / "legacy_calm_agitated_train_activations_v0_1.npz"
    np.savez_compressed(
        array_path,
        **{control_array_key(*key): value for key, value in matrices.items()},
    )
    features_path = output_root / "target_response_token_counts_v0_1.json"
    features_payload = {
        "feature_version": "atlas_v2_surface_feature_v0_1",
        "feature": "response_token_count",
        "records": [
            {"sample_id": sample_id, "value": value}
            for sample_id, value in sorted(target_token_counts.items())
        ],
        "raw_text_persisted": False,
    }
    features_path.write_text(
        json.dumps(features_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    metadata = {
        "artifact_version": "atlas_v2_control_artifact_v0_1",
        "control_plan_path": CONTROL_PLAN_PATH,
        "control_plan_sha256": canonical_content_sha256(plan),
        "runtime_config_sha256": canonical_content_sha256(runtime),
        "model": runtime["model"],
        "source_path": plan["unrelated_control"]["source_path"],
        "source_sha256": plan["unrelated_control"]["source_sha256"],
        "axis_id": plan["unrelated_control"]["axis_id"],
        "fit_split": "train",
        "records": [
            {
                "sample_id": row.sample_id,
                "pair_id": row.pair_id,
                "role": row.pole,
                "row_index": index,
            }
            for index, row in enumerate(rows)
        ],
        "array_path": array_path.relative_to(root).as_posix(),
        "array_sha256": file_sha256(array_path),
        "array_keys": sorted(control_array_key(*key) for key in matrices),
        "surface_features_path": features_path.relative_to(root).as_posix(),
        "surface_features_sha256": file_sha256(features_path),
        "raw_text_persisted": False,
        "claim_boundary": (
            "Legacy template-dominated calm-agitated activations are an unrelated confound "
            "stress-test only and are not validated Trait representation evidence."
        ),
    }
    metadata_path = output_root / "control_artifact_v0_1.metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata_path


def load_control_artifact(root: Path, metadata_path: Path) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, int]]:
    metadata = read_json(metadata_path)
    if metadata.get("artifact_version") != "atlas_v2_control_artifact_v0_1":
        raise ValueError("wrong control artifact version")
    plan = load_control_plan(root)
    from research_foundation.representation_freeze import canonical_content_sha256

    if metadata["control_plan_sha256"] != canonical_content_sha256(plan):
        raise ValueError("control artifact plan hash mismatch")
    array_path = root / metadata["array_path"]
    if file_sha256(array_path) != metadata["array_sha256"]:
        raise ValueError("control activation array hash mismatch")
    with np.load(array_path, allow_pickle=False) as payload:
        matrices = {key: np.asarray(payload[key]) for key in payload.files}
    if sorted(matrices) != metadata["array_keys"]:
        raise ValueError("control activation keys differ from metadata")
    feature_path = root / metadata["surface_features_path"]
    if file_sha256(feature_path) != metadata["surface_features_sha256"]:
        raise ValueError("surface feature hash mismatch")
    features = read_json(feature_path)
    counts = {record["sample_id"]: record["value"] for record in features["records"]}
    if len(counts) != len(features["records"]):
        raise ValueError("duplicate surface feature sample ID")
    return metadata, matrices, counts
