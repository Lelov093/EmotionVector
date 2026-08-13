from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_controls import (  # noqa: E402
    load_control_plan,
    load_unrelated_train_rows,
    response_token_counts,
    write_control_artifact,
)
from research_foundation.atlas_v2_extraction import (  # noqa: E402
    extract_candidate_matrices,
    load_quantized_model,
    load_runtime_config,
    load_train_dev_text_rows,
)


TARGET_REVIEW = ROOT / (
    "results/local_artifacts/research_foundation/public_mapping_pilot_v0_2/"
    "pku_safe_rlhf_mapping_review_v0_2.jsonl"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract frozen Atlas v2 control activations")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-model-run", action="store_true")
    args = parser.parse_args()
    plan = load_control_plan(ROOT)
    runtime = load_runtime_config(ROOT)
    unrelated_rows = load_unrelated_train_rows(ROOT, plan)
    target_rows, _, _ = load_train_dev_text_rows(ROOT, TARGET_REVIEW)
    summary = {
        "status": "prepared",
        "unrelated_axis": plan["unrelated_control"]["axis_id"],
        "unrelated_train_responses": len(unrelated_rows),
        "target_feature_responses": len(target_rows),
        "model_run": False,
        "test_opened": False,
    }
    if args.prepare_only:
        print(json.dumps(summary, indent=2))
        return 0
    if not args.confirm_model_run:
        raise SystemExit("refusing control model execution without --confirm-model-run")
    model, tokenizer = load_quantized_model(runtime)
    matrices = extract_candidate_matrices(
        model,
        tokenizer,
        unrelated_rows,
        layers=runtime["candidate_specifications"]["layers"],
        pooling_modes=runtime["candidate_specifications"]["pooling"],
        max_sequence_tokens=runtime["execution"]["max_sequence_tokens"],
    )
    counts = response_token_counts(tokenizer, target_rows)
    metadata_path = write_control_artifact(
        ROOT, plan, runtime, unrelated_rows, matrices, counts
    )
    summary.update(
        {
            "status": "control_extraction_complete",
            "model_run": True,
            "matrix_shapes": {
                f"{key[0]}::{key[1]}": list(value.shape)
                for key, value in matrices.items()
            },
            "metadata_path": metadata_path.relative_to(ROOT).as_posix(),
        }
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
