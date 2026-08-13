from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.audit import audit_registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit existing EmotionVector research datasets without model execution.")
    parser.add_argument(
        "--config",
        default="configs/research/data_foundation_audit_v0_1.json",
        help="Repository-relative audit registry.",
    )
    parser.add_argument(
        "--summary",
        default="results/summaries/research_data_foundation_audit_v0_1.json",
    )
    parser.add_argument(
        "--report",
        default="results/cards/research_data_foundation_audit_v0_1.md",
    )
    parser.add_argument("--check-only", action="store_true", help="Print audit JSON without writing artifacts.")
    return parser.parse_args()


def write_report(path: Path, result: dict) -> None:
    lines = [
        "# Research Data Foundation Audit v0.1",
        "",
        "## Scope",
        "",
        "Existing tracked local data only. No public dataset download, model run, embedding deduplication or human annotation was performed.",
        "",
        "## Summary",
        "",
        f"- datasets audited: {result['summary']['dataset_count']}",
        f"- datasets with blockers: {result['summary']['datasets_with_blockers']}",
        f"- blocker counts: `{json.dumps(result['summary']['blocker_counts'], sort_keys=True)}`",
        "",
        "## Dataset Evidence",
        "",
    ]
    for dataset in result["datasets"]:
        lines.extend(
            [
                f"### {dataset['dataset_id']}",
                "",
                f"- path: `{dataset['path']}`",
                f"- SHA-256: `{dataset['sha256']}`",
                f"- rows: {dataset['row_count']}",
                f"- splits: `{json.dumps(dataset['split_counts'], sort_keys=True)}`",
                f"- formal use status: `{dataset['formal_use_status']}`",
                f"- duplicate IDs: {dataset['duplicate_id_count']}",
                "- v2 family coverage: `" + json.dumps(
                    {field: value["coverage"] for field, value in dataset["family_field_coverage"].items()},
                    sort_keys=True,
                ) + "`",
                "- cross-split exact text duplicates: `" + json.dumps(
                    {
                        field: len(values)
                        for field, values in dataset["cross_split_exact_text_duplicates"].items()
                    },
                    sort_keys=True,
                ) + "`",
                "- legacy group leaks: `" + json.dumps(
                    {field: len(values) for field, values in dataset["legacy_group_leaks"].items()},
                    sort_keys=True,
                ) + "`",
                f"- template phrase rows: `{json.dumps(dataset['template_phrase_row_counts'], sort_keys=True)}`",
                f"- semantic duplicate check: `{dataset['semantic_duplicate_check']['status']}`",
                "- blockers:",
            ]
        )
        if dataset["blockers"]:
            for blocker in dataset["blockers"]:
                lines.append(
                    f"  - `{blocker['blocker_id']}` ({blocker['evidence_level']}): "
                    f"`{json.dumps(blocker['details'], sort_keys=True)}`"
                )
        else:
            lines.append("  - none detected by implemented checks")
        lines.append("")
    lines.extend(
        [
            "## Not Yet Verified",
            "",
            "- Human-valid task/scenario/template/semantic family assignments.",
            "- Embedding-based semantic deduplication and human cluster adjudication.",
            "- Independent human blind evaluation or annotation agreement.",
            "- Suitability of any public dataset for formal Trait mapping.",
            "",
            "## Claim Boundary",
            "",
            result["claim_boundary"],
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    config_path = ROOT / args.config
    registry = json.loads(config_path.read_text(encoding="utf-8"))
    result = audit_registry(ROOT, registry)
    if args.check_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    summary_path = ROOT / args.summary
    report_path = ROOT / args.report
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(report_path, result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
