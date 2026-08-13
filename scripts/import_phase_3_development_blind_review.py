from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import file_sha256
from research_foundation.phase3_selection import freeze_formal_annotations


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze user-confirmed Phase 3 blind development ratings before unblinding.")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    formal, freeze = freeze_formal_annotations(ROOT, args.input.resolve())
    print(json.dumps({
        "status": "frozen_before_condition_key_access",
        "formal_annotations": formal.relative_to(ROOT).as_posix(),
        "formal_annotations_sha256": file_sha256(formal),
        "freeze_manifest": freeze.relative_to(ROOT).as_posix(),
        "condition_key_accessed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
