from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import (  # noqa: E402
    EMOTION_DATA_PATH,
    LAYER_IDX,
    MAX_INPUT_TOKENS,
    MODEL_NAME,
    VECTOR_SAVE_PATH,
    ensure_project_dirs,
    print_environment_summary,
)
from backend.core.model_loader import load_model_and_tokenizer  # noqa: E402
from backend.core.vector_builder import (  # noqa: E402
    build_emotion_vectors,
    group_texts_by_label,
    load_jsonl,
    save_vector_artifact,
)


def main() -> None:
    ensure_project_dirs()
    print_environment_summary()

    print("[01_build_vectors] Reading design document if available...")
    docs_path = PROJECT_ROOT / "docs" / "emotion_vector_项目设计文档.md"
    if docs_path.exists():
        print(f"[01_build_vectors] Design document found: {docs_path}")
    else:
        print(f"[01_build_vectors] WARNING: Design document not found: {docs_path}")

    print(f"[01_build_vectors] Loading dataset: {EMOTION_DATA_PATH}")
    rows = load_jsonl(EMOTION_DATA_PATH)
    grouped = group_texts_by_label(rows)

    for label, texts in grouped.items():
        print(f"[01_build_vectors] label={label}, count={len(texts)}")

    required = {"calm", "angry", "neutral"}
    missing = required - set(grouped.keys())
    if missing:
        raise ValueError(f"Missing required labels in dataset: {missing}")

    model, tokenizer = load_model_and_tokenizer(MODEL_NAME)

    vectors = build_emotion_vectors(
        model=model,
        tokenizer=tokenizer,
        grouped_texts=grouped,
        emotion_labels=["calm", "angry"],
        neutral_label="neutral",
        layer_idx=LAYER_IDX,
        max_length=MAX_INPUT_TOKENS,
    )

    metadata = {
        "method": "mean_emotion_activation_minus_mean_neutral_activation",
        "num_calm": len(grouped["calm"]),
        "num_angry": len(grouped["angry"]),
        "num_neutral": len(grouped["neutral"]),
        "max_input_tokens": MAX_INPUT_TOKENS,
        "hidden_state_index_note": (
            "layer is 0-based transformer block index; "
            "HF hidden_states index = layer + 1"
        ),
    }

    save_vector_artifact(
        save_path=VECTOR_SAVE_PATH,
        model_name=MODEL_NAME,
        layer_idx=LAYER_IDX,
        position="last_valid_token",
        vectors=vectors,
        metadata=metadata,
    )

    print("[01_build_vectors] Done.")
    print(f"[01_build_vectors] Vector artifact saved to: {VECTOR_SAVE_PATH}")


if __name__ == "__main__":
    main()
