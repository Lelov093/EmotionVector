from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import (  # noqa: E402
    LAYER_IDX,
    MAX_INPUT_TOKENS,
    MODEL_NAME,
    SCORE_RESULT_CSV_PATH,
    SCORE_RESULT_JSONL_PATH,
    VECTOR_SAVE_PATH,
    ensure_project_dirs,
    print_environment_summary,
)
from backend.core.emotion_scorer import predict_label, score_text  # noqa: E402
from backend.core.model_loader import load_model_and_tokenizer  # noqa: E402
from backend.core.vector_builder import load_vector_artifact  # noqa: E402


TEST_TEXTS = [
    {
        "id": "test_A_calm_001",
        "expected": "calm",
        "text": "他被质疑后没有立刻反驳，而是先确认问题发生在哪里。",
    },
    {
        "id": "test_A_calm_002",
        "expected": "calm",
        "text": "情况突然变得混乱，她仍然按顺序检查信息来源和可行方案。",
    },
    {
        "id": "test_B_angry_001",
        "expected": "angry",
        "text": "她听到对方连续嘲讽后，语气明显变得尖锐。",
    },
    {
        "id": "test_B_angry_002",
        "expected": "angry",
        "text": "他看着被随意否定的成果，回答开始变得强硬而短促。",
    },
    {
        "id": "test_C_neutral_001",
        "expected": "neutral-ish",
        "text": "这份文档记录了模型加载方式、缓存路径和实验参数。",
    },
    {
        "id": "test_C_neutral_002",
        "expected": "neutral-ish",
        "text": "脚本会读取 JSONL 数据，并将评分结果保存为 CSV 文件。",
    },
]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    print(f"[02_score_texts] Loading vector artifact: {VECTOR_SAVE_PATH}")
    artifact = load_vector_artifact(VECTOR_SAVE_PATH)

    artifact_model_name = artifact["model_name"]
    artifact_layer = artifact["layer"]
    vectors = artifact["vectors"]

    if artifact_model_name != MODEL_NAME:
        print(
            f"[02_score_texts] WARNING: artifact model {artifact_model_name} "
            f"!= config model {MODEL_NAME}"
        )

    if artifact_layer != LAYER_IDX:
        print(
            f"[02_score_texts] WARNING: artifact layer {artifact_layer} "
            f"!= config layer {LAYER_IDX}"
        )

    print(f"[02_score_texts] Loaded vectors: {list(vectors.keys())}")

    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    rows = []

    for item in TEST_TEXTS:
        print(f"[02_score_texts] Scoring: {item['id']}")

        scores = score_text(
            model=model,
            tokenizer=tokenizer,
            text=item["text"],
            vectors=vectors,
            layer_idx=LAYER_IDX,
            max_length=MAX_INPUT_TOKENS,
        )

        pred = predict_label(scores, min_top_score=0.05, neutral_margin=0.03)

        row = {
            "id": item["id"],
            "expected": item["expected"],
            "predicted": pred,
            "text": item["text"],
            **{f"{label}_score": score for label, score in scores.items()},
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    SCORE_RESULT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SCORE_RESULT_CSV_PATH, index=False, encoding="utf-8-sig")
    write_jsonl(SCORE_RESULT_JSONL_PATH, rows)

    print("\n" + "=" * 80)
    print("Score Results")
    print("=" * 80)

    display_cols = ["id", "expected", "predicted"]
    for label in vectors.keys():
        display_cols.append(f"{label}_score")

    print(df[display_cols].to_string(index=False))

    print("=" * 80)
    print(f"[02_score_texts] CSV saved to: {SCORE_RESULT_CSV_PATH}")
    print(f"[02_score_texts] JSONL saved to: {SCORE_RESULT_JSONL_PATH}")
    print("[02_score_texts] Done.")


if __name__ == "__main__":
    main()
