from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_adapter import build_test_access_event, read_json  # noqa: E402


DEFAULT_LOG = Path(
    "results/local_artifacts/research_foundation/representation_test_access_log_v0_1.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Irreversibly record the single Atlas v2 frozen-test opening."
    )
    parser.add_argument("--selection-lock", required=True, type=Path)
    parser.add_argument("--planned-test-activation", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--dtype", required=True)
    parser.add_argument("--quantization", default=None)
    parser.add_argument("--layer", required=True, type=int)
    parser.add_argument("--pooling", required=True)
    parser.add_argument("--dimension", required=True, type=int)
    parser.add_argument("--array-dtype", choices=("float16", "float32", "float64"), required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--access-log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--confirm-single-test-opening", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_single_test_opening:
        raise SystemExit(
            "refusing to open frozen test without --confirm-single-test-opening"
        )
    lock_path = args.selection_lock if args.selection_lock.is_absolute() else ROOT / args.selection_lock
    log_path = args.access_log if args.access_log.is_absolute() else ROOT / args.access_log
    if log_path.exists():
        raise SystemExit(f"refusing second test opening; access log already exists: {log_path}")
    event = build_test_access_event(
        ROOT,
        read_json(lock_path),
        selection_lock_path=lock_path.resolve().relative_to(ROOT.resolve()).as_posix(),
        planned_test_activation_path=args.planned_test_activation,
        model={
            "model_id": args.model_id,
            "revision": args.model_revision,
            "dtype": args.dtype,
            "quantization": args.quantization,
        },
        representation_spec={
            "layer": args.layer,
            "pooling": args.pooling,
            "dimension": args.dimension,
            "array_dtype": args.array_dtype,
        },
        prior_events=[],
        opened_at=datetime.now(timezone.utc).isoformat(),
        operator_id=args.operator_id,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(log_path, flags)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    print(json.dumps(event, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
