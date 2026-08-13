from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable


MAPPING_DECISIONS = {"accept", "reject", "ambiguous", "needs_rewrite"}
PKU_BEHAVIORS = {
    "reasonable_accept",
    "reasonable_refusal",
    "clarification",
    "alternative",
    "unsafe_compliance",
    "over_refusal",
    "other",
}
PAIR_CONTRAST_STATUSES = {
    "valid_single_axis",
    "same_axis_not_opposite",
    "multi_axis",
    "insufficient_trait_evidence",
    "ambiguous",
}
QUALITY_FLAGS = {
    "keyword_leakage",
    "length_mismatch",
    "task_answer_mismatch",
    "confound_risk",
    "unsafe_content",
    "too_subtle",
    "too_obvious",
    "exact_duplicate",
    "near_duplicate",
    "template_dominated",
    "insufficient_context",
    "source_label_only",
    "multi_axis_confound",
    "poor_response_quality",
    "other",
}
FAMILY_REVIEW_FIELDS = (
    "task_family_id",
    "scenario_family_id",
    "prompt_template_id",
    "semantic_cluster_id",
)


def load_axis_poles(path: Path) -> dict[str, tuple[str, str]]:
    """Load axis/pole pairs directly from the authoritative YAML registry.

    PyYAML is used when available. The constrained fallback keeps CPU-only CI
    dependency-free while still reading, rather than copying, the registry.
    """
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        result: dict[str, tuple[str, str]] = {}
        for group in payload["groups"].values():
            for axis in group["axes"]:
                result[str(axis["axis_id"])] = (
                    str(axis["positive_pole"]),
                    str(axis["negative_pole"]),
                )
        if not result:
            raise ValueError(f"No axes found in {path}")
        return result
    except ModuleNotFoundError:
        pass

    result: dict[str, tuple[str, str]] = {}
    axis_id: str | None = None
    positive: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        axis_match = re.match(r"^\s*-\s+axis_id:\s*(\S+)\s*$", line)
        if axis_match:
            axis_id = axis_match.group(1)
            positive = None
            continue
        positive_match = re.match(r"^\s*positive_pole:\s*(\S+)\s*$", line)
        if axis_id and positive_match:
            positive = positive_match.group(1)
            continue
        negative_match = re.match(r"^\s*negative_pole:\s*(\S+)\s*$", line)
        if axis_id and positive and negative_match:
            result[axis_id] = (positive, negative_match.group(1))
            axis_id = None
            positive = None
    if not result:
        raise ValueError(f"No axes found in {path}")
    return result


def _empty_family_review() -> dict[str, None]:
    return {field: None for field in FAMILY_REVIEW_FIELDS}


def content_digest(*parts: object) -> str:
    return sha256("\u241f".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _proposed_without_source(proposed: dict[str, Any]) -> dict[str, Any]:
    return {
        field: proposed[field]
        for field in (*FAMILY_REVIEW_FIELDS, "assignment_status")
    }


def upgrade_empathetic_rows_v2(
    review_rows: list[dict[str, Any]], manifest_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    upgraded_reviews: list[dict[str, Any]] = []
    upgraded_manifest: list[dict[str, Any]] = []
    manifest_by_id = {row["sample_id"]: row for row in manifest_rows}
    for row in review_rows:
        source_family_id = row["proposed_family_assignment"]["source_family_id"]
        upgraded = {
            "schema_version": "public_mapping_review_v0_2",
            "record_type": row["record_type"],
            "dataset_id": row["dataset_id"],
            "sample_id": row["sample_id"],
            "source_family_id": source_family_id,
            "source_locator": row["source_locator"],
            "source_context_label": row["source_context_label"],
            "situation_prompt": row["situation_prompt"],
            "user_utterance": row["user_utterance"],
            "candidate_response": row["candidate_response"],
            "content_sha256": row["content_sha256"],
            "candidate_trait_axes": row["candidate_trait_axes"],
            "proposed_family_assignment": _proposed_without_source(row["proposed_family_assignment"]),
            "human_review": {
                "mapping_decision": None,
                "reviewer_id": None,
                "reviewed_at": None,
                "trait_annotation": {"axis_id": None, "pole": None},
                "reviewed_family_assignment": _empty_family_review(),
                "quality_flags": [],
                "rewrite_notes": "",
                "notes": "",
            },
        }
        upgraded_reviews.append(upgraded)
        source_manifest = manifest_by_id[row["sample_id"]]
        upgraded_manifest.append(
            {
                "sample_id": row["sample_id"],
                "dataset_id": row["dataset_id"],
                "source_family_id": source_family_id,
                "source_locator": source_manifest["source_locator"],
                "source_context_label": source_manifest["source_context_label"],
                "content_sha256": source_manifest["content_sha256"],
                "candidate_trait_axes": source_manifest["candidate_trait_axes"],
                "proposed_family_assignment": _proposed_without_source(
                    source_manifest["proposed_family_assignment"]
                ),
                "human_review_status": "pending",
            }
        )
    return upgraded_reviews, upgraded_manifest


def upgrade_pku_rows_v2(
    review_rows: list[dict[str, Any]], manifest_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    upgraded_reviews: list[dict[str, Any]] = []
    upgraded_manifest: list[dict[str, Any]] = []
    manifest_by_id = {row["sample_id"]: row for row in manifest_rows}
    for row in review_rows:
        source_family_id = row["proposed_family_assignment"]["source_family_id"]
        upgraded = {
            "schema_version": "public_mapping_review_v0_2",
            "record_type": row["record_type"],
            "dataset_id": row["dataset_id"],
            "sample_id": row["sample_id"],
            "source_family_id": source_family_id,
            "content_warning": row["content_warning"],
            "source_locator": row["source_locator"],
            "prompt": row["prompt"],
            "response_0": row["response_0"],
            "response_1": row["response_1"],
            "source_labels": row["source_labels"],
            "content_sha256": row["content_sha256"],
            "candidate_trait_axes": row["candidate_trait_axes"],
            "proposed_family_assignment": _proposed_without_source(row["proposed_family_assignment"]),
            "human_review": {
                "mapping_decision": None,
                "reviewer_id": None,
                "reviewed_at": None,
                "response_annotations": [
                    {
                        "response_id": "response_0",
                        "behavior": None,
                        "trait_annotation": {"axis_id": None, "pole": None},
                    },
                    {
                        "response_id": "response_1",
                        "behavior": None,
                        "trait_annotation": {"axis_id": None, "pole": None},
                    },
                ],
                "pair_contrast": {"status": None, "axis_id": None},
                "reviewed_family_assignment": _empty_family_review(),
                "quality_flags": [],
                "rewrite_notes": "",
                "notes": "",
            },
        }
        upgraded_reviews.append(upgraded)
        source_manifest = manifest_by_id[row["sample_id"]]
        upgraded_manifest.append(
            {
                "sample_id": row["sample_id"],
                "dataset_id": row["dataset_id"],
                "source_family_id": source_family_id,
                "source_locator": source_manifest["source_locator"],
                "source_label_summary": source_manifest["source_label_summary"],
                "response_sha256": source_manifest["response_sha256"],
                "content_sha256": source_manifest["content_sha256"],
                "candidate_trait_axes": source_manifest["candidate_trait_axes"],
                "proposed_family_assignment": _proposed_without_source(
                    source_manifest["proposed_family_assignment"]
                ),
                "human_review_status": "pending",
            }
        )
    return upgraded_reviews, upgraded_manifest


def expected_identity_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        record["sample_id"]: record
        for dataset in manifest["datasets"]
        for record in dataset["records"]
    }


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_trait_annotation(
    sample_id: str,
    annotation: Any,
    candidate_axes: set[str],
    axis_poles: dict[str, tuple[str, str]],
    errors: list[str],
    label: str,
) -> tuple[str, str] | None:
    if not isinstance(annotation, dict):
        errors.append(f"{sample_id}: {label} must be an object")
        return None
    axis_id = annotation.get("axis_id")
    pole = annotation.get("pole")
    if axis_id is None and pole is None:
        return None
    if not _nonempty(axis_id) or not _nonempty(pole):
        errors.append(f"{sample_id}: {label} requires axis_id and pole together")
        return None
    if axis_id not in axis_poles:
        errors.append(f"{sample_id}: {label} unknown axis_id {axis_id}")
        return None
    if axis_id not in candidate_axes:
        errors.append(f"{sample_id}: {label} axis_id {axis_id} is outside candidate_trait_axes")
    if pole not in axis_poles[axis_id]:
        errors.append(f"{sample_id}: {label} pole {pole} is invalid for {axis_id}")
        return None
    return axis_id, pole


def _validate_family_values(sample_id: str, family: Any, errors: list[str]) -> dict[str, Any]:
    if not isinstance(family, dict):
        errors.append(f"{sample_id}: reviewed_family_assignment must be an object")
        return {}
    if set(family) != set(FAMILY_REVIEW_FIELDS):
        errors.append(f"{sample_id}: reviewed_family_assignment must contain exactly four reviewable fields")
    for field in FAMILY_REVIEW_FIELDS:
        value = family.get(field)
        if value is not None and not _nonempty(value):
            errors.append(f"{sample_id}: {field} must be null or a non-empty string")
    return family


def _validate_pair_contrast(
    sample_id: str,
    pair: Any,
    traits: list[tuple[str, str] | None],
    axis_poles: dict[str, tuple[str, str]],
    errors: list[str],
) -> str | None:
    if not isinstance(pair, dict):
        errors.append(f"{sample_id}: pair_contrast must be an object")
        return None
    status = pair.get("status")
    axis_id = pair.get("axis_id")
    if status is None and axis_id is None:
        return None
    if status not in PAIR_CONTRAST_STATUSES:
        errors.append(f"{sample_id}: invalid pair_contrast status")
        return None
    if status in {"valid_single_axis", "same_axis_not_opposite"}:
        if axis_id not in axis_poles:
            errors.append(f"{sample_id}: {status} requires a registry axis_id")
            return status
        if any(trait is None for trait in traits):
            errors.append(f"{sample_id}: {status} requires both response trait annotations")
            return status
        typed_traits = [trait for trait in traits if trait is not None]
        if any(trait[0] != axis_id for trait in typed_traits):
            errors.append(f"{sample_id}: pair axis must match both response axes")
            return status
        observed_poles = {trait[1] for trait in typed_traits}
        opposite_poles = set(axis_poles[axis_id])
        if status == "valid_single_axis" and observed_poles != opposite_poles:
            errors.append(f"{sample_id}: valid_single_axis requires opposite registry poles")
        if status == "same_axis_not_opposite" and observed_poles == opposite_poles:
            errors.append(f"{sample_id}: opposite poles must use valid_single_axis")
    elif status == "multi_axis":
        if axis_id is not None:
            errors.append(f"{sample_id}: multi_axis must not select one pair axis")
        if any(trait is None for trait in traits) or len({trait[0] for trait in traits if trait}) != 2:
            errors.append(f"{sample_id}: multi_axis requires two different response axes")
    elif status == "insufficient_trait_evidence":
        if axis_id is not None:
            errors.append(f"{sample_id}: insufficient_trait_evidence must not select a pair axis")
        if all(trait is not None for trait in traits):
            errors.append(f"{sample_id}: both mapped responses require a more specific contrast status")
    elif status == "ambiguous" and axis_id is not None:
        errors.append(f"{sample_id}: ambiguous pair contrast must not select one pair axis")
    return status


def validate_completed_review_v2(
    rows: Iterable[dict[str, Any]],
    axis_poles: dict[str, tuple[str, str]],
    expected_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        sample_id = row.get("sample_id")
        if not _nonempty(sample_id):
            errors.append(f"row {index}: missing sample_id")
            continue
        if sample_id in seen:
            errors.append(f"{sample_id}: duplicate sample_id")
        seen.add(sample_id)
        if row.get("schema_version") != "public_mapping_review_v0_2":
            errors.append(f"{sample_id}: wrong schema_version")
        expected = expected_by_id.get(sample_id)
        if expected is None:
            errors.append(f"{sample_id}: not present in the tracked v0.2 manifest")
        else:
            for field in (
                "dataset_id",
                "source_family_id",
                "source_locator",
                "content_sha256",
                "candidate_trait_axes",
                "proposed_family_assignment",
            ):
                if row.get(field) != expected.get(field):
                    errors.append(f"{sample_id}: provenance-derived {field} was modified")
            if row.get("dataset_id") == "empathetic_dialogues":
                if row.get("source_context_label") != expected.get("source_context_label"):
                    errors.append(f"{sample_id}: provenance-derived source_context_label was modified")
            elif row.get("dataset_id") == "pku_safe_rlhf":
                if row.get("source_labels") != expected.get("source_label_summary"):
                    errors.append(f"{sample_id}: provenance-derived source_labels were modified")

        candidate_axes = row.get("candidate_trait_axes")
        if not isinstance(candidate_axes, list) or not candidate_axes:
            errors.append(f"{sample_id}: candidate_trait_axes must be a non-empty list")
            candidate_axis_set: set[str] = set()
        else:
            candidate_axis_set = set(candidate_axes)
            unknown = candidate_axis_set - set(axis_poles)
            if unknown:
                errors.append(f"{sample_id}: unknown candidate axes {sorted(unknown)}")

        review = row.get("human_review")
        if not isinstance(review, dict):
            errors.append(f"{sample_id}: missing human_review")
            continue
        if "source_family_id" in review:
            errors.append(f"{sample_id}: source_family_id is provenance-derived and cannot be human-edited")
        decision = review.get("mapping_decision")
        if decision not in MAPPING_DECISIONS:
            errors.append(f"{sample_id}: invalid or missing mapping_decision")
        else:
            if not _nonempty(review.get("reviewer_id")):
                errors.append(f"{sample_id}: completed decision requires reviewer_id")
            reviewed_at = review.get("reviewed_at")
            if not _nonempty(reviewed_at):
                errors.append(f"{sample_id}: completed decision requires reviewed_at")
            else:
                try:
                    parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("timezone is required")
                except ValueError:
                    errors.append(f"{sample_id}: reviewed_at must be an ISO-8601 datetime with timezone")
        flags = review.get("quality_flags")
        if not isinstance(flags, list):
            errors.append(f"{sample_id}: quality_flags must be a list")
            flags = []
        elif len(flags) != len(set(flags)):
            errors.append(f"{sample_id}: quality_flags must be unique")
        unknown_flags = set(flags) - QUALITY_FLAGS
        if unknown_flags:
            errors.append(f"{sample_id}: unknown quality_flags {sorted(unknown_flags)}")
        if "other" in flags and not _nonempty(review.get("notes")):
            errors.append(f"{sample_id}: quality flag other requires explanatory notes")
        family = _validate_family_values(sample_id, review.get("reviewed_family_assignment"), errors)

        dataset_id = row.get("dataset_id")
        mapped_trait_count = 0
        pair_status: str | None = None
        if dataset_id == "empathetic_dialogues":
            if content_digest(
                row.get("situation_prompt"), row.get("user_utterance"), row.get("candidate_response")
            ) != row.get("content_sha256"):
                errors.append(f"{sample_id}: raw content no longer matches content_sha256")
            trait = _validate_trait_annotation(
                sample_id,
                review.get("trait_annotation"),
                candidate_axis_set,
                axis_poles,
                errors,
                "trait_annotation",
            )
            mapped_trait_count = int(trait is not None)
        elif dataset_id == "pku_safe_rlhf":
            if content_digest(
                row.get("prompt"), row.get("response_0"), row.get("response_1")
            ) != row.get("content_sha256"):
                errors.append(f"{sample_id}: raw content no longer matches content_sha256")
            annotations = review.get("response_annotations")
            if not isinstance(annotations, list) or len(annotations) != 2:
                errors.append(f"{sample_id}: response_annotations must contain exactly two responses")
                annotations = []
            traits: list[tuple[str, str] | None] = []
            for response_index, response_id in enumerate(("response_0", "response_1")):
                annotation = annotations[response_index] if response_index < len(annotations) else {}
                if annotation.get("response_id") != response_id:
                    errors.append(f"{sample_id}: response annotation order/id mismatch for {response_id}")
                behavior = annotation.get("behavior")
                if behavior is not None and behavior not in PKU_BEHAVIORS:
                    errors.append(f"{sample_id}: invalid {response_id} behavior")
                traits.append(
                    _validate_trait_annotation(
                        sample_id,
                        annotation.get("trait_annotation"),
                        candidate_axis_set,
                        axis_poles,
                        errors,
                        f"{response_id}.trait_annotation",
                    )
                )
            mapped_trait_count = sum(trait is not None for trait in traits)
            pair_status = _validate_pair_contrast(
                sample_id, review.get("pair_contrast"), traits, axis_poles, errors
            )
            if decision in {"accept", "needs_rewrite"}:
                for annotation in annotations:
                    if annotation.get("behavior") not in PKU_BEHAVIORS:
                        errors.append(f"{sample_id}: {decision} requires both response behaviors")
                if pair_status is None:
                    errors.append(f"{sample_id}: {decision} requires pair_contrast.status")
                if decision == "accept" and pair_status == "ambiguous":
                    errors.append(f"{sample_id}: accept cannot use ambiguous pair contrast")
        else:
            errors.append(f"{sample_id}: unsupported dataset_id {dataset_id}")

        if decision == "accept":
            for field in FAMILY_REVIEW_FIELDS:
                if not _nonempty(family.get(field)):
                    errors.append(f"{sample_id}: accept requires {field}")
            if mapped_trait_count < 1:
                errors.append(f"{sample_id}: accept requires at least one valid trait annotation")
        elif decision == "needs_rewrite":
            if not _nonempty(family.get("scenario_family_id")):
                errors.append(f"{sample_id}: needs_rewrite requires scenario_family_id")
            if mapped_trait_count < 1:
                errors.append(f"{sample_id}: needs_rewrite requires a defensible axis/pole")
            if not _nonempty(review.get("rewrite_notes")):
                errors.append(f"{sample_id}: needs_rewrite requires rewrite_notes")
        elif decision == "ambiguous":
            if not _nonempty(review.get("notes")):
                errors.append(f"{sample_id}: ambiguous requires explanatory notes")
        elif decision == "reject":
            if not flags and not _nonempty(review.get("notes")):
                errors.append(f"{sample_id}: reject requires a quality flag or explanatory notes")
    missing = set(expected_by_id) - seen
    if missing:
        errors.append(f"review packet is missing {len(missing)} manifest samples")
    return errors


def validate_rows_against_schema_v2(
    rows: Iterable[dict[str, Any]], schema_path: Path
) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError:
        return [
            "jsonschema is required for formal v0.2 validation; use the project environment before review"
        ]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        for error in sorted(validator.iter_errors(row), key=lambda item: list(item.absolute_path)):
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"row {row_index} {location}: {error.message}")
    return errors


def family_allocation_unit_id(source_family_id: str, family: dict[str, str]) -> str:
    values = [source_family_id, *(family[field] for field in FAMILY_REVIEW_FIELDS)]
    return "famu_" + sha256("\u241f".join(values).encode("utf-8")).hexdigest()[:20]


def reviewed_family_candidates_v2(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert only accepted, human-reviewed raw samples into allocation candidates.

    reject, ambiguous, and needs_rewrite records are deliberately omitted. A
    needs_rewrite source can enter a later dataset only through a new derived
    sample with explicit lineage; its original wording is never exported here.
    """
    candidates: list[dict[str, Any]] = []
    for row in rows:
        review = row["human_review"]
        if review["mapping_decision"] != "accept":
            continue
        family = review["reviewed_family_assignment"]
        base = {
            "source_family_id": row["source_family_id"],
            **{field: family[field] for field in FAMILY_REVIEW_FIELDS},
            "assignment_status": "human_verified",
        }
        allocation_unit_id = family_allocation_unit_id(row["source_family_id"], family)
        if row["dataset_id"] == "empathetic_dialogues":
            trait = review["trait_annotation"]
            candidates.append(
                {
                    "sample_id": row["sample_id"],
                    "source_sample_id": row["sample_id"],
                    "response_id": None,
                    "axis_id": trait["axis_id"],
                    "pole": trait["pole"],
                    "allocation_unit_id": allocation_unit_id,
                    **base,
                }
            )
        else:
            for annotation in review["response_annotations"]:
                trait = annotation["trait_annotation"]
                if trait["axis_id"] is None:
                    continue
                candidates.append(
                    {
                        "sample_id": f"{row['sample_id']}__{annotation['response_id']}",
                        "source_sample_id": row["sample_id"],
                        "response_id": annotation["response_id"],
                        "axis_id": trait["axis_id"],
                        "pole": trait["pole"],
                        "allocation_unit_id": allocation_unit_id,
                        **base,
                    }
                )
    return candidates


def family_split_records_v2(
    candidates: Iterable[dict[str, Any]], allocation_by_unit: dict[str, str]
) -> list[dict[str, Any]]:
    """Materialize family_split_v2 records from family-unit allocations.

    Assignments are keyed by the complete five-family allocation unit, never by
    sample ID. This makes ID-level splitting impossible through this contract.
    """
    allowed_splits = {"train", "dev", "test", "excluded"}
    records: list[dict[str, Any]] = []
    split_by_family_tuple: dict[tuple[str, ...], str] = {}
    for candidate in candidates:
        allocation_unit_id = candidate["allocation_unit_id"]
        if allocation_unit_id not in allocation_by_unit:
            raise ValueError(f"Missing split for allocation unit {allocation_unit_id}")
        split = allocation_by_unit[allocation_unit_id]
        if split not in allowed_splits:
            raise ValueError(f"Invalid split {split} for {allocation_unit_id}")
        family_tuple = tuple(
            candidate[field] for field in ("source_family_id", *FAMILY_REVIEW_FIELDS)
        )
        previous = split_by_family_tuple.setdefault(family_tuple, split)
        if previous != split:
            raise ValueError(f"Family tuple assigned to both {previous} and {split}")
        records.append(
            {
                "sample_id": candidate["sample_id"],
                "split": split,
                "source_family_id": candidate["source_family_id"],
                "task_family_id": candidate["task_family_id"],
                "scenario_family_id": candidate["scenario_family_id"],
                "prompt_template_id": candidate["prompt_template_id"],
                "semantic_cluster_id": candidate["semantic_cluster_id"],
                "assignment_status": "human_verified" if split != "excluded" else "excluded",
            }
        )
    return sorted(records, key=lambda row: row["sample_id"])


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
