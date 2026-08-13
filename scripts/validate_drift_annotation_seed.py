"""
QA validation for drift_cases_seed.jsonl before human annotation begins.

Checks: JSON validity, required fields, annotation emptiness, duplicates, distributions.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_seed.jsonl"
QA_OUTPUT_PATH = PROJECT_ROOT / "results" / "summary" / "drift_annotation_seed_qa.json"

REQUIRED_FIELDS = ["case_id", "character_id", "condition", "scenario_type", "prompt", "response", "detector_prediction"]
OPTIONAL_FIELDS = ["character_name", "detector_version", "annotation", "source", "scenario_notes"]


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def validate() -> dict:
    cases = load_jsonl(SEED_PATH)
    total = len(cases)
    warnings: list[str] = []
    missing_req: list[str] = []
    empty_prompt: list[str] = []
    empty_response: list[str] = []
    non_empty_anns: list[str] = []
    dup_ids: list[str] = []
    dup_pr: list[str] = []

    # Field checks
    for c in cases:
        cid = c.get("case_id", "?")
        for f in REQUIRED_FIELDS:
            if f not in c or c[f] is None:
                missing_req.append(f"{cid}:{f}")
        if not c.get("prompt", "").strip():
            empty_prompt.append(cid)
        if not c.get("response", "").strip():
            empty_response.append(cid)

        # Annotation emptiness
        ann = c.get("annotation")
        if ann is not None and isinstance(ann, dict):
            filled = [k for k, v in ann.items() if v is not None and v != ""]
            if filled:
                non_empty_anns.append(f"{cid}:{filled}")

    # Duplicates
    id_counts = Counter(c.get("case_id") for c in cases)
    dup_ids = [k for k, v in id_counts.items() if v > 1]

    pr_pairs = [(c.get("prompt", ""), c.get("response", "")) for c in cases]
    pr_counts = Counter(pr_pairs)
    dup_pr = [f"dup_{i}" for i, (k, v) in enumerate(pr_counts.items()) if v > 1]

    # Distributions
    dist_char = dict(Counter(c.get("character_id", "?") for c in cases))
    dist_cond = dict(Counter(c.get("condition", "?") for c in cases))
    dist_type = dict(Counter(c.get("scenario_type", "?") for c in cases))
    dist_risk = dict(Counter(
        c.get("detector_prediction", {}).get("risk_level", "?") for c in cases
    ))

    empty_ann_count = total - len(non_empty_anns)

    # Status
    has_errors = bool(missing_req or empty_prompt or empty_response or non_empty_anns or dup_ids)
    status = "fail" if (missing_req or non_empty_anns) else ("warning" if (has_errors) else "pass")

    result = {
        "source_file": str(SEED_PATH),
        "status": status,
        "total_cases": total,
        "empty_annotation_cases": empty_ann_count,
        "non_empty_annotation_cases": len(non_empty_anns),
        "duplicate_case_ids": dup_ids,
        "duplicate_prompt_response_pairs_count": len(dup_pr),
        "missing_required_fields": missing_req,
        "empty_prompt_cases": empty_prompt,
        "empty_response_cases": empty_response,
        "distributions": {
            "character": dist_char,
            "condition": dist_cond,
            "scenario_type": dist_type,
            "risk_level": dist_risk,
        },
        "warnings": warnings,
    }

    return result


def main() -> int:
    print("=" * 60)
    print("Drift Annotation Seed QA")
    print("=" * 60)

    if not SEED_PATH.exists():
        print(f"ERROR: {SEED_PATH} not found")
        return 1

    result = validate()
    QA_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QA_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nStatus: {result['status']}")
    print(f"Total cases: {result['total_cases']}")
    print(f"Empty annotations: {result['empty_annotation_cases']}")
    print(f"Non-empty annotations: {result['non_empty_annotation_cases']}")
    print(f"Missing required fields: {len(result['missing_required_fields'])}")
    print(f"Empty prompts: {len(result['empty_prompt_cases'])}")
    print(f"Empty responses: {len(result['empty_response_cases'])}")
    print(f"Duplicate case IDs: {len(result['duplicate_case_ids'])}")
    print(f"Dup prompt+response: {result['duplicate_prompt_response_pairs_count']}")

    if result["status"] == "pass":
        print("\nQA PASSED — ready for human annotation.")
    elif result["status"] == "warning":
        print("\nQA WARNING — see details above. May still proceed with caution.")
    else:
        print("\nQA FAILED — fix issues before annotation.")

    print(f"\nSaved: {QA_OUTPUT_PATH}")
    print("=" * 60)
    return 0 if result["status"] != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
