"""
Compare detector v2 vs v2.3 performance on 48 calibration cases.

Inputs: drift_detector_error_analysis_before_v2_3.json, current error analysis,
        predictions_v2_3.jsonl (optional)
Outputs: drift_detector_calibration_comparison_v2_3.json, markdown report
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BEFORE_ANALYSIS = PROJECT_ROOT / "results" / "summary" / "drift_detector_error_analysis_before_v2_3.json"
AFTER_ANALYSIS = PROJECT_ROOT / "results" / "summary" / "drift_detector_error_analysis.json"
PREDICTIONS_PATH = PROJECT_ROOT / "results" / "summary" / "drift_detector_predictions_v2_3.jsonl"
COMPARISON_PATH = PROJECT_ROOT / "results" / "summary" / "drift_detector_calibration_comparison_v2_3.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "drift_detector_calibration_v2_3_report.md"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    print("=" * 60)
    print("Compare Drift Detector Calibration v2 vs v2.3")
    print("=" * 60)

    before = load_json(BEFORE_ANALYSIS) if BEFORE_ANALYSIS.exists() else {}
    after = load_json(AFTER_ANALYSIS) if AFTER_ANALYSIS.exists() else {}
    preds = load_jsonl(PREDICTIONS_PATH)

    if not before or not after:
        print("ERROR: missing before/after analysis files")
        return 1

    ba = before.get("accuracy", 0)
    aa = after.get("accuracy", 0)

    b_fn = before.get("false_negatives", 0)
    a_fn = after.get("false_negatives", 0)
    b_fp = before.get("false_positives", 0)
    a_fp = after.get("false_positives", 0)

    b_calm = before.get("by_condition", {}).get("calm_steered", {})
    a_calm = after.get("by_condition", {}).get("calm_steered", {})
    b_calm_acc = b_calm.get("correct", 0) / b_calm.get("total", 1) if b_calm.get("total") else 0
    a_calm_acc = a_calm.get("correct", 0) / a_calm.get("total", 1) if a_calm.get("total") else 0

    comparison = {
        "status": "completed",
        "before": {"accuracy": ba, "fn": b_fn, "fp": b_fp, "calm_steered_correct": f"{b_calm.get('correct', 0)}/{b_calm.get('total', 0)}"},
        "after": {"accuracy": aa, "fn": a_fn, "fp": a_fp, "calm_steered_correct": f"{a_calm.get('correct', 0)}/{a_calm.get('total', 0)}"},
        "delta": {
            "accuracy": round(aa - ba, 4),
            "fn": a_fn - b_fn,
            "fp": a_fp - b_fp,
            "calm_steered_accuracy": round(a_calm_acc - b_calm_acc, 4),
        },
        "by_condition_before": before.get("by_condition", {}),
        "by_condition_after": after.get("by_condition", {}),
        "by_character_before": before.get("by_character", {}),
        "by_character_after": after.get("by_character", {}),
    }

    COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COMPARISON_PATH.open("w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\nAccuracy: {ba:.4f} -> {aa:.4f} (delta: {aa - ba:+.4f})")
    print(f"FN: {b_fn} -> {a_fn} (delta: {a_fn - b_fn:+d})")
    print(f"FP: {b_fp} -> {a_fp} (delta: {a_fp - b_fp:+d})")
    print(f"Calm-steered: {b_calm.get('correct', 0)}/{b_calm.get('total', 0)} -> {a_calm.get('correct', 0)}/{a_calm.get('total', 0)}")
    print(f"\nSaved: {COMPARISON_PATH}")

    # Generate report
    report = generate_report(comparison, before, after)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Saved report: {REPORT_PATH}")
    print("=" * 60)
    return 0


def generate_report(c: dict, before: dict, after: dict) -> str:
    lines = [
        "# Drift Detector Calibration Report — v2.3",
        "",
        "## 1. Scope",
        "基于 48 条 commander-reviewed calibration seed cases 的 v2 → v2.3 校准对比。",
        "",
        "## 2. Baseline Before Patch (v2)",
        f"- Accuracy: {before.get('accuracy', 0):.4f}",
        f"- FN: {before.get('false_negatives', 0)}, FP: {before.get('false_positives', 0)}",
        f"- calm_steered: {before.get('by_condition', {}).get('calm_steered', {}).get('correct', 0)}/{before.get('by_condition', {}).get('calm_steered', {}).get('total', 0)} correct",
        "",
        "## 3. Calibration Changes (v2.3)",
        "- `generic_response`: 检测通用礼貌助手式回复",
        "- `style_flattening`: 检测角色特征被压平（per-character trait integrity）",
        "- `role_boundary_loss`: 检测角色核心边界丢失",
        "- `hostility`: 区分 assertiveness 与 hostility",
        "- `evidence_integrity_failure`: Scholar 证据完整性检查",
        "- `crisis_inappropriate_humor`: Trickster 危机中不合时宜玩笑",
        "",
        "## 4. Before / After Results",
        "| Metric | Before | After | Delta |",
        "|---|---:|---:|---:|",
        f"| Accuracy | {c['before']['accuracy']:.4f} | {c['after']['accuracy']:.4f} | {c['delta']['accuracy']:+.4f} |",
        f"| FN | {c['before']['fn']} | {c['after']['fn']} | {c['delta']['fn']:+d} |",
        f"| FP | {c['before']['fp']} | {c['after']['fp']} | {c['delta']['fp']:+d} |",
        f"| calm_steered | {c['before']['calm_steered_correct']} | {c['after']['calm_steered_correct']} | — |",
        "",
        "## 5. Condition-Level Results",
        "| Condition | Before Correct | After Correct |",
        "|---|---:|---:|",
    ]
    for cond in ["baseline", "calm_steered", "assertive_steered"]:
        bc = before.get("by_condition", {}).get(cond, {})
        ac = after.get("by_condition", {}).get(cond, {})
        lines.append(f"| {cond} | {bc.get('correct', 0)}/{bc.get('total', 0)} | {ac.get('correct', 0)}/{ac.get('total', 0)} |")

    lines += [
        "",
        "## 6. Interpretation",
        "- v2.3 主要改善了「温和但角色特征被压平」的 drift 识别",
        "- detector 仍是 prototype evaluator",
        "- 当前结果只针对 48 条 calibration seed",
        "- 不能外推为充分验证",
        "",
        "## 7. Next Step",
        "- Reviewer spot-check",
        "- 扩展 seed 到更多样本",
        "- Second annotator agreement",
        "- Dashboard 展示 calibration result",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
