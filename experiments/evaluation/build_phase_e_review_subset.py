from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AXES = [
    "calm-agitated",
    "warm-cold",
    "empathetic-detached",
    "supportive-critical",
    "assertive-compliant",
    "boundary-preserving-over-accommodating",
    "cautious-impulsive",
    "confident-uncertain",
    "stable-reactive",
    "analytical-intuitive",
    "concise-expressive",
    "reflective-impulsively-answering",
]


def main() -> int:
    args = parse_args()
    dataset = {r["eval_id"]: r for r in read_jsonl(resolve(args.dataset))}
    packet = {r["eval_id"]: r for r in read_jsonl(resolve(args.review_packet))}
    judges = read_jsonl(resolve(args.judge_results))
    judge_by_pair = {(r["eval_id"], normalize_comparison(r["comparison_type"])): r for r in judges}
    judges_by_axis = defaultdict(list)
    for row in judges:
        judges_by_axis[row["axis_id"]].append(row)

    subset = []
    for axis in AXES:
        subset.extend(select_axis_items(axis, dataset, packet, judges_by_axis[axis], judge_by_pair))
    subset = [build_item(i + 1, item, dataset, packet, judge_by_pair) for i, item in enumerate(subset)]

    write_jsonl(resolve(args.subset), subset)
    write_jsonl(resolve(args.ai_packet), subset)
    write_card(resolve(args.subset_card), subset)
    write_ai_markdown(resolve(args.ai_markdown), subset)
    write_instructions(resolve(args.instructions))
    summary = build_summary(subset)
    write_json(resolve(args.summary), summary)
    write_report(resolve(args.report), summary)
    print(json.dumps({"review_subset": "PASS", "items": len(subset), "axes": len(summary["axes_coverage"])}, indent=2))
    return 0


def select_axis_items(axis: str, dataset: dict, packet: dict, judges: list[dict], judge_by_pair: dict) -> list[dict]:
    selected = []
    if any("selected-steering" in j["comparison_type"] for j in judges):
        selected += pick_judge(judges, "selected-steering vs base", 1)
        selected += pick_judge(judges, "selected-steering vs prompt-only", 1)
        selected += pick_test(axis, dataset, packet, "prompt_only_vs_base", selected)
    else:
        selected += pick_judge(judges, "prompt-only vs base", 2)
        selected += pick_test(axis, dataset, packet, "prompt_only_vs_base", selected)
    while len(selected) < 3:
        selected += pick_fallback(axis, dataset, packet, selected, judge_by_pair)
    return selected[:3]


def pick_judge(judges: list[dict], comparison: str, count: int) -> list[dict]:
    rows = [j for j in judges if j["comparison_type"] == comparison]
    rows.sort(key=lambda r: (judge_priority(r), r["eval_id"]))
    return [{"eval_id": r["eval_id"], "comparison_type": normalize_comparison(r["comparison_type"])} for r in rows[:count]]


def pick_test(axis: str, dataset: dict, packet: dict, comparison: str, selected: list[dict]) -> list[dict]:
    used = {s["eval_id"] for s in selected}
    rows = [r for r in dataset.values() if r["axis_id"] == axis and r["split"] == "test" and r["eval_id"] in packet and r["eval_id"] not in used]
    rows.sort(key=lambda r: r["eval_id"])
    return [{"eval_id": rows[0]["eval_id"], "comparison_type": comparison}] if rows else []


def pick_fallback(axis: str, dataset: dict, packet: dict, selected: list[dict], judge_by_pair: dict) -> list[dict]:
    used = {(s["eval_id"], s["comparison_type"]) for s in selected}
    for row in sorted(dataset.values(), key=lambda r: r["eval_id"]):
        if row["axis_id"] != axis or row["eval_id"] not in packet:
            continue
        for comparison in ["prompt_only_vs_base", "steering_vs_base", "steering_vs_prompt_only"]:
            if (row["eval_id"], comparison) not in used and comparison_available(packet[row["eval_id"]], comparison):
                return [{"eval_id": row["eval_id"], "comparison_type": comparison}]
    return []


def build_item(idx: int, selected: dict, dataset: dict, packet: dict, judge_by_pair: dict) -> dict:
    eval_id = selected["eval_id"]
    comparison = selected["comparison_type"]
    data = dataset[eval_id]
    review = packet[eval_id]
    judge = judge_by_pair.get((eval_id, comparison))
    outputs = normalize_outputs(review["outputs"])
    reasons, flags = selection_reasons(comparison, review, judge)
    return {
        "review_item_id": f"phase_e_review_subset_v01_{idx:03d}",
        "eval_id": eval_id,
        "axis_id": data["axis_id"],
        "target_pole": data["target_pole"],
        "contrast_pole": data["contrast_pole"],
        "prompt_family": data["prompt_family"],
        "split": data["split"],
        "user_prompt": data["user_prompt"],
        "expected_behavior": data["expected_behavior"],
        "risk_notes": data.get("risk_notes", ""),
        "comparison_type": comparison,
        "outputs": outputs,
        "heuristic_scores": review.get("heuristic_scores", {}),
        "external_judge": {"phase_e_batch2_pairwise": [judge] if judge else []},
        "selection_reason": reasons,
        "known_flags": flags,
        "ai_preannotation": empty_ai_preannotation(),
        "human_review": empty_human_review(),
    }


def normalize_outputs(outputs: dict) -> dict:
    result = {}
    for src, dst in [("base", "base"), ("prompt-only", "prompt_only"), ("selected-steering", "selected_steering")]:
        out = outputs.get(src)
        result[dst] = {
            "condition": src,
            "text": out.get("output_text") if out else None,
            "metadata": out.get("generation_metadata", {}) if out else {},
        }
    return result


def selection_reasons(comparison: str, review: dict, judge: dict | None) -> tuple[list[str], list[str]]:
    reasons = [comparison]
    flags = []
    if judge:
        conf = float(judge["llm_judge"]["confidence"])
        reasons.append("judge_backed")
        if conf >= 0.85:
            reasons.append("high_judge_confidence")
        if conf <= 0.65:
            reasons.append("low_judge_confidence")
            flags.append("low_judge_confidence")
        if heuristic_disagrees(review, judge):
            reasons.append("heuristic_judge_disagreement")
            flags.append("heuristic_judge_disagreement")
        if judge["llm_judge"].get("side_effect_risk") != "low":
            flags.append("judge_side_effect_risk")
    else:
        reasons.append("test_split_coverage")
        flags.append("no_external_judge_for_this_item")
    scores = review.get("heuristic_scores", {})
    if condition_score(scores, "prompt-only") > condition_score(scores, "base"):
        reasons.append("prompt_only_stronger")
    if "selected-steering" in scores:
        reasons.append("selected_steering_available")
        if condition_score(scores, "selected-steering") <= condition_score(scores, "prompt-only"):
            reasons.append("selected_steering_mixed")
            flags.append("selected_steering_not_above_prompt_only")
    if any_side_effect(scores):
        reasons.append("side_effect_or_style_risk")
        flags.append("heuristic_side_effect_or_style_risk")
    return sorted(set(reasons)), sorted(set(flags))


def heuristic_disagrees(review: dict, judge: dict) -> bool:
    a = condition_from_judge(judge["condition_a"])
    b = condition_from_judge(judge["condition_b"])
    delta = condition_score(review.get("heuristic_scores", {}), a) - condition_score(review.get("heuristic_scores", {}), b)
    heuristic = "tie" if abs(delta) < 0.5 else ("A" if delta > 0 else "B")
    return heuristic != judge["llm_judge"]["preferred_output"]


def condition_score(scores: dict, condition: str) -> float:
    s = scores.get(condition, {})
    return float(s.get("trait_expression_score", 0) + s.get("response_quality_score", 0) + s.get("usefulness_score", 0) - s.get("side_effect_load", 0))


def any_side_effect(scores: dict) -> bool:
    for s in scores.values():
        if s.get("side_effect_load", 0) or s.get("over_refusal", 0) or s.get("synthetic_style_markers", 0):
            return True
    return False


def comparison_available(review: dict, comparison: str) -> bool:
    outputs = review.get("outputs", {})
    if comparison == "prompt_only_vs_base":
        return "base" in outputs and "prompt-only" in outputs
    if comparison == "steering_vs_base":
        return "selected-steering" in outputs and "base" in outputs
    if comparison == "steering_vs_prompt_only":
        return "selected-steering" in outputs and "prompt-only" in outputs
    return False


def judge_priority(row: dict) -> tuple[int, float]:
    conf = float(row["llm_judge"]["confidence"])
    low = 0 if conf <= 0.65 else 1
    high = 0 if conf >= 0.85 else 1
    return (low, high, -conf)


def normalize_comparison(value: str) -> str:
    return value.replace("prompt-only", "prompt_only").replace("selected-steering", "steering").replace(" vs ", "_vs_")


def condition_from_judge(value: str) -> str:
    return {"prompt-only": "prompt-only", "selected-steering": "selected-steering"}.get(value, value)


def empty_ai_preannotation() -> dict:
    return {
        "annotator_type": "ai_assistant",
        "annotator": None,
        "status": "pending",
        "preferred_output": None,
        "trait_expression_score": None,
        "response_quality_score": None,
        "usefulness_score": None,
        "side_effect_score": None,
        "confidence": None,
        "failure_tags": [],
        "notes": None,
        "annotated_at": None,
    }


def empty_human_review() -> dict:
    return {
        "reviewer": None,
        "review_status": "pending_user_review",
        "preferred_output": None,
        "trait_expression_score": None,
        "response_quality_score": None,
        "usefulness_score": None,
        "side_effect_score": None,
        "confidence": None,
        "failure_tags": [],
        "correction_notes": None,
        "reviewed_at": None,
    }


def build_summary(rows: list[dict]) -> dict:
    judge_conf = [j["llm_judge"]["confidence"] for row in rows for j in row["external_judge"]["phase_e_batch2_pairwise"]]
    return {
        "created_at": utcnow(),
        "total_review_items": len(rows),
        "axes_coverage": sorted(Counter(r["axis_id"] for r in rows)),
        "items_per_axis": dict(Counter(r["axis_id"] for r in rows)),
        "comparison_type_distribution": dict(Counter(r["comparison_type"] for r in rows)),
        "split_distribution": dict(Counter(r["split"] for r in rows)),
        "selected_steering_available_items": sum(1 for r in rows if r["outputs"]["selected_steering"]["text"]),
        "judge_confidence_distribution": {
            "count": len(judge_conf),
            "low_or_equal_0_65": sum(1 for v in judge_conf if v <= 0.65),
            "high_or_equal_0_85": sum(1 for v in judge_conf if v >= 0.85),
        },
        "heuristic_judge_disagreement_count": sum(1 for r in rows if "heuristic_judge_disagreement" in r["known_flags"]),
        "selection_reasons": dict(Counter(reason for r in rows for reason in r["selection_reason"])),
        "known_limitations": [
            "AI preannotation fields are pending/null and are not human labels.",
            "External judge evidence exists only for the Batch 2 pairwise sample.",
            "Selected steering exists only for six axes.",
            "Test split coverage includes heuristic-only items when no external judge item exists.",
        ],
        "next_step": "Send phase_e_ai_preannotation_packet_v0_1.md or .jsonl to the AI assistant for preannotation, then perform user secondary review.",
    }


def write_card(path: Path, rows: list[dict]) -> None:
    summary = build_summary(rows)
    path.write_text(
        "# Phase E Review Subset v0.1\n\n"
        f"- total_review_items: {summary['total_review_items']}\n"
        f"- axes_coverage: {', '.join(summary['axes_coverage'])}\n"
        f"- split_distribution: {summary['split_distribution']}\n"
        f"- comparison_type_distribution: {summary['comparison_type_distribution']}\n"
        "- ai_preannotation: pending/null\n"
        "- human_review: pending/null\n",
        encoding="utf-8",
    )


def write_ai_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        "# Phase E AI Preannotation Packet v0.1",
        "",
        "Use this packet for AI preannotation only. Do not mark these as human labels.",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row['review_item_id']}",
            "",
            f"- axis: `{row['axis_id']}`",
            f"- target vs contrast: `{row['target_pole']}` vs `{row['contrast_pole']}`",
            f"- split: `{row['split']}`",
            f"- comparison_type: `{row['comparison_type']}`",
            f"- selection_reason: `{', '.join(row['selection_reason'])}`",
            f"- known_flags: `{', '.join(row['known_flags']) or 'none'}`",
            "",
            f"Prompt: {row['user_prompt']}",
            "",
            f"Expected behavior: {row['expected_behavior']}",
            "",
            "Outputs:",
        ]
        for name, out in row["outputs"].items():
            if out["text"]:
                lines += [f"- {name}: {clean_md(out['text'])}"]
        lines += [
            "",
            f"Heuristic scores: `{json.dumps(row['heuristic_scores'], ensure_ascii=False)[:1200]}`",
            f"External judge: `{json.dumps(row['external_judge'], ensure_ascii=False)[:1200]}`",
            "",
            "Preannotation fields to fill: preferred_output, trait_expression_score, response_quality_score, usefulness_score, side_effect_score, confidence, failure_tags, notes.",
            "",
        ]
    path.write_text("\n".join(line.rstrip() for line in lines), encoding="utf-8")


def write_instructions(path: Path) -> None:
    path.write_text(
        "# Phase E AI Preannotation Instructions v0.1\n\n"
        "- You are an AI pre-annotator only. The human reviewer is the final reviewer.\n"
        "- AI preannotation is not human annotation.\n"
        "- Fill: `preferred_output`, `trait_expression_score`, `response_quality_score`, `usefulness_score`, `side_effect_score`, `confidence`, `failure_tags`, `notes`.\n"
        "- Scores use 1-5. For `side_effect_score`, 1 means low side effect and 5 means high side effect.\n"
        "- `preferred_output` may be `base`, `prompt_only`, `selected_steering`, or `tie`, depending on available outputs.\n"
        "- Do not prefer longer answers by default.\n"
        "- Do not prefer safer answers by default; balance trait expression, quality, usefulness, and side effects.\n"
        "- Use low confidence when uncertain or when outputs are truncated/ambiguous.\n",
        encoding="utf-8",
    )


def clean_md(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines())


def write_report(path: Path, summary: dict) -> None:
    path.write_text(
        "# Phase E Batch 3A Review Subset Report\n\n"
        f"- total_review_items: {summary['total_review_items']}\n"
        f"- axes_coverage: {', '.join(summary['axes_coverage'])}\n"
        f"- items_per_axis: {summary['items_per_axis']}\n"
        f"- comparison_type_distribution: {summary['comparison_type_distribution']}\n"
        f"- split_distribution: {summary['split_distribution']}\n"
        f"- selected_steering_available_items: {summary['selected_steering_available_items']}\n"
        f"- judge_confidence_distribution: {summary['judge_confidence_distribution']}\n"
        f"- heuristic_judge_disagreement_count: {summary['heuristic_judge_disagreement_count']}\n"
        f"- selection_reasons: {summary['selection_reasons']}\n\n"
        "Known limitations:\n"
        + "\n".join(f"- {v}" for v in summary["known_limitations"])
        + "\n\nNext step: send `data/evaluation/human_review/phase_e_ai_preannotation_packet_v0_1.md` or `.jsonl` to the AI assistant for preannotation.\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/evaluation/trait_eval_12axis_v0_1.jsonl")
    parser.add_argument("--review-packet", default="data/evaluation/human_review/trait_eval_12axis_review_packet_v0_2.jsonl")
    parser.add_argument("--judge-results", default="results/cards/phase_e_batch2_judge_results.jsonl")
    parser.add_argument("--subset", default="data/evaluation/human_review/phase_e_review_subset_v0_1.jsonl")
    parser.add_argument("--subset-card", default="data/evaluation/human_review/phase_e_review_subset_v0_1.card.md")
    parser.add_argument("--ai-packet", default="data/evaluation/human_review/phase_e_ai_preannotation_packet_v0_1.jsonl")
    parser.add_argument("--ai-markdown", default="data/evaluation/human_review/phase_e_ai_preannotation_packet_v0_1.md")
    parser.add_argument("--instructions", default="data/evaluation/human_review/phase_e_annotation_instructions_for_ai_v0_1.md")
    parser.add_argument("--summary", default="results/summaries/phase_e_batch3_review_subset_summary.json")
    parser.add_argument("--report", default="results/cards/phase_e_batch3_review_subset_report.md")
    return parser.parse_args()


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
