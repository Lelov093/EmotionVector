from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.steering.judge_client import judge_pair, load_judge_config, smoke_check


def main() -> int:
    args = parse_args()
    if args.mode == "model-output":
        return run_model_output_judge(args)

    packet = read_jsonl(resolve(args.packet))
    judge_config = load_judge_config()
    try:
        smoke = smoke_check(judge_config)
    except Exception as exc:
        summary = {
            "created_at": utcnow(),
            "judge_available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "packet_count": len(packet),
            "sample_count": 0,
            "results_written": False,
        }
        write_json(resolve(args.summary), summary)
        print(json.dumps(summary, indent=2))
        return 0 if args.allow_unavailable else 1

    if args.smoke_only:
        summary = {
            "created_at": utcnow(),
            "judge_available": True,
            "smoke_check": smoke,
            "packet_count": len(packet),
            "sample_count": 0,
            "results_written": False,
        }
        write_json(resolve(args.summary), summary)
        print(json.dumps(summary, indent=2))
        return 0

    rows = packet[: args.limit]
    results = []
    for row in rows:
        judged = judge_pair(judge_config, row)
        judged.pop("_raw_response", None)
        results.append({**row, "llm_judge": judged})
    prefs = Counter(row["llm_judge"]["preferred_output"] for row in results)
    summary = {
        "created_at": utcnow(),
        "judge_available": True,
        "smoke_check": smoke,
        "judge_model_effective": results[0]["llm_judge"]["model_used"] if results else smoke.get("model_used"),
        "fallback_used": any(row["llm_judge"]["fallback_used"] for row in results),
        "packet_count": len(packet),
        "sample_count": len(results),
        "preference_counts": dict(prefs),
        "avg_confidence": round(sum(row["llm_judge"]["confidence"] for row in results) / len(results), 4) if results else 0,
        "reference_only": True,
        "limitations": [
            "This is a reference-output judge calibration packet, not a model-output evaluation.",
            "LLM judge results are not final human labels.",
        ],
    }
    write_jsonl(resolve(args.results), results)
    write_json(resolve(args.summary), summary)
    print(json.dumps(summary, indent=2))
    return 0


def run_model_output_judge(args: argparse.Namespace) -> int:
    records = read_jsonl(resolve(args.heuristic_results))
    pairs = build_model_output_pairs(records, args.limit)
    judge_config = load_judge_config()
    try:
        smoke = smoke_check(judge_config)
    except Exception as exc:
        summary = {
            "created_at": utcnow(),
            "judge_available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "pair_count": len(pairs),
            "sample_count": 0,
            "results_written": False,
        }
        write_json(resolve(args.summary), summary)
        print(json.dumps(summary, indent=2))
        return 0 if args.allow_unavailable else 1

    results = []
    for row in pairs:
        judged = judge_pair(judge_config, row)
        judged.pop("_raw_response", None)
        results.append({**row, "llm_judge": judged})

    prefs = Counter(row["llm_judge"]["preferred_output"] for row in results)
    by_type = Counter(row["comparison_type"] for row in results)
    by_axis = Counter(row["axis_id"] for row in results)
    summary = {
        "created_at": utcnow(),
        "judge_available": True,
        "smoke_check": smoke,
        "judge_model_effective": results[0]["llm_judge"]["model_used"] if results else smoke.get("model_used"),
        "fallback_used": any(row["llm_judge"]["fallback_used"] for row in results),
        "pair_count": len(pairs),
        "sample_count": len(results),
        "axis_counts": dict(by_axis),
        "comparison_type_counts": dict(by_type),
        "preference_counts": dict(prefs),
        "avg_confidence": round(sum(row["llm_judge"]["confidence"] for row in results) / len(results), 4) if results else 0,
        "model_output_evaluation": True,
        "limitations": [
            "External judge results are not human labels.",
            "Selected steering is only available for six axes in this batch.",
            "Pairwise sample is a review packet, not a publication-scale evaluation.",
        ],
    }
    write_jsonl(resolve(args.results), results)
    write_json(resolve(args.summary), summary)
    write_report(resolve(args.report), summary, results)
    if args.review_packet:
        update_review_packet(resolve(args.review_packet), results)
    print(json.dumps(summary, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["calibration", "model-output"], default="calibration")
    parser.add_argument("--packet", default="results/cards/phase_e_batch1_judge_calibration_packet.jsonl")
    parser.add_argument("--heuristic-results", default="results/cards/phase_e_batch2_heuristic_eval_results.jsonl")
    parser.add_argument("--results", default="results/cards/phase_e_batch1_judge_calibration_results.jsonl")
    parser.add_argument("--summary", default="results/summaries/phase_e_batch1_judge_calibration_summary.json")
    parser.add_argument("--report", default="results/cards/phase_e_batch2_judge_report.md")
    parser.add_argument("--review-packet")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--allow-unavailable", action="store_true")
    return parser.parse_args()


def build_model_output_pairs(records: list[dict], limit: int) -> list[dict]:
    by_eval: dict[str, dict[str, dict]] = defaultdict(dict)
    for record in records:
        if record.get("output_text"):
            by_eval[record["eval_id"]][record["condition_id"]] = record

    axes = sorted({r["axis_id"] for r in records})
    pairs = []
    extras = []
    for axis in axes:
        axis_items = [v for k, v in sorted(by_eval.items()) if any(r["axis_id"] == axis for r in v.values())]
        prompt_pairs = [make_pair(v, "prompt-only", "base") for v in axis_items if "prompt-only" in v and "base" in v]
        steering_base = [make_pair(v, "selected-steering", "base") for v in axis_items if "selected-steering" in v and "base" in v]
        steering_prompt = [make_pair(v, "selected-steering", "prompt-only") for v in axis_items if "selected-steering" in v and "prompt-only" in v]
        if steering_base:
            pairs.extend(prompt_pairs[:1] + steering_base[:1] + steering_prompt[:1])
            extras.extend(prompt_pairs[1:2])
        else:
            pairs.extend(prompt_pairs[:3])
            extras.extend(prompt_pairs[3:4])
    return [p for p in (pairs + extras) if p][:limit]


def make_pair(items: dict[str, dict], condition_a: str, condition_b: str) -> dict:
    a = items[condition_a]
    b = items[condition_b]
    return {
        "judge_item_id": f"{a['eval_id']}__{condition_a}_vs_{condition_b}",
        "eval_id": a["eval_id"],
        "axis_id": a["axis_id"],
        "comparison_type": f"{condition_a} vs {condition_b}",
        "condition_a": condition_a,
        "condition_b": condition_b,
        "user_prompt": a["user_prompt"],
        "expected_behavior": a["expected_behavior"],
        "output_a": a["output_text"],
        "output_b": b["output_text"],
        "heuristic_a": a["heuristic_scores"],
        "heuristic_b": b["heuristic_scores"],
    }


def write_report(path: Path, summary: dict, results: list[dict]) -> None:
    lines = [
        "# Phase E Batch 2 Judge Report",
        "",
        f"- created_at: `{summary['created_at']}`",
        f"- judge_available: `{summary['judge_available']}`",
        f"- judge_model_effective: `{summary.get('judge_model_effective')}`",
        f"- sample_count: `{summary['sample_count']}`",
        f"- axis_counts: `{summary['axis_counts']}`",
        f"- comparison_type_counts: `{summary['comparison_type_counts']}`",
        f"- preference_counts: `{summary['preference_counts']}`",
        f"- avg_confidence: `{summary['avg_confidence']}`",
        "",
        "These are external judge results for real model outputs. They are not human labels.",
        "",
        "## Sampled Failure / Ambiguous Cases",
    ]
    for row in results[:10]:
        judge = row["llm_judge"]
        if judge["preferred_output"] == "tie" or judge["side_effect_risk"] != "low":
            lines.append(f"- `{row['judge_item_id']}` preferred `{judge['preferred_output']}`, risk `{judge['side_effect_risk']}`: {judge['reason']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_review_packet(path: Path, judge_results: list[dict]) -> None:
    if not path.exists():
        return
    by_eval = defaultdict(list)
    for row in judge_results:
        by_eval[row["eval_id"]].append(
            {
                "judge_item_id": row["judge_item_id"],
                "comparison_type": row["comparison_type"],
                "condition_a": row["condition_a"],
                "condition_b": row["condition_b"],
                "llm_judge": row["llm_judge"],
            }
        )
    rows = read_jsonl(path)
    for row in rows:
        row["external_judge"] = {"phase_e_batch2_pairwise": by_eval.get(row["eval_id"], [])}
    write_jsonl(path, rows)


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
