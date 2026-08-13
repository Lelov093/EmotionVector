from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED = {
    "sample_id",
    "axis_id",
    "target_pole",
    "split",
    "instruction",
    "user_prompt",
    "response",
    "source",
    "derived_from",
    "pair_id",
    "scenario_id",
    "prompt_family",
    "transformation_type",
    "generator_model",
    "judge_model",
    "human_annotated",
    "created_at",
}


def main() -> int:
    args = parse_args()
    rows = read_jsonl(resolve(args.dataset))
    errors: list[str] = []
    warnings: list[str] = []
    validate_required(rows, errors)
    validate_splits(rows, errors)
    validate_target(rows, errors)
    validate_leakage(rows, errors)
    validate_quality(rows, warnings)
    summary = build_summary(rows, errors, warnings)
    if args.summary:
        write_json(resolve(args.summary), summary)
    if args.report:
        write_report(resolve(args.report), args.dataset, summary)
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


def validate_required(rows: list[dict], errors: list[str]) -> None:
    for idx, row in enumerate(rows, start=1):
        missing = REQUIRED - set(row)
        if missing:
            errors.append(f"row {idx} missing fields: {sorted(missing)}")
        for key in ["source", "derived_from", "transformation_type"]:
            if not row.get(key):
                errors.append(f"row {idx} has empty {key}")


def validate_splits(rows: list[dict], errors: list[str]) -> None:
    counts = Counter(row.get("split") for row in rows)
    if counts.get("train", 0) < 48:
        errors.append(f"train split too small: {counts.get('train', 0)}")
    if counts.get("dev", 0) < 12:
        errors.append(f"dev split too small: {counts.get('dev', 0)}")
    if counts.get("test", 0) < 12:
        errors.append(f"test split too small: {counts.get('test', 0)}")
    unknown = set(counts) - {"train", "dev", "test"}
    if unknown:
        errors.append(f"unknown splits: {sorted(unknown)}")


def validate_target(rows: list[dict], errors: list[str]) -> None:
    for row in rows:
        if row.get("axis_id") != "boundary-preserving-over-accommodating":
            errors.append(f"{row.get('sample_id')} wrong axis_id")
        if row.get("target_pole") != "boundary-preserving":
            errors.append(f"{row.get('sample_id')} wrong target_pole")
        text = " ".join(str(row.get(k, "")) for k in ["target_pole", "response"]).lower()
        if row.get("target_pole") == "over-accommodating" or "as you wish" in text:
            errors.append(f"{row.get('sample_id')} appears to use negative pole as SFT target")


def validate_leakage(rows: list[dict], errors: list[str]) -> None:
    for key in ["pair_id", "scenario_id"]:
        splits_by_key: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            splits_by_key[str(row.get(key))].add(str(row.get("split")))
        leaks = {k: v for k, v in splits_by_key.items() if len(v) > 1}
        if leaks:
            errors.append(f"{key} leakage across splits: {list(leaks)[:5]}")


def validate_quality(rows: list[dict], warnings: list[str]) -> None:
    responses = [row.get("response", "") for row in rows]
    dupes = [text for text, count in Counter(responses).items() if count > 1]
    if dupes:
        warnings.append(f"exact duplicate responses: {len(dupes)}")
    near = near_duplicates(responses)
    if near:
        warnings.append(f"near-duplicate response pairs over threshold: {len(near)}")

    counts = Counter(row.get("prompt_family") for row in rows)
    if len(counts) < 5:
        warnings.append(f"low prompt family coverage: {dict(counts)}")

    lengths = [len(re.findall(r"\b\w+\b", text)) for text in responses]
    if lengths:
        warnings.append(f"length_words min/avg/max: {min(lengths)}/{round(sum(lengths)/len(lengths), 2)}/{max(lengths)}")

    joined = "\n".join(responses).lower()
    for label, terms in {
        "refusal_inflation": ["i cannot", "i can't", "i will not"],
        "excessive_apology": ["sorry", "apologize"],
        "hedging": ["maybe", "perhaps", "might"],
        "boundary_phrase_overuse": ["boundary", "role limit"],
    }.items():
        count = sum(joined.count(term) for term in terms)
        rate = round(count / max(1, len(rows)), 4)
        warnings.append(f"{label}: {count} hits, per_sample={rate}")

    source_counts = Counter(row.get("source") for row in rows)
    warnings.append(f"source_distribution: {dict(source_counts)}")


def near_duplicates(texts: list[str]) -> list[tuple[int, int]]:
    token_sets = [set(re.findall(r"\b\w+\b", text.lower())) for text in texts]
    out = []
    for i, left in enumerate(token_sets):
        for j in range(i + 1, len(token_sets)):
            right = token_sets[j]
            if not left or not right:
                continue
            score = len(left & right) / len(left | right)
            if score >= 0.92:
                out.append((i, j))
    return out


def build_summary(rows: list[dict], errors: list[str], warnings: list[str]) -> dict:
    return {
        "dataset_rows": len(rows),
        "split_counts": dict(Counter(row.get("split") for row in rows)),
        "prompt_family_counts": dict(Counter(row.get("prompt_family") for row in rows)),
        "source_counts": dict(Counter(row.get("source") for row in rows)),
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }


def write_report(path: Path, dataset: str, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Post-training Dataset Validation\n\n"
        f"- Dataset: `{dataset}`\n"
        f"- Rows: {summary['dataset_rows']}\n"
        f"- Passed: {summary['passed']}\n"
        f"- Split counts: {summary['split_counts']}\n"
        f"- Prompt families: {summary['prompt_family_counts']}\n\n"
        "## Errors\n\n"
        + ("\n".join(f"- {e}" for e in summary["errors"]) or "- None")
        + "\n\n## Warnings\n\n"
        + ("\n".join(f"- {w}" for w in summary["warnings"]) or "- None")
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--report")
    parser.add_argument("--summary")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
