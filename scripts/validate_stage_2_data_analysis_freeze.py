from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.representation_freeze import canonical_content_sha256  # noqa: E402


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate_schema(instance: dict, schema_path: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency is present in the project environment
        raise RuntimeError("jsonschema is required for freeze validation") from exc
    jsonschema.Draft202012Validator(load(schema_path), format_checker=jsonschema.FormatChecker()).validate(instance)


def main() -> int:
    decision_path = "data/research_foundation/manifests/public_dataset_use_decisions_v0_1.json"
    manifest_path = "data/research_foundation/manifests/representation_family_split_v2_1.json"
    freeze_path = "data/research_foundation/manifests/representation_family_split_v2_1.freeze.json"
    plan_path = "configs/research/representation_atlas_v2_analysis_plan_v0_1.json"
    decisions = load(decision_path)
    manifest = load(manifest_path)
    freeze = load(freeze_path)
    plan = load(plan_path)
    validate_schema(decisions, "data/research_foundation/schemas/public_dataset_use_decisions_v0_1.schema.json")
    validate_schema(manifest, "data/research_foundation/schemas/representation_family_split_v2_1.schema.json")
    decision_sha = canonical_content_sha256(decisions)
    manifest_sha = canonical_content_sha256(manifest)
    errors: list[str] = []
    if manifest["source_decision"]["sha256"] != decision_sha:
        errors.append("license decision hash mismatch")
    if freeze["manifest_sha256"] != manifest_sha:
        errors.append("freeze manifest hash mismatch")
    if plan["dataset"]["manifest_sha256"] != manifest_sha:
        errors.append("analysis-plan dataset hash mismatch")
    if plan["selection_policy"]["test_opening_status"] != "not_opened":
        errors.append("test was marked opened before analysis execution")
    required_controls = {
        "random_isotropic_direction",
        "shuffled_label_direction",
        "surface_style_direction",
        "unrelated_trait_direction",
        "orthogonalized_target_direction",
        "sign_flipped_target_direction",
    }
    observed_controls = {item["control_id"] for item in plan["null_and_control_registry"]}
    if observed_controls != required_controls:
        errors.append("analysis-plan control registry mismatch")
    if any(check["status"] == "fail" for check in manifest["checks"]):
        errors.append("mandatory split check failed")
    if plan["sample_size_gate"]["confirmatory_claim_allowed"]:
        errors.append("small pilot incorrectly allows confirmatory claims")
    if errors:
        raise ValueError("; ".join(errors))
    print(
        json.dumps(
            {
                "status": "pass",
                "license_decisions": len(decisions["decisions"]),
                "eligible_pairs": len(manifest["records"]),
                "pair_counts": manifest["counts"]["pairs"],
                "mandatory_checks": CounterLike(manifest["checks"]),
                "manifest_sha256": manifest_sha,
                "test_opening_status": plan["selection_policy"]["test_opening_status"],
                "confirmatory_claim_allowed": plan["sample_size_gate"]["confirmatory_claim_allowed"],
            },
            indent=2,
        )
    )
    return 0


def CounterLike(checks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
