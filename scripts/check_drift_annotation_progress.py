"""
Check current human annotation progress.

Reads: data/annotations/drift_cases_for_human_annotation.jsonl
Outputs: drift_annotation_progress.json + terminal summary
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_for_human_annotation.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "results" / "summary" / "drift_annotation_progress.json"


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def is_labeled(case: dict) -> bool:
    ann = case.get("annotation")
    if ann is None or not isinstance(ann, dict):
        return False
    return ann.get("human_drift_label") is not None


def main() -> int:
    print("=" * 60)
    print("Drift Annotation Progress Check")
    print("=" * 60)

    if not SOURCE_PATH.exists():
        print(f"ERROR: {SOURCE_PATH} not found")
        return 1

    cases = load_jsonl(SOURCE_PATH)
    total = len(cases)
    lab = [c for c in cases if is_labeled(c)]
    unl = total - len(lab)
    pct = round(len(lab) / total * 100, 1) if total > 0 else 0.0

    print(f"Total cases: {total}")
    print(f"Labeled: {len(lab)}")
    print(f"Unlabeled: {unl}")
    print(f"Progress: {pct}%")

    # Label distribution
    label_dist = Counter(
        (c.get("annotation", {}) or {}).get("human_drift_label", "unlabeled")
        for c in cases
    )
    score_dist = Counter(
        (c.get("annotation", {}) or {}).get("human_drift_score")
        for c in cases
    )

    print(f"\nLabel distribution:")
    for k, v in label_dist.most_common():
        print(f"  {k}: {v}")

    # Invalid checks
    invalid_labels = [
        c["case_id"] for c in lab
        if (c.get("annotation", {}) or {}).get("human_drift_label") not in (
            "no_drift", "mild_drift", "clear_drift", "uncertain", "minor_drift", "major_drift"
        )
    ]
    missing_notes = [c["case_id"] for c in lab if not (c.get("annotation", {}) or {}).get("notes", "").strip()]

    status = "waiting_for_human_annotations" if len(lab) == 0 else (
        "partial" if len(lab) < total else "labeling_complete"
    )

    result = {
        "status": status,
        "total_cases": total,
        "labeled_cases": len(lab),
        "unlabeled_cases": unl,
        "progress_percentage": pct,
        "label_distribution": dict(label_dist),
        "score_distribution": {str(k): v for k, v in score_dist.items()},
        "invalid_label_cases": invalid_labels,
        "missing_notes_cases": missing_notes,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if invalid_labels:
        print(f"\nWARNING: {len(invalid_labels)} cases with invalid labels")
    if missing_notes:
        print(f"NOTE: {len(missing_notes)} labeled cases without notes")

    print(f"\nSaved: {OUTPUT_PATH}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
