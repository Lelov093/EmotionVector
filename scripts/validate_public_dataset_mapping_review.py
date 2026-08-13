from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.public_pilot import iter_jsonl, validate_completed_review  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate completed single-researcher public mapping reviews.")
    parser.add_argument("paths", nargs="+", help="Local review JSONL paths")
    return parser.parse_args()


def main() -> int:
    errors: list[str] = []
    row_count = 0
    for value in parse_args().paths:
        rows = [row for _, row in iter_jsonl(ROOT / value)]
        row_count += len(rows)
        errors.extend(f"{value}: {error}" for error in validate_completed_review(rows))
    print(json.dumps({"rows": row_count, "errors": errors, "valid": not errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
