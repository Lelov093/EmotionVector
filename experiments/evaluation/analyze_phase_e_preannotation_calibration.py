from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    args = parse_args()
    rows = read_jsonl(resolve(args.merged))
    calibration = analyze_calibration(rows)
    taxonomy = build_taxonomy(rows)
    write_json(resolve(args.summary), calibration["summary"])
    write_jsonl(resolve(args.vs_judge), calibration["vs_judge"])
    write_jsonl(resolve(args.vs_heuristic), calibration["vs_heuristic"])
    write_report(resolve(args.report), calibration["summary"])
    write_json(resolve(args.taxonomy_json), taxonomy)
    write_taxonomy_md(resolve(args.taxonomy_md), taxonomy)
    print(json.dumps({"analysis": "PASS", "items": len(rows), "axes": len(taxonomy["axes"])}, indent=2))
    return 0


def analyze_calibration(rows: list[dict]) -> dict:
    vs_judge = []
    vs_heuristic = []
    for row in rows:
        ai_pref = row["ai_preannotation"]["preferred_output"]
        for judge in row["external_judge"].get("phase_e_batch2_pairwise", []):
            judge_pref = judge_condition(judge)
            vs_judge.append(
                {
                    "review_item_id": row["review_item_id"],
                    "axis_id": row["axis_id"],
                    "comparison_type": row["comparison_type"],
                    "ai_preannotation_preferred": ai_pref,
                    "external_judge_preferred": judge_pref,
                    "agreement": agree(ai_pref, judge_pref),
                    "judge_confidence": judge["llm_judge"]["confidence"],
                }
            )
        heuristic_pref = heuristic_preferred(row)
        vs_heuristic.append(
            {
                "review_item_id": row["review_item_id"],
                "axis_id": row["axis_id"],
                "comparison_type": row["comparison_type"],
                "ai_preannotation_preferred": ai_pref,
                "heuristic_preferred": heuristic_pref,
                "agreement": agree(ai_pref, heuristic_pref),
            }
        )

    summary = {
        "created_at": utcnow(),
        "item_count": len(rows),
        "preferred_output_distribution": dict(Counter(r["ai_preannotation"]["preferred_output"] for r in rows)),
        "per_axis_preferred_output_distribution": per_axis_pref(rows),
        "comparison_type_distribution": dict(Counter(r["comparison_type"] for r in rows)),
        "ai_vs_external_judge": summarize_agreement(vs_judge),
        "ai_vs_heuristic": summarize_agreement(vs_heuristic),
        "confidence_distribution": dict(Counter(str(r["ai_preannotation"]["confidence"]) for r in rows)),
        "side_effect_score_distribution": dict(Counter(str(r["ai_preannotation"]["side_effect_score"]) for r in rows)),
        "failure_tag_frequency": dict(Counter(tag for r in rows for tag in r["ai_preannotation"].get("failure_tags", []))),
        "main_observed_patterns": observed_patterns(rows),
        "claim_boundary": "AI preannotation with user secondary review is not independent human annotation.",
    }
    return {"summary": summary, "vs_judge": vs_judge, "vs_heuristic": vs_heuristic}


def build_taxonomy(rows: list[dict]) -> dict:
    axes = {}
    for axis in sorted({r["axis_id"] for r in rows}):
        items = [r for r in rows if r["axis_id"] == axis]
        tags = Counter(tag for r in items for tag in r["ai_preannotation"].get("failure_tags", []))
        prefs = Counter(r["ai_preannotation"]["preferred_output"] for r in items)
        disagreements = sum(1 for r in items if not agree(r["ai_preannotation"]["preferred_output"], heuristic_preferred(r)))
        steering_items = sum(1 for r in items if r["outputs"]["selected_steering"]["text"])
        axes[axis] = {
            "difficulty": difficulty(items, disagreements),
            "base_already_strong": prefs["base"] >= 2,
            "prompt_only_effect": prompt_effect(prefs),
            "selected_steering_availability": "partial" if steering_items else "none",
            "selected_steering_signal": steering_signal(prefs, steering_items),
            "disagreement_level": level(disagreements, len(items)),
            "common_failure_modes": [tag for tag, _ in tags.most_common(4)],
            "recommended_next_action": next_action(axis, prefs, tags, steering_items),
        }
    return {"created_at": utcnow(), "axes": axes}


def judge_condition(judge: dict) -> str:
    preferred = judge["llm_judge"]["preferred_output"]
    if preferred == "tie":
        return "tie"
    cond = judge["condition_a"] if preferred == "A" else judge["condition_b"]
    return norm_condition(cond)


def heuristic_preferred(row: dict) -> str:
    scores = row.get("heuristic_scores", {})
    available = [name for name in ["base", "prompt-only", "selected-steering"] if row["outputs"].get(name.replace("-", "_"), {}).get("text") or row["outputs"].get(name, {}).get("text")]
    vals = {norm_condition(name): score(scores.get(name, {})) for name in available}
    if not vals:
        return "tie"
    ordered = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
    return "tie" if len(ordered) > 1 and ordered[0][1] == ordered[1][1] else ordered[0][0]


def score(s: dict) -> float:
    return s.get("trait_expression_score", 0) + s.get("response_quality_score", 0) + s.get("usefulness_score", 0) - s.get("side_effect_load", 0)


def norm_condition(value: str) -> str:
    return value.replace("-", "_")


def agree(a: str, b: str) -> bool:
    return norm_condition(a) == norm_condition(b)


def summarize_agreement(records: list[dict]) -> dict:
    return {
        "count": len(records),
        "agreement": sum(1 for r in records if r["agreement"]),
        "disagreement": sum(1 for r in records if not r["agreement"]),
        "tie_related_ambiguity": sum(1 for r in records if "tie" in {r.get("ai_preannotation_preferred"), r.get("external_judge_preferred"), r.get("heuristic_preferred")}),
    }


def per_axis_pref(rows: list[dict]) -> dict:
    out = {}
    for axis in sorted({r["axis_id"] for r in rows}):
        out[axis] = dict(Counter(r["ai_preannotation"]["preferred_output"] for r in rows if r["axis_id"] == axis))
    return out


def observed_patterns(rows: list[dict]) -> list[str]:
    prefs = Counter(r["ai_preannotation"]["preferred_output"] for r in rows)
    tags = Counter(tag for r in rows for tag in r["ai_preannotation"].get("failure_tags", []))
    patterns = [
        f"Prompt-only was preferred most often ({prefs.get('prompt_only', 0)} / {len(rows)}).",
        f"Base was still preferred in {prefs.get('base', 0)} cases, showing several base-strong prompts.",
        f"Selected steering was preferred in {prefs.get('selected_steering', 0)} cases, so the steering signal remains mixed.",
    ]
    for tag, count in tags.most_common(5):
        patterns.append(f"Common tag: {tag} ({count}).")
    return patterns


def difficulty(items: list[dict], disagreements: int) -> str:
    avg_conf = sum(i["ai_preannotation"]["confidence"] for i in items) / len(items)
    if avg_conf >= 4 and disagreements <= 1:
        return "easy"
    if avg_conf <= 3 or disagreements >= 2:
        return "hard"
    return "medium"


def prompt_effect(prefs: Counter) -> str:
    if prefs["prompt_only"] >= 2:
        return "strong"
    if prefs["prompt_only"] == 1:
        return "moderate"
    return "weak"


def steering_signal(prefs: Counter, steering_items: int) -> str:
    if not steering_items:
        return "unavailable"
    if prefs["selected_steering"] >= 2:
        return "positive"
    if prefs["selected_steering"] == 1:
        return "mixed"
    return "weak"


def level(count: int, total: int) -> str:
    ratio = count / max(total, 1)
    if ratio >= 0.67:
        return "high"
    if ratio >= 0.34:
        return "medium"
    return "low"


def next_action(axis: str, prefs: Counter, tags: Counter, steering_items: int) -> str:
    if "output_truncated" in tags:
        return "rerun a small subset with higher max_new_tokens before final claims"
    if prefs["prompt_only"] >= 2:
        return "treat prompt-only as a strong baseline for this axis"
    if steering_items and prefs["selected_steering"] == 0:
        return "do not prioritize steering expansion until vector effect is clearer"
    if "prompt_only_overly_poetic" in tags or "prompt_only_axis_leakage" in tags:
        return "tighten prompt-only instruction and check style leakage"
    return "retain in final review set and calibrate with human review"


def write_report(path: Path, summary: dict) -> None:
    path.write_text(
        "# Phase E Batch 3 Preannotation Calibration Report\n\n"
        f"- item_count: {summary['item_count']}\n"
        f"- preferred_output_distribution: {summary['preferred_output_distribution']}\n"
        f"- comparison_type_distribution: {summary['comparison_type_distribution']}\n"
        f"- ai_vs_external_judge: {summary['ai_vs_external_judge']}\n"
        f"- ai_vs_heuristic: {summary['ai_vs_heuristic']}\n"
        f"- confidence_distribution: {summary['confidence_distribution']}\n"
        f"- side_effect_score_distribution: {summary['side_effect_score_distribution']}\n"
        f"- failure_tag_frequency: {summary['failure_tag_frequency']}\n\n"
        "This is AI-preannotation calibration with user secondary review acceptance, not independent human evaluation.\n",
        encoding="utf-8",
    )


def write_taxonomy_md(path: Path, taxonomy: dict) -> None:
    lines = [
        "# Phase E Batch 3 Axis Difficulty Taxonomy",
        "",
        "| axis | difficulty | base_strength | prompt_only_effect | steering_signal | disagreement_level | main_failure_modes | recommended_next |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for axis, row in taxonomy["axes"].items():
        lines.append(
            f"| {axis} | {row['difficulty']} | {row['base_already_strong']} | {row['prompt_only_effect']} | {row['selected_steering_signal']} | {row['disagreement_level']} | {', '.join(row['common_failure_modes']) or 'none'} | {row['recommended_next_action']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--merged", default="data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl")
    p.add_argument("--report", default="results/cards/phase_e_batch3_preannotation_calibration_report.md")
    p.add_argument("--summary", default="results/summaries/phase_e_batch3_preannotation_calibration_summary.json")
    p.add_argument("--vs-judge", default="results/cards/phase_e_batch3_preannotation_vs_judge_records.jsonl")
    p.add_argument("--vs-heuristic", default="results/cards/phase_e_batch3_preannotation_vs_heuristic_records.jsonl")
    p.add_argument("--taxonomy-md", default="results/cards/phase_e_batch3_axis_difficulty_taxonomy.md")
    p.add_argument("--taxonomy-json", default="results/summaries/phase_e_batch3_axis_difficulty_taxonomy.json")
    return p.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
