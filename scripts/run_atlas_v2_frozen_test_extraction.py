from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_adapter import DATASET_MANIFEST_PATH, read_json  # noqa: E402
from research_foundation.atlas_v2_extraction import (  # noqa: E402
    extract_candidate_matrices,
    load_quantized_model,
    load_test_runtime_config,
    load_test_text_rows,
    write_test_activation_artifact,
)
from research_foundation.representation_freeze import canonical_content_sha256  # noqa: E402


DEFAULT_REVIEW = Path(
    "results/local_artifacts/research_foundation/public_mapping_pilot_v0_2/"
    "pku_safe_rlhf_mapping_review_v0_2.jsonl"
)
DEFAULT_ACCESS_LOG = Path(
    "results/local_artifacts/research_foundation/representation_test_access_log_v0_1.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas v2 single frozen-test extraction")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--run-frozen-test", action="store_true")
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--access-log", type=Path, default=DEFAULT_ACCESS_LOG)
    parser.add_argument("--confirm-model-run", action="store_true")
    parser.add_argument("--confirm-single-test-extraction", action="store_true")
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
    runtime = load_test_runtime_config(ROOT)
    manifest = read_json(ROOT / DATASET_MANIFEST_PATH)
    test_pairs = [row for row in manifest["records"] if row["split"] == "test"]
    prepared = {
        "status": "prepared_without_test_text_access",
        "dataset_manifest_sha256": canonical_content_sha256(manifest),
        "test_pair_count": len(test_pairs),
        "test_response_count": sum(len(row["responses"]) for row in test_pairs),
        "representation_specification": runtime["representation_specification"],
        "planned_array_path": runtime["artifact_policy"]["array_path"],
        "model_run": False,
    }
    if args.prepare_only:
        print(json.dumps(prepared, indent=2))
        return 0
    if not args.confirm_model_run or not args.confirm_single_test_extraction:
        raise SystemExit("refusing frozen test model run without both explicit confirmations")
    review_path = args.review if args.review.is_absolute() else ROOT / args.review
    log_path = args.access_log if args.access_log.is_absolute() else ROOT / args.access_log
    rows, manifest, runtime, event = load_test_text_rows(ROOT, review_path, log_path)
    import torch

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    gpu_before = gpu_memory_snapshot()
    model, tokenizer = load_quantized_model(runtime)
    spec = runtime["representation_specification"]
    matrices = extract_candidate_matrices(
        model,
        tokenizer,
        rows,
        layers=[spec["layer"]],
        pooling_modes=[spec["pooling"]],
        max_sequence_tokens=runtime["execution"]["max_sequence_tokens"],
    )
    matrix = matrices[(spec["layer"], spec["pooling"])]
    metadata_path = write_test_activation_artifact(
        ROOT, rows, manifest, runtime, event, matrix
    )
    result = {
        **prepared,
        "status": "single_frozen_test_extraction_complete",
        "model_run": True,
        "access_event_id": event["event_id"],
        "matrix_shape": list(matrix.shape),
        "metadata_path": metadata_path.relative_to(ROOT).as_posix(),
        "gpu_before": gpu_before,
        "gpu_after": gpu_memory_snapshot(),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
