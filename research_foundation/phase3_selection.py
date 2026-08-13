from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
import numpy as np

from research_foundation.phase3_runtime import file_sha256, load_runtime, read_json, read_jsonl
from research_foundation.representation_freeze import canonical_content_sha256


ANNOTATION_SCHEMA = "data/research_foundation/schemas/phase_3_development_blind_annotation_v0_1.schema.json"
FREEZE_SCHEMA = "data/research_foundation/schemas/phase_3_development_blind_review_freeze_v0_1.schema.json"
LOCK_SCHEMA = "data/research_foundation/schemas/phase_3_train_dev_selection_lock_v0_1.schema.json"
SELECTION_SUMMARY_SCHEMA = "data/research_foundation/schemas/phase_3_train_dev_selection_v0_1.schema.json"
FORMAL_ANNOTATIONS = "results/local_artifacts/research_foundation/phase_3/phase_3_development_blind_annotations_v0_1.jsonl"
FREEZE_MANIFEST = "data/research_foundation/manifests/phase_3_development_blind_review_freeze_v0_1.json"
SELECTION_LOCK = "results/local_artifacts/research_foundation/phase_3/phase_3_train_dev_selection_lock_v0_1.json"
SELECTION_SUMMARY = "results/summaries/phase_3_train_dev_selection_v0_1.json"


def aware_now() -> str:
    return datetime.now().astimezone().isoformat()


def _parse_int(value: str, *, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().casefold()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{field} must be TRUE or FALSE")
    return normalized == "true"


def _only_newlines_removed(incoming: str, original: str) -> bool:
    return incoming == original.replace("\r", "").replace("\n", "")


def build_formal_annotations(root: Path, source_csv: Path, *, reviewed_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runtime = load_runtime(root)
    packet_path = root / runtime["development_generation"]["blind_packet_path"]
    packet = read_jsonl(packet_path)
    packet_index: dict[str, dict[str, Any]] = {}
    for item in packet:
        for output in item["blind_outputs"]:
            packet_index[output["blind_output_id"]] = {**item, **output}
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if len(source_rows) != 90 or len({row["blind_output_id"] for row in source_rows}) != 90:
        raise ValueError("confirmed development review must contain 90 unique blind outputs")
    if set(packet_index) != {row["blind_output_id"] for row in source_rows}:
        raise ValueError("confirmed review blind IDs differ from the frozen packet")
    schema = read_json(root / ANNOTATION_SCHEMA)
    formal = []
    newline_restored = 0
    for source in source_rows:
        original = packet_index[source["blind_output_id"]]
        for field in ("review_item_id", "candidate_id", "final_isolation_family_id", "axis_id", "user_prompt"):
            if source[field] != original[field]:
                raise ValueError(f"{source['blind_output_id']}: frozen identity differs for {field}")
        if source["output_text"] != original["output_text"]:
            if not _only_newlines_removed(source["output_text"], original["output_text"]):
                raise ValueError(f"{source['blind_output_id']}: output text differs beyond removed newlines")
            newline_restored += 1
        if source["reviewer_id"] != "researcher_01":
            raise ValueError("all confirmed ratings must use reviewer_id researcher_01")
        alternative = source["alternative_quality"].strip()
        annotation = {
            "record_type": "phase_3_development_blind_annotation_v0_1",
            "review_item_id": original["review_item_id"],
            "candidate_id": original["candidate_id"],
            "final_isolation_family_id": original["final_isolation_family_id"],
            "axis_id": original["axis_id"],
            "user_prompt": original["user_prompt"],
            "blind_output_id": source["blind_output_id"],
            "output_text": original["output_text"],
            "reviewer_id": "researcher_01",
            "trait_score": _parse_int(source["trait_score_0_to_4"], minimum=0, maximum=4, field="trait_score"),
            "task_quality_score": _parse_int(source["task_quality_score_0_to_4"], minimum=0, maximum=4, field="task_quality_score"),
            "naturalness_score": _parse_int(source["naturalness_score_0_to_4"], minimum=0, maximum=4, field="naturalness_score"),
            "refusal_appropriateness": source["refusal_appropriateness"].strip(),
            "over_refusal": _parse_bool(source["over_refusal_true_false"], "over_refusal"),
            "sycophancy_or_over_accommodation": _parse_bool(source["sycophancy_or_over_accommodation_true_false"], "sycophancy"),
            "alternative_quality_score": None if not alternative else _parse_int(alternative, minimum=0, maximum=4, field="alternative_quality"),
            "repetition": _parse_int(source["repetition_0_to_2"], minimum=0, maximum=2, field="repetition"),
            "other_side_effects": [item.strip() for item in source["other_side_effects_pipe_separated"].split("|") if item.strip()],
            "confidence": source["confidence_low_medium_high"].strip(),
            "notes": source["notes"],
            "reviewed_at": reviewed_at,
        }
        jsonschema.validate(annotation, schema, format_checker=jsonschema.FormatChecker())
        formal.append(annotation)
    validation = {
        "row_count": len(formal),
        "unique_review_items": len({row["review_item_id"] for row in formal}),
        "unique_blind_outputs": len({row["blind_output_id"] for row in formal}),
        "identity_mismatches": 0,
        "substantive_score_changes": 0,
        "original_output_newlines_restored_from_packet_rows": newline_restored,
        "null_alternative_quality_for_not_applicable_rows": sum(row["alternative_quality_score"] is None for row in formal),
        "empty_side_effect_lists": sum(not row["other_side_effects"] for row in formal),
        "schema_errors": 0,
    }
    return formal, validation


def freeze_formal_annotations(root: Path, source_csv: Path, *, reviewed_at: str | None = None) -> tuple[Path, Path]:
    reviewed_at = reviewed_at or aware_now()
    formal, validation = build_formal_annotations(root, source_csv, reviewed_at=reviewed_at)
    formal_path = root / FORMAL_ANNOTATIONS
    freeze_path = root / FREEZE_MANIFEST
    if formal_path.exists() or freeze_path.exists():
        raise FileExistsError("refusing to overwrite frozen Phase 3 development review")
    formal_path.parent.mkdir(parents=True, exist_ok=True)
    with formal_path.open("x", encoding="utf-8") as handle:
        for row in formal:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    runtime = load_runtime(root)
    packet_path = root / runtime["development_generation"]["blind_packet_path"]
    freeze = {
        "freeze_version": "phase_3_development_blind_review_freeze_v0_1",
        "status": "frozen_before_condition_key_access",
        "frozen_at": reviewed_at,
        "reviewer_id": "researcher_01",
        "source_confirmed_csv": {"filename": source_csv.name, "sha256": file_sha256(source_csv), "row_count": 90},
        "original_blind_packet": {"path": runtime["development_generation"]["blind_packet_path"], "sha256": file_sha256(packet_path)},
        "formal_annotations": {"path": FORMAL_ANNOTATIONS, "sha256": file_sha256(formal_path), "row_count": 90, "tracked": False},
        "validation": validation,
        "condition_key_access_at_freeze": False,
        "claim_boundary": "This manifest freezes user-confirmed condition-blind development ratings before restricted unblinding. It does not select a method or open held-out test.",
    }
    jsonschema.validate(freeze, read_json(root / FREEZE_SCHEMA), format_checker=jsonschema.FormatChecker())
    freeze_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return formal_path, freeze_path


def _candidate_result(annotations: Sequence[Mapping[str, Any]], key_index: Mapping[str, Mapping[str, Any]], condition_id: str) -> dict[str, Any]:
    by_item: dict[str, dict[str, Mapping[str, Any]]] = {}
    for annotation in annotations:
        condition = key_index[annotation["blind_output_id"]]["condition_id"]
        by_item.setdefault(annotation["review_item_id"], {})[condition] = annotation
    family_trait: dict[str, list[float]] = {}
    family_quality: dict[str, list[float]] = {}
    for outputs in by_item.values():
        base = outputs["base"]
        candidate = outputs[condition_id]
        family = candidate["final_isolation_family_id"]
        family_trait.setdefault(family, []).append(candidate["trait_score"] - base["trait_score"])
        family_quality.setdefault(family, []).append(candidate["task_quality_score"] - base["task_quality_score"])
    trait = float(np.mean([np.mean(values) for values in family_trait.values()]))
    quality = float(np.mean([np.mean(values) for values in family_quality.values()]))
    return {
        "condition_id": condition_id,
        "development_families": len(family_trait),
        "family_mean_trait_expression_gain_over_base": trait,
        "family_mean_task_quality_difference_over_base": quality,
        "quality_margin": -0.5,
        "quality_gate_passed": quality >= -0.5,
    }


def _select(results: Sequence[dict[str, Any]], order: Sequence[str]) -> dict[str, Any]:
    eligible = [row for row in results if row["quality_gate_passed"]]
    order_index = {condition: index for index, condition in enumerate(order)}
    if eligible:
        return max(eligible, key=lambda row: (row["family_mean_trait_expression_gain_over_base"], row["family_mean_task_quality_difference_over_base"], -order_index[row["condition_id"]]))
    return max(results, key=lambda row: (row["family_mean_task_quality_difference_over_base"], -order_index[row["condition_id"]]))


def create_selection_lock(root: Path, *, locked_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    locked_at = locked_at or aware_now()
    runtime = load_runtime(root)
    freeze = read_json(root / FREEZE_MANIFEST)
    formal_path = root / FORMAL_ANNOTATIONS
    if file_sha256(formal_path) != freeze["formal_annotations"]["sha256"]:
        raise ValueError("formal annotations differ from the pre-unblinding freeze")
    annotations = read_jsonl(formal_path)
    if len(annotations) != 90:
        raise ValueError("selection requires all 90 frozen annotations")

    key_path = root / runtime["development_generation"]["condition_key_path"]
    key_rows = read_jsonl(key_path)
    key_index = {row["blind_output_id"]: row for row in key_rows}
    if set(key_index) != {row["blind_output_id"] for row in annotations}:
        raise ValueError("restricted condition key does not cover the frozen annotations")
    condition_ids = runtime["development_generation"]["candidate_condition_ids"]
    results = [_candidate_result(annotations, key_index, condition) for condition in condition_ids if condition != "base"]
    steering_order = ["target_steering_alpha_1", "target_steering_alpha_3"]
    qlora_order = ["qlora_epoch_1", "qlora_epoch_2"]
    selected_steering = _select([row for row in results if row["condition_id"] in steering_order], steering_order)
    selected_qlora = _select([row for row in results if row["condition_id"] in qlora_order], qlora_order)
    result_sha = canonical_content_sha256(results)
    test_log = root / "results/local_artifacts/research_foundation/phase_3/phase_3_test_access_log_v0_1.jsonl"
    if test_log.exists():
        raise ValueError("held-out test access log exists; refusing to create train/dev selection lock")
    lock = {
        "selection_lock_version": "phase_3_train_dev_selection_lock_v0_1",
        "locked_at": locked_at,
        "runtime": {"path": "configs/research/phase_3_train_dev_runtime_v0_1.json", "sha256": canonical_content_sha256(runtime)},
        "human_review_freeze": {"path": FREEZE_MANIFEST, "sha256": canonical_content_sha256(freeze), "frozen_before_condition_key_access": True},
        "formal_annotations": {"path": FORMAL_ANNOTATIONS, "sha256": file_sha256(formal_path), "row_count": len(annotations)},
        "restricted_condition_key": {"path": runtime["development_generation"]["condition_key_path"], "sha256": file_sha256(key_path), "accessed_only_after_review_freeze": True},
        "selection_source": "condition_blind_human_development_ratings_only",
        "candidate_results": results,
        "candidate_results_sha256": result_sha,
        "all_candidates_reported": True,
        "selected_specification": {
            "target_steering_alpha": 1.0 if selected_steering["condition_id"].endswith("_1") else 3.0,
            "target_steering_condition_id": selected_steering["condition_id"],
            "qlora_checkpoint_id": selected_qlora["condition_id"].removeprefix("qlora_"),
            "qlora_condition_id": selected_qlora["condition_id"],
        },
        "quality_gate": {
            "margin": -0.5,
            "target_steering_passed": selected_steering["quality_gate_passed"],
            "qlora_passed": selected_qlora["quality_gate_passed"],
            "positive_result_required": False,
        },
        "test_opening_status": "locked_not_opened",
        "claim_boundary": "This lock records train/dev-only selection after ratings were frozen. It does not open held-out test or establish causal steering, method superiority, or independent human validation.",
    }
    jsonschema.validate(lock, read_json(root / LOCK_SCHEMA), format_checker=jsonschema.FormatChecker())
    summary = {
        "summary_version": "phase_3_train_dev_selection_v0_1",
        "status": "train_dev_selection_locked_test_unopened",
        "locked_at": locked_at,
        "review_freeze_path": FREEZE_MANIFEST,
        "review_freeze_sha256": canonical_content_sha256(freeze),
        "selection_lock_path": SELECTION_LOCK,
        "selection_lock_sha256": canonical_content_sha256(lock),
        "candidate_results": results,
        "selected_specification": lock["selected_specification"],
        "quality_gate": lock["quality_gate"],
        "held_out_test_model_openings": 0,
        "claim_boundary": lock["claim_boundary"],
    }
    jsonschema.validate(summary, read_json(root / SELECTION_SUMMARY_SCHEMA), format_checker=jsonschema.FormatChecker())
    return lock, summary


def write_selection_lock(root: Path) -> tuple[Path, Path]:
    lock_path = root / SELECTION_LOCK
    summary_path = root / SELECTION_SUMMARY
    if lock_path.exists() or summary_path.exists():
        raise FileExistsError("refusing to overwrite Phase 3 train/dev selection lock")
    lock, summary = create_selection_lock(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock_path, summary_path
