from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_test_runtime import load_held_out_runtime, write_access_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Irreversibly record the single Phase 3 held-out opening.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorization-reference", required=True)
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to open held-out test without --execute")
    runtime = load_held_out_runtime(ROOT, require_unopened=True)
    path = write_access_event(ROOT, runtime, authorization_reference=args.authorization_reference)
    print(json.dumps({
        "status": "opened_once",
        "access_log": path.relative_to(ROOT).as_posix(),
        "model_opening_number": 1,
        "test_pairs_read": 0,
        "model_or_gpu_run": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
