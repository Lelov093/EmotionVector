"""Validate Trait Space seed datasets without model calls or extra deps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_FIELDS = {
    "sample_id",
    "axis_id",
    "pole",
    "split",
    "prompt_family",
    "scenario_id",
    "text",
    "language",
    "explicit_marker",
    "intensity",
    "source",
    "annotator",
    "created_at",
    "revision",
    "quality_flags",
    "confound_notes",
    "pair_id",
    "positive_negative_pair_role",
    "length_control_group",
    "task_answer_equivalence_group",
    "notes",
}

VALID_SPLITS = {"train", "dev", "test"}
VALID_LANGUAGES = {"zh", "en", "mixed"}
PLACEHOLDER_RE = re.compile(r"\b(TODO|placeholder|example|lorem|xxx)\b", re.I)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def load_registry(path: Path) -> dict[str, dict]:
    axes: dict[str, dict] = {}
    current: dict | None = None
    axis_re = re.compile(r"^\s+- axis_id: (.+?)\s*$")
    field_re = re.compile(r"^\s{8}([a-z_]+): (.+?)\s*$")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            axis_match = axis_re.match(line)
            if axis_match:
                axis_id = axis_match.group(1)
                current = {"axis_id": axis_id}
                axes[axis_id] = current
                continue
            if current is None:
                continue
            field_match = field_re.match(line)
            if field_match:
                key, value = field_match.groups()
                if value in {"true", "false"}:
                    current[key] = value == "true"
                else:
                    current[key] = value
    return axes


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def add_warning(warnings: list[str], message: str) -> None:
    warnings.append(message)


def validate(dataset: Path, manifest_path: Path, registry_path: Path) -> dict:
    rows = load_jsonl(dataset)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = load_registry(registry_path)
    first_batch_axes = sorted(
        axis_id for axis_id, axis in registry.items() if axis.get("recommended_first_batch") is True
    )

    errors: list[str] = []
    warnings: list[str] = []
    sample_ids: set[str] = set()
    text_counter: Counter[str] = Counter()
    pairs: dict[str, list[dict]] = defaultdict(list)

    for row_no, row in enumerate(rows, 1):
        missing = REQUIRED_FIELDS - row.keys()
        if missing:
            add_error(errors, f"row {row_no}: missing fields {sorted(missing)}")
            continue
        extra = set(row.keys()) - REQUIRED_FIELDS
        if extra:
            add_error(errors, f"{row['sample_id']}: unexpected fields {sorted(extra)}")
        if row["sample_id"] in sample_ids:
            add_error(errors, f"duplicate sample_id {row['sample_id']}")
        sample_ids.add(row["sample_id"])
        axis = registry.get(row["axis_id"])
        if axis is None:
            add_error(errors, f"{row['sample_id']}: axis_id not in registry: {row['axis_id']}")
        elif row["pole"] not in {axis.get("positive_pole"), axis.get("negative_pole")}:
            add_error(errors, f"{row['sample_id']}: pole {row['pole']} does not match axis {row['axis_id']}")
        if row["split"] not in VALID_SPLITS:
            add_error(errors, f"{row['sample_id']}: invalid split {row['split']}")
        if row["language"] not in VALID_LANGUAGES:
            add_error(errors, f"{row['sample_id']}: invalid language {row['language']}")
        if not isinstance(row["intensity"], int) or not 1 <= row["intensity"] <= 5:
            add_error(errors, f"{row['sample_id']}: intensity outside 1..5")
        if not isinstance(row["quality_flags"], list):
            add_error(errors, f"{row['sample_id']}: quality_flags must be an array")
        if not isinstance(row["confound_notes"], list):
            add_error(errors, f"{row['sample_id']}: confound_notes must be an array")
        if not str(row["text"]).strip():
            add_error(errors, f"{row['sample_id']}: empty text")
        if PLACEHOLDER_RE.search(row["text"]):
            add_error(errors, f"{row['sample_id']}: placeholder token found in text")
        text_counter[row["text"]] += 1
        pairs[row["pair_id"]].append(row)

    for text, count in text_counter.items():
        if count > 1:
            add_error(errors, f"duplicate text appears {count} times: {text[:80]}")

    pair_split_leaks = []
    for pair_id, items in pairs.items():
        if len(items) != 2:
            add_error(errors, f"{pair_id}: expected 2 samples, found {len(items)}")
            continue
        roles = {item["positive_negative_pair_role"] for item in items}
        if roles != {"positive", "negative"}:
            add_error(errors, f"{pair_id}: expected one positive and one negative role, found {sorted(roles)}")
        if len({item["axis_id"] for item in items}) != 1:
            add_error(errors, f"{pair_id}: axis mismatch inside pair")
        if len({item["split"] for item in items}) != 1:
            pair_split_leaks.append(pair_id)
            add_error(errors, f"{pair_id}: pair crosses split")
        if len({item["scenario_id"] for item in items}) != 1:
            add_error(errors, f"{pair_id}: scenario mismatch inside pair")
        lengths = [len(item["text"]) for item in items]
        if min(lengths) and max(lengths) / min(lengths) > 1.7:
            add_warning(warnings, f"{pair_id}: length ratio {max(lengths) / min(lengths):.2f} exceeds 1.70")

    pair_counts_by_axis_split: dict[str, Counter[str]] = defaultdict(Counter)
    sample_counts_by_split: Counter[str] = Counter()
    pair_counts_by_split: Counter[str] = Counter()
    families_by_axis: dict[str, set[str]] = defaultdict(set)
    train_families = {row["prompt_family"] for row in rows if row["split"] == "train"}

    for row in rows:
        sample_counts_by_split[row["split"]] += 1
        families_by_axis[row["axis_id"]].add(row["prompt_family"])
    for pair_id, items in pairs.items():
        if len(items) != 2:
            continue
        axis_id = items[0]["axis_id"]
        split = items[0]["split"]
        pair_counts_by_axis_split[axis_id][split] += 1
        pair_counts_by_split[split] += 1

    for split in VALID_SPLITS:
        if sample_counts_by_split[split] == 0:
            add_error(errors, f"split {split} has no samples")

    for axis_id in first_batch_axes:
        split_counts = pair_counts_by_axis_split[axis_id]
        actual = (split_counts["train"], split_counts["dev"], split_counts["test"])
        if actual != (6, 2, 2):
            add_error(errors, f"{axis_id}: expected 6/2/2 pairs, found {actual}")
        if len(families_by_axis[axis_id]) < 3:
            add_warning(warnings, f"{axis_id}: prompt families may be too narrow: {sorted(families_by_axis[axis_id])}")

    axes_in_dataset = sorted({row["axis_id"] for row in rows})
    if axes_in_dataset != first_batch_axes:
        add_error(errors, f"dataset axes {axes_in_dataset} do not match first-batch axes {first_batch_axes}")
    if len(pairs) != 60 or len(rows) != 120:
        add_error(errors, f"expected 60 pairs / 120 samples, found {len(pairs)} pairs / {len(rows)} samples")

    manifest_errors = compare_manifest(manifest, rows, pairs, pair_counts_by_split, sample_counts_by_split, train_families)
    errors.extend(manifest_errors)

    return {
        "passed": not errors,
        "dataset_path": str(dataset),
        "manifest_path": str(manifest_path),
        "validation_timestamp": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "samples": len(rows),
            "pairs": len(pairs),
            "samples_by_split": dict(sorted(sample_counts_by_split.items())),
            "pairs_by_split": dict(sorted(pair_counts_by_split.items())),
            "pairs_by_axis_split": {
                axis: dict(counter) for axis, counter in sorted(pair_counts_by_axis_split.items())
            },
        },
        "axis_coverage": axes_in_dataset,
        "first_batch_axes": first_batch_axes,
        "pair_leakage": {
            "cross_split_pair_count": len(pair_split_leaks),
            "cross_split_pair_ids": pair_split_leaks,
        },
        "prompt_family_holdout": check_prompt_family_holdout(manifest, train_families, rows),
        "warnings": warnings,
        "errors": errors,
        "suggested_fixes": suggested_fixes(errors, warnings),
    }


def compare_manifest(
    manifest: dict,
    rows: list[dict],
    pairs: dict[str, list[dict]],
    pair_counts_by_split: Counter[str],
    sample_counts_by_split: Counter[str],
    train_families: set[str],
) -> list[str]:
    errors = []
    if sorted(manifest.get("axes_included", [])) != sorted({row["axis_id"] for row in rows}):
        errors.append("manifest axes_included does not match dataset axes")
    if sorted(manifest.get("prompt_families", [])) != sorted({row["prompt_family"] for row in rows}):
        errors.append("manifest prompt_families does not match dataset prompt families")
    for split in ("train", "dev", "test"):
        expected = manifest.get("counts", {}).get(split, {})
        if expected.get("samples") != sample_counts_by_split[split]:
            errors.append(f"manifest {split}.samples mismatch")
        if expected.get("pairs") != pair_counts_by_split[split]:
            errors.append(f"manifest {split}.pairs mismatch")
    holdout = set(manifest.get("holdout_families", []))
    leaked = sorted(holdout & train_families)
    if leaked:
        errors.append(f"holdout families present in train split: {leaked}")
    return errors


def check_prompt_family_holdout(manifest: dict, train_families: set[str], rows: list[dict]) -> dict:
    holdout = set(manifest.get("holdout_families", []))
    test_families = {row["prompt_family"] for row in rows if row["split"] == "test"}
    return {
        "strict_family_level_holdout": bool(holdout),
        "holdout_families": sorted(holdout),
        "holdout_in_train": sorted(holdout & train_families),
        "holdout_in_test": sorted(holdout & test_families),
        "result": "pass" if holdout and not (holdout & train_families) and holdout <= test_families else "review_required",
    }


def suggested_fixes(errors: list[str], warnings: list[str]) -> list[str]:
    fixes = []
    if any("length ratio" in warning for warning in warnings):
        fixes.append("Review flagged pairs and shorten/expand one side before model extraction.")
    if any("holdout" in error for error in errors):
        fixes.append("Move held-out prompt families out of train or update the manifest.")
    if any("6/2/2" in error for error in errors):
        fixes.append("Rebalance each first-batch axis to 6 train, 2 dev, and 2 test pairs.")
    if not fixes and errors:
        fixes.append("Fix listed structural errors and rerun validation.")
    if not fixes and warnings:
        fixes.append("Warnings do not block the Batch 2 gate; review them before publication.")
    if not fixes:
        fixes.append("No blocking fixes. Proceed to Batch 3 after human review planning.")
    return fixes


def write_markdown_report(result: dict, report_path: Path, command: str) -> None:
    status = "PASS" if result["passed"] else "FAIL"
    lines = [
        "# Trait Space Seed v0.1 Validation Report",
        "",
        f"- validation command: `{command}`",
        f"- validation timestamp: `{result['validation_timestamp']}`",
        f"- dataset path: `{result['dataset_path']}`",
        f"- manifest path: `{result['manifest_path']}`",
        f"- final status: `{status}`",
        "",
        "## Counts",
        "",
        f"- sample count: {result['counts']['samples']}",
        f"- pair count: {result['counts']['pairs']}",
        f"- sample split counts: `{json.dumps(result['counts']['samples_by_split'], sort_keys=True)}`",
        f"- pair split counts: `{json.dumps(result['counts']['pairs_by_split'], sort_keys=True)}`",
        "",
        "## Axis Coverage",
        "",
        "- " + "\n- ".join(result["axis_coverage"]),
        "",
        "## Leakage",
        "",
        f"- cross-split pair leakage: {result['pair_leakage']['cross_split_pair_count']}",
        f"- prompt-family holdout result: `{result['prompt_family_holdout']['result']}`",
        f"- holdout families: `{json.dumps(result['prompt_family_holdout']['holdout_families'])}`",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in result["warnings"]] or ["- none"])
    lines.extend(["", "## Errors", ""])
    lines.extend([f"- {error}" for error in result["errors"]] or ["- none"])
    lines.extend(["", "## Known Limitations", ""])
    lines.extend(
        [
            "- Seed scale is sufficient for Batch 2 but not enough for broad publication claims.",
            "- Samples are initial curated seed data and still need independent human review.",
            "- Prompt-family holdout is implemented as axis-local test-family holdout, not a full ontology-wide family benchmark.",
        ]
    )
    lines.extend(["", "## Batch 2 Gate", ""])
    lines.append(f"- dataset passes Batch 2 gate: {'yes' if result['passed'] else 'no'}")
    lines.extend(["", "## Suggested Fixes", ""])
    lines.extend([f"- {fix}" for fix in result["suggested_fixes"]])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/trait_space/curated/trait_space_seed_v0_1.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("data/trait_space/splits/trait_space_seed_v0_1_split_manifest.json"))
    parser.add_argument("--registry", type=Path, default=Path("data/trait_space/axis_registry.yaml"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    result = validate(args.dataset, args.manifest, args.registry)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    if args.report:
        command = "python scripts/validate_trait_space_dataset.py --dataset " + str(args.dataset)
        command += " --manifest " + str(args.manifest)
        command += " --report " + str(args.report)
        write_markdown_report(result, args.report, command)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
