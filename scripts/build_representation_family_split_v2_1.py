from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.representation_freeze import (  # noqa: E402
    allocate_components,
    build_family_components,
    build_manifest,
    canonical_content_sha256,
    canonical_json_bytes,
    representation_pairs,
)
from research_foundation.public_mapping_v2 import (  # noqa: E402
    expected_identity_index,
    load_axis_poles,
    validate_completed_review_v2,
    validate_rows_against_schema_v2,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and freeze the single-axis representation-ready family split without emitting raw text."
    )
    parser.add_argument(
        "--reviews",
        nargs="+",
        required=True,
        help="Complete EmpatheticDialogues and PKU v0.2 review packets; only eligible PKU pairs are emitted.",
    )
    parser.add_argument(
        "--license-decisions",
        default="data/research_foundation/manifests/public_dataset_use_decisions_v0_1.json",
    )
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument(
        "--mapping-manifest",
        default="data/research_foundation/manifests/public_mapping_pilot_v0_2.json",
    )
    parser.add_argument("--axis-registry", default="data/trait_space/axis_registry.yaml")
    parser.add_argument(
        "--review-schema",
        default="data/research_foundation/schemas/public_mapping_review_v0_2.schema.json",
    )
    parser.add_argument(
        "--output",
        default="data/research_foundation/manifests/representation_family_split_v2_1.json",
    )
    parser.add_argument(
        "--freeze-output",
        default="data/research_foundation/manifests/representation_family_split_v2_1.freeze.json",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    review_paths = [ROOT / value for value in args.reviews]
    decision_path = ROOT / args.license_decisions
    decisions = json.loads(decision_path.read_text(encoding="utf-8"))
    decision_by_dataset = {decision["dataset_id"]: decision for decision in decisions["decisions"]}
    pku_decision = decision_by_dataset.get("pku_safe_rlhf")
    if not pku_decision or pku_decision.get("decision") != "approved_noncommercial_research_use":
        raise ValueError("PKU-SafeRLHF non-commercial research-use decision is not approved")
    review_rows = [row for path in review_paths for row in read_jsonl(path)]
    mapping_manifest = json.loads((ROOT / args.mapping_manifest).read_text(encoding="utf-8"))
    review_errors = validate_rows_against_schema_v2(review_rows, ROOT / args.review_schema)
    review_errors.extend(
        validate_completed_review_v2(
            review_rows,
            load_axis_poles(ROOT / args.axis_registry),
            expected_identity_index(mapping_manifest),
        )
    )
    if review_errors:
        preview = "; ".join(review_errors[:5])
        raise ValueError(
            f"Review validation failed with {len(review_errors)} errors: {preview}"
        )
    pairs = representation_pairs(
        review_rows, source_revision=pku_decision["source_revision"]
    )
    components = build_family_components(pairs)
    pair_split, split_counts = allocate_components(components, args.seed)
    decision_sha = canonical_content_sha256(decisions)
    manifest = build_manifest(
        pairs,
        pair_split,
        components,
        created_at=args.created_at,
        seed=args.seed,
        license_decision_path=args.license_decisions,
        license_decision_sha256=decision_sha,
    )
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(manifest)
    output_path.write_bytes(payload)
    freeze = {
        "freeze_version": "representation_family_split_v2_1_freeze",
        "frozen_at": args.created_at,
        "manifest_path": args.output,
        "manifest_sha256": canonical_content_sha256(manifest),
        "hash_basis": "canonical_json_sort_keys_compact_utf8",
        "pair_counts": split_counts,
        "test_pair_ids_sha256": sha256(
            "\n".join(
                sorted(record["pair_id"] for record in manifest["records"] if record["split"] == "test")
            ).encode("utf-8")
        ).hexdigest(),
        "condition": "frozen_before_any_stage_2_model_execution",
    }
    freeze_path = ROOT / args.freeze_output
    freeze_path.write_bytes(canonical_json_bytes(freeze))
    print(
        json.dumps(
            {
                "eligible_pairs": len(pairs),
                "components": len(components),
                "split_pair_counts": split_counts,
                "manifest_sha256": freeze["manifest_sha256"],
                "output": args.output,
                "freeze_output": args.freeze_output,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
