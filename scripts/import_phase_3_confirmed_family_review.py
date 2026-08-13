from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_data_contract import import_confirmed_phase_3_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description="Import user-confirmed Phase 3 family reviews")
    parser.add_argument("jsonl", type=Path, help="Primary confirmed prereview JSONL")
    parser.add_argument("csv", type=Path, help="CSV cross-check file")
    args = parser.parse_args()
    summary = import_confirmed_phase_3_reviews(ROOT, args.jsonl.resolve(), args.csv.resolve())
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
