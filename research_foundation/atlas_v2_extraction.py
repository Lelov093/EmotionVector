from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from research_foundation.atlas_v2_adapter import (
    ACTIVATION_SCHEMA_PATH,
    ANALYSIS_PLAN_PATH,
    DATASET_MANIFEST_PATH,
    RUNTIME_CONFIG_PATH,
    file_sha256,
    read_json,
    validate_schema,
)
from research_foundation.public_mapping_v2 import (
    expected_identity_index,
    load_axis_poles,
    validate_completed_review_v2,
    validate_rows_against_schema_v2,
)
from research_foundation.representation_freeze import (
    canonical_content_sha256,
    content_sha256,
)


RUNTIME_SCHEMA_PATH = "data/research_foundation/schemas/atlas_v2_runtime_v0_1.schema.json"
TEST_RUNTIME_CONFIG_PATH = "configs/research/representation_atlas_v2_test_runtime_v0_1.json"
TEST_RUNTIME_SCHEMA_PATH = "data/research_foundation/schemas/atlas_v2_test_runtime_v0_1.schema.json"
MAPPING_MANIFEST_PATH = "data/research_foundation/manifests/public_mapping_pilot_v0_2.json"
MAPPING_SCHEMA_PATH = "data/research_foundation/schemas/public_mapping_review_v0_2.schema.json"
AXIS_REGISTRY_PATH = "data/trait_space/axis_registry.yaml"
ALLOWED_SPLITS = ("train", "dev")


@dataclass(frozen=True)
class FrozenTextRow:
    sample_id: str
    pair_id: str
    split: str
    pole: str
    prompt: str
    response: str


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_runtime_config(root: Path, path: Path | None = None) -> dict[str, Any]:
    runtime_path = path or root / RUNTIME_CONFIG_PATH
    runtime = read_json(runtime_path)
    validate_schema(runtime, root / RUNTIME_SCHEMA_PATH)
    return runtime


def resolve_frozen_text_rows(
    manifest: dict[str, Any],
    review_rows: Sequence[dict[str, Any]],
    *,
    allowed_splits: Sequence[str] = ALLOWED_SPLITS,
) -> list[FrozenTextRow]:
    selected_splits = tuple(allowed_splits)
    if not selected_splits or set(selected_splits) - {"train", "dev", "test"}:
        raise ValueError("allowed_splits must be a non-empty subset of train/dev/test")
    review_index = {row["sample_id"]: row for row in review_rows}
    if len(review_index) != len(review_rows):
        raise ValueError("mapping review contains duplicate sample_id values")
    resolved: list[FrozenTextRow] = []
    for pair in manifest["records"]:
        if pair["split"] not in selected_splits:
            continue
        review = review_index.get(pair["source_sample_id"])
        if review is None:
            raise ValueError(f"missing local review text for {pair['source_sample_id']}")
        if content_sha256(review["prompt"]) != pair["prompt_sha256"]:
            raise ValueError(f"{pair['pair_id']}: prompt hash mismatch")
        annotation_by_id = {
            item["response_id"]: item
            for item in review["human_review"]["response_annotations"]
        }
        response_by_id = {item["response_id"]: item for item in pair["responses"]}
        if set(annotation_by_id) != set(response_by_id):
            raise ValueError(f"{pair['pair_id']}: review response IDs differ from frozen pair")
        for response_id in ("response_0", "response_1"):
            frozen = response_by_id[response_id]
            text = review[response_id]
            annotation = annotation_by_id[response_id]
            if content_sha256(text) != frozen["content_sha256"]:
                raise ValueError(f"{frozen['sample_id']}: response hash mismatch")
            trait = annotation["trait_annotation"]
            if trait["axis_id"] != pair["axis_id"] or trait["pole"] != frozen["pole"]:
                raise ValueError(f"{frozen['sample_id']}: reviewed pole differs from frozen pair")
            resolved.append(
                FrozenTextRow(
                    sample_id=frozen["sample_id"],
                    pair_id=pair["pair_id"],
                    split=pair["split"],
                    pole=frozen["pole"],
                    prompt=review["prompt"],
                    response=text,
                )
            )
    expected = sum(
        len(pair["responses"])
        for pair in manifest["records"]
        if pair["split"] in selected_splits
    )
    if len(resolved) != expected:
        raise ValueError("resolved train/dev text coverage is incomplete")
    return resolved


def load_test_runtime_config(root: Path, path: Path | None = None) -> dict[str, Any]:
    runtime_path = path or root / TEST_RUNTIME_CONFIG_PATH
    runtime = read_json(runtime_path)
    validate_schema(runtime, root / TEST_RUNTIME_SCHEMA_PATH)
    return runtime


def load_test_text_rows(
    root: Path, review_path: Path, access_log_path: Path
) -> tuple[list[FrozenTextRow], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve frozen test text only after validating the unique access event."""
    events = read_jsonl(access_log_path)
    if len(events) != 1:
        raise ValueError("test extraction requires exactly one recorded access event")
    event = events[0]
    validate_schema(event, root / "data/research_foundation/schemas/atlas_v2_test_access_event_v0_1.schema.json")
    runtime = load_test_runtime_config(root)
    manifest = read_json(root / DATASET_MANIFEST_PATH)
    if canonical_content_sha256(manifest) != event["dataset_manifest_sha256"]:
        raise ValueError("test access event dataset hash differs from frozen manifest")
    expected_model = {
        "model_id": runtime["model"]["model_id"],
        "revision": runtime["model"]["revision"],
        "dtype": runtime["model"]["load_dtype"],
        "quantization": runtime["model"]["quantization"],
    }
    if event["model"] != expected_model:
        raise ValueError("test access event model differs from frozen test runtime")
    if event["representation_spec"] != runtime["representation_specification"]:
        raise ValueError("test access event representation differs from frozen test runtime")
    if event["planned_test_activation_path"] != runtime["artifact_policy"]["array_path"]:
        raise ValueError("test access event path differs from frozen test runtime")

    reviews = read_jsonl(review_path)
    schema_errors = validate_rows_against_schema_v2(reviews, root / MAPPING_SCHEMA_PATH)
    mapping_manifest = read_json(root / MAPPING_MANIFEST_PATH)
    expected = {
        sample_id: identity
        for sample_id, identity in expected_identity_index(mapping_manifest).items()
        if identity.get("dataset_id") == "pku_safe_rlhf"
    }
    review_errors = validate_completed_review_v2(
        reviews,
        load_axis_poles(root / AXIS_REGISTRY_PATH),
        expected,
    )
    errors = schema_errors + review_errors
    if errors:
        raise ValueError(f"local mapping review failed validation: {'; '.join(errors[:5])}")
    rows = resolve_frozen_text_rows(manifest, reviews, allowed_splits=("test",))
    return rows, manifest, runtime, event


def load_train_dev_text_rows(
    root: Path, review_path: Path
) -> tuple[list[FrozenTextRow], dict[str, Any], dict[str, Any]]:
    runtime = load_runtime_config(root)
    if runtime["execution"]["allowed_splits"] != list(ALLOWED_SPLITS):
        raise ValueError("runtime is not frozen to train/dev-only extraction")
    reviews = read_jsonl(review_path)
    schema_errors = validate_rows_against_schema_v2(reviews, root / MAPPING_SCHEMA_PATH)
    mapping_manifest = read_json(root / MAPPING_MANIFEST_PATH)
    expected = {
        sample_id: identity
        for sample_id, identity in expected_identity_index(mapping_manifest).items()
        if identity.get("dataset_id") == "pku_safe_rlhf"
    }
    review_errors = validate_completed_review_v2(
        reviews,
        load_axis_poles(root / AXIS_REGISTRY_PATH),
        expected,
    )
    errors = schema_errors + review_errors
    if errors:
        raise ValueError(f"local mapping review failed validation: {'; '.join(errors[:5])}")
    manifest = read_json(root / DATASET_MANIFEST_PATH)
    rows = resolve_frozen_text_rows(manifest, reviews)
    return rows, manifest, runtime


def response_input_ids(
    tokenizer: Any, prompt: str, response: str, *, max_sequence_tokens: int
) -> tuple[list[int], int]:
    prefix_payload = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=True,
        add_generation_prompt=True,
    )
    prefix_ids = _flat_token_ids(prefix_payload, "chat-template prefix")
    response_ids = _flat_token_ids(
        tokenizer(response, add_special_tokens=False), "response"
    )
    if not prefix_ids or not response_ids:
        raise ValueError("prompt prefix and response must each produce at least one token")
    input_ids = list(prefix_ids) + list(response_ids)
    if len(input_ids) > max_sequence_tokens:
        raise ValueError(
            f"input has {len(input_ids)} tokens and exceeds frozen limit {max_sequence_tokens}; "
            "truncation is forbidden"
        )
    return input_ids, len(prefix_ids)


def _flat_token_ids(payload: Any, name: str) -> list[int]:
    if isinstance(payload, Mapping):
        if "input_ids" not in payload:
            raise ValueError(f"{name} tokenizer payload is missing input_ids")
        payload = payload["input_ids"]
    if hasattr(payload, "tolist"):
        payload = payload.tolist()
    if (
        isinstance(payload, list)
        and len(payload) == 1
        and isinstance(payload[0], list)
    ):
        payload = payload[0]
    if not isinstance(payload, list) or any(
        not isinstance(token_id, int) for token_id in payload
    ):
        raise ValueError(f"{name} input_ids must be a flat integer list")
    return payload


def _model_input_device(model: Any):
    try:
        return model.get_input_embeddings().weight.device
    except (AttributeError, StopIteration):
        return next(model.parameters()).device


def load_quantized_model(runtime: dict[str, Any]):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    model_cfg = runtime["model"]
    common = {
        "cache_dir": model_cfg["cache_root"],
        "revision": model_cfg["revision"],
        "local_files_only": True,
    }
    tokenizer = AutoTokenizer.from_pretrained(model_cfg["model_id"], **common)
    model = AutoModelForCausalLM.from_pretrained(
        model_cfg["model_id"],
        quantization_config=BitsAndBytesConfig(load_in_8bit=True),
        device_map=runtime["execution"]["device_map"],
        dtype=torch.bfloat16,
        **common,
    )
    model.eval()
    return model, tokenizer


def extract_candidate_matrices(
    model: Any,
    tokenizer: Any,
    rows: Sequence[FrozenTextRow],
    *,
    layers: Sequence[int],
    pooling_modes: Sequence[str],
    max_sequence_tokens: int,
) -> dict[tuple[int, str], np.ndarray]:
    import torch

    if not rows:
        raise ValueError("at least one frozen text row is required")
    allowed_pooling = {"last_response_token", "mean_response_tokens"}
    if set(pooling_modes) - allowed_pooling:
        raise ValueError("unsupported response pooling mode")
    collected: dict[tuple[int, str], list[np.ndarray]] = {
        (layer, pooling): [] for layer in layers for pooling in pooling_modes
    }
    device = _model_input_device(model)
    model.eval()
    for row in rows:
        token_ids, response_start = response_input_ids(
            tokenizer,
            row.prompt,
            row.response,
            max_sequence_tokens=max_sequence_tokens,
        )
        input_ids = torch.tensor([token_ids], dtype=torch.long, device=device)
        attention_mask = torch.ones_like(input_ids)
        with torch.inference_mode():
            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                output_hidden_states=True,
                use_cache=False,
            )
        hidden_states = outputs.hidden_states
        if hidden_states is None:
            raise RuntimeError("model did not return hidden states")
        for layer in layers:
            hidden_index = layer + 1
            if hidden_index >= len(hidden_states):
                raise ValueError(f"layer {layer} is outside the model hidden-state range")
            response_hidden = hidden_states[hidden_index][0, response_start:, :]
            if response_hidden.shape[0] == 0:
                raise ValueError(f"{row.sample_id}: response span is empty")
            for pooling in pooling_modes:
                pooled = (
                    response_hidden[-1]
                    if pooling == "last_response_token"
                    else response_hidden.mean(dim=0)
                )
                collected[(layer, pooling)].append(
                    pooled.detach().float().cpu().numpy()
                )
        del outputs, hidden_states, input_ids, attention_mask
    matrices = {
        key: np.asarray(values, dtype=np.float32)
        for key, values in collected.items()
    }
    for key, matrix in matrices.items():
        if not np.isfinite(matrix).all():
            raise ValueError(f"{key}: extracted activation matrix contains non-finite values")
    return matrices


def write_activation_artifacts(
    root: Path,
    rows: Sequence[FrozenTextRow],
    manifest: dict[str, Any],
    runtime: dict[str, Any],
    matrices: dict[tuple[int, str], np.ndarray],
    *,
    created_at: str | None = None,
) -> list[Path]:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    analysis_plan = read_json(root / ANALYSIS_PLAN_PATH)
    output_root = root / runtime["artifact_policy"]["root"]
    output_root.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "sample_id": row.sample_id,
            "pair_id": row.pair_id,
            "split": row.split,
            "pole": row.pole,
            "row_index": index,
        }
        for index, row in enumerate(rows)
    ]
    metadata_paths: list[Path] = []
    for (layer, pooling), matrix in sorted(matrices.items()):
        if matrix.shape[0] != len(rows) or matrix.ndim != 2:
            raise ValueError(f"layer {layer} / {pooling}: activation matrix shape mismatch")
        stem = f"train_dev_layer_{layer}_{pooling}"
        array_path = output_root / f"{stem}.npz"
        np.savez_compressed(array_path, embeddings=matrix.astype(np.float32, copy=False))
        relative_array = array_path.resolve().relative_to(root.resolve()).as_posix()
        metadata = {
            "artifact_version": "atlas_v2_activation_artifact_v0_1",
            "created_at": created_at,
            "dataset": {
                "manifest_path": DATASET_MANIFEST_PATH,
                "manifest_sha256": canonical_content_sha256(manifest),
            },
            "analysis_plan": {
                "path": ANALYSIS_PLAN_PATH,
                "sha256": canonical_content_sha256(analysis_plan),
            },
            "runtime_config": {
                "path": RUNTIME_CONFIG_PATH,
                "sha256": canonical_content_sha256(runtime),
            },
            "model": {
                "model_id": runtime["model"]["model_id"],
                "revision": runtime["model"]["revision"],
                "dtype": runtime["model"]["load_dtype"],
                "quantization": runtime["model"]["quantization"],
            },
            "representation_spec": {
                "layer": layer,
                "pooling": pooling,
                "dimension": int(matrix.shape[1]),
                "array_dtype": "float32",
            },
            "splits": list(ALLOWED_SPLITS),
            "records": records,
            "array_artifact": {
                "path": relative_array,
                "sha256": file_sha256(array_path),
                "format": "npz",
                "embedding_key": "embeddings",
            },
            "claim_boundary": (
                "Train/dev activation artifact only. It is not held-out test evidence and does "
                "not establish causal steering."
            ),
        }
        validate_schema(metadata, root / ACTIVATION_SCHEMA_PATH)
        metadata_path = output_root / f"{stem}.metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        metadata_paths.append(metadata_path)
    return metadata_paths


def write_test_activation_artifact(
    root: Path,
    rows: Sequence[FrozenTextRow],
    manifest: dict[str, Any],
    runtime: dict[str, Any],
    event: dict[str, Any],
    matrix: np.ndarray,
    *,
    created_at: str | None = None,
) -> Path:
    """Write the single test-only activation artifact bound to its access event."""
    if {row.split for row in rows} != {"test"}:
        raise ValueError("test artifact writer accepts test rows only")
    spec = runtime["representation_specification"]
    if matrix.shape != (len(rows), spec["dimension"]):
        raise ValueError("test activation matrix shape differs from frozen specification")
    if matrix.dtype != np.float32 or not np.isfinite(matrix).all():
        raise ValueError("test activation matrix must be finite float32")
    relative_array = runtime["artifact_policy"]["array_path"]
    if relative_array != event["planned_test_activation_path"]:
        raise ValueError("test output path differs from access event")
    array_path = root / relative_array
    if array_path.exists():
        raise FileExistsError(f"refusing to overwrite test activation artifact: {array_path}")
    array_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(array_path, embeddings=matrix)
    analysis_plan = read_json(root / ANALYSIS_PLAN_PATH)
    records = [
        {
            "sample_id": row.sample_id,
            "pair_id": row.pair_id,
            "split": "test",
            "pole": row.pole,
            "row_index": index,
        }
        for index, row in enumerate(rows)
    ]
    metadata = {
        "artifact_version": "atlas_v2_activation_artifact_v0_1",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "manifest_path": DATASET_MANIFEST_PATH,
            "manifest_sha256": canonical_content_sha256(manifest),
        },
        "analysis_plan": {
            "path": ANALYSIS_PLAN_PATH,
            "sha256": canonical_content_sha256(analysis_plan),
        },
        "runtime_config": {
            "path": TEST_RUNTIME_CONFIG_PATH,
            "sha256": canonical_content_sha256(runtime),
        },
        "model": event["model"],
        "representation_spec": spec,
        "splits": ["test"],
        "records": records,
        "array_artifact": {
            "path": relative_array,
            "sha256": file_sha256(array_path),
            "format": "npz",
            "embedding_key": "embeddings",
        },
        "claim_boundary": (
            "Single-opening held-out test activation artifact for pilot representation evidence "
            "only; it does not establish causal steering or a confirmatory-scale result."
        ),
    }
    validate_schema(metadata, root / ACTIVATION_SCHEMA_PATH)
    metadata_path = root / runtime["artifact_policy"]["metadata_path"]
    if metadata_path.exists():
        raise FileExistsError(f"refusing to overwrite test metadata: {metadata_path}")
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata_path
