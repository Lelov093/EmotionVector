from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.public_mapping_v2 import (  # noqa: E402
    load_axis_poles,
    upgrade_empathetic_rows_v2,
    upgrade_pku_rows_v2,
)
from research_foundation.public_pilot import (  # noqa: E402
    build_empathetic_candidates,
    build_pku_candidates,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build schema-v0.2 public Trait-mapping pilot packets.")
    parser.add_argument("--config", default="configs/research/public_mapping_pilot_v0_2.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads((ROOT / args.config).read_text(encoding="utf-8"))
    sampling = json.loads((ROOT / config["sampling_config_path"]).read_text(encoding="utf-8"))
    axis_poles = load_axis_poles(ROOT / config["axis_registry_path"])

    empathetic = sampling["datasets"]["empathetic_dialogues"]
    emp_v1, emp_manifest_v1, emp_summary = build_empathetic_candidates(
        {name: ROOT / path for name, path in empathetic["split_paths"].items()},
        seed=config["random_seed"],
        per_context=empathetic["per_context"],
    )
    pku = sampling["datasets"]["pku_safe_rlhf"]
    pku_v1, pku_manifest_v1, pku_summary = build_pku_candidates(
        {name: ROOT / path for name, path in pku["model_paths"].items()},
        seed=config["random_seed"],
        mixed_per_model=pku["mixed_safety_per_model"],
        both_safe_per_model=pku["both_safe_per_model"],
    )
    emp_review, emp_manifest = upgrade_empathetic_rows_v2(emp_v1, emp_manifest_v1)
    pku_review, pku_manifest = upgrade_pku_rows_v2(pku_v1, pku_manifest_v1)

    for dataset_id, records in (
        ("empathetic_dialogues", emp_review),
        ("pku_safe_rlhf", pku_review),
    ):
        unknown = {
            axis
            for record in records
            for axis in record["candidate_trait_axes"]
            if axis not in axis_poles
        }
        if unknown:
            raise ValueError(f"{dataset_id} references axes missing from the registry: {sorted(unknown)}")

    local_root = ROOT / config["local_review_root"]
    write_jsonl(local_root / "empathetic_dialogues_mapping_review_v0_2.jsonl", emp_review)
    write_jsonl(local_root / "pku_safe_rlhf_mapping_review_v0_2.jsonl", pku_review)

    manifest = {
        "manifest_version": "public_mapping_pilot_v0_2",
        "created_at": config["created_at"],
        "random_seed": config["random_seed"],
        "status": "v0_2_blank_packets_prepared_pending_single_researcher_review",
        "review_schema_path": config["review_schema_path"],
        "axis_registry_path": config["axis_registry_path"],
        "local_review_root": config["local_review_root"],
        "historical_predecessor": config["historical_predecessor"],
        "datasets": [
            {
                "dataset_id": "empathetic_dialogues",
                "source_revision": empathetic["source_revision"],
                "license_identifier": "CC-BY-NC-4.0",
                "summary": emp_summary,
                "records": emp_manifest,
            },
            {
                "dataset_id": "pku_safe_rlhf",
                "source_revision": pku["source_revision"],
                "license_identifier": "CC-BY-NC-4.0",
                "summary": pku_summary,
                "records": pku_manifest,
            },
        ],
        "formal_split_status": "not_created",
        "human_review_status": "not_started",
        "claim_boundary": (
            "The v0.2 files are blank review instruments. Proposed families are non-authoritative; "
            "only accepted human-reviewed mappings may enter later family-unit allocation."
        ),
    }
    manifest_path = ROOT / config["tracked_manifest_path"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": "public_mapping_review_v0_2",
                "empathetic_dialogues_candidates": len(emp_review),
                "pku_safe_rlhf_candidates": len(pku_review),
                "human_reviews_completed": 0,
                "v0_1_preserved": True,
                "formal_split_created": False,
                "local_review_root": config["local_review_root"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
