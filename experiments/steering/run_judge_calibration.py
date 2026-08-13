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


BATCH2_PAIRWISE = ROOT / "results/cards/steering_phase_c_batch2_pairwise_records.jsonl"
BATCH2_RAW = ROOT / "results/local_artifacts/steering/phase_c_batch2_qwen3_4b/steering_generations.jsonl"
BATCH2_PROMPTS = ROOT / "data/trait_space/steering_prompts/phase_c_batch1_steering_prompts.jsonl"

SAMPLE_OUT = ROOT / "results/cards/steering_phase_c_batch3_judge_sample.jsonl"
HUMAN_OUT = ROOT / "results/cards/steering_phase_c_batch3_human_review_ready.jsonl"
JUDGE_OUT = ROOT / "results/cards/steering_phase_c_batch3_llm_judge_results.jsonl"
SUMMARY_OUT = ROOT / "results/summaries/steering_phase_c_batch3_judge_calibration_summary.json"
REPORT_OUT = ROOT / "results/cards/steering_phase_c_batch3_judge_calibration_report.md"
RAW_LOCAL_OUT = ROOT / "results/local_artifacts/steering/phase_c_batch3_judge_raw_responses.jsonl"


def main() -> int:
    args = parse_args()
    config = load_judge_config()
    smoke = smoke_check(config)
    if args.smoke_check:
        print(json.dumps({"smoke_check": "PASS", **smoke}, indent=2))
        return 0

    sample = build_sample(args.sample_size)
    write_jsonl(SAMPLE_OUT, sample)
    write_jsonl(HUMAN_OUT, [human_row(row) for row in sample])
    for path in [JUDGE_OUT, RAW_LOCAL_OUT]:
        if path.exists():
            path.unlink()

    results = []
    raw_rows = []
    for index, item in enumerate(sample, start=1):
        print(f"[judge {index}/{len(sample)}] {item['axis_id']} {item['comparison_type']}")
        result = judge_pair(config, item)
        raw = result.pop("_raw_response", None)
        result_row = {
            "judge_item_id": item["judge_item_id"],
            "axis_id": item["axis_id"],
            "comparison_type": item["comparison_type"],
            "prompt_id": item["prompt_id"],
            "activation_alpha": item["activation_alpha"],
            "heuristic_preference": item["heuristic_preference"],
            "llm_judge": result,
        }
        results.append(result_row)
        if raw is not None:
            raw_rows.append({"judge_item_id": item["judge_item_id"], "raw_response": raw})
        append_jsonl(JUDGE_OUT, result_row)

    if raw_rows:
        RAW_LOCAL_OUT.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(RAW_LOCAL_OUT, raw_rows)

    summary = summarize(results, sample, smoke, config)
    write_json(SUMMARY_OUT, summary)
    REPORT_OUT.write_text(report_markdown(summary), encoding="utf-8")
    print(json.dumps({"calibration": "PASS", "sample_count": len(sample), "judge_results": len(results)}, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-check", action="store_true")
    parser.add_argument("--sample-size", type=int, default=60)
    return parser.parse_args()


def build_sample(sample_size: int) -> list[dict]:
    pairwise = read_jsonl(BATCH2_PAIRWISE)
    raw_by_key = raw_generation_index()
    prompts = {row["prompt_id"]: row["user_prompt"] for row in read_jsonl(BATCH2_PROMPTS)}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in pairwise:
        grouped[(row["axis_id"], row["baseline_condition"])].append(row)

    per_group = max(1, sample_size // max(1, len(grouped)))
    selected = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda r: (abs(r["trait_expression_delta"]), r["activation_alpha"], r["prompt_id"]))
        selected.extend(diverse_take(rows, per_group))

    if len(selected) < sample_size:
        used = {case_key(row) for row in selected}
        for row in pairwise:
            if case_key(row) not in used:
                selected.append(row)
                used.add(case_key(row))
            if len(selected) >= sample_size:
                break
    selected = selected[:sample_size]

    sample = []
    for idx, row in enumerate(selected, start=1):
        activation = raw_by_key[(row["axis_id"], row["prompt_id"], 24, "activation-steering", row["activation_alpha"])]
        baseline_layer = "shared" if row["baseline_condition"] in {"no-steering", "prompt-only"} else 24
        baseline = raw_by_key[(row["axis_id"], row["prompt_id"], baseline_layer, row["baseline_condition"], row["baseline_alpha"])]
        sample.append(
            {
                "judge_item_id": f"phase_c_b3_{idx:03d}",
                "axis_id": row["axis_id"],
                "prompt_id": row["prompt_id"],
                "comparison_type": f"activation vs {row['baseline_condition']}",
                "activation_alpha": row["activation_alpha"],
                "baseline_condition": row["baseline_condition"],
                "baseline_alpha": row["baseline_alpha"],
                "user_prompt": prompts[row["prompt_id"]],
                "output_a_role": "activation-steering",
                "output_a": activation["output_text"],
                "output_b_role": row["baseline_condition"],
                "output_b": baseline["output_text"],
                "heuristic_preference": heuristic_preference(row),
                "heuristic_trait_delta": row["trait_expression_delta"],
                "heuristic_quality_delta": row["response_quality_delta"],
                "heuristic_side_effect_delta": row["side_effect_delta"],
                "heuristic_uncertainty": [row["activation_uncertainty"], row["baseline_uncertainty"]],
            }
        )
    return sample


def diverse_take(rows: list[dict], count: int) -> list[dict]:
    if len(rows) <= count:
        return rows
    picks = [rows[0], rows[len(rows) // 2], rows[-1]]
    for row in rows:
        if row not in picks:
            picks.append(row)
        if len(picks) >= count:
            break
    return picks[:count]


def raw_generation_index() -> dict:
    index = {}
    for row in read_jsonl(BATCH2_RAW):
        layer = row["layer"]
        key = (row["axis_id"], row["prompt_id"], layer, row["condition_id"], row["alpha"])
        index[key] = row
    return index


def heuristic_preference(row: dict) -> str:
    score = row["trait_expression_delta"] + 0.5 * row["response_quality_delta"] - 0.5 * row["side_effect_delta"]
    if score > 0.5:
        return "A"
    if score < -0.5:
        return "B"
    return "tie"


def summarize(results: list[dict], sample: list[dict], smoke: dict, config) -> dict:
    agreement = []
    by_axis = defaultdict(list)
    by_comparison = defaultdict(list)
    preference_by_comparison = defaultdict(Counter)
    low_confidence = []
    disagreements = []
    for row in results:
        judge_pref = normalized_pref(row["llm_judge"]["preferred_output"])
        heuristic = row["heuristic_preference"]
        agrees = judge_pref == heuristic
        agreement.append(agrees)
        by_axis[row["axis_id"]].append(agrees)
        by_comparison[row["comparison_type"]].append(agrees)
        preference_by_comparison[row["comparison_type"]][judge_pref] += 1
        if row["llm_judge"]["confidence"] < 0.5:
            low_confidence.append(row["judge_item_id"])
        if not agrees:
            disagreements.append(row["judge_item_id"])

    model_used_counts = Counter(row["llm_judge"]["model_used"] for row in results)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "smoke_check": smoke,
        "judge_model_requested": config.model,
        "judge_model_effective": model_used_counts.most_common(1)[0][0] if model_used_counts else config.model,
        "model_used_counts": dict(model_used_counts),
        "fallback_used_count": sum(1 for row in results if row["llm_judge"]["fallback_used"]),
        "fallback_models": config.fallbacks,
        "sample_count": len(sample),
        "result_count": len(results),
        "agreement_rate": mean_bool(agreement),
        "agreement_by_axis": {k: mean_bool(v) for k, v in by_axis.items()},
        "agreement_by_comparison_type": {k: mean_bool(v) for k, v in by_comparison.items()},
        "judge_preference_by_comparison_type": {k: dict(v) for k, v in preference_by_comparison.items()},
        "major_disagreement_case_ids": disagreements[:30],
        "low_confidence_case_ids": low_confidence[:30],
        "side_effect_disagreement_cases": [
            row["judge_item_id"]
            for row in results
            if row["llm_judge"]["side_effect_risk"] == "high"
            and row["heuristic_preference"] == "A"
        ][:30],
        "heuristic_likely_overestimated_cases": [
            row["judge_item_id"]
            for row in results
            if row["heuristic_preference"] == "A" and normalized_pref(row["llm_judge"]["preferred_output"]) != "A"
        ][:30],
        "prompt_only_dominates_cases": [
            row["judge_item_id"]
            for row in results
            if row["comparison_type"] == "activation vs prompt-only"
            and normalized_pref(row["llm_judge"]["preferred_output"]) == "B"
        ][:30],
        "random_shuffled_competitive_cases": [
            row["judge_item_id"]
            for row in results
            if row["comparison_type"] in {"activation vs random-vector", "activation vs shuffled-vector"}
            and normalized_pref(row["llm_judge"]["preferred_output"]) in {"B", "tie"}
        ][:30],
        "limitations": [
            "External LLM judge is calibration evidence, not ground truth.",
            "Sample is small and drawn from Batch 2 outputs.",
            "A is always activation-steering, so position bias is possible.",
            "No raw API key or secrets are stored.",
        ],
    }


def report_markdown(summary: dict) -> str:
    lines = [
        "# Phase C Batch 3 Judge Calibration Report",
        "",
        f"- Judge model requested: `{summary['judge_model_requested']}`",
        f"- Judge model effective: `{summary['judge_model_effective']}`",
        f"- Fallback-used count: {summary['fallback_used_count']}",
        f"- Sample count: {summary['sample_count']}",
        f"- Result count: {summary['result_count']}",
        f"- Agreement rate: {summary['agreement_rate']}",
        "",
        "## Agreement By Axis",
        "",
    ]
    for axis, value in summary["agreement_by_axis"].items():
        lines.append(f"- `{axis}`: {value}")
    lines.extend(["", "## Agreement By Comparison", ""])
    for comp, value in summary["agreement_by_comparison_type"].items():
        prefs = summary["judge_preference_by_comparison_type"].get(comp, {})
        lines.append(f"- `{comp}`: agreement {value}, judge preferences {prefs}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- External LLM judge is calibration evidence, not final truth.",
            "- Disagreement with the heuristic evaluator should be treated as a research finding.",
            "- This does not prove stable personality or behavior control.",
            "",
        ]
    )
    return "\n".join(lines)


def human_row(row: dict) -> dict:
    return {
        "judge_item_id": row["judge_item_id"],
        "axis_id": row["axis_id"],
        "comparison_type": row["comparison_type"],
        "user_prompt": row["user_prompt"],
        "output_a_role": row["output_a_role"],
        "output_a": row["output_a"],
        "output_b_role": row["output_b_role"],
        "output_b": row["output_b"],
        "human_preferred_output": "",
        "human_trait_expression_delta": "",
        "human_response_quality_delta": "",
        "human_side_effect_risk": "",
        "human_notes": "",
    }


def normalized_pref(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("a"):
        return "A"
    if value.startswith("b"):
        return "B"
    return "tie"


def mean_bool(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


def case_key(row: dict) -> tuple:
    return (row["axis_id"], row["prompt_id"], row["baseline_condition"], row["activation_alpha"])


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
