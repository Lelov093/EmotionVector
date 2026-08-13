"""
Phase 1.7: Alternative Vector Construction Methods Comparison

Compares 4 methods:
  1. baseline_neutral_contrast (existing)
  2. one_vs_rest
  3. direct_contrast_axis
  4. orthogonalized_angry_only

Activations are extracted ONCE and cached to avoid redundant computation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import (  # noqa: E402
    LAYER_IDX,
    LOG_DIR,
    MAX_INPUT_TOKENS,
    MODEL_NAME,
    RAW_DATA_DIR,
    VECTOR_DIR,
    ensure_project_dirs,
    print_environment_summary,
)
from backend.core.activation_collector import get_last_token_activation  # noqa: E402
from backend.core.emotion_scorer import predict_label  # noqa: E402
from backend.core.model_loader import load_model_and_tokenizer  # noqa: E402
from backend.core.vector_builder import group_texts_by_label, load_jsonl  # noqa: E402

# ── Paths ──────────────────────────────────────────────────────────
TRAIN_DATA_PATH = RAW_DATA_DIR / "emotion_seed_prompts.jsonl"
EVAL_DATA_PATH = RAW_DATA_DIR / "emotion_eval_prompts.jsonl"

COMP_SCORES_PATH = LOG_DIR / "vector_method_comparison_scores.csv"
COMP_SUMMARY_PATH = LOG_DIR / "vector_method_comparison_summary.csv"
ALT_VECTORS_PATH = VECTOR_DIR / "qwen_1_5b_layer16_alternative_vectors.pt"
REPORT_PATH = PROJECT_ROOT / "report" / "phase_1_7_vector_method_comparison.md"

# ── Helpers ────────────────────────────────────────────────────────


def l2_normalize(v: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    return F.normalize(v.float(), p=2, dim=0, eps=eps)


def cosine_sim(a: torch.Tensor, b: torch.Tensor) -> float:
    a_f = a.float()
    b_f = b.float()
    return float(torch.dot(a_f, b_f) / (a_f.norm() * b_f.norm() + 1e-12))


def write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


# ── Activation Caching ─────────────────────────────────────────────


def extract_all_activations(model, tokenizer, grouped_texts, eval_rows) -> dict[str, torch.Tensor]:
    """Extract activations for every text once. Return dict of label → stacked tensor."""
    print("[05_compare] Extracting activations (one pass)...")

    act_dict: dict[str, list[torch.Tensor]] = {}

    # Train texts grouped by label
    for label, texts in grouped_texts.items():
        act_dict[label] = []
        for i, text in enumerate(texts, 1):
            print(f"  train {label} {i}/{len(texts)}")
            act = get_last_token_activation(
                model, tokenizer, text, LAYER_IDX, MAX_INPUT_TOKENS
            )
            act_dict[label].append(act)

    # Eval texts grouped by expected label
    eval_texts: dict[str, list[str]] = {}
    eval_ids: list[dict] = []
    for row in eval_rows:
        expected = row["expected"]
        eval_texts.setdefault(expected, []).append(row["text"])
        eval_ids.append(
            {
                "id": row["id"],
                "expected": expected,
                "text": row["text"],
            }
        )

    act_dict["eval"] = []
    for item in eval_ids:
        print(f"  eval {item['id']}")
        act = get_last_token_activation(
            model, tokenizer, item["text"], LAYER_IDX, MAX_INPUT_TOKENS
        )
        act_dict["eval"].append(act)

    # Stack everything
    result: dict[str, torch.Tensor] = {}
    for key, acts in act_dict.items():
        result[key] = torch.stack(acts, dim=0)

    # Store eval metadata separately
    result["_eval_meta"] = eval_ids  # type: ignore[assignment]

    return result


# ── Method Builders ─────────────────────────────────────────────────


def build_baseline(acts: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Method 1: baseline_neutral_contrast"""
    neutral_mean = acts["neutral"].mean(dim=0)
    return {
        "calm": l2_normalize(acts["calm"].mean(dim=0) - neutral_mean),
        "angry": l2_normalize(acts["angry"].mean(dim=0) - neutral_mean),
    }


def build_one_vs_rest(acts: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Method 2: one_vs_rest"""
    calm_acts = acts["calm"]
    angry_acts = acts["angry"]
    neutral_acts = acts["neutral"]

    others_calm = torch.cat([angry_acts, neutral_acts], dim=0)
    others_angry = torch.cat([calm_acts, neutral_acts], dim=0)

    return {
        "calm": l2_normalize(calm_acts.mean(dim=0) - others_calm.mean(dim=0)),
        "angry": l2_normalize(angry_acts.mean(dim=0) - others_angry.mean(dim=0)),
    }


def build_direct_contrast(acts: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Method 3: direct_contrast_axis — single angry_vs_calm axis + baseline for strength"""
    axis = l2_normalize(acts["angry"].mean(dim=0) - acts["calm"].mean(dim=0))

    # Also keep baseline for neutral strength detection
    neutral_mean = acts["neutral"].mean(dim=0)
    baseline_calm = l2_normalize(acts["calm"].mean(dim=0) - neutral_mean)
    baseline_angry = l2_normalize(acts["angry"].mean(dim=0) - neutral_mean)

    return {
        "angry_vs_calm_axis": axis,
        "_baseline_calm": baseline_calm,
        "_baseline_angry": baseline_angry,
    }


def build_orthogonalized(acts: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Method 4: orthogonalized_angry_only — remove calm component from angry"""
    neutral_mean = acts["neutral"].mean(dim=0)
    calm_vec = l2_normalize(acts["calm"].mean(dim=0) - neutral_mean)
    angry_raw = acts["angry"].mean(dim=0) - neutral_mean

    # Projection of angry onto calm
    proj = torch.dot(angry_raw.float(), calm_vec.float()) * calm_vec
    angry_orth = l2_normalize(angry_raw - proj)

    return {
        "calm": calm_vec,
        "angry": angry_orth,
    }


# ── Predictors ─────────────────────────────────────────────────────


def predict_bivector(
    activation: torch.Tensor,
    vectors: dict[str, torch.Tensor],
    min_top_score: float,
    neutral_margin: float,
) -> str:
    """Standard predict_label for two-vector methods."""
    scores = {
        "calm": cosine_sim(activation, vectors["calm"]),
        "angry": cosine_sim(activation, vectors["angry"]),
    }
    return predict_label(scores, min_top_score=min_top_score, neutral_margin=neutral_margin)


def predict_axis(
    activation: torch.Tensor,
    vectors: dict[str, torch.Tensor],
    axis_abs_threshold: float,
) -> str:
    """Prediction for direct_contrast_axis method."""
    axis_score = cosine_sim(activation, vectors["angry_vs_calm_axis"])

    # Strength check using baseline vectors for neutral detection
    strength_calm = cosine_sim(activation, vectors["_baseline_calm"])
    strength_angry = cosine_sim(activation, vectors["_baseline_angry"])
    max_strength = max(strength_calm, strength_angry)

    if max_strength < 0.05:
        return "neutral-ish"

    if abs(axis_score) < axis_abs_threshold:
        return "neutral-ish"

    return "angry" if axis_score > 0 else "calm"


# ── Scoring ────────────────────────────────────────────────────────


def score_eval_bivector(
    eval_acts: torch.Tensor,
    vectors: dict[str, torch.Tensor],
    eval_meta: list[dict],
) -> pd.DataFrame:
    """Score eval set with two-vector method. Returns DataFrame with per-sample scores."""
    rows = []
    for i, act in enumerate(eval_acts):
        calm_s = cosine_sim(act, vectors["calm"])
        angry_s = cosine_sim(act, vectors["angry"])
        top_score = max(calm_s, angry_s)
        second = min(calm_s, angry_s)
        rows.append(
            {
                **eval_meta[i],
                "calm_score": calm_s,
                "angry_score": angry_s,
                "top_score": top_score,
                "margin": top_score - second,
            }
        )
    return pd.DataFrame(rows)


def score_eval_axis(
    eval_acts: torch.Tensor,
    vectors: dict[str, torch.Tensor],
    eval_meta: list[dict],
) -> pd.DataFrame:
    """Score eval set with direct_contrast_axis method."""
    rows = []
    for i, act in enumerate(eval_acts):
        axis_score = cosine_sim(act, vectors["angry_vs_calm_axis"])
        strength_calm = cosine_sim(act, vectors["_baseline_calm"])
        strength_angry = cosine_sim(act, vectors["_baseline_angry"])
        rows.append(
            {
                **eval_meta[i],
                "axis_score": axis_score,
                "strength_calm": strength_calm,
                "strength_angry": strength_angry,
                "max_strength": max(strength_calm, strength_angry),
            }
        )
    return pd.DataFrame(rows)


# ── Metrics ────────────────────────────────────────────────────────


def compute_metrics_bivector(
    df: pd.DataFrame, vectors: dict[str, torch.Tensor], min_top_score: float, neutral_margin: float
) -> dict:
    """Compute metrics for two-vector method at given thresholds."""
    preds = []
    for _, row in df.iterrows():
        scores = {"calm": row["calm_score"], "angry": row["angry_score"]}
        preds.append(predict_label(scores, min_top_score=min_top_score, neutral_margin=neutral_margin))

    df_copy = df.copy()
    df_copy["predicted"] = preds

    total = len(df_copy)
    correct = int((df_copy["predicted"] == df_copy["expected"]).sum())

    per_class = {}
    for cls_name in ["calm", "angry", "neutral-ish"]:
        sub = df_copy[df_copy["expected"] == cls_name]
        if not sub.empty:
            c = int((sub["predicted"] == sub["expected"]).sum())
            per_class[f"{cls_name}_accuracy"] = round(c / len(sub), 4)
        else:
            per_class[f"{cls_name}_accuracy"] = 0.0

    # Argmax calm/angry
    binary = df_copy[df_copy["expected"].isin(["calm", "angry"])]
    if not binary.empty:
        binary_preds = binary.apply(
            lambda r: "calm" if r["calm_score"] >= r["angry_score"] else "angry", axis=1
        )
        argmax_correct = int((binary_preds == binary["expected"]).sum())
        argmax_acc = round(argmax_correct / len(binary), 4)
    else:
        argmax_acc = 0.0

    vec_cos = cosine_sim(vectors["calm"], vectors["angry"])

    return {
        "overall_accuracy": round(correct / total, 4) if total else 0.0,
        **per_class,
        "argmax_calm_angry_accuracy": argmax_acc,
        "vector_cosine": round(vec_cos, 4),
        "average_margin": round(float(df["margin"].mean()), 4),
        "average_top_score": round(float(df["top_score"].mean()), 4),
        "correct": correct,
        "total": total,
    }


def _predict_axis_from_scores(
    axis_score: float, strength_calm: float, strength_angry: float, axis_abs_threshold: float
) -> str:
    """Prediction for direct_contrast_axis using pre-computed scores."""
    max_strength = max(strength_calm, strength_angry)
    if max_strength < 0.05:
        return "neutral-ish"
    if abs(axis_score) < axis_abs_threshold:
        return "neutral-ish"
    return "angry" if axis_score > 0 else "calm"


def compute_metrics_axis(
    df: pd.DataFrame, vectors: dict[str, torch.Tensor], axis_abs_threshold: float
) -> dict:
    """Compute metrics for axis method at given threshold."""
    df_copy = df.copy()
    preds = df_copy.apply(
        lambda r: _predict_axis_from_scores(
            r["axis_score"], r["strength_calm"], r["strength_angry"], axis_abs_threshold
        ),
        axis=1,
    )
    df_copy["predicted"] = preds

    total = len(df_copy)
    correct = int((df_copy["predicted"] == df_copy["expected"]).sum())

    per_class = {}
    for cls_name in ["calm", "angry", "neutral-ish"]:
        sub = df_copy[df_copy["expected"] == cls_name]
        if not sub.empty:
            c = int((sub["predicted"] == sub["expected"]).sum())
            per_class[f"{cls_name}_accuracy"] = round(c / len(sub), 4)
        else:
            per_class[f"{cls_name}_accuracy"] = 0.0

    # Argmax calm/angry using axis sign
    binary = df_copy[df_copy["expected"].isin(["calm", "angry"])]
    if not binary.empty:
        binary_preds = binary.apply(
            lambda r: "angry" if r["axis_score"] > 0 else "calm", axis=1
        )
        argmax_correct = int((binary_preds == binary["expected"]).sum())
        argmax_acc = round(argmax_correct / len(binary), 4)
    else:
        argmax_acc = 0.0

    return {
        "overall_accuracy": round(correct / total, 4) if total else 0.0,
        **per_class,
        "argmax_calm_angry_accuracy": argmax_acc,
        "vector_cosine": 0.0,  # single axis, no pair
        "average_margin": round(float(df_copy["axis_score"].abs().mean()), 4),
        "average_top_score": round(float(df_copy["max_strength"].mean()), 4),
        "correct": correct,
        "total": total,
    }


# ── Threshold Sweep ────────────────────────────────────────────────


def sweep_bivector(
    df: pd.DataFrame, vectors: dict[str, torch.Tensor]
) -> pd.DataFrame:
    """Sweep thresholds for two-vector methods."""
    min_top_values = [-0.10, -0.05, 0.00, 0.03, 0.05, 0.08, 0.10]
    margin_values = [0.00, 0.01, 0.02, 0.03, 0.05, 0.08]

    results = []
    for mts in min_top_values:
        for nm in margin_values:
            m = compute_metrics_bivector(df, vectors, mts, nm)
            m["min_top_score"] = mts
            m["neutral_margin"] = nm
            results.append(m)

    return pd.DataFrame(results).sort_values("overall_accuracy", ascending=False)


def sweep_axis(
    df: pd.DataFrame, vectors: dict[str, torch.Tensor]
) -> pd.DataFrame:
    """Sweep axis_abs_threshold for direct_contrast_axis method."""
    axis_values = [0.00, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10]

    results = []
    for at in axis_values:
        m = compute_metrics_axis(df, vectors, at)
        m["axis_abs_threshold"] = at
        results.append(m)

    return pd.DataFrame(results).sort_values("overall_accuracy", ascending=False)


# ── Confusion Matrix ───────────────────────────────────────────────


def confusion_matrix_text(df: pd.DataFrame) -> str:
    """Text representation of confusion matrix."""
    labels = sorted(set(list(df["expected"].unique()) + list(df["predicted"].unique())))
    lines = ["| actual \\ predicted | " + " | ".join(labels) + " |"]
    lines.append("|---" * (len(labels) + 1) + "|")
    for actual in labels:
        row = df[df["expected"] == actual]
        cells = [str(int((row["predicted"] == pred).sum())) for pred in labels]
        lines.append(f"| {actual} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ── Report Generator ───────────────────────────────────────────────


def generate_report(
    summary_rows: list[dict],
    all_scores: dict[str, pd.DataFrame],
    all_sweeps: dict[str, pd.DataFrame],
    all_vectors: dict[str, dict],
) -> str:
    """Generate comparison Markdown report."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Phase 1.7 Vector Method Comparison Report",
        "",
        f"*Generated: {now}*",
        "",
        "## 1. Objective",
        "",
        "Compare 4 alternative vector construction methods against the baseline "
        "to find one that significantly improves calm-vs-angry discrimination, "
        "reduces vector collinearity, and maintains neutral-ish detection.",
        "",
        "The baseline (`mean(emotion) - mean(neutral)`) was diagnosed in Phase 1.6 "
        "as producing highly collinear vectors (cosine=0.81) with angry accuracy at chance level (0.500).",
        "",
        "## 2. Background",
        "",
        "- **Model**: Qwen2.5-1.5B-Instruct, layer 16, last-token activation",
        "- **Train set**: 10 calm / 10 angry / 20 neutral (`emotion_seed_prompts.jsonl`)",
        "- **Eval set**: 10 calm / 10 angry / 10 neutral-ish (`emotion_eval_prompts.jsonl`)",
        "- **Scoring**: cosine similarity between activation and emotion vector",
        "",
        "## 3. Compared Methods",
        "",
        "### 3.1 Baseline Neutral Contrast",
        "",
        "```",
        "calm = L2(mean(calm_acts) - mean(neutral_acts))",
        "angry = L2(mean(angry_acts) - mean(neutral_acts))",
        "```",
        "",
        "Both vectors depart from the same neutral baseline, causing high collinearity.",
        "",
        "### 3.2 One-vs-Rest",
        "",
        "```",
        "calm = L2(mean(calm_acts) - mean(angry_acts ∪ neutral_acts))",
        "angry = L2(mean(angry_acts) - mean(calm_acts ∪ neutral_acts))",
        "```",
        "",
        "Each vector explicitly contrasts against all other classes.",
        "",
        "### 3.3 Direct Contrast Axis",
        "",
        "```",
        "angry_vs_calm_axis = L2(mean(angry_acts) - mean(calm_acts))",
        "prediction = sign(cosine(text, axis)) → angry/calm",
        "neutral-ish  = |cosine| < axis_abs_threshold",
        "```",
        "",
        "Single axis directly encodes the calm↔angry distinction.",
        "",
        "### 3.4 Orthogonalized Angry Vector",
        "",
        "```",
        "calm = baseline calm (unchanged)",
        "angry_raw = mean(angry_acts) - mean(neutral_acts)",
        "angry = L2(angry_raw - projection(angry_raw, calm))",
        "```",
        "",
        "Removes the calm-component from the angry vector to reduce collinearity.",
        "",
        "## 4. Evaluation Setup",
        "",
        "- Threshold sweep performed for each method",
        "- Best thresholds selected by overall accuracy",
        "- All metrics reported at best thresholds",
        "",
        "## 5. Results Summary",
        "",
        "| Method | Overall Acc | Calm Acc | Angry Acc | Neutral Acc | Argmax Acc | Vec Cosine |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in summary_rows:
        name = row["method"]
        lines.append(
            f"| {name} "
            f"| {row.get('overall_accuracy', 0):.3f} "
            f"| {row.get('calm_accuracy', 0):.3f} "
            f"| {row.get('angry_accuracy', 0):.3f} "
            f"| {row.get('neutral-ish_accuracy', 0):.3f} "
            f"| {row.get('argmax_calm_angry_accuracy', 0):.3f} "
            f"| {row.get('vector_cosine', 0):.3f} |"
        )

    lines += [
        "",
        "## 6. Confusion Matrix by Method",
        "",
    ]

    for row in summary_rows:
        name = row["method"]
        lines.append(f"### {name}")
        lines.append("")
        if name in all_scores:
            df = all_scores[name]
            best_row = row
            if name == "direct_contrast_axis":
                df_copy = df.copy()
                at = best_row.get("axis_abs_threshold", 0.03)
                preds = df_copy.apply(
                    lambda r: _predict_axis_from_scores(
                        r["axis_score"], r["strength_calm"], r["strength_angry"], at
                    ),
                    axis=1,
                )
                df_copy["predicted"] = preds
                lines.append(confusion_matrix_text(df_copy))
            else:
                mts = best_row.get("min_top_score", 0.05)
                nm = best_row.get("neutral_margin", 0.03)
                df_copy = df.copy()
                preds = []
                for _, r in df_copy.iterrows():
                    scores = {"calm": r["calm_score"], "angry": r["angry_score"]}
                    preds.append(predict_label(scores, min_top_score=mts, neutral_margin=nm))
                df_copy["predicted"] = preds
                lines.append(confusion_matrix_text(df_copy))
        lines.append("")

    lines += [
        "## 7. Key Findings",
        "",
    ]

    # Find best
    best = max(summary_rows, key=lambda r: r.get("angry_accuracy", 0))
    best_overall = max(summary_rows, key=lambda r: r.get("overall_accuracy", 0))

    baseline_row = [r for r in summary_rows if r["method"] == "baseline_neutral_contrast"]
    baseline_angry = baseline_row[0]["angry_accuracy"] if baseline_row else 0.0

    angry_improvements = [
        r for r in summary_rows
        if r.get("angry_accuracy", 0) > baseline_angry
    ]

    lines.append("### 7.1 Angry Accuracy Improvement")
    lines.append("")
    if angry_improvements:
        for r in angry_improvements:
            delta = r.get("angry_accuracy", 0) - baseline_angry
            lines.append(
                f"- **{r['method']}**: angry_acc = {r.get('angry_accuracy', 0):.3f} "
                f"(Δ = {delta:+.3f} vs. baseline {baseline_angry:.3f})"
            )
    else:
        lines.append(
            "No method significantly improved angry accuracy over baseline. "
            "This suggests the fundamental limitation may be in the model's "
            "activation space (Qwen2.5-1.5B, single layer, last token), "
            "not just the vector construction formula."
        )

    lines += [
        "",
        "### 7.2 Vector Collinearity Reduction",
        "",
    ]
    for r in summary_rows:
        if r["method"] != "direct_contrast_axis":
            lines.append(
                f"- **{r['method']}**: cosine = {r.get('vector_cosine', 0):.4f} "
                f"(baseline = 0.8096)"
            )

    lines += [
        "",
        "### 7.3 Neutral-ish Accuracy Trade-off",
        "",
    ]
    for r in summary_rows:
        lines.append(
            f"- **{r['method']}**: neutral_acc = {r.get('neutral-ish_accuracy', 0):.3f}"
        )

    lines += [
        "",
        "## 8. Recommended Method for Next Phase",
        "",
    ]

    # Recommendation logic
    if angry_improvements:
        best_angry = max(angry_improvements, key=lambda r: r.get("angry_accuracy", 0))
        lines.append(
            f"**Recommended: `{best_angry['method']}`** "
            f"(angry_acc = {best_angry.get('angry_accuracy', 0):.3f}, "
            f"overall_acc = {best_angry.get('overall_accuracy', 0):.3f})"
        )
    else:
        lines.append(
            "No single method stands out as clearly superior. "
            "Consider combining approaches (e.g., one-vs-rest + orthogonalization) "
            "or addressing data/model limitations first."
        )

    lines += [
        "",
        "## 9. Limitations",
        "",
        "- Only 10 samples per emotion class — difference-of-means is high-variance.",
        "- Qwen2.5-1.5B is a small model; emotion concept separation may be inherently weak.",
        "- Single layer (16), single position (last token) — may miss useful signals.",
        "- Eval set is only 30 samples — threshold tuning on this set risks overfitting.",
        "- The project does **not** claim models have subjective emotions.",
        "",
        "## 10. Next Step",
        "",
    ]

    if angry_improvements and best_angry.get("angry_accuracy", 0) >= 0.6:
        lines.append(
            "Angry accuracy has improved to a usable level. "
            "**Recommended: proceed to Phase 2 activation steering** — "
            "test whether the improved vectors produce meaningful behavior "
            "changes when injected during generation."
        )
    else:
        lines.append(
            "Angry accuracy remains below reliable levels across all methods. "
            "**Recommended options before Phase 2:**",
            "",
            "1. **Increase training data**: Expand each class from 10 to 30-50 samples.",
            "2. **Multi-layer scan**: Compare vector quality at layers 8/14/20/26.",
            "3. **Multi-token pooling**: Use mean of last 3-5 valid tokens.",
            "4. **Accept current limitation**: Proceed to steering with calm vector only "
            "(which works well) and treat angry as a known limitation.",
        )

    return "\n".join(lines) + "\n"


# ── Main ───────────────────────────────────────────────────────────


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    # ── Load data ─────────────────────────────────────────────────
    print(f"[05_compare] Loading train data: {TRAIN_DATA_PATH}")
    train_rows = load_jsonl(TRAIN_DATA_PATH)
    grouped = group_texts_by_label(train_rows)
    for label, texts in grouped.items():
        print(f"  train {label}: {len(texts)} samples")

    print(f"[05_compare] Loading eval data: {EVAL_DATA_PATH}")
    eval_rows = load_jsonl(EVAL_DATA_PATH)
    print(f"  eval samples: {len(eval_rows)}")

    # ── Load model ────────────────────────────────────────────────
    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    # ── Extract activations once ──────────────────────────────────
    acts = extract_all_activations(model, tokenizer, grouped, eval_rows)
    eval_acts = acts["eval"]  # [30, hidden_size]
    eval_meta = acts["_eval_meta"]  # list of dicts

    # ── Build vectors for all 4 methods ───────────────────────────
    print("\n[05_compare] Building vectors...")

    methods: dict[str, dict] = {}

    print("  Method 1: baseline_neutral_contrast")
    methods["baseline_neutral_contrast"] = build_baseline(acts)

    print("  Method 2: one_vs_rest")
    methods["one_vs_rest"] = build_one_vs_rest(acts)

    print("  Method 3: direct_contrast_axis")
    methods["direct_contrast_axis"] = build_direct_contrast(acts)

    print("  Method 4: orthogonalized_angry_only")
    methods["orthogonalized_angry_only"] = build_orthogonalized(acts)

    # ── Score eval with each method ───────────────────────────────
    print("\n[05_compare] Scoring eval set with each method...")

    all_scores: dict[str, pd.DataFrame] = {}
    all_best_metrics: list[dict] = []
    all_sweeps: dict[str, pd.DataFrame] = {}

    for method_name, vectors in methods.items():
        print(f"\n{'='*60}")
        print(f"Method: {method_name}")
        print(f"{'='*60}")

        if method_name == "direct_contrast_axis":
            # Score with axis method
            df = score_eval_axis(eval_acts, vectors, eval_meta)
            all_scores[method_name] = df

            # Sweep
            sweep = sweep_axis(df, vectors)
            all_sweeps[method_name] = sweep
            best = sweep.iloc[0].to_dict()

            print(f"  Best overall accuracy: {best['overall_accuracy']:.3f}")
            print(f"  calm_acc: {best.get('calm_accuracy', 0):.3f}")
            print(f"  angry_acc: {best.get('angry_accuracy', 0):.3f}")
            print(f"  neutral_acc: {best.get('neutral-ish_accuracy', 0):.3f}")
            print(f"  argmax_calm_angry_acc: {best.get('argmax_calm_angry_accuracy', 0):.3f}")
            print(f"  best axis_abs_threshold: {best.get('axis_abs_threshold', 0):.3f}")

            best["method"] = method_name
            all_best_metrics.append(best)

        else:
            # Score with bivector method
            df = score_eval_bivector(eval_acts, vectors, eval_meta)
            all_scores[method_name] = df

            # Sweep
            sweep = sweep_bivector(df, vectors)
            all_sweeps[method_name] = sweep
            best = sweep.iloc[0].to_dict()

            vec_cos = cosine_sim(vectors["calm"], vectors["angry"])
            print(f"  vector_cosine: {vec_cos:.4f}")
            print(f"  Best overall accuracy: {best['overall_accuracy']:.3f}")
            print(f"  calm_acc: {best.get('calm_accuracy', 0):.3f}")
            print(f"  angry_acc: {best.get('angry_accuracy', 0):.3f}")
            print(f"  neutral_acc: {best.get('neutral-ish_accuracy', 0):.3f}")
            print(f"  argmax_calm_angry_acc: {best.get('argmax_calm_angry_accuracy', 0):.3f}")
            print(f"  best_params: min_top_score={best.get('min_top_score', 0):.2f}, "
                  f"neutral_margin={best.get('neutral_margin', 0):.2f}")

            best["method"] = method_name
            best["vector_cosine"] = round(vec_cos, 4)
            all_best_metrics.append(best)

    # ── Save alternative vectors ──────────────────────────────────
    print(f"\n[05_compare] Saving alternative vectors to: {ALT_VECTORS_PATH}")
    ALT_VECTORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"methods": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                            for k, v in methods.items()},
                "model_name": MODEL_NAME,
                "layer": LAYER_IDX},
               ALT_VECTORS_PATH)

    # ── Save scores ───────────────────────────────────────────────
    all_scores_combined = []
    for method_name, df in all_scores.items():
        df_copy = df.copy()
        df_copy["method"] = method_name
        all_scores_combined.append(df_copy)
    combined_df = pd.concat(all_scores_combined, ignore_index=True)
    write_csv(COMP_SCORES_PATH, combined_df)
    print(f"Saved scores: {COMP_SCORES_PATH}")

    # ── Save summary ──────────────────────────────────────────────
    summary_df = pd.DataFrame(all_best_metrics)
    write_csv(COMP_SUMMARY_PATH, summary_df)
    print(f"Saved summary: {COMP_SUMMARY_PATH}")

    # ── Generate report ───────────────────────────────────────────
    report_md = generate_report(all_best_metrics, all_scores, all_sweeps, methods)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_md, encoding="utf-8")
    print(f"Saved report: {REPORT_PATH}")

    # ── Final summary ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("Phase 1.7 Vector Method Comparison — Final Summary")
    print("=" * 80)

    for row in sorted(all_best_metrics, key=lambda r: r.get("angry_accuracy", 0), reverse=True):
        print(f"\n{row['method']}:")
        print(f"  overall_acc: {row.get('overall_accuracy', 0):.3f}")
        print(f"  calm_acc:    {row.get('calm_accuracy', 0):.3f}")
        print(f"  angry_acc:   {row.get('angry_accuracy', 0):.3f}")
        print(f"  neutral_acc: {row.get('neutral-ish_accuracy', 0):.3f}")
        print(f"  argmax_acc:  {row.get('argmax_calm_angry_accuracy', 0):.3f}")
        if "vector_cosine" in row:
            print(f"  vec_cosine:  {row.get('vector_cosine', 0):.4f}")

    # Find best
    best_angry = max(all_best_metrics, key=lambda r: r.get("angry_accuracy", 0))
    print(f"\nBest angry accuracy: {best_angry['method']} "
          f"({best_angry.get('angry_accuracy', 0):.3f})")

    best_overall = max(all_best_metrics, key=lambda r: r.get("overall_accuracy", 0))
    print(f"Best overall accuracy: {best_overall['method']} "
          f"({best_overall.get('overall_accuracy', 0):.3f})")

    print(f"\nSaved summary: {COMP_SUMMARY_PATH}")
    print(f"Saved report: {REPORT_PATH}")
    print("[05_compare] Done.")


if __name__ == "__main__":
    main()
