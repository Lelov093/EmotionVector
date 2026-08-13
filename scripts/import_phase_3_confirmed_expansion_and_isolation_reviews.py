from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_expansion_review import import_confirmed_expansion_and_isolation_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description="Import confirmed Phase 3 expansion and isolation reviews")
    parser.add_argument("expansion_jsonl", type=Path)
    parser.add_argument("isolation_jsonl", type=Path)
    args = parser.parse_args()
    result = import_confirmed_expansion_and_isolation_reviews(
        ROOT,
        args.expansion_jsonl.resolve(),
        args.isolation_jsonl.resolve(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
