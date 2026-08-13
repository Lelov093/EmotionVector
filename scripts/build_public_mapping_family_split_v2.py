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
    family_split_records_v2,
    load_axis_poles,
    read_jsonl,
    reviewed_family_candidates_v2,
    validate_completed_review_v2,
    validate_rows_against_schema_v2,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build family_split_v2 only from completed v0.2 reviews.")
    parser.add_argument("--reviews", nargs="+", required=True)
    parser.add_argument("--allocation-manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--mapping-manifest",
        default="data/research_foundation/manifests/public_mapping_pilot_v0_2.json",
    )
    parser.add_argument("--axis-registry", default="data/trait_space/axis_registry.yaml")
    parser.add_argument(
        "--review-schema",
        default="data/research_foundation/schemas/public_mapping_review_v0_2.schema.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping_manifest = json.loads((ROOT / args.mapping_manifest).read_text(encoding="utf-8"))
    rows = [row for value in args.reviews for row in read_jsonl(ROOT / value)]
    errors = validate_rows_against_schema_v2(rows, ROOT / args.review_schema)
    errors.extend(validate_completed_review_v2(
        rows,
        load_axis_poles(ROOT / args.axis_registry),
        expected_identity_index(mapping_manifest),
    ))
    if errors:
        raise ValueError(f"Review validation failed with {len(errors)} errors; no split was written")
    allocation = json.loads((ROOT / args.allocation_manifest).read_text(encoding="utf-8"))
    allocation_by_unit = {
        row["allocation_unit_id"]: row["split"] for row in allocation["allocation_units"]
    }
    candidates = reviewed_family_candidates_v2(rows)
    records = family_split_records_v2(candidates, allocation_by_unit)
    output = {
        "manifest_version": allocation["manifest_version"],
        "dataset_version": allocation["dataset_version"],
        "created_at": allocation["created_at"],
        "random_seed": allocation["random_seed"],
        "allocation_unit": "source_task_scenario_template_semantic_family",
        "test_access_policy": allocation["test_access_policy"],
        "records": records,
        "leakage_checks": allocation["leakage_checks"],
        "human_review_status": "complete",
    }
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
