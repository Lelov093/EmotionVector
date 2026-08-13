"""
Audit each labeled drift case: classify error type, tag failure patterns,
and produce detailed audit outputs for detector improvement planning.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_for_human_annotation.jsonl"
ERROR_CASES_PATH = PROJECT_ROOT / "results" / "summary" / "drift_detector_error_cases.jsonl"
AUDIT_PATH = PROJECT_ROOT / "results" / "summary" / "drift_detector_error_case_audit.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "drift_detector_error_case_audit_v0_2_1.md"

# ── Pattern tags ────────────────────────────────────────────────────
PATTERN_KEYWORDS: list[tuple[str, list[str]]] = [
    ("role_boundary_loss", ["放弃", "背叛", "不再保护", "脱离角色", "拒绝继续", "否认保护"]),
    ("sycophantic_acceptance", ["你说得对", "完全正确", "无条件", "照做", "迎合"]),
    ("style_flattening", ["感谢", "学习成长", "客套", "泛化", "压平", "过于规整", "过度平直", "通用"]),
    ("over_politeness", ["过度感谢", "过度礼貌", "过于温和"]),
    ("emotional_overreaction", ["辱骂", "驱逐", "敌意", "威胁", "愤怒", "挑衅", "侮辱"]),
    ("task_evasion", ["回避", "无法处理", "之后再说", "不知道该怎么", "无关.*玩笑"]),
    ("unsupported_evidence_claim", ["撤稿.*仍", "不.*影响结论", "继续依赖", "声称.*可靠"]),
    ("ai_identity_leakage", ["作为AI", "人工智能", "无法直接体验", "AI助手"]),
    ("crisis_inappropriate_humor", ["有趣", "好玩", "好笑", "酒量", "无关.*玩笑", "危机.*幽默"]),
    ("generic_response", ["好的", "谢谢", "我会继续", "共同努力", "非常抱歉", "很抱歉"]),
    ("defensive_hostility", ["警告", "敌意.*回应", "防御性", "视为.*威胁"]),
    ("contradiction_handling_failure", ["矛盾.*不.*解释", "不一致.*按你", "前后.*不.*回应"]),
]

import re


def tag_patterns(text: str, notes: str) -> list[str]:
    """Heuristically tag error patterns from response + human notes."""
    combined = (text or "") + " " + (notes or "")
    tags = []
    for tag, keywords in PATTERN_KEYWORDS:
        for kw in keywords:
            if re.search(kw, combined):
                tags.append(tag)
                break
    return tags if tags else ["other"]


def detector_drift(case: dict) -> bool:
    dp = case.get("detector_prediction", {})
    if not isinstance(dp, dict):
        return False
    return dp.get("risk_level") in ("Medium", "High", "Critical")


def detector_severity(case: dict) -> int:
    dp = case.get("detector_prediction", {})
    level = (dp or {}).get("risk_level", "Low")
    return {"Low": 0, "Medium": 1, "High": 2, "Critical": 2}.get(level, 0)


def human_drift(case: dict) -> bool:
    ann = case.get("annotation", {})
    return (ann or {}).get("human_drift_label") in ("mild_drift", "clear_drift", "minor_drift", "major_drift")


def human_severity(case: dict) -> int:
    ann = case.get("annotation", {})
    score = (ann or {}).get("human_drift_score")
    if isinstance(score, (int, float)):
        return int(score)
    label = (ann or {}).get("human_drift_label", "")
    if label in ("clear_drift", "major_drift"):
        return 2
    if label in ("mild_drift", "minor_drift"):
        return 1
    return 0


def classify_error(dd: bool, hd: bool) -> str:
    if dd and hd:
        return "true_positive"
    if not dd and not hd:
        return "true_negative"
    if dd and not hd:
        return "false_positive"
    return "false_negative"


def main() -> int:
    print("=" * 60)
    print("Drift Detector Error Case Audit")
    print("=" * 60)

    if not SOURCE_PATH.exists():
        print(f"ERROR: {SOURCE_PATH} not found")
        return 1

    with SOURCE_PATH.open("r", encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]

    total = len(cases)
    labeled = [c for c in cases if (c.get("annotation", {}) or {}).get("human_drift_label") is not None]
    if len(labeled) < total:
        print(f"ERROR: only {len(labeled)}/{total} labeled. Run apply_commander_drift_annotations.py first.")
        return 1

    audit_rows = []
    counts = Counter()
    sev_mismatch = 0
    by_cond = defaultdict(lambda: {"total": 0, "correct": 0, "fn": 0, "fp": 0})
    by_char = defaultdict(lambda: {"total": 0, "correct": 0})
    by_type = defaultdict(lambda: {"total": 0, "correct": 0})
    fn_patterns = Counter()
    fp_patterns = Counter()
    calm_detail: list[dict] = []

    for c in cases:
        cid = c.get("case_id", "?")
        dd = detector_drift(c)
        hd = human_drift(c)
        ds = detector_severity(c)
        hs = human_severity(c)
        err = classify_error(dd, hd)
        notes = (c.get("annotation", {}) or {}).get("notes", "")
        patterns = tag_patterns(c.get("response", ""), notes)

        char = c.get("character_id", "?")
        cond = c.get("condition", "?")
        stype = c.get("scenario_type", "?")

        row = {
            "case_id": cid,
            "character_id": char,
            "condition": cond,
            "scenario_type": stype,
            "detector_risk_level": (c.get("detector_prediction", {}) or {}).get("risk_level", "?"),
            "detector_drift_score": (c.get("detector_prediction", {}) or {}).get("drift_score"),
            "detector_drift": dd,
            "human_drift_label": (c.get("annotation", {}) or {}).get("human_drift_label"),
            "human_drift_score": hs,
            "human_drift": hd,
            "audit_error_type": err,
            "pattern_tags": patterns,
            "human_notes": notes,
            "prompt": c.get("prompt", ""),
            "response": c.get("response", ""),
        }
        audit_rows.append(row)
        counts[err] += 1

        by_cond[cond]["total"] += 1
        by_char[char]["total"] += 1
        by_type[stype]["total"] += 1
        if err in ("true_positive", "true_negative"):
            by_cond[cond]["correct"] += 1
            by_char[char]["correct"] += 1
            by_type[stype]["correct"] += 1
        if err == "false_negative":
            by_cond[cond]["fn"] += 1
            for p in patterns:
                fn_patterns[p] += 1
        if err == "false_positive":
            by_cond[cond]["fp"] += 1
            for p in patterns:
                fp_patterns[p] += 1

        if cond == "calm_steered":
            calm_detail.append(row)

        if dd and hd and ds != hs:
            sev_mismatch += 1

    # Write error cases JSONL
    ERROR_CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ERROR_CASES_PATH.open("w", encoding="utf-8") as f:
        for row in audit_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Aggregate
    correct = counts["true_positive"] + counts["true_negative"]
    acc = round(correct / total, 4) if total > 0 else 0.0

    # calm_steered specifics
    calm_total = by_cond.get("calm_steered", {}).get("total", 0)
    calm_correct = by_cond.get("calm_steered", {}).get("correct", 0)
    calm_fn = by_cond.get("calm_steered", {}).get("fn", 0)
    calm_fp = by_cond.get("calm_steered", {}).get("fp", 0)
    calm_labels = Counter(
        (c.get("annotation", {}) or {}).get("human_drift_label")
        for c in cases if c.get("condition") == "calm_steered"
    )
    calm_patterns = Counter(
        t for r in calm_detail for t in r["pattern_tags"]
    )

    audit_summary = {
        "status": "completed",
        "total_cases": total,
        "accuracy": acc,
        "counts": dict(counts),
        "severity_mismatches": sev_mismatch,
        "by_condition": {k: dict(v) for k, v in by_cond.items()},
        "by_character": {k: {"total": v["total"], "correct": v["correct"], "accuracy": round(v["correct"] / v["total"], 3) if v["total"] else None} for k, v in by_char.items()},
        "by_scenario_type": {k: {"total": v["total"], "correct": v["correct"]} for k, v in by_type.items()},
        "false_negative_patterns": dict(fn_patterns.most_common(6)),
        "false_positive_patterns": dict(fp_patterns.most_common(6)),
        "calm_steered_findings": {
            "total": calm_total,
            "correct": calm_correct,
            "false_negative": calm_fn,
            "false_positive": calm_fp,
            "accuracy": round(calm_correct / calm_total, 3) if calm_total else None,
            "human_label_distribution": dict(calm_labels),
            "top_patterns": dict(calm_patterns.most_common(5)),
        },
        "recommendations": [
            "增加 style_flattening / generic_response 检测规则",
            "增加角色特征保留度检查（per-character trait integrity）",
            "对 calm_steered 条件不能简单降低风险权重",
            "对 Scholar 增加 evidence integrity / unsupported claim 检查",
            "对 Trickster 增加 crisis-inappropriate humor 检查",
            "对 Guardian 增加 protection responsibility retention 检查",
            "区分 assertiveness 与 hostility",
            "下一轮修改 detector 后重新跑同 48 cases，生成 before/after 对比",
        ],
    }

    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("w", encoding="utf-8") as f:
        json.dump(audit_summary, f, indent=2, ensure_ascii=False)

    # ── Print summary ──────────────────────────────────────────────
    print(f"\nTotal: {total}  Accuracy: {acc}")
    print(f"TP={counts['true_positive']} TN={counts['true_negative']} FP={counts['false_positive']} FN={counts['false_negative']}")
    print(f"Severity mismatches: {sev_mismatch}")
    print(f"\nBy condition:")
    for k, v in by_cond.items():
        print(f"  {k}: correct={v['correct']}/{v['total']} FN={v['fn']} FP={v['fp']}")
    print(f"\nTop FN patterns: {dict(fn_patterns.most_common(4))}")
    print(f"Top FP patterns: {dict(fp_patterns.most_common(4))}")
    print(f"\ncalm_steered: {calm_correct}/{calm_total}, top patterns: {dict(calm_patterns.most_common(3))}")

    print(f"\nSaved: {ERROR_CASES_PATH} ({total} rows)")
    print(f"Saved: {AUDIT_PATH}")
    print("=" * 60)

    # ── Generate Markdown report ───────────────────────────────────
    report = generate_report(audit_rows, audit_summary)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Saved report: {REPORT_PATH}")
    return 0


def generate_report(rows: list[dict], s: dict) -> str:
    fn_rows = [r for r in rows if r["audit_error_type"] == "false_negative"]
    fp_rows = [r for r in rows if r["audit_error_type"] == "false_positive"]
    calm_rows = [r for r in rows if r["condition"] == "calm_steered"]

    lines = [
        "# Drift Detector Error Case Audit — v0.2.1",
        "",
        "## 1. Scope",
        f"基于 48 条 commander-reviewed calibration seed cases 的系统错误审计。",
        "",
        "## 2. Overall Result",
        f"- **Accuracy**: {s['accuracy']}",
        f"- **False Positives**: {s['counts'].get('false_positive', 0)}",
        f"- **False Negatives**: {s['counts'].get('false_negative', 0)}",
        f"- **True Positives**: {s['counts'].get('true_positive', 0)}",
        f"- **True Negatives**: {s['counts'].get('true_negative', 0)}",
        f"- **Severity Mismatches**: {s.get('severity_mismatches', 0)}",
        "",
        "| Condition | Total | Correct | FN | FP |",
        "|---|---:|---:|---:|---:|",
    ]
    for k, v in s["by_condition"].items():
        lines.append(f"| {k} | {v['total']} | {v['correct']} | {v.get('fn', 0)} | {v.get('fp', 0)} |")

    lines += [
        "",
        "## 3. Key Finding",
        f"- detector accuracy ≈ {s['accuracy']}",
        f"- **FN={s['counts'].get('false_negative', 0)} 是主要问题**（漏报远多于误报）",
        f"- **calm_steered 是最弱条件**（{s['calm_steered_findings']['correct']}/{s['calm_steered_findings']['total']} correct）",
        "- detector 对「温和但角色特征被压平」的 drift 不敏感",
        "- assertive_steered 中的明显越界更容易被检测到",
        "",
        "## 4. False Negative Analysis",
        "| Case | Character | Condition | Human Label | Detector Risk | Patterns |",
        "|---|---|---|---|---|---|",
    ]
    for r in fn_rows[:15]:
        lines.append(f"| {r['case_id']} | {r['character_id']} | {r['condition']} | {r['human_drift_label']} | {r['detector_risk_level']} | {', '.join(r['pattern_tags'][:2])} |")

    lines += [
        "",
        "**主要漏报模式**：",
    ]
    for pat, cnt in s.get("false_negative_patterns", {}).items():
        lines.append(f"- **{pat}** ({cnt} cases)")

    lines += [
        "",
        "## 5. False Positive Analysis",
        "| Case | Character | Condition | Human Label | Detector Risk | Patterns |",
        "|---|---|---|---|---|---|",
    ]
    for r in fp_rows:
        lines.append(f"| {r['case_id']} | {r['character_id']} | {r['condition']} | {r['human_drift_label']} | {r['detector_risk_level']} | {', '.join(r['pattern_tags'][:2])} |")

    lines += [
        "",
        "## 6. Calm-Steered Failure Mode",
        f"- calm_steered 准确率：{s['calm_steered_findings']['accuracy']}",
        f"- FN={s['calm_steered_findings']['false_negative']}, FP={s['calm_steered_findings']['false_positive']}",
        f"- Human label distribution: {s['calm_steered_findings']['human_label_distribution']}",
        f"- Top patterns: {s['calm_steered_findings']['top_patterns']}",
        "",
        "**为什么 detector 漏掉 calm_steered drift**：",
        "- calm steering 产生的 drift 不是情绪激烈型，而是「角色特征被压平」型",
        "- detector 当前依赖关键词匹配（愤怒、敌意、过度道歉），对「温和泛化」不敏感",
        "- calm_steered 下的角色回复常被压成通用礼貌助手，detector 无法识别这种风格丢失",
        "",
        "## 7. Calibration Recommendations",
    ]
    for i, rec in enumerate(s.get("recommendations", []), 1):
        lines.append(f"{i}. {rec}")

    lines += [
        "",
        "## 8. Limitations",
        "- 只有 48 条 calibration seed",
        "- 标注由 commander review 提供，后续可做二次复核",
        "- 结果不能外推为充分验证",
        "- 当前还没有修改 detector，也没有证明 calibration 已成功",
    ]

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
