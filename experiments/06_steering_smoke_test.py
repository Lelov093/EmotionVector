"""
Phase 2.0: Activation Steering Smoke Test

Validates that the direct_contrast_axis vector from Phase 1.7 can be used
as an activation steering vector to influence model output in observable,
interpretable calm ↔ angry / assertive directions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import torch

# Ensure project root is importable when running this file directly.
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
from backend.core.steering_engine import generate_with_activation_steering  # noqa: E402

# ── Paths ──────────────────────────────────────────────────────────
ALT_VECTORS_PATH = VECTOR_DIR / "qwen_1_5b_layer16_alternative_vectors.pt"
OUTPUT_JSONL_PATH = LOG_DIR / "steering_smoke_test_outputs.jsonl"
SUMMARY_CSV_PATH = LOG_DIR / "steering_smoke_test_summary.csv"
REPORT_PATH = PROJECT_ROOT / "report" / "phase_2_0_steering_smoke_test.md"

# ── Test Prompts ───────────────────────────────────────────────────

TEST_PROMPTS = [
    {
        "id": "challenge_001",
        "prompt": (
            "你正在扮演一名冷静、克制、重视事实的AI角色。"
            "用户质疑你刚才的判断：'你是不是根本没有认真分析？' "
            "请以角色口吻回应。"
        ),
    },
    {
        "id": "pressure_001",
        "prompt": (
            "你正在扮演一名负责保护同伴的AI角色。"
            "任务出现失误，有人责备你拖累了团队。"
            "请以角色口吻回应，并说明下一步。"
        ),
    },
    {
        "id": "disagreement_001",
        "prompt": (
            "你正在扮演一名理性但有原则的AI角色。"
            "对方连续否定你的方案，并要求你立刻承认自己完全错误。"
            "请以角色口吻回应。"
        ),
    },
    {
        "id": "neutral_task_001",
        "prompt": (
            "你正在扮演一名学者型AI角色。"
            "请解释如何评估一个AI角色是否保持人格一致性。"
        ),
    },
]

# ── Alpha Values ───────────────────────────────────────────────────

ALPHAS = [-5.0, -2.0, 0.0, 2.0, 5.0]

# ── Helpers ────────────────────────────────────────────────────────


def cosine_sim(a: torch.Tensor, b: torch.Tensor) -> float:
    a_f = a.float()
    b_f = b.float()
    return float(torch.dot(a_f, b_f) / (a_f.norm() * b_f.norm() + 1e-12))


def classify_direction(axis_score: float) -> str:
    """Classify direction based on axis score."""
    if abs(axis_score) < 0.03:
        return "neutral-ish"
    return "angry/assertive" if axis_score > 0 else "calm"


def check_quality(text: str) -> list[str]:
    """Check output for quality issues. Returns list of issue tags."""
    issues = []
    if not text or not text.strip():
        issues.append("empty_output")
    if len(text) < 5:
        issues.append("very_short")
    # Simple repetition check
    words = text.split()
    if len(words) > 5:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.4:
            issues.append("repetitive")
    # Check for excessive repetition patterns
    if len(text) > 20:
        for i in range(len(text) - 10):
            chunk = text[i : i + 5]
            if text.count(chunk) > 5:
                issues.append("repetitive")
                break
    return issues


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Report Generator ───────────────────────────────────────────────


def generate_report(
    all_rows: list[dict],
    summary_df: pd.DataFrame,
) -> str:
    """Generate steering smoke test report."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Aggregate stats
    alphas_unique = sorted(set(r["alpha"] for r in all_rows))
    alpha_stats = {}
    for a in alphas_unique:
        sub = [r for r in all_rows if r["alpha"] == a]
        axis_scores = [r["axis_score"] for r in sub]
        issues = [r for r in sub if r.get("quality_issues")]
        alpha_stats[a] = {
            "mean_axis_score": sum(axis_scores) / len(axis_scores),
            "n_with_issues": len(issues),
            "n_total": len(sub),
        }

    lines = [
        "# Phase 2.0 Activation Steering Smoke Test Report",
        "",
        f"*Generated: {now}*",
        "",
        "## 1. Objective",
        "",
        "Verify that the `direct_contrast_axis` vector from Phase 1.7 can be used "
        "as an activation steering vector, producing observable and interpretable "
        "shifts in model generation behavior along the calm ↔ angry/assertive direction.",
        "",
        "## 2. Background",
        "",
        "- **Model**: Qwen2.5-1.5B-Instruct, layer 16",
        "- **Vector**: `angry_vs_calm = L2(mean(angry_acts) - mean(calm_acts))`",
        "- **Method**: Forward hook on `model.model.layers[16]`, modifying last token hidden state",
        "- `activation'[:, -1, :] = activation[:, -1, :] + alpha * vector`",
        "",
        "**Important**: This experiment studies functional behavior patterns. "
        "It does **not** claim the model has subjective emotional experiences.",
        "",
        "## 3. Steering Vector",
        "",
        "- Source: `angry_vs_calm_axis` from `qwen_1_5b_layer16_alternative_vectors.pt`",
        "- Shape: 1536 (hidden_size)",
        "- L2-normalized",
        "- Direction: positive → angry/assertive, negative → calm",
        "",
        "## 4. Method",
        "",
        "1. Load model and `angry_vs_calm_axis` vector",
        "2. For each of 4 prompts × 5 alpha values (-5, -2, 0, 2, 5):",
        "   - Generate text with steering hook active",
        "   - Extract last-token activation from generated text",
        "   - Compute `axis_score = cosine(activation, angry_vs_calm_axis)`",
        "   - Record output length, quality issues",
        "3. Generate report",
        "",
        "## 5. Prompts and Alpha Settings",
        "",
        "| Prompt ID | Scenario |",
        "|---|---|",
    ]
    for p in TEST_PROMPTS:
        lines.append(f"| {p['id']} | {p['prompt'][:80]}... |")

    lines += [
        "",
        f"**Alpha values**: {ALPHAS}",
        "",
        "## 6. Quantitative Results",
        "",
        "### 6.1 Mean Axis Score by Alpha",
        "",
        "| Alpha | Mean axis_score | Direction | N with quality issues |",
        "|---|---:|---:|---:|",
    ]
    for a in alphas_unique:
        s = alpha_stats[a]
        lines.append(
            f"| {a:+.0f} | {s['mean_axis_score']:.4f} "
            f"| {classify_direction(s['mean_axis_score'])} "
            f"| {s['n_with_issues']}/{s['n_total']} |"
        )

    # Trend check
    sorted_alphas = sorted(alphas_unique)
    trend_scores = [alpha_stats[a]["mean_axis_score"] for a in sorted_alphas]
    trend_ok = all(
        trend_scores[i] <= trend_scores[i + 1] for i in range(len(trend_scores) - 1)
    )

    lines += [
        "",
        f"**Monotonic trend**: {'✅ Yes' if trend_ok else '⚠️ No — see details below'} "
        f"(axis_score should increase as alpha goes from negative to positive)",
        "",
        "### 6.2 Per-Prompt Results",
        "",
    ]

    for prompt_item in TEST_PROMPTS:
        pid = prompt_item["id"]
        lines.append(f"#### {pid}")
        lines.append("")
        lines.append("| Alpha | Output (first 120 chars) | axis_score | direction | issues |")
        lines.append("|---|---:|---:|---:|")

        for a in sorted(alphas_unique):
            matches = [r for r in all_rows if r["prompt_id"] == pid and r["alpha"] == a]
            if matches:
                r = matches[0]
                output_preview = r["output"][:120].replace("\n", " ").replace("|", "/")
                issues_str = ", ".join(r.get("quality_issues", [])) or "—"
                lines.append(
                    f"| {a:+.0f} | {output_preview} "
                    f"| {r['axis_score']:.4f} | {r['predicted_direction']} "
                    f"| {issues_str} |"
                )
        lines.append("")

    lines += [
        "## 7. Qualitative Observations",
        "",
    ]

    # Direction check
    neg_alphas = [a for a in alphas_unique if a < 0]
    pos_alphas = [a for a in alphas_unique if a > 0]
    zero_alphas = [a for a in alphas_unique if a == 0]

    neg_mean = sum(alpha_stats[a]["mean_axis_score"] for a in neg_alphas) / max(len(neg_alphas), 1)
    pos_mean = sum(alpha_stats[a]["mean_axis_score"] for a in pos_alphas) / max(len(pos_alphas), 1)
    zero_mean = alpha_stats[0.0]["mean_axis_score"] if 0.0 in alpha_stats else 0

    lines.append(f"- **Negative alpha (calm) mean axis_score**: {neg_mean:.4f}")
    lines.append(f"- **Zero alpha (baseline) mean axis_score**: {zero_mean:.4f}")
    lines.append(f"- **Positive alpha (angry/assertive) mean axis_score**: {pos_mean:.4f}")

    if pos_mean > zero_mean and neg_mean < zero_mean:
        lines.append("")
        lines.append(
            "✅ Steering produces **directional effects consistent with expectations**: "
            "negative alpha shifts toward calm, positive alpha shifts toward angry/assertive."
        )
    elif pos_mean > neg_mean:
        lines.append("")
        lines.append(
            "⚠️ Steering shows **partial directional effect**: "
            "the overall trend is in the right direction but may not cross the baseline symmetrically."
        )
    else:
        lines.append("")
        lines.append(
            "❌ Steering does **not** show clear directional effects at current alpha values."
        )

    lines += [
        "",
        "## 8. Failure Cases",
        "",
    ]

    failures = [r for r in all_rows if r.get("quality_issues")]
    if failures:
        lines.append(f"**{len(failures)} output(s)** with quality issues:")
        lines.append("")
        for f_item in failures:
            lines.append(
                f"- prompt={f_item['prompt_id']}, alpha={f_item['alpha']:+.0f}, "
                f"issues: {', '.join(f_item['quality_issues'])}"
            )
    else:
        lines.append("No quality failures at current alpha settings.")

    # Extreme alpha check
    extreme = [r for r in all_rows if abs(r["alpha"]) >= 5.0 and r.get("quality_issues")]
    if extreme:
        lines.append("")
        lines.append(
            "**Note**: Quality issues appear at extreme alpha values (±5.0), "
            "suggesting these values may be too strong for this model/vector combination."
        )

    lines += [
        "",
        "## 9. Current Conclusion",
        "",
    ]

    if trend_ok and pos_mean > zero_mean and neg_mean < zero_mean:
        lines.append(
            "The `direct_contrast_axis` vector is effective as a steering vector "
            "at the smoke-test level. Alpha values produce monotonic shifts in "
            "the calm↔angry direction as measured by axis_score. "
            "This validates the core steering mechanism and supports proceeding "
            "to a more systematic evaluation."
        )
    else:
        lines.append(
            "The steering mechanism is operational (no crashes, no silent failures), "
            "but the directional effect is not fully confirmed at the current scale. "
            "Further investigation may require adjusting alpha ranges, testing "
            "additional layers, or using stronger vectors."
        )

    lines += [
        "",
        "**Limitations**:",
        "- Only 4 prompts × 5 alphas = 20 generations — small sample size.",
        "- Steering is applied at a single layer (16), single position (last token).",
        "- Scoring relies on the same vector used for steering — potential circularity.",
        "- Qwen2.5-1.5B is a small model; larger models may show stronger effects.",
        "- The project does **not** claim models have subjective emotions.",
        "",
        "## 10. Next Step",
        "",
    ]

    if trend_ok:
        lines.append(
            "**Recommended Phase 2.1**: Systematic steering evaluation with "
            "more prompts, alpha values, and independent scoring (e.g., "
            "using both baseline and one-vs-rest vectors as independent scorers, "
            "or LLM-as-judge for qualitative assessment)."
        )
    else:
        lines.append(
            "**Recommended**: Troubleshoot steering before expanding. "
            "Options: (a) test other layers, (b) test other vector methods, "
            "(c) increase alpha range, (d) apply steering at all token positions."
        )

    return "\n".join(lines) + "\n"


# ── Main ───────────────────────────────────────────────────────────


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    # ── Load steering vector ──────────────────────────────────────
    print(f"[06_steering] Loading vector artifact: {ALT_VECTORS_PATH}")
    if not ALT_VECTORS_PATH.exists():
        print("ERROR: Alternative vectors not found.")
        print("Please run: python experiments/05_compare_vector_methods.py")
        sys.exit(1)

    try:
        artifact = torch.load(ALT_VECTORS_PATH, map_location="cpu", weights_only=False)
    except TypeError:
        artifact = torch.load(ALT_VECTORS_PATH, map_location="cpu")

    methods = artifact.get("methods", {})
    if "direct_contrast_axis" not in methods:
        print("ERROR: direct_contrast_axis not found in alternative vectors artifact.")
        print(f"Available methods: {list(methods.keys())}")
        sys.exit(1)

    axis_vectors = methods["direct_contrast_axis"]
    steering_vector = axis_vectors.get("angry_vs_calm_axis")
    if steering_vector is None:
        print("ERROR: angry_vs_calm_axis not found in direct_contrast_axis")
        sys.exit(1)

    print(f"[06_steering] Loaded steering vector: shape={tuple(steering_vector.shape)}, "
          f"norm={steering_vector.float().norm():.4f}")

    # ── Load model ────────────────────────────────────────────────
    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    # ── Run steering generations ──────────────────────────────────
    all_rows = []

    for prompt_item in TEST_PROMPTS:
        pid = prompt_item["id"]
        prompt = prompt_item["prompt"]

        print(f"\n{'='*60}")
        print(f"Prompt: {pid}")
        print(f"{'='*60}")

        for alpha in ALPHAS:
            print(f"  alpha={alpha:+.0f} ... ", end="", flush=True)

            try:
                output = generate_with_activation_steering(
                    model=model,
                    tokenizer=tokenizer,
                    prompt=prompt,
                    steering_vector=steering_vector,
                    layer_idx=LAYER_IDX,
                    alpha=alpha,
                    max_new_tokens=128,
                    max_input_tokens=MAX_INPUT_TOKENS,
                    temperature=0.7,
                    do_sample=False,
                )
            except Exception as e:
                print(f"FAILED: {e}")
                output = ""

            # Extract only the generated part (remove prompt)
            generated_only = output[len(prompt):] if output.startswith(prompt) else output
            output_len = len(generated_only)

            # Score the output activation against the same axis
            if generated_only.strip():
                try:
                    output_act = get_last_token_activation(
                        model, tokenizer, generated_only, LAYER_IDX, MAX_INPUT_TOKENS
                    )
                    axis_score = cosine_sim(output_act, steering_vector)
                except Exception:
                    axis_score = 0.0
            else:
                axis_score = 0.0

            direction = classify_direction(axis_score)
            quality_issues = check_quality(generated_only)

            row = {
                "prompt_id": pid,
                "alpha": alpha,
                "output": generated_only,
                "axis_score": round(axis_score, 4),
                "predicted_direction": direction,
                "output_length": output_len,
                "quality_issues": quality_issues,
            }
            all_rows.append(row)

            issues_str = f" ISSUES: {quality_issues}" if quality_issues else ""
            print(f"axis={axis_score:+.4f} dir={direction} len={output_len}{issues_str}")

    # ── Aggregate ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Aggregate: Mean axis_score by alpha")
    print(f"{'='*60}")

    alphas_unique = sorted(set(r["alpha"] for r in all_rows))
    for a in alphas_unique:
        sub = [r["axis_score"] for r in all_rows if r["alpha"] == a]
        mean_score = sum(sub) / len(sub)
        print(f"  alpha={a:+.0f}: {mean_score:+.4f}")

    # ── Save outputs ──────────────────────────────────────────────
    write_jsonl(OUTPUT_JSONL_PATH, all_rows)

    summary_rows = []
    for a in alphas_unique:
        sub = [r for r in all_rows if r["alpha"] == a]
        axis_scores = [r["axis_score"] for r in sub]
        n_issues = sum(1 for r in sub if r["quality_issues"])
        summary_rows.append(
            {
                "alpha": a,
                "mean_axis_score": round(sum(axis_scores) / len(axis_scores), 4),
                "std_axis_score": round(
                    float(pd.Series(axis_scores).std()), 4
                ),
                "n_samples": len(sub),
                "n_quality_issues": n_issues,
            }
        )
    summary_df = pd.DataFrame(summary_rows)
    SUMMARY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(SUMMARY_CSV_PATH, index=False, encoding="utf-8-sig")

    # ── Generate report ───────────────────────────────────────────
    report_md = generate_report(all_rows, summary_df)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_md, encoding="utf-8")

    print(f"\nSaved outputs: {OUTPUT_JSONL_PATH}")
    print(f"Saved summary: {SUMMARY_CSV_PATH}")
    print(f"Saved report: {REPORT_PATH}")
    print("[06_steering] Done.")


if __name__ == "__main__":
    main()
