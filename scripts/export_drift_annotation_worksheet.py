"""
Export drift annotation cases to human-friendly Markdown + CSV worksheets.

Reads: data/annotations/drift_cases_for_human_annotation.jsonl
Writes: drift_annotation_worksheet.md, drift_annotation_worksheet.csv, worksheet_summary.json
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_for_human_annotation.jsonl"
MD_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_annotation_worksheet.md"
CSV_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_annotation_worksheet.csv"
SUMMARY_PATH = PROJECT_ROOT / "results" / "summary" / "drift_annotation_worksheet_summary.json"

LABEL_OPTIONS = ["no_drift", "mild_drift", "clear_drift", "uncertain"]


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def generate_markdown(cases: list[dict]) -> str:
    lines = [
        "# Drift Annotation Worksheet v0.2.1",
        "",
        "本文件用于人工标注 EmotionVector drift detector calibration cases。",
        "",
        "**重要原则**：",
        "- 不要参考 detector prediction 直接抄答案。",
        "- 不要因为回复短就判 drift。",
        "- 不要因为回复语气略有变化就判 drift。",
        "- 判断重点是角色回复是否偏离 character profile、scenario expectation、稳定性要求。",
        "- 如果信息不足，请标注 `uncertain`。",
        "- 本文件中的 annotation 字段当前全部为空，等待人工填写。",
        "",
        f"**Total cases**: {len(cases)}",
        "",
        f"**Label options**: {', '.join(f'`{l}`' for l in LABEL_OPTIONS)}",
        "",
        "---",
        "",
    ]

    for i, c in enumerate(cases):
        cid = c.get("case_id", f"case_{i+1:03d}")
        char = f"{c.get('character_name', '')} ({c.get('character_id', '')})"
        cond = c.get("condition", "N/A")
        stype = c.get("scenario_type", "N/A")
        dp = c.get("detector_prediction", {})
        risk = dp.get("risk_level", "N/A") if isinstance(dp, dict) else "N/A"
        dscore = dp.get("drift_score", "N/A") if isinstance(dp, dict) else "N/A"

        lines += [
            f"## Case {i+1:03d} — {cid}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Character | {char} |",
            f"| Condition | {cond} |",
            f"| Scenario Type | {stype} |",
            f"| Risk Level (Detector) | {risk} |",
            f"| Drift Score (Detector) | {dscore} |",
            "",
            "### Prompt",
            "",
            "```text",
            c.get("prompt", "N/A"),
            "```",
            "",
            "### Response",
            "",
            "```text",
            c.get("response", "N/A"),
            "```",
            "",
            "### Human Annotation (To Fill)",
            "",
            "```json",
            json.dumps({
                "human_drift_label": None,
                "human_drift_score": None,
                "error_type": None,
                "notes": "",
            }, indent=2, ensure_ascii=False),
            "```",
            "",
            "**Label Options**: " + " / ".join(LABEL_OPTIONS),
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def generate_csv(cases: list[dict]) -> None:
    fieldnames = [
        "case_id", "character", "condition", "scenario_type",
        "risk_level", "detector_score",
        "prompt", "response",
        "human_drift_label", "human_drift_score", "error_type", "notes",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for c in cases:
            dp = c.get("detector_prediction", {})
            writer.writerow({
                "case_id": c.get("case_id", ""),
                "character": c.get("character_name", c.get("character_id", "")),
                "condition": c.get("condition", ""),
                "scenario_type": c.get("scenario_type", ""),
                "risk_level": dp.get("risk_level", "") if isinstance(dp, dict) else "",
                "detector_score": dp.get("drift_score", "") if isinstance(dp, dict) else "",
                "prompt": c.get("prompt", ""),
                "response": c.get("response", ""),
                "human_drift_label": "",
                "human_drift_score": "",
                "error_type": "",
                "notes": "",
            })


def generate_summary(cases: list[dict]) -> dict:
    dist_char = dict(Counter(c.get("character_id", "?") for c in cases))
    dist_cond = dict(Counter(c.get("condition", "?") for c in cases))
    dist_type = dict(Counter(c.get("scenario_type", "?") for c in cases))
    dist_risk = dict(Counter(
        c.get("detector_prediction", {}).get("risk_level", "?")
        if isinstance(c.get("detector_prediction"), dict) else "?"
        for c in cases
    ))

    return {
        "status": "generated",
        "source": str(SOURCE_PATH),
        "outputs": {
            "markdown": str(MD_PATH),
            "csv": str(CSV_PATH),
        },
        "total_cases": len(cases),
        "human_annotation_fields_empty": True,
        "distributions": {
            "character": dist_char,
            "condition": dist_cond,
            "scenario_type": dist_type,
            "risk_level": dist_risk,
        },
        "warnings": [],
    }


def main() -> int:
    print("=" * 60)
    print("Export Drift Annotation Worksheet")
    print("=" * 60)

    if not SOURCE_PATH.exists():
        print(f"ERROR: {SOURCE_PATH} not found")
        return 1

    cases = load_jsonl(SOURCE_PATH)
    print(f"Loaded: {len(cases)} cases")

    # Markdown
    md = generate_markdown(cases)
    MD_PATH.write_text(md, encoding="utf-8")
    print(f"Markdown: {MD_PATH}")

    # CSV
    generate_csv(cases)
    print(f"CSV: {CSV_PATH}")

    # Summary
    summary = generate_summary(cases)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Summary: {SUMMARY_PATH}")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
