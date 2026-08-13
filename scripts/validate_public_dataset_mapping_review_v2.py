from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.public_mapping_v2 import (  # noqa: E402
    expected_identity_index,
    load_axis_poles,
    read_jsonl,
    validate_completed_review_v2,
    validate_rows_against_schema_v2,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate completed public mapping reviews against v0.2.")
    parser.add_argument("paths", nargs="+", help="Local v0.2 review JSONL paths")
    parser.add_argument(
        "--manifest",
        default="data/research_foundation/manifests/public_mapping_pilot_v0_2.json",
    )
    parser.add_argument("--axis-registry", default="data/trait_space/axis_registry.yaml")
    parser.add_argument(
        "--schema",
        default="data/research_foundation/schemas/public_mapping_review_v0_2.schema.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
    expected = expected_identity_index(manifest)
    axis_poles = load_axis_poles(ROOT / args.axis_registry)
    rows = [row for value in args.paths for row in read_jsonl(ROOT / value)]
    errors = validate_rows_against_schema_v2(rows, ROOT / args.schema)
    errors.extend(validate_completed_review_v2(rows, axis_poles, expected))
    print(
        json.dumps(
            {
                "schema_version": "public_mapping_review_v0_2",
                "rows": len(rows),
                "errors": errors,
                "valid": not errors,
            },
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
