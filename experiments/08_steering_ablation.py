"""
Phase 2.2: Multi-layer / Multi-position Steering Ablation

Compares 5 steering scopes across alphas ∈ [-10, -5, 0, 5, 10]
to determine which scope produces the most stable directional effect.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import (  # noqa: E402
    LAYER_IDX,
    LOG_DIR,
    MAX_INPUT_TOKENS,
    MODEL_NAME,
    VECTOR_DIR,
    ensure_project_dirs,
    print_environment_summary,
)
from backend.core.activation_collector import get_last_token_activation  # noqa: E402
from backend.core.model_loader import load_model_and_tokenizer  # noqa: E402
from backend.core.steering_engine import (  # noqa: E402
    format_chat_prompt,
    generate_with_multi_layer_steering,
)

# ── Paths ──────────────────────────────────────────────────────────
ALT_VECTORS_PATH = VECTOR_DIR / "qwen_1_5b_layer16_alternative_vectors.pt"
OUTPUT_JSONL_PATH = LOG_DIR / "steering_ablation_outputs.jsonl"
SUMMARY_CSV_PATH = LOG_DIR / "steering_ablation_summary.csv"
REPORT_PATH = PROJECT_ROOT / "report" / "phase_2_2_steering_ablation_report.md"

# ── Scopes ─────────────────────────────────────────────────────────

SCOPES = [
    {
        "name": "single_layer_last_token",
        "layers": [16],
        "position_mode": "last",
    },
    {
        "name": "multi_layer_last_token",
        "layers": [12, 14, 16, 18, 20],
        "position_mode": "last",
    },
    {
        "name": "single_layer_all_tokens",
        "layers": [16],
        "position_mode": "all",
    },
    {
        "name": "multi_layer_all_tokens",
        "layers": [12, 14, 16, 18, 20],
        "position_mode": "all",
    },
    {
        "name": "late_multi_layer_last_token",
        "layers": [20, 22, 24, 26],
        "position_mode": "last",
    },
]

ALPHAS = [-10.0, -5.0, 0.0, 5.0, 10.0]

TEST_PROMPTS = [
    {
        "id": "challenge_001",
        "text": "用户质疑你刚才的判断：你是不是根本没有认真分析？请以冷静、克制、重视事实的AI角色口吻回应。",
    },
    {
        "id": "pressure_001",
        "text": "任务出现失误，有人责备你拖累了团队。请以负责保护同伴的AI角色口吻回应，并说明下一步。",
    },
    {
        "id": "disagreement_001",
        "text": "对方连续否定你的方案，并要求你立刻承认自己完全错误。请以理性但有原则的AI角色口吻回应。",
    },
]

BAD_MARKERS = ["Human:", "User:", "用户：", "用户:", "Assistant:", "助手：", "human:", "user:"]


# ── Helpers ────────────────────────────────────────────────────────


def _cosine(a: torch.Tensor, b: torch.Tensor) -> float:
    a_f, b_f = a.float(), b.float()
    return float(torch.dot(a_f, b_f) / (a_f.norm() * b_f.norm() + 1e-12))


def has_extra_dialogue(text: str) -> bool:
    return any(m in text for m in BAD_MARKERS)


def has_repetition(text: str) -> bool:
    words = text.split()
    if len(words) < 6:
        return False
    return len(set(words)) / len(words) < 0.5


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


# ── Scope metrics ──────────────────────────────────────────────────


def compute_scope_metrics(scope_rows: list[dict]) -> dict:
    """Compute summary metrics for one steering scope."""
    df = pd.DataFrame(scope_rows)
    alphas = sorted(df["alpha"].unique())

    # Mean axis_score by alpha
    axis_by_alpha = {a: float(df[df["alpha"] == a]["axis_score"].mean()) for a in alphas}

    # Linear fit: axis_score = slope * alpha + intercept
    alpha_vals = np.array(alphas, dtype=float)
    axis_vals = np.array([axis_by_alpha[a] for a in alphas], dtype=float)
    slope, intercept = np.polyfit(alpha_vals, axis_vals, 1)

    # Directional consistency
    nonzero = [a for a in alphas if a != 0]
    baseline_scores = df[df["alpha"] == 0]["axis_score"]
    baseline_mean = float(baseline_scores.mean()) if len(baseline_scores) > 0 else 0.0

    satisfied = 0
    total_nonzero = 0
    for a in nonzero:
        sub = df[df["alpha"] == a]["axis_score"]
        sub_mean = float(sub.mean())
        total_nonzero += 1
        if (a < 0 and sub_mean < baseline_mean) or (a > 0 and sub_mean > baseline_mean):
            satisfied += 1
    directional_consistency = satisfied / total_nonzero if total_nonzero > 0 else 0.0

    # Quality
    n_extra = int(df["has_extra_dialogue"].sum())
    n_rep = int(df["has_repetition"].sum())
    n_total = len(df)

    return {
        "scope_name": scope_rows[0]["scope_name"],
        "axis_slope": round(float(slope), 6),
        "axis_intercept": round(float(intercept), 6),
        "directional_consistency": round(directional_consistency, 4),
        "extra_dialogue_rate": round(n_extra / n_total, 4) if n_total else 0.0,
        "repetition_rate": round(n_rep / n_total, 4) if n_total else 0.0,
        "mean_output_length": round(float(df["output_length"].mean()), 1),
        "axis_by_alpha": {str(a): axis_by_alpha[a] for a in alphas},
    }


# ── Report ─────────────────────────────────────────────────────────


def generate_report(scope_metrics: list[dict], all_rows: list[dict]) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Phase 2.2 Steering Ablation Report",
        f"*Generated: {now}*",
        "",
        "## 1. Objective",
        "Compare 5 steering scopes (layer ranges × position modes) to determine "
        "which configuration produces the most stable calm↔angry directional "
        "effect in generated text.",
        "",
        "## 2. Background",
        "- Phase 2.1 confirmed the hook works (projected_delta = α × 1.0 at layer 16).",
        "- But single-layer last-token injection does not propagate to generation.",
        "- This ablation tests whether multi-layer and/or all-position injection amplifies the effect.",
        "",
        "## 3. Steering Scopes",
        "",
        "| Scope | Layers | Position | Description |",
        "|---|---|---|---|",
    ]
    for s in SCOPES:
        lines.append(
            f"| {s['name']} | {s['layers']} | {s['position_mode']} | "
            f"{'Baseline (Phase 2.0/2.1)' if s['name'] == 'single_layer_last_token' else ''} |"
        )

    lines += [
        "",
        "## 4. Experimental Setup",
        f"- Model: {MODEL_NAME}",
        f"- Vector: angry_vs_calm_axis (1536-dim, L2-normalized)",
        f"- Alphas: {ALPHAS}",
        f"- Prompts: {len(TEST_PROMPTS)} role-play scenarios",
        f"- Total generations: {len(SCOPES)} scopes × {len(ALPHAS)} alphas × {len(TEST_PROMPTS)} prompts = "
        f"{len(SCOPES) * len(ALPHAS) * len(TEST_PROMPTS)}",
        "- Generation: greedy decoding, max 96 new tokens, repetition_penalty=1.05",
        "- Scoring: axis_score = cosine(generated_text_activation, steering_vector)",
        "",
        "## 5. Quantitative Results",
        "",
        "### 5.1 Summary Table",
        "",
        "| Scope | axis_slope | directional_consistency | extra_dialogue | repetition | mean_len |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    best_slope = max(scope_metrics, key=lambda m: abs(m["axis_slope"]))
    for m in scope_metrics:
        marker = " ← best" if m["scope_name"] == best_slope["scope_name"] else ""
        lines.append(
            f"| {m['scope_name']}{marker} "
            f"| {m['axis_slope']:.6f} "
            f"| {m['directional_consistency']:.2f} "
            f"| {m['extra_dialogue_rate']:.0%} "
            f"| {m['repetition_rate']:.0%} "
            f"| {m['mean_output_length']:.0f} |"
        )

    lines += [
        "",
        "### 5.2 Axis Score by Alpha (per scope)",
        "",
    ]
    for m in scope_metrics:
        lines.append(f"#### {m['scope_name']}")
        lines.append(f"slope={m['axis_slope']:.6f}, intercept={m['axis_intercept']:.4f}")
        lines.append("| Alpha | mean axis_score |")
        lines.append("|---|---:|")
        for a_str, val in sorted(m["axis_by_alpha"].items(), key=lambda x: float(x[0])):
            lines.append(f"| {float(a_str):+.0f} | {val:+.4f} |")
        lines.append("")

    lines += [
        "### 5.3 Qualitative Observations",
        "",
    ]

    # Check for quality issues
    quality_issues = [r for r in all_rows if r.get("has_extra_dialogue") or r.get("has_repetition")]
    if quality_issues:
        lines.append(f"**{len(quality_issues)} outputs with quality issues:**")
        for r in quality_issues[:10]:
            flags = []
            if r.get("has_extra_dialogue"):
                flags.append("extra_dialogue")
            if r.get("has_repetition"):
                flags.append("repetition")
            lines.append(
                f"- {r['scope_name']}, {r['prompt_id']}, alpha={r['alpha']:+.0f}: "
                f"{', '.join(flags)}"
            )
    else:
        lines.append("No quality issues detected across all scopes and alphas.")

    lines += [
        "",
        "## 6. Key Findings",
        "",
    ]

    # Multi vs single
    single_slope = [m for m in scope_metrics if "single_layer" in m["scope_name"] and "all_tokens" not in m["scope_name"]]
    multi_slope = [m for m in scope_metrics if "multi_layer" in m["scope_name"] and "all_tokens" not in m["scope_name"]]
    if single_slope and multi_slope:
        ss = abs(single_slope[0]["axis_slope"])
        ms = abs(multi_slope[0]["axis_slope"])
        if ms > ss:
            lines.append(f"### 6.1 Multi-layer > single-layer: ✅ (|slope|: {ms:.6f} > {ss:.6f})")
        else:
            lines.append(f"### 6.1 Multi-layer NOT better: |slope|: {ms:.6f} ≤ {ss:.6f}")

    # All vs last
    all_pos = [m for m in scope_metrics if "all_tokens" in m["scope_name"]]
    last_pos = [m for m in scope_metrics if "last_token" in m["scope_name"] and "all_tokens" not in m["scope_name"]]
    if all_pos and last_pos:
        best_all = max(all_pos, key=lambda m: abs(m["axis_slope"]))
        best_last = max(last_pos, key=lambda m: abs(m["axis_slope"]))
        if abs(best_all["axis_slope"]) > abs(best_last["axis_slope"]):
            lines.append(f"### 6.2 All-token > last-token: ✅")
        else:
            lines.append(f"### 6.2 All-token NOT better than last-token")

    # Late vs mid
    late_scope = [m for m in scope_metrics if "late" in m["scope_name"]]
    mid_scope = [m for m in scope_metrics if "multi_layer_last_token" == m["scope_name"]]
    if late_scope and mid_scope:
        if abs(late_scope[0]["axis_slope"]) > abs(mid_scope[0]["axis_slope"]):
            lines.append(f"### 6.3 Late-layer > mid-layer: ✅")
        else:
            lines.append(f"### 6.3 Late-layer NOT better than mid-layer")

    # Best overall
    best = max(scope_metrics, key=lambda m: (m["directional_consistency"], abs(m["axis_slope"])))
    lines += [
        "",
        f"### 6.4 Best scope: **{best['scope_name']}**",
        f"- axis_slope: {best['axis_slope']:.6f}",
        f"- directional_consistency: {best['directional_consistency']:.2f}",
        f"- extra_dialogue: {best['extra_dialogue_rate']:.0%}",
        f"- repetition: {best['repetition_rate']:.0%}",
        "",
        "## 7. Current Conclusion",
        "",
    ]

    if best["directional_consistency"] >= 0.75 and abs(best["axis_slope"]) > 0.001:
        lines.append(
            "✅ Steering produces **directionally consistent** effects with the best scope. "
            "This is sufficient evidence to proceed to a more systematic steering evaluation."
        )
    elif abs(best["axis_slope"]) > 0.0005:
        lines.append(
            "⚠️ Steering shows **partial directional effects** — the slope is in the right "
            "direction but consistency is below threshold. May need stronger alpha or "
            "additional technical improvements before Phase 2.3."
        )
    else:
        lines.append(
            "❌ Steering does **not** produce reliable directional effects even with "
            "multi-layer multi-position injection. The Qwen2.5-1.5B-Instruct model's "
            "decoding process appears robust to activation perturbations at the tested "
            "strengths and positions."
        )

    lines += [
        "",
        "**Limitations**:",
        "- 75 generations total (5 scopes × 5 alphas × 3 prompts) — small sample.",
        "- Scoring uses the same vector as steering — potential circularity.",
        "- Qwen2.5-1.5B-Instruct safety alignment may be a hard constraint.",
        "- Single-vector steering may not capture full emotional spectrum.",
        "",
        "## 8. Recommended Next Step",
        "",
    ]

    if best["directional_consistency"] >= 0.75:
        lines.append(
            "**Recommended Phase 2.3**: Systematic steering evaluation with the best scope, "
            "more prompts, and independent scoring (one-vs-rest vectors or LLM-as-judge)."
        )
    else:
        lines.append(
            "**Recommended**: Consider accepting current limitation and pivot to:",
            "",
            "1. **Multi-vector approach** (calm vector for calm steering, angry vector for angry steering) — use Phase 1.7 one-vs-rest or baseline vectors instead of single axis.",
            "2. **Base model test** — Qwen2.5-1.5B (non-instruct) to isolate alignment from architecture.",
            "3. **Direct logit manipulation** — skip activation steering, directly bias output token logits.",
            "4. **Accept limitation, document honestly** — the steering infrastructure works but Qwen2.5-1.5B-Instruct is resistant at this scale. This is a legitimate finding for the project.",
        )

    return "\n".join(lines) + "\n"


# ── Main ───────────────────────────────────────────────────────────


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    # Load steering vector
    print(f"[08_ablation] Loading: {ALT_VECTORS_PATH}")
    try:
        artifact = torch.load(ALT_VECTORS_PATH, map_location="cpu", weights_only=False)
    except TypeError:
        artifact = torch.load(ALT_VECTORS_PATH, map_location="cpu")
    steering_vector = artifact["methods"]["direct_contrast_axis"]["angry_vs_calm_axis"]
    print(f"[08_ablation] Vector: shape={tuple(steering_vector.shape)}, norm={steering_vector.float().norm():.4f}")

    # Load model
    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    all_rows = []
    scope_metrics_list = []

    for scope in SCOPES:
        scope_name = scope["name"]
        layers = scope["layers"]
        pos_mode = scope["position_mode"]

        print(f"\n{'='*60}")
        print(f"Scope: {scope_name}")
        print(f"  layers={layers}, position={pos_mode}")
        print(f"{'='*60}")

        scope_rows = []

        for alpha in ALPHAS:
            for pitem in TEST_PROMPTS:
                pid = pitem["id"]
                prompt = format_chat_prompt(tokenizer, pitem["text"])

                print(f"  {pid} alpha={alpha:+.0f} ... ", end="", flush=True)

                try:
                    output = generate_with_multi_layer_steering(
                        model=model,
                        tokenizer=tokenizer,
                        prompt=prompt,
                        steering_vector=steering_vector,
                        layer_indices=layers,
                        alpha=alpha,
                        position_mode=pos_mode,
                        max_new_tokens=96,
                        max_input_tokens=MAX_INPUT_TOKENS,
                        do_sample=False,
                        repetition_penalty=1.05,
                    )
                except Exception as e:
                    output = f"ERROR: {e}"
                    print(f"FAILED: {e}")
                    output = ""

                output_len = len(output)

                # Score
                try:
                    out_act = get_last_token_activation(
                        model, tokenizer, output, LAYER_IDX, MAX_INPUT_TOKENS
                    )
                    axis_score = _cosine(out_act, steering_vector)
                except Exception:
                    axis_score = 0.0

                row = {
                    "scope_name": scope_name,
                    "layers": str(layers),
                    "position_mode": pos_mode,
                    "prompt_id": pid,
                    "alpha": alpha,
                    "output": output,
                    "axis_score": round(axis_score, 4),
                    "output_length": output_len,
                    "has_extra_dialogue": has_extra_dialogue(output),
                    "has_repetition": has_repetition(output),
                }
                scope_rows.append(row)
                all_rows.append(row)

                flags = ""
                if row["has_extra_dialogue"]:
                    flags += " EXTRA"
                if row["has_repetition"]:
                    flags += " REP"
                print(f"axis={axis_score:+.4f} len={output_len}{flags}")

        # Compute scope metrics
        metrics = compute_scope_metrics(scope_rows)
        scope_metrics_list.append(metrics)

        print(f"  axis_slope: {metrics['axis_slope']:.6f}")
        print(f"  directional_consistency: {metrics['directional_consistency']:.2f}")
        print(f"  extra_dialogue: {metrics['extra_dialogue_rate']:.0%}")
        print(f"  repetition: {metrics['repetition_rate']:.0%}")

    # Save outputs
    write_jsonl(OUTPUT_JSONL_PATH, all_rows)
    summary_df = pd.DataFrame(scope_metrics_list)
    write_csv(SUMMARY_CSV_PATH, summary_df)

    # Generate report
    report_md = generate_report(scope_metrics_list, all_rows)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_md, encoding="utf-8")

    # Print final summary
    print(f"\n{'='*80}")
    print("Phase 2.2 Steering Ablation — Final Summary")
    print(f"{'='*80}")

    best = max(scope_metrics_list, key=lambda m: (m["directional_consistency"], abs(m["axis_slope"])))
    for m in scope_metrics_list:
        marker = " ← BEST" if m["scope_name"] == best["scope_name"] else ""
        print(
            f"{m['scope_name']}{marker}: "
            f"slope={m['axis_slope']:.6f}, "
            f"dir_consistency={m['directional_consistency']:.2f}"
        )

    print(f"\nBest scope: {best['scope_name']}")
    print(f"Saved outputs: {OUTPUT_JSONL_PATH}")
    print(f"Saved summary: {SUMMARY_CSV_PATH}")
    print(f"Saved report: {REPORT_PATH}")
    print("[08_ablation] Done.")


if __name__ == "__main__":
    main()
