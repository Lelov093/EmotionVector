from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_extraction import (  # noqa: E402
    extract_candidate_matrices,
    load_quantized_model,
    load_train_dev_text_rows,
    write_activation_artifacts,
)


DEFAULT_REVIEW = Path(
    "results/local_artifacts/research_foundation/public_mapping_pilot_v0_2/"
    "pku_safe_rlhf_mapping_review_v0_2.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas v2 frozen train/dev activation extraction")
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--full-train-dev", action="store_true")
    parser.add_argument("--confirm-model-run", action="store_true")
    parser.add_argument("--confirm-full-train-dev", action="store_true")
    return parser.parse_args()


def gpu_memory_snapshot() -> dict:
    import torch

    if not torch.cuda.is_available():
        return {"cuda_available": False}
    free, total = torch.cuda.mem_get_info()
    return {
        "cuda_available": True,
        "device_name": torch.cuda.get_device_name(0),
        "free_mib": round(free / 1024**2, 1),
        "total_mib": round(total / 1024**2, 1),
        "allocated_mib": round(torch.cuda.memory_allocated() / 1024**2, 1),
        "reserved_mib": round(torch.cuda.memory_reserved() / 1024**2, 1),
        "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2, 1),
    }


def main() -> int:
    args = parse_args()
    review_path = args.review if args.review.is_absolute() else ROOT / args.review
    rows, manifest, runtime = load_train_dev_text_rows(ROOT, review_path)
    summary = {
        "status": "prepared",
        "model_id": runtime["model"]["model_id"],
        "revision": runtime["model"]["revision"],
        "splits": runtime["execution"]["allowed_splits"],
        "response_count": len(rows),
        "layers": runtime["candidate_specifications"]["layers"],
        "pooling": runtime["candidate_specifications"]["pooling"],
        "model_run": False,
        "test_opened": False,
    }
    if args.prepare_only:
        print(json.dumps(summary, indent=2))
        return 0
    if not args.confirm_model_run:
        raise SystemExit("refusing model execution without --confirm-model-run")
    if args.full_train_dev and not args.confirm_full_train_dev:
        raise SystemExit("refusing full train/dev extraction without --confirm-full-train-dev")
    import torch

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    gpu_before = gpu_memory_snapshot()
    model, tokenizer = load_quantized_model(runtime)
    selected_rows = rows[: runtime["artifact_policy"]["smoke_samples"]] if args.smoke else rows
    matrices = extract_candidate_matrices(
        model,
        tokenizer,
        selected_rows,
        layers=runtime["candidate_specifications"]["layers"],
        pooling_modes=runtime["candidate_specifications"]["pooling"],
        max_sequence_tokens=runtime["execution"]["max_sequence_tokens"],
    )
    if args.smoke:
        summary.update(
            {
                "status": "smoke_pass",
                "model_run": True,
                "smoke_response_count": len(selected_rows),
                "matrix_shapes": {f"{key[0]}::{key[1]}": list(value.shape) for key, value in matrices.items()},
                "canonical_artifacts_written": False,
                "gpu_before": gpu_before,
                "gpu_after": gpu_memory_snapshot(),
            }
        )
    else:
        metadata_paths = write_activation_artifacts(ROOT, rows, manifest, runtime, matrices)
        summary.update(
            {
                "status": "full_train_dev_extraction_complete",
                "model_run": True,
                "metadata_paths": [path.relative_to(ROOT).as_posix() for path in metadata_paths],
                "gpu_before": gpu_before,
                "gpu_after": gpu_memory_snapshot(),
            }
        )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
