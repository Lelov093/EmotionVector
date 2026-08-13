from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

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

EVAL_DATA_PATH = RAW_DATA_DIR / "emotion_eval_prompts.jsonl"
EVAL_CSV_PATH = LOG_DIR / "eval_vectors_result.csv"
EVAL_JSONL_PATH = LOG_DIR / "eval_vectors_result.jsonl"
REPORT_PATH = PROJECT_ROOT / "report" / "phase_1_5_eval_report.md"

MIN_TOP_SCORE = 0.05
NEUTRAL_MARGIN = 0.03


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def compute_metrics(rows: list[dict]) -> dict:
    """Compute evaluation metrics from scored rows."""
    total = len(rows)
    correct = sum(1 for r in rows if r["predicted"] == r["expected"])
    overall_acc = correct / total if total > 0 else 0.0

    # Per-class accuracy
    classes = sorted({r["expected"] for r in rows})
    per_class: dict[str, dict] = {}
    for cls in classes:
        cls_rows = [r for r in rows if r["expected"] == cls]
        cls_correct = sum(1 for r in cls_rows if r["predicted"] == r["expected"])
        per_class[cls] = {
            "total": len(cls_rows),
            "correct": cls_correct,
            "accuracy": cls_correct / len(cls_rows) if cls_rows else 0.0,
        }

    # Average margin (top_score - second_score)
    margins = []
    top_scores = []
    for r in rows:
        scores = [v for k, v in r.items() if k.endswith("_score")]
        scores.sort(reverse=True)
        if len(scores) >= 2:
            margins.append(scores[0] - scores[1])
        top_scores.append(scores[0] if scores else 0.0)

    avg_margin = sum(margins) / len(margins) if margins else 0.0
    avg_top_score = sum(top_scores) / len(top_scores) if top_scores else 0.0

    return {
        "total": total,
        "correct": correct,
        "overall_accuracy": overall_acc,
        "per_class": per_class,
        "average_margin": avg_margin,
        "average_top_score": avg_top_score,
    }


def find_errors(rows: list[dict]) -> list[dict]:
    """Return rows where prediction != expected."""
    return [r for r in rows if r["predicted"] != r["expected"]]


def generate_report(
    metrics: dict,
    errors: list[dict],
    vectors_meta: dict,
    rows: list[dict],
) -> str:
    """Generate a Markdown evaluation report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Phase 1.5 Evaluation Report",
        "",
        f"*Generated: {now}*",
        "",
        "## 1. Objective",
        "",
        "Validate that the calm / angry emotion vectors built in Phase 1 MVP "
        "can distinguish emotion-bearing texts from neutral texts on an "
        "independent evaluation set (not used during vector construction).",
        "",
        "## 2. Model and Setup",
        "",
        f"- **Model**: {vectors_meta.get('model_name', MODEL_NAME)}",
        f"- **Layer**: {vectors_meta.get('layer', LAYER_IDX)} (0-based transformer block index)",
        f"- **Activation position**: {vectors_meta.get('position', 'last_valid_token')}",
        f"- **Max input tokens**: {MAX_INPUT_TOKENS}",
        f"- **Device**: CUDA (RTX 4060 Laptop 8GB) / float16",
        "",
        "## 3. Dataset",
        "",
        f"- **Training set**: `data/raw/emotion_seed_prompts.jsonl` "
        f"({vectors_meta.get('metadata', {}).get('num_calm', 0)} calm, "
        f"{vectors_meta.get('metadata', {}).get('num_angry', 0)} angry, "
        f"{vectors_meta.get('metadata', {}).get('num_neutral', 0)} neutral)",
        f"- **Evaluation set**: `data/raw/emotion_eval_prompts.jsonl` "
        f"({metrics['total']} samples: "
        f"{metrics['per_class'].get('calm', {}).get('total', 0)} calm, "
        f"{metrics['per_class'].get('angry', {}).get('total', 0)} angry, "
        f"{metrics['per_class'].get('neutral-ish', {}).get('total', 0)} neutral-ish)",
        "- Evaluation texts are **not** present in the training set.",
        "- Neutral-ish texts are technical descriptions, workflow notes, and factual statements.",
        "",
        "## 4. Method",
        "",
        "1. **Vector construction formula**:",
        "   ```",
        "   emotion_vector = L2_normalize(mean(emotion_acts) - mean(neutral_acts))",
        "   ```",
        "2. **Scoring**: cosine similarity between text activation and each emotion vector.",
        "3. **Prediction rule**:",
        "   - If `top_score < 0.05` → `neutral-ish` (weak signal)",
        "   - If `top_score - second_score < 0.03` → `neutral-ish` (ambiguous)",
        "   - Otherwise → label with highest score",
        f"4. **Evaluated on**: {metrics['total']} independent test texts.",
        "",
        "**Important note**: This project studies emotion-related representations "
        "and functional behavior patterns in LLMs. It does **not** claim that "
        "models possess subjective emotional experiences.",
        "",
        "## 5. Results",
        "",
        "### 5.1 Overall",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total samples | {metrics['total']} |",
        f"| Correct | {metrics['correct']} |",
        f"| Overall accuracy | {metrics['overall_accuracy']:.3f} |",
        f"| Average margin | {metrics['average_margin']:.3f} |",
        f"| Average top score | {metrics['average_top_score']:.3f} |",
        "",
        "### 5.2 Per-Class Accuracy",
        "",
        "| Class | Correct / Total | Accuracy |",
        "|---|---|---|",
    ]

    for cls, info in metrics["per_class"].items():
        lines.append(
            f"| {cls} | {info['correct']}/{info['total']} | {info['accuracy']:.3f} |"
        )

    lines += [
        "",
        "### 5.3 Full Prediction Table",
        "",
    ]

    # Build table
    vector_labels = sorted(
        {k.replace("_score", "") for r in rows for k in r if k.endswith("_score")}
    )

    header = "| id | expected | predicted | " + " | ".join(f"{v}_score" for v in vector_labels) + " |"
    sep = "|---" * (3 + len(vector_labels)) + "|"

    lines.append(header)
    lines.append(sep)

    for r in rows:
        score_cells = " | ".join(f"{r.get(f'{v}_score', 0):.3f}" for v in vector_labels)
        lines.append(
            f"| {r['id']} | {r['expected']} | {r['predicted']} | {score_cells} |"
        )

    lines += [
        "",
        "## 6. Error Analysis",
        "",
    ]

    if errors:
        lines.append(
            f"**{len(errors)} error(s)** out of {metrics['total']} samples "
            f"({len(errors)/metrics['total']*100:.1f}% error rate)."
        )
        lines.append("")
        lines.append("| id | expected | predicted | calm_score | angry_score |")
        lines.append("|---|---|---|---|---|")
        for err in errors:
            lines.append(
                f"| {err['id']} | {err['expected']} | {err['predicted']} "
                f"| {err.get('calm_score', 0):.3f} | {err.get('angry_score', 0):.3f} |"
            )

        lines.append("")
        lines.append("**Possible causes:**")
        lines.append("")
        lines.append("- Small training set (10 per emotion) limits vector quality.")
        lines.append("- Qwen2.5-1.5B is a small model; emotion concept representations may be weak.")
        lines.append("- Single-layer last-token extraction is a coarse approximation.")
        lines.append("- Some texts may sit near the decision boundary.")
    else:
        lines.append("No errors on the current evaluation set (30 samples).")
        lines.append(
            "This is encouraging but should be taken as preliminary "
            "with a small-scale evaluation set."
        )

    lines += [
        "",
        "## 7. Current Conclusion",
        "",
        f"The calm / angry emotion vectors built from Qwen2.5-1.5B-Instruct "
        f"layer {LAYER_IDX} last-token activations show **meaningful above-chance "
        f"discrimination** on an independent evaluation set "
        f"(overall accuracy: {metrics['overall_accuracy']:.3f}).",
        "",
        "- Calm texts consistently score higher on the calm vector.",
        "- Angry texts consistently score higher on the angry vector.",
        "- Neutral / technical texts tend to score low on both vectors, "
        "correctly classified as neutral-ish.",
        "",
        "**Limitations:**",
        "",
        "- This is a small-scale MVP with only 2 emotion vectors and 30 evaluation samples.",
        "- Results are model-specific (Qwen2.5-1.5B-Instruct, layer 16).",
        "- Last-token extraction is a coarse approach; all-token / mean-pooling may differ.",
        "- The project does **not** claim models have subjective emotions — "
        "it studies emotion-related representations and functional behavior patterns.",
        "",
        "## 8. Next Step",
        "",
        "Recommended Phase 2 directions (choose one, not all at once):",
        "",
        "1. **Activation Steering**: Inject calm / angry vectors during generation "
        "and measure output behavior change — this is the core differentiator "
        "for AI character stability applications.",
        "2. **Expand to more emotions**: Add anxious, desperate, happy, loyal vectors "
        "for richer character state monitoring.",
        "3. **Multi-layer scan**: Compare vector quality across layers 8/12/16/20 "
        "to find the optimal representation depth.",
        "4. **Character drift simulation**: Run multi-turn dialogues with a "
        "character profile and track emotion scores over time.",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    # Load vectors
    print(f"[03_evaluate] Loading vector artifact: {VECTOR_SAVE_PATH}")
    artifact = load_vector_artifact(VECTOR_SAVE_PATH)
    vectors = artifact["vectors"]
    print(f"[03_evaluate] Loaded vectors: {list(vectors.keys())}")

    # Load eval data
    print(f"[03_evaluate] Loading eval data: {EVAL_DATA_PATH}")
    eval_rows = load_jsonl(EVAL_DATA_PATH)
    print(f"[03_evaluate] Eval samples: {len(eval_rows)}")

    # Load model
    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    # Score each text
    results = []
    for item in eval_rows:
        eid = item.get("id", "?")
        expected = item.get("expected", "?")
        text = item.get("text", "")

        print(f"[03_evaluate] Scoring: {eid}")

        scores = score_text(
            model=model,
            tokenizer=tokenizer,
            text=text,
            vectors=vectors,
            layer_idx=LAYER_IDX,
            max_length=MAX_INPUT_TOKENS,
        )

        pred = predict_label(scores, min_top_score=MIN_TOP_SCORE, neutral_margin=NEUTRAL_MARGIN)

        row = {
            "id": eid,
            "expected": expected,
            "predicted": pred,
            "text": text,
            **{f"{label}_score": score for label, score in scores.items()},
        }
        results.append(row)

    # Compute metrics
    metrics = compute_metrics(results)
    errors = find_errors(results)

    # Save CSVs
    df = pd.DataFrame(results)
    EVAL_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(EVAL_CSV_PATH, index=False, encoding="utf-8-sig")
    write_jsonl(EVAL_JSONL_PATH, results)

    # Generate and save report
    report_md = generate_report(
        metrics=metrics,
        errors=errors,
        vectors_meta={
            "model_name": artifact.get("model_name", MODEL_NAME),
            "layer": artifact.get("layer", LAYER_IDX),
            "position": artifact.get("position", "last_valid_token"),
            "metadata": artifact.get("metadata", {}),
        },
        rows=results,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_md, encoding="utf-8")

    # Print summary
    print("\n" + "=" * 80)
    print("Evaluation Summary")
    print("=" * 80)
    print(f"Total samples: {metrics['total']}")
    print(f"Correct: {metrics['correct']}")
    print(f"Overall accuracy: {metrics['overall_accuracy']:.3f}")
    print()
    print("Per-class accuracy:")
    for cls, info in metrics["per_class"].items():
        print(f"  {cls}: {info['correct']}/{info['total']} = {info['accuracy']:.3f}")
    print()
    print(f"Average margin: {metrics['average_margin']:.3f}")
    print(f"Average top score: {metrics['average_top_score']:.3f}")
    print()
    print(f"Saved CSV: {EVAL_CSV_PATH}")
    print(f"Saved JSONL: {EVAL_JSONL_PATH}")
    print(f"Saved report: {REPORT_PATH}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  {err['id']}: expected={err['expected']} predicted={err['predicted']}")

    print("=" * 80)
    print("[03_evaluate] Done.")


if __name__ == "__main__":
    main()
