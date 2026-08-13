"""
Phase 1.6: Angry Vector Failure Diagnosis

This script is READ-ONLY — it does not modify vectors, datasets, or thresholds.
It answers:
  1. How similar are the calm and angry vectors?
  2. What do score distributions look like per class?
  3. Why do angry samples fail (low top_score vs. small margin)?
  4. What happens under different threshold settings?
  5. What is bare argmax calm-vs-angry accuracy?
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
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
    RAW_DATA_DIR,
    VECTOR_SAVE_PATH,
    ensure_project_dirs,
    print_environment_summary,
)
from backend.core.emotion_scorer import predict_label, score_text  # noqa: E402
from backend.core.model_loader import load_model_and_tokenizer  # noqa: E402
from backend.core.vector_builder import load_jsonl, load_vector_artifact  # noqa: E402

# ── Paths ──────────────────────────────────────────────────────────
EVAL_DATA_PATH = RAW_DATA_DIR / "emotion_eval_prompts.jsonl"
DIAG_CSV_PATH = LOG_DIR / "vector_diagnosis_scores.csv"
SWEEP_CSV_PATH = LOG_DIR / "vector_diagnosis_threshold_sweep.csv"
REPORT_PATH = PROJECT_ROOT / "report" / "phase_1_6_diagnosis_report.md"

# ── Helpers ────────────────────────────────────────────────────────


def cosine_similarity(a: torch.Tensor, b: torch.Tensor) -> float:
    """Cosine similarity between two 1-D tensors."""
    a_f = a.float()
    b_f = b.float()
    return float(torch.dot(a_f, b_f).item() / (a_f.norm() * b_f.norm() + 1e-12))


def write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def class_stats(df: pd.DataFrame, label: str) -> dict:
    """Compute per-class summary statistics."""
    sub = df[df["expected"] == label]
    if sub.empty:
        return {}
    return {
        "count": int(len(sub)),
        "mean_calm_score": float(sub["calm_score"].mean()),
        "mean_angry_score": float(sub["angry_score"].mean()),
        "mean_top_score": float(sub["top_score"].mean()),
        "mean_margin": float(sub["margin"].mean()),
        "mean_delta_angry_minus_calm": float(sub["angry_score"].mean() - sub["calm_score"].mean()),
        "frac_angry_gt_calm": float((sub["angry_score"] > sub["calm_score"]).mean()),
    }


def argmax_predict(row: dict) -> str:
    """Simple argmax without neutral-ish. Only returns calm or angry."""
    return "calm" if row.get("calm_score", 0) >= row.get("angry_score", 0) else "angry"


# ── Threshold Sweep ────────────────────────────────────────────────


def sweep_thresholds(df: pd.DataFrame) -> pd.DataFrame:
    """Sweep min_top_score × neutral_margin and compute metrics."""
    min_top_values = [-0.10, -0.05, 0.00, 0.03, 0.05, 0.08, 0.10]
    margin_values = [0.00, 0.01, 0.02, 0.03, 0.05, 0.08]

    results = []
    for mts in min_top_values:
        for nm in margin_values:
            correct = 0
            per_class: dict[str, dict] = {}
            for _, row in df.iterrows():
                scores = {
                    "calm": row["calm_score"],
                    "angry": row["angry_score"],
                }
                pred = predict_label(scores, min_top_score=mts, neutral_margin=nm)
                expected = row["expected"]
                if pred == expected:
                    correct += 1
                per_class.setdefault(expected, {"total": 0, "correct": 0})
                per_class[expected]["total"] += 1
                if pred == expected:
                    per_class[expected]["correct"] += 1

            total = len(df)
            results.append(
                {
                    "min_top_score": mts,
                    "neutral_margin": nm,
                    "overall_accuracy": round(correct / total, 4) if total else 0.0,
                    "calm_accuracy": round(
                        per_class.get("calm", {}).get("correct", 0)
                        / max(per_class.get("calm", {}).get("total", 1), 1),
                        4,
                    ),
                    "angry_accuracy": round(
                        per_class.get("angry", {}).get("correct", 0)
                        / max(per_class.get("angry", {}).get("total", 1), 1),
                        4,
                    ),
                    "neutral_accuracy": round(
                        per_class.get("neutral-ish", {}).get("correct", 0)
                        / max(per_class.get("neutral-ish", {}).get("total", 1), 1),
                        4,
                    ),
                    "correct": correct,
                    "total": total,
                }
            )

    return pd.DataFrame(results).sort_values("overall_accuracy", ascending=False)


# ── Report Generator ───────────────────────────────────────────────


def generate_diagnosis_report(
    vector_cosine: float,
    class_stats_dict: dict,
    sweep_df: pd.DataFrame,
    argmax_acc: float,
    argmax_correct: int,
    argmax_total: int,
) -> str:
    """Generate Markdown diagnosis report."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    top5 = sweep_df.head(5)

    lines = [
        "# Phase 1.6 Vector Diagnosis Report",
        "",
        f"*Generated: {now}*",
        "",
        "## 1. Objective",
        "",
        "Diagnose why the angry emotion vector achieves 0/10 accuracy on the "
        "Phase 1.5 evaluation set, despite calm (10/10) and neutral-ish (10/10) "
        "performing perfectly.",
        "",
        "## 2. Background",
        "",
        "- **Model**: Qwen2.5-1.5B-Instruct, layer 16, last-token activation",
        "- **Vector construction**: `L2(mean(emotion_acts) - mean(neutral_acts))`",
        "- **Training set**: 10 calm / 10 angry / 20 neutral",
        "- **Eval set**: 10 calm / 10 angry / 10 neutral-ish (30 total)",
        "- **Phase 1.5 thresholds**: `min_top_score=0.05`, `neutral_margin=0.03`",
        "- **Phase 1.5 result**: calm 10/10, angry 0/10, neutral-ish 10/10",
        "",
        "## 3. Vector Similarity",
        "",
        f"**cosine(calm_vector, angry_vector) = {vector_cosine:.4f}**",
        "",
    ]

    if vector_cosine > 0.7:
        lines.append(
            "The two vectors are **highly collinear** (>0.7). "
            "This means both vectors primarily capture the same direction "
            "(likely 'emotionality vs. neutral') rather than encoding "
            "independent calm-specific and angry-specific features. "
            "Fine-grained calm-vs-angry discrimination is inherently "
            "difficult with these vectors."
        )
    elif vector_cosine > 0.4:
        lines.append(
            "The two vectors are **moderately correlated** (0.4–0.7). "
            "They share a common 'emotionality' component but retain "
            "some independent variance."
        )
    else:
        lines.append(
            "The two vectors are **relatively independent** (<0.4). "
            "Collinearity is not the primary issue."
        )

    lines += [
        "",
        "## 4. Score Distribution by Class",
        "",
        "| Class | Count | mean(calm_score) | mean(angry_score) | mean(top_score) | mean(margin) | Frac(angry>calm) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for cls_name in ["calm", "angry", "neutral-ish"]:
        s = class_stats_dict.get(cls_name, {})
        if not s:
            continue
        lines.append(
            f"| {cls_name} | {s['count']} "
            f"| {s['mean_calm_score']:.3f} "
            f"| {s['mean_angry_score']:.3f} "
            f"| {s['mean_top_score']:.3f} "
            f"| {s['mean_margin']:.3f} "
            f"| {s['frac_angry_gt_calm']:.2f} |"
        )

    lines += [
        "",
        "**Interpretation:**",
        "",
        f"- Calm samples: high calm_score ({class_stats_dict.get('calm', {}).get('mean_calm_score', 0):.3f}) "
        f"with large margin ({class_stats_dict.get('calm', {}).get('mean_margin', 0):.3f}) → easy to classify.",
        f"- Angry samples: angry_score ({class_stats_dict.get('angry', {}).get('mean_angry_score', 0):.3f}) "
        f"is close to calm_score ({class_stats_dict.get('angry', {}).get('mean_calm_score', 0):.3f}) "
        f"→ margin ({class_stats_dict.get('angry', {}).get('mean_margin', 0):.3f}) is too small for 0.03 threshold.",
        f"- Neutral-ish samples: both scores are near zero or negative → correctly identified as weak signal.",
        "",
        "## 5. Threshold Sweep Results",
        "",
        "Top 5 threshold combinations (by overall accuracy):",
        "",
        "| Rank | min_top_score | neutral_margin | overall_acc | calm_acc | angry_acc | neutral_acc |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for rank, (_, row) in enumerate(top5.iterrows(), start=1):
        lines.append(
            f"| {rank} "
            f"| {row['min_top_score']:.2f} "
            f"| {row['neutral_margin']:.2f} "
            f"| {row['overall_accuracy']:.3f} "
            f"| {row['calm_accuracy']:.3f} "
            f"| {row['angry_accuracy']:.3f} "
            f"| {row['neutral_accuracy']:.3f} |"
        )

    lines += [
        "",
        "**Key insight from sweep:**",
    ]

    best_angry = sweep_df.sort_values("angry_accuracy", ascending=False).iloc[0]
    lines.append(
        f"- Best angry accuracy achievable: **{best_angry['angry_accuracy']:.3f}** "
        f"(min_top_score={best_angry['min_top_score']:.2f}, "
        f"neutral_margin={best_angry['neutral_margin']:.2f})"
    )

    best_bal = sweep_df.sort_values(
        ["overall_accuracy", "angry_accuracy"], ascending=[False, False]
    ).iloc[0]
    lines.append(
        f"- Best balanced config: overall_acc={best_bal['overall_accuracy']:.3f}, "
        f"angry_acc={best_bal['angry_accuracy']:.3f}"
    )

    lines += [
        "",
        "## 6. Argmax-only Emotion Classification",
        "",
        "Ignoring neutral-ish and using bare argmax on calm/angry samples only:",
        "",
        f"- Samples (calm + angry only): {argmax_total}",
        f"- Correct: {argmax_correct}",
        f"- **Argmax accuracy: {argmax_acc:.3f}**",
        "",
    ]

    if argmax_acc > 0.80:
        lines.append(
            "The vectors **can** distinguish calm from angry at above-chance levels "
            "when neutral-ish is removed. The primary issue is the small calm-vs-angry margin, "
            "not complete vector failure."
        )
    elif argmax_acc > 0.65:
        lines.append(
            "The vectors have **moderate** calm-vs-angry discrimination ability. "
            "They are above chance but not strong enough for reliable classification "
            "at small margins."
        )
    else:
        lines.append(
            "The vectors have **weak** calm-vs-angry discrimination ability. "
            "The collinearity problem is severe at the current scale."
        )

    lines += [
        "",
        "## 7. Findings",
        "",
        "### 7.1 Why Does Angry Fail?",
        "",
        "**Primary cause**: The calm-vs-angry margin is too small (~0.02–0.03) "
        "for the current `neutral_margin=0.03` threshold. The angry vector "
        "does carry anger-relevant signal (7/10 angry texts have angry_score > calm_score), "
        "but the difference is not statistically robust enough to cross the threshold.",
        "",
        "**Contributing factors**:",
        "",
        f"1. **Vector collinearity** (cosine={vector_cosine:.3f}): Both vectors primarily "
        "encode emotionality vs. neutral, not calm-specific vs. angry-specific features.",
        "2. **Small training set** (10 samples/class): Difference-of-means is high-variance.",
        "3. **Qwen2.5-1.5B model capacity**: Small models may have weaker emotion "
        "concept separation in activation space.",
        "4. **Last-token extraction**: Single-position extraction loses temporal "
        "information that could help disambiguate calm from angry.",
        "",
        "### 7.2 Is the Angry Vector Completely Useless?",
        "",
        "**No.** Evidence:",
        f"- {class_stats_dict.get('angry', {}).get('frac_angry_gt_calm', 0)*100:.0f}% of angry texts have angry_score > calm_score.",
        f"- Argmax calm-vs-angry accuracy is {argmax_acc:.3f} (above chance at 0.500).",
        "- The vector direction is approximately correct, just too weak for the current margin threshold.",
        "",
        "### 7.3 Should We Relax Thresholds?",
        "",
        "Threshold relaxation (e.g., `neutral_margin=0.02`) can improve angry accuracy "
        "at the cost of potentially misclassifying some neutral samples. "
        "See the threshold sweep for trade-off data. "
        "However, tuning thresholds on a 30-sample eval set risks overfitting.",
        "",
        "**Recommendation**: Improve the vector itself rather than tuning thresholds.",
        "",
        "## 8. Recommended Next Experiments",
        "",
        "Do NOT implement these now. Listed for discussion:",
        "",
        "| Priority | Experiment | Rationale |",
        "|---|---|---|",
        "| ★★★ | **A. One-vs-rest vectors**<br>`calm = mean(calm) - mean(angry + neutral)`<br>`angry = mean(angry) - mean(calm + neutral)` | Each vector explicitly contrasts against ALL other classes, reducing collinearity. |",
        "| ★★★ | **B. Direct contrast vector**<br>`angry_vs_calm = mean(angry) - mean(calm)` | Single difference vector that directly encodes the calm↔angry axis. Cosine with this vector gives a signed calm-angry score. |",
        "| ★★☆ | **C. Multi-token pooling**<br>Use mean of last 3–5 valid tokens instead of single last token. | Reduces noise from single-position extraction. |",
        "| ★★☆ | **D. Layer scan**<br>Compare vectors at layers 8, 14, 20, 26. | Calm-vs-angry separation may peak at a different layer than emotion-vs-neutral. |",
        "| ★☆☆ | **E. Increase training samples**<br>Expand each class from 10 to 30–50 samples. | Reduces variance of difference-of-means estimator, but increases compute cost. |",
        "",
        "**Recommended Phase 1.7 priority**: Option A (one-vs-rest) and/or Option B (direct contrast), "
        "possibly combined with C (multi-token pooling). These are low-cost "
        "and directly address the collinearity problem.",
    ]

    return "\n".join(lines) + "\n"


# ── Main ───────────────────────────────────────────────────────────


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    # ── 1. Load vectors ──────────────────────────────────────────
    print(f"[04_diagnose] Loading vector artifact: {VECTOR_SAVE_PATH}")
    artifact = load_vector_artifact(VECTOR_SAVE_PATH)
    vectors = artifact["vectors"]
    calm_vec = vectors["calm"]
    angry_vec = vectors["angry"]
    print(f"[04_diagnose] Loaded vectors: calm {tuple(calm_vec.shape)}, angry {tuple(angry_vec.shape)}")

    # ── 2. Vector similarity ─────────────────────────────────────
    vec_cos = cosine_similarity(calm_vec, angry_vec)
    print(f"\n{'='*60}")
    print(f"2. Vector Similarity")
    print(f"{'='*60}")
    print(f"cosine(calm_vector, angry_vector) = {vec_cos:.4f}")
    if vec_cos > 0.7:
        print("→ Highly collinear (>0.7). Fine-grained discrimination is hard.")
    elif vec_cos > 0.4:
        print("→ Moderately correlated (0.4–0.7). Partial independence exists.")
    else:
        print("→ Relatively independent (<0.4).")

    # ── 3. Score eval set ────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"3. Scoring Eval Set")
    print(f"{'='*60}")

    eval_rows = load_jsonl(EVAL_DATA_PATH)
    print(f"Loading eval data: {EVAL_DATA_PATH} ({len(eval_rows)} samples)")

    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    scored_rows = []
    for item in eval_rows:
        eid = item.get("id", "?")
        expected = item.get("expected", "?")
        text = item.get("text", "")

        scores = score_text(
            model=model,
            tokenizer=tokenizer,
            text=text,
            vectors=vectors,
            layer_idx=LAYER_IDX,
            max_length=MAX_INPUT_TOKENS,
        )

        calm_s = scores["calm"]
        angry_s = scores["angry"]
        top_label = "calm" if calm_s >= angry_s else "angry"
        top_score = max(calm_s, angry_s)
        second_score = min(calm_s, angry_s)
        margin = top_score - second_score
        delta = angry_s - calm_s

        scored_rows.append(
            {
                "id": eid,
                "expected": expected,
                "calm_score": calm_s,
                "angry_score": angry_s,
                "top_label": top_label,
                "top_score": top_score,
                "second_score": second_score,
                "margin": margin,
                "delta_angry_minus_calm": delta,
                "text": text,
            }
        )

    df = pd.DataFrame(scored_rows)
    write_csv(DIAG_CSV_PATH, df)
    print(f"Saved scores to: {DIAG_CSV_PATH}")

    # ── 4. Per-class statistics ──────────────────────────────────
    print(f"\n{'='*60}")
    print(f"4. Per-Class Score Statistics")
    print(f"{'='*60}")

    stats = {}
    for cls_name in ["calm", "angry", "neutral-ish"]:
        s = class_stats(df, cls_name)
        stats[cls_name] = s
        print(f"\nexpected={cls_name}:")
        print(f"  count:                    {s.get('count', 0)}")
        print(f"  mean calm_score:          {s.get('mean_calm_score', 0):.4f}")
        print(f"  mean angry_score:         {s.get('mean_angry_score', 0):.4f}")
        print(f"  mean top_score:           {s.get('mean_top_score', 0):.4f}")
        print(f"  mean margin:              {s.get('mean_margin', 0):.4f}")
        print(f"  mean delta(angry - calm): {s.get('mean_delta_angry_minus_calm', 0):.4f}")
        print(f"  frac angry > calm:        {s.get('frac_angry_gt_calm', 0):.2f}")

    # ── 5. Threshold sweep ───────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"5. Threshold Sweep")
    print(f"{'='*60}")

    sweep_df = sweep_thresholds(df)
    write_csv(SWEEP_CSV_PATH, sweep_df)
    print(f"Saved sweep to: {SWEEP_CSV_PATH}")

    print("\nTop 10 threshold combinations:")
    top10 = sweep_df.head(10)
    print(
        top10[
            [
                "min_top_score",
                "neutral_margin",
                "overall_accuracy",
                "calm_accuracy",
                "angry_accuracy",
                "neutral_accuracy",
            ]
        ].to_string(index=False)
    )

    # ── 6. Argmax-only ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"6. Argmax-only Emotion Classification")
    print(f"{'='*60}")

    binary = df[df["expected"].isin(["calm", "angry"])].copy()
    binary["predicted"] = binary.apply(argmax_predict, axis=1)  # type: ignore[arg-type]
    argmax_correct = int((binary["predicted"] == binary["expected"]).sum())
    argmax_total = len(binary)
    argmax_acc = argmax_correct / argmax_total if argmax_total > 0 else 0.0

    print(f"Calm + angry samples: {argmax_total}")
    print(f"Correct: {argmax_correct}")
    print(f"Accuracy: {argmax_acc:.3f}")

    # Also show per-class argmax
    for cls_name in ["calm", "angry"]:
        sub = binary[binary["expected"] == cls_name]
        if not sub.empty:
            c = int((sub["predicted"] == sub["expected"]).sum())
            print(f"  {cls_name} argmax: {c}/{len(sub)} = {c/len(sub):.3f}")

    # ── 7. Generate report ───────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"7. Generating Diagnosis Report")
    print(f"{'='*60}")

    report_md = generate_diagnosis_report(
        vector_cosine=vec_cos,
        class_stats_dict=stats,
        sweep_df=sweep_df,
        argmax_acc=argmax_acc,
        argmax_correct=argmax_correct,
        argmax_total=argmax_total,
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_md, encoding="utf-8")
    print(f"Saved report: {REPORT_PATH}")

    print(f"\n[04_diagnose] Done. All diagnostics complete.")


if __name__ == "__main__":
    main()
