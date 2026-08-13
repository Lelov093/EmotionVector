from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


FAMILY_FIELDS = (
    "source_family_id",
    "task_family_id",
    "scenario_family_id",
    "prompt_template_id",
    "semantic_cluster_id",
)


def normalize_text(value: str) -> str:
    """Normalize text for conservative exact-duplicate checks."""
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


def word_ngrams(value: str, n: int = 3) -> set[tuple[str, ...]]:
    tokens = normalize_text(value).split()
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index : index + n]) for index in range(len(tokens) - n + 1)}


def jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # JSONL records are delimited by LF/CRLF. str.splitlines() also splits on
    # Unicode separators such as U+2028, which may legally occur inside a JSON
    # string and previously produced false malformed-record findings.
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            rows.append(payload)
    return rows


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def field_coverage(rows: list[dict[str, Any]], fields: list[str] | tuple[str, ...]) -> dict[str, dict[str, Any]]:
    total = len(rows)
    result: dict[str, dict[str, Any]] = {}
    for field in fields:
        present = sum(1 for row in rows if row.get(field) not in (None, ""))
        result[field] = {
            "present": present,
            "missing": total - present,
            "coverage": (present / total) if total else 0.0,
        }
    return result


def cross_split_group_leaks(
    rows: list[dict[str, Any]], group_field: str, split_field: str
) -> list[dict[str, Any]]:
    split_by_group: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group = row.get(group_field)
        split = row.get(split_field)
        if group not in (None, "") and split not in (None, ""):
            split_by_group[str(group)].add(str(split))
    return [
        {"group_id": group, "splits": sorted(splits)}
        for group, splits in sorted(split_by_group.items())
        if len(splits) > 1
    ]


def cross_split_text_duplicates(
    rows: list[dict[str, Any]], text_field: str, split_field: str
) -> list[dict[str, Any]]:
    split_by_text: dict[str, set[str]] = defaultdict(set)
    raw_example: dict[str, str] = {}
    for row in rows:
        value = row.get(text_field)
        split = row.get(split_field)
        if not isinstance(value, str) or not value.strip() or split in (None, ""):
            continue
        normalized = normalize_text(value)
        split_by_text[normalized].add(str(split))
        raw_example.setdefault(normalized, value)
    return [
        {
            "normalized_text": normalized,
            "text_example": raw_example[normalized],
            "splits": sorted(splits),
        }
        for normalized, splits in sorted(split_by_text.items())
        if len(splits) > 1
    ]


def cross_split_near_duplicates(
    rows: list[dict[str, Any]],
    text_field: str,
    split_field: str,
    threshold: float,
    example_limit: int = 20,
) -> dict[str, Any]:
    prepared: list[tuple[int, str, str, set[tuple[str, ...]]]] = []
    for index, row in enumerate(rows):
        value = row.get(text_field)
        split = row.get(split_field)
        if isinstance(value, str) and value.strip() and split not in (None, ""):
            prepared.append((index, str(split), value, word_ngrams(value)))
    count = 0
    examples: list[dict[str, Any]] = []
    for left_index, left_split, left_text, left_ngrams in prepared:
        for right_index, right_split, right_text, right_ngrams in prepared:
            if right_index <= left_index or right_split == left_split:
                continue
            score = jaccard(left_ngrams, right_ngrams)
            if score < threshold or normalize_text(left_text) == normalize_text(right_text):
                continue
            count += 1
            if len(examples) < example_limit:
                examples.append(
                    {
                        "left_split": left_split,
                        "right_split": right_split,
                        "similarity": round(score, 6),
                        "left_text": left_text,
                        "right_text": right_text,
                    }
                )
    return {"count": count, "threshold": threshold, "examples": examples}


def template_phrase_counts(rows: list[dict[str, Any]], text_fields: list[str], phrases: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for phrase in phrases:
        needle = phrase.casefold()
        counts[phrase] = sum(
            1
            for row in rows
            if any(isinstance(row.get(field), str) and needle in row[field].casefold() for field in text_fields)
        )
    return counts


def audit_dataset(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = root / spec["path"]
    rows = read_jsonl(path)
    split_field = spec.get("split_field", "split")
    text_fields = spec.get("text_fields", [])
    id_field = spec["id_field"]
    ids = [row.get(id_field) for row in rows]
    split_counts = Counter(str(row.get(split_field)) for row in rows)
    family_coverage = field_coverage(rows, FAMILY_FIELDS)
    family_leaks = {
        field: cross_split_group_leaks(rows, field, split_field)
        for field in FAMILY_FIELDS
        if family_coverage[field]["present"]
    }
    legacy_group_leaks = {
        field: cross_split_group_leaks(rows, field, split_field)
        for field in spec.get("legacy_group_fields", [])
    }
    exact_duplicates = {
        field: cross_split_text_duplicates(rows, field, split_field) for field in text_fields
    }
    near_duplicates = {
        field: cross_split_near_duplicates(
            rows,
            field,
            split_field,
            float(spec.get("near_duplicate_threshold", 0.9)),
        )
        for field in text_fields
    }
    template_counts = template_phrase_counts(
        rows,
        text_fields,
        spec.get("known_template_phrases", []),
    )
    blockers: list[dict[str, Any]] = []
    missing_family_fields = [field for field, coverage in family_coverage.items() if coverage["missing"]]
    if missing_family_fields:
        blockers.append(
            {
                "blocker_id": "missing_v2_family_fields",
                "evidence_level": "direct",
                "details": missing_family_fields,
            }
        )
    if any(exact_duplicates.values()):
        blockers.append(
            {
                "blocker_id": "exact_text_leakage_across_splits",
                "evidence_level": "direct",
                "details": {field: len(items) for field, items in exact_duplicates.items() if items},
            }
        )
    if any(family_leaks.values()) or any(legacy_group_leaks.values()):
        blockers.append(
            {
                "blocker_id": "family_or_group_leakage_across_splits",
                "evidence_level": "direct",
                "details": {
                    **{field: len(items) for field, items in family_leaks.items() if items},
                    **{field: len(items) for field, items in legacy_group_leaks.items() if items},
                },
            }
        )
    phrase_blockers = {
        phrase: count
        for phrase, count in template_counts.items()
        if count >= int(spec.get("template_blocker_min_rows", 2))
    }
    if phrase_blockers:
        blockers.append(
            {
                "blocker_id": "repeated_template_phrase",
                "evidence_level": "direct",
                "details": phrase_blockers,
            }
        )
    return {
        "dataset_id": spec["dataset_id"],
        "path": spec["path"],
        "sha256": file_sha256(path),
        "row_count": len(rows),
        "split_counts": dict(sorted(split_counts.items())),
        "duplicate_id_count": sum(count - 1 for count in Counter(ids).values() if count > 1),
        "family_field_coverage": family_coverage,
        "family_leaks": family_leaks,
        "legacy_group_leaks": legacy_group_leaks,
        "cross_split_exact_text_duplicates": exact_duplicates,
        "cross_split_near_duplicates": near_duplicates,
        "template_phrase_row_counts": template_counts,
        "semantic_duplicate_check": {
            "status": "not_run",
            "reason": "No embedding/model execution is authorized in this work block; semantic_cluster_id is not assigned.",
        },
        "formal_use_status": spec["formal_use_status"],
        "blockers": blockers,
    }


def audit_registry(root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    datasets = [audit_dataset(root, spec) for spec in registry["datasets"]]
    return {
        "audit_version": registry["audit_version"],
        "generated_from_config": registry["config_path"],
        "evidence_scope": "existing tracked local data only",
        "datasets": datasets,
        "summary": {
            "dataset_count": len(datasets),
            "datasets_with_blockers": sum(bool(dataset["blockers"]) for dataset in datasets),
            "blocker_counts": dict(
                Counter(
                    blocker["blocker_id"]
                    for dataset in datasets
                    for blocker in dataset["blockers"]
                )
            ),
        },
        "claim_boundary": (
            "This audit identifies structural risks in existing artifacts. It does not certify a v2 split, "
            "independent human annotation, semantic deduplication, or research validity."
        ),
    }
