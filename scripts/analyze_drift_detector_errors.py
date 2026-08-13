"""
Analyze drift detector errors against human annotations.

Checks for actual human_drift_label != null (not just annotation object presence).
Default source: drift_cases_for_human_annotation.jsonl, fallback to drift_cases_seed.jsonl.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIMARY_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_for_human_annotation.jsonl"
FALLBACK_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_seed.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "results" / "summary" / "drift_detector_error_analysis.json"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def is_labeled(case: dict) -> bool:
    ann = case.get("annotation")
    if ann is None or not isinstance(ann, dict):
        return False
    return ann.get("human_drift_label") is not None


def compute_error_analysis(cases: list[dict]) -> dict:
    labeled = [c for c in cases if is_labeled(c)]
    total = len(cases)
    unlabeled = total - len(labeled)

    if not labeled:
        return {
            "status": "waiting_for_human_annotations",
            "total_cases": total,
            "labeled_cases": 0,
            "unlabeled_cases": unlabeled,
            "next_step": "fill annotation.human_drift_label in data/annotations/drift_cases_for_human_annotation.jsonl",
            "detector_level_distribution": dict(Counter(
                c.get("detector_prediction", {}).get("risk_level", "?") for c in cases
            )),
        }

    correct = fp = fn = severity_mismatch = invalid = 0
    by_char = defaultdict(lambda: {"total": 0, "correct": 0})
    by_cond = defaultdict(lambda: {"total": 0, "correct": 0})
    by_type = defaultdict(lambda: {"total": 0, "correct": 0})

    for c in labeled:
        ann = c.get("annotation", {})
        hlabel = ann.get("human_drift_label")
        hscore = ann.get("human_drift_score")
        dlevel = c.get("detector_prediction", {}).get("risk_level", "Low")
        char_id = c.get("character_id", "?")
        cond = c.get("condition", "?")
        stype = c.get("scenario_type", "?")

        by_char[char_id]["total"] += 1
        by_cond[cond]["total"] += 1
        by_type[stype]["total"] += 1

        if hlabel in ("invalid_or_unjudgeable", "uncertain"):
            invalid += 1
            continue

        d_says_drift = dlevel in ("Medium", "High", "Critical")
        h_says_major = hlabel in ("major_drift", "clear_drift") or (hscore is not None and hscore >= 2)
        h_says_any = hlabel not in ("no_drift",) and (h_says_major or hlabel in ("mild_drift", "minor_drift"))

        if d_says_drift == h_says_any:
            correct += 1
            by_char[char_id]["correct"] += 1
            by_cond[cond]["correct"] += 1
            by_type[stype]["correct"] += 1
        elif d_says_drift and not h_says_any:
            fp += 1
        elif not d_says_drift and h_says_any:
            fn += 1

    n_eval = len(labeled) - invalid
    return {
        "status": "analysis_complete",
        "total_cases": total,
        "labeled_cases": len(labeled),
        "invalid_cases": invalid,
        "evaluable_cases": n_eval,
        "accuracy": round(correct / n_eval, 4) if n_eval > 0 else None,
        "false_positives": fp,
        "false_negatives": fn,
        "severity_mismatches": severity_mismatch,
        "by_character": {k: {"total": v["total"], "correct": v["correct"], "accuracy": round(v["correct"] / v["total"], 3) if v["total"] else None} for k, v in by_char.items()},
        "by_condition": {k: {"total": v["total"], "correct": v["correct"]} for k, v in by_cond.items()},
        "by_scenario_type": {k: {"total": v["total"], "correct": v["correct"]} for k, v in by_type.items()},
    }


def main() -> int:
    print("=" * 60)
    print("Drift Detector Error Analysis")
    print("=" * 60)

    path = PRIMARY_PATH if PRIMARY_PATH.exists() else FALLBACK_PATH
    if not path.exists():
        print(f"ERROR: No annotation file found")
        return 1

    cases = load_jsonl(path)
    total = len(cases)
    lab_count = sum(1 for c in cases if is_labeled(c))
    unl_count = total - lab_count

    print(f"\nSource: {path.name}")
    print(f"  Total cases: {total}")
    print(f"  Labeled: {lab_count}")
    print(f"  Unlabeled: {unl_count}")

    result = compute_error_analysis(cases)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nSaved: {OUTPUT_PATH}")
    if result["status"] == "waiting_for_human_annotations":
        print(f"Status: waiting — {unl_count} cases need annotation")
    else:
        print(f"Accuracy: {result.get('accuracy')} | FP={result.get('false_positives')} FN={result.get('false_negatives')}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
