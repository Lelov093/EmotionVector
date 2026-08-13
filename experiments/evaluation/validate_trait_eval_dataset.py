from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED = {
    "eval_id",
    "axis_id",
    "target_pole",
    "contrast_pole",
    "prompt_family",
    "scenario_id",
    "user_prompt",
    "expected_behavior",
    "risk_notes",
    "confounds",
    "source",
    "derived_from",
    "generator_model",
    "human_annotated",
    "split",
    "created_at",
    "revision",
}


def main() -> int:
    args = parse_args()
    rows = read_jsonl(resolve(args.dataset))
    registry = yaml.safe_load(resolve(args.axis_registry).read_text(encoding="utf-8"))
    poles = axis_poles(registry)
    errors: list[str] = []
    warnings: list[str] = []
    validate_required(rows, errors)
    validate_axes(rows, poles, errors)
    validate_splits(rows, errors)
    validate_sources(rows, errors)
    validate_leakage(rows, errors)
    validate_text_quality(rows, warnings)
    summary = build_summary(rows, errors, warnings)
    write_json(resolve(args.summary), summary)
    write_report(resolve(args.report), args.dataset, summary)
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


def validate_required(rows: list[dict], errors: list[str]) -> None:
    ids = Counter(row.get("eval_id") for row in rows)
    for idx, row in enumerate(rows, start=1):
        missing = REQUIRED - set(row)
        if missing:
            errors.append(f"row {idx} missing fields: {sorted(missing)}")
        if ids[row.get("eval_id")] > 1:
            errors.append(f"duplicate eval_id: {row.get('eval_id')}")


def validate_axes(rows: list[dict], poles: dict[str, tuple[str, str]], errors: list[str]) -> None:
    covered = {row.get("axis_id") for row in rows}
    missing_axes = set(poles) - covered
    extra_axes = covered - set(poles)
    if missing_axes:
        errors.append(f"missing axes: {sorted(missing_axes)}")
    if extra_axes:
        errors.append(f"unknown axes: {sorted(extra_axes)}")
    for axis_id, (positive, negative) in poles.items():
        axis_rows = [row for row in rows if row.get("axis_id") == axis_id]
        if len(axis_rows) < 8:
            errors.append(f"{axis_id} has fewer than 8 prompts: {len(axis_rows)}")
        families = {row.get("prompt_family") for row in axis_rows}
        if len(families) < 3:
            errors.append(f"{axis_id} has fewer than 3 prompt families: {sorted(families)}")
        for row in axis_rows:
            if row.get("target_pole") != positive or row.get("contrast_pole") != negative:
                errors.append(f"{row.get('eval_id')} has invalid poles for {axis_id}")


def validate_splits(rows: list[dict], errors: list[str]) -> None:
    allowed = {"dev", "test"}
    bad = {row.get("split") for row in rows} - allowed
    if bad:
        errors.append(f"invalid splits: {sorted(bad)}")
    for axis_id in sorted({row.get("axis_id") for row in rows}):
        counts = Counter(row.get("split") for row in rows if row.get("axis_id") == axis_id)
        if counts.get("dev", 0) < 3:
            errors.append(f"{axis_id} dev split too small: {counts.get('dev', 0)}")
        if counts.get("test", 0) < 5:
            errors.append(f"{axis_id} test split too small: {counts.get('test', 0)}")


def validate_sources(rows: list[dict], errors: list[str]) -> None:
    allowed_sources = {"derived_from_trait_seed", "curated_by_codex_from_axis_registry", "llm_generated_candidate", "judge_filtered_candidate"}
    for row in rows:
        if row.get("source") not in allowed_sources:
            errors.append(f"{row.get('eval_id')} invalid source: {row.get('source')}")
        if not row.get("derived_from"):
            errors.append(f"{row.get('eval_id')} missing derived_from")
        if row.get("human_annotated") is not False:
            errors.append(f"{row.get('eval_id')} has fake or non-false human_annotated")


def validate_leakage(rows: list[dict], errors: list[str]) -> None:
    split_by_scenario: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        split_by_scenario[row.get("scenario_id")].add(row.get("split"))
    leaks = {k: v for k, v in split_by_scenario.items() if len(v) > 1}
    if leaks:
        errors.append(f"scenario leakage across splits: {list(leaks)[:5]}")


def validate_text_quality(rows: list[dict], warnings: list[str]) -> None:
    prompts = [row.get("user_prompt", "") for row in rows]
    duplicates = sum(c - 1 for c in Counter(prompts).values() if c > 1)
    if duplicates:
        warnings.append(f"duplicate prompts: {duplicates}")
    near = near_duplicate_count(prompts)
    if near:
        warnings.append(f"near_duplicate_prompt_pairs: {near}")
    phrase_limits = {
        "The request asks me to": 0,
        "If you want, I can help": 0,
        "please be": 5,
        "act more": 5,
    }
    joined = "\n".join(prompts).lower()
    for phrase, limit in phrase_limits.items():
        hits = joined.count(phrase.lower())
        if hits > limit:
            warnings.append(f"synthetic_or_leading_phrase_overuse: {phrase} hits={hits}")
    refusal_terms = ["cannot", "can't", "refuse", "not allowed", "safety"]
    refusal_hits = sum(joined.count(t) for t in refusal_terms)
    if refusal_hits > len(rows) * 0.35:
        warnings.append(f"refusal_heavy_warning: {refusal_hits} prompt hits")
    boundary_hits = sum(joined.count(t) for t in ["boundary", "role limit", "safe alternative"])
    if boundary_hits > len(rows) * 0.25:
        warnings.append(f"boundary_phrase_overuse_warning: {boundary_hits} prompt hits")
    apology_hits = sum(joined.count(t) for t in ["sorry", "apologize"])
    if apology_hits > len(rows) * 0.1:
        warnings.append(f"excessive_apology_warning: {apology_hits} prompt hits")
    hedging_hits = sum(joined.count(t) for t in ["maybe", "perhaps", "might"])
    if hedging_hits > len(rows) * 0.2:
        warnings.append(f"excessive_hedging_warning: {hedging_hits} prompt hits")


def build_summary(rows: list[dict], errors: list[str], warnings: list[str]) -> dict:
    return {
        "dataset_rows": len(rows),
        "axis_count": len({row.get("axis_id") for row in rows}),
        "split_counts": dict(Counter(row.get("split") for row in rows)),
        "source_counts": dict(Counter(row.get("source") for row in rows)),
        "prompt_family_count_by_axis": {
            axis: len({row.get("prompt_family") for row in rows if row.get("axis_id") == axis})
            for axis in sorted({row.get("axis_id") for row in rows})
        },
        "counts_by_axis_split": {
            axis: dict(Counter(row.get("split") for row in rows if row.get("axis_id") == axis))
            for axis in sorted({row.get("axis_id") for row in rows})
        },
        "human_annotated_true_count": sum(1 for row in rows if row.get("human_annotated") is True),
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }


def write_report(path: Path, dataset: str, summary: dict) -> None:
    text = "# Trait Eval 12-axis v0.1 Validation Report\n\n"
    text += f"- Dataset: `{dataset}`\n"
    text += f"- Rows: {summary['dataset_rows']}\n"
    text += f"- Axis count: {summary['axis_count']}\n"
    text += f"- Split counts: {summary['split_counts']}\n"
    text += f"- Human annotated true count: {summary['human_annotated_true_count']}\n"
    text += f"- Passed: {summary['passed']}\n\n"
    text += "## Errors\n\n" + ("\n".join(f"- {e}" for e in summary["errors"]) or "- None") + "\n\n"
    text += "## Warnings\n\n" + ("\n".join(f"- {w}" for w in summary["warnings"]) or "- None") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def axis_poles(registry: dict) -> dict[str, tuple[str, str]]:
    out = {}
    for group in registry["groups"].values():
        for axis in group["axes"]:
            out[axis["axis_id"]] = (axis["positive_pole"], axis["negative_pole"])
    return out


def near_duplicate_count(texts: list[str]) -> int:
    sets = [set(re.findall(r"\b\w+\b", text.lower())) for text in texts]
    count = 0
    for i, left in enumerate(sets):
        for right in sets[i + 1 :]:
            if left and right and len(left & right) / len(left | right) >= 0.9:
                count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--axis-registry", default="data/trait_space/axis_registry.yaml")
    parser.add_argument("--report", required=True)
    parser.add_argument("--summary", required=True)
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
