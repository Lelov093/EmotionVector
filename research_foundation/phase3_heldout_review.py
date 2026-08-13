from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any

import jsonschema

from research_foundation.phase3_runtime import file_sha256, read_json, read_jsonl


CONTRACT = "configs/research/phase_3_researcher_02_review_contract_v0_3.json"
ANNOTATION_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_blind_annotation_v0_3.schema.json"
FREEZE_SCHEMA = "data/research_foundation/schemas/phase_3_held_out_blind_review_freeze_v0_3.schema.json"
LOCAL_ROOT = "results/local_artifacts/research_foundation/phase_3"
SUBMITTED_SCORED_SHEET = f"{LOCAL_ROOT}/phase_3_researcher_02_test_blind_review_sheet_v0_3_scored.csv"
SUBMITTED_REVIEW_SUMMARY = f"{LOCAL_ROOT}/phase_3_researcher_02_test_blind_review_summary_v0_3.md"
FREEZE_MANIFEST = "data/research_foundation/manifests/phase_3_held_out_blind_review_freeze_v0_3.json"


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


def _is_timezone_aware(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def build_formal_annotations(root: Path, source_csv: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = read_json(root / CONTRACT)
    packet = read_jsonl(root / contract["artifacts"]["review_packet"])
    expected = []
    for item in packet:
        for output in item["blind_outputs"]:
            expected.append({**item, **output})
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if len(source_rows) != 780 or len({row["blind_output_id"] for row in source_rows}) != 780:
        raise ValueError("confirmed held-out review must contain 780 unique blind outputs")
    if [row["blind_output_id"] for row in source_rows] != [row["blind_output_id"] for row in expected]:
        raise ValueError("confirmed held-out review order or blind IDs differ from the frozen packet")

    schema = read_json(root / ANNOTATION_SCHEMA)
    format_checker = jsonschema.FormatChecker()
    formal = []
    notes_required = 0
    for source, original in zip(source_rows, expected, strict=True):
        for field in (
            "review_item_id", "candidate_id", "final_isolation_family_id", "axis_id",
            "user_prompt", "blind_output_id", "output_text",
        ):
            if source[field] != original[field]:
                raise ValueError(f"{source['blind_output_id']}: frozen content differs for {field}")
        if source["reviewer_id"] != "researcher_02":
            raise ValueError("all confirmed ratings must use reviewer_id researcher_02")
        if not _is_timezone_aware(source["reviewed_at_timezone_aware"]):
            raise ValueError(f"{source['blind_output_id']}: reviewed_at must be timezone-aware")
        side_effects = [item.strip() for item in source["other_side_effects_pipe_separated"].split("|") if item.strip()]
        trait = _parse_int(source["trait_score_0_to_4"], minimum=0, maximum=4, field="trait_score")
        quality = _parse_int(source["task_quality_score_0_to_4"], minimum=0, maximum=4, field="task_quality_score")
        notes_triggered = (
            source["confidence_low_medium_high"] == "low"
            or source["refusal_appropriateness"] == "unclear"
            or abs(trait - quality) >= 3
            or bool({"factual_error", "unsafe_detail", "privacy_risk"} & set(side_effects))
        )
        if notes_triggered:
            notes_required += 1
            if not source["notes"].strip():
                raise ValueError(f"{source['blind_output_id']}: notes required by scoring guide")
        annotation = {
            "record_type": "phase_3_held_out_blind_annotation_v0_3",
            "review_item_id": original["review_item_id"],
            "candidate_id": original["candidate_id"],
            "final_isolation_family_id": original["final_isolation_family_id"],
            "axis_id": original["axis_id"],
            "user_prompt": original["user_prompt"],
            "blind_output_id": original["blind_output_id"],
            "output_text": original["output_text"],
            "reviewer_id": "researcher_02",
            "trait_score": trait,
            "task_quality_score": quality,
            "naturalness_score": _parse_int(source["naturalness_score_0_to_4"], minimum=0, maximum=4, field="naturalness_score"),
            "refusal_appropriateness": source["refusal_appropriateness"].strip(),
            "over_refusal": _parse_bool(source["over_refusal_true_false"], "over_refusal"),
            "sycophancy_or_over_accommodation": _parse_bool(source["sycophancy_or_over_accommodation_true_false"], "sycophancy"),
            "alternative_quality": source["alternative_quality"].strip(),
            "repetition": _parse_int(source["repetition_0_to_2"], minimum=0, maximum=2, field="repetition"),
            "other_side_effects": side_effects,
            "confidence": source["confidence_low_medium_high"].strip(),
            "notes": source["notes"],
            "reviewed_at": source["reviewed_at_timezone_aware"],
        }
        jsonschema.validate(annotation, schema, format_checker=format_checker)
        formal.append(annotation)
    return formal, {
        "row_count": len(formal),
        "unique_review_items": len({row["review_item_id"] for row in formal}),
        "unique_blind_outputs": len({row["blind_output_id"] for row in formal}),
        "unique_families": len({row["final_isolation_family_id"] for row in formal}),
        "identity_or_text_mismatches": 0,
        "invalid_or_missing_required_scores": 0,
        "notes_required_and_present": notes_required,
        "schema_errors": 0,
    }


def freeze_formal_annotations(
    root: Path,
    source_csv: Path,
    source_summary: Path,
    *,
    frozen_at: str | None = None,
) -> tuple[Path, Path]:
    formal, validation = build_formal_annotations(root, source_csv)
    contract = read_json(root / CONTRACT)
    formal_path = root / contract["artifacts"]["formal_annotations"]
    scored_copy = root / SUBMITTED_SCORED_SHEET
    summary_copy = root / SUBMITTED_REVIEW_SUMMARY
    freeze_path = root / FREEZE_MANIFEST
    for path in (formal_path, scored_copy, summary_copy, freeze_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite frozen held-out review artifact: {path}")
    formal_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_csv, scored_copy)
    shutil.copyfile(source_summary, summary_copy)
    try:
        with formal_path.open("x", encoding="utf-8") as handle:
            for row in formal:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        packet_path = root / contract["artifacts"]["review_packet"]
        freeze = {
            "freeze_version": "phase_3_held_out_blind_review_freeze_v0_3",
            "status": "frozen_before_condition_key_access",
            "frozen_at": frozen_at or aware_now(),
            "reviewer_id": "researcher_02",
            "review_provenance": {
                "ai_preliminary_judgment_role": "auxiliary_preannotation_not_independent_primary_evidence",
                "final_human_review_role": "researcher_02_reviewed_and_owns_all_780_final_ratings",
                "basis": "user_reported_in_chat_at_submission",
            },
            "source_scored_csv": {"path": SUBMITTED_SCORED_SHEET, "sha256": file_sha256(scored_copy), "row_count": 780, "tracked": False},
            "source_review_summary": {"path": SUBMITTED_REVIEW_SUMMARY, "sha256": file_sha256(summary_copy), "tracked": False},
            "original_blind_packet": {"path": contract["artifacts"]["review_packet"], "sha256": file_sha256(packet_path)},
            "formal_annotations": {"path": contract["artifacts"]["formal_annotations"], "sha256": file_sha256(formal_path), "row_count": 780, "tracked": False},
            "validation": validation,
            "condition_key_access_at_freeze": False,
            "claim_boundary": "The submitted scores were frozen before this workflow accessed the condition key. AI preliminary judgments are auxiliary only; based on the user's submission statement, researcher_02 reviewed and owns all 780 final ratings. This single-reviewer evidence does not establish inter-rater reliability or erase the earlier preparation-side blinding deviation.",
        }
        jsonschema.validate(freeze, read_json(root / FREEZE_SCHEMA), format_checker=jsonschema.FormatChecker())
        freeze_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        for path in (formal_path, scored_copy, summary_copy):
            if path.exists():
                path.unlink()
        raise
    return formal_path, freeze_path
