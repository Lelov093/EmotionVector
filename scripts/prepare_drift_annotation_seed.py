"""
Prepare a small annotation seed from the full character benchmark outputs.

Selects representative cases across characters, conditions, scenario types,
and drift score ranges. Does NOT fabricate human annotations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_PATH = PROJECT_ROOT / "results" / "logs" / "full_character_benchmark_outputs.jsonl"
SCENARIOS_PATH = PROJECT_ROOT / "data" / "raw" / "character_stability_scenarios.jsonl"
SEED_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_seed.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def select_cases(all_rows: list[dict], scenarios: list[dict], target: int = 48) -> list[dict]:
    """
    Select a balanced set of cases for annotation.
    Strategy: cover all characters x all scenario types x all conditions,
    plus extra borderline / extreme-drift cases.
    """
    # Build scenario lookup
    scenario_map = {s["id"]: s for s in scenarios}

    selected: list[dict] = []
    used_ids: set[str] = set()

    # 1. Core: up to 12 per character (balanced across scenario_type x condition)
    for char_id in ["guardian_001", "scholar_001", "trickster_001"]:
        char_rows = [r for r in all_rows if r["character_id"] == char_id]
        added = 0
        for row in char_rows:
            key = f"{row['scenario_id']}_{row['condition']}"
            if key in used_ids:
                continue
            used_ids.add(key)
            selected.append(row)
            added += 1
            if added >= 12:
                break

    # 2. Extra: top-3 highest drift per character
    for char_id in ["guardian_001", "scholar_001", "trickster_001"]:
        char_rows = [r for r in all_rows if r["character_id"] == char_id]
        char_rows.sort(key=lambda r: r.get("drift_score", 0), reverse=True)
        added = 0
        for row in char_rows:
            key = f"{row['scenario_id']}_{row['condition']}"
            if key in used_ids:
                continue
            used_ids.add(key)
            selected.append(row)
            added += 1
            if added >= 2:
                break

    # 3. Extra: borderline cases (drift around 0.20-0.30)
    borderline = [r for r in all_rows if 0.20 <= r.get("drift_score", 0) <= 0.30]
    borderline.sort(key=lambda r: r.get("drift_score", 0))
    added = 0
    for row in borderline:
        key = f"{row['scenario_id']}_{row['condition']}"
        if key in used_ids:
            continue
        used_ids.add(key)
        selected.append(row)
        added += 1
        if added >= 4:
            break

    # 4. Extra: calm_steered improved cases
    calm_rows = [r for r in all_rows if r["condition"] == "calm_steered" and r.get("drift_score", 0) < 0.15]
    calm_rows.sort(key=lambda r: r.get("drift_score", 0))
    added = 0
    for row in calm_rows:
        key = f"{row['scenario_id']}_{row['condition']}"
        if key in used_ids:
            continue
        used_ids.add(key)
        selected.append(row)
        added += 1
        if added >= 2:
            break

    # Attach scenario prompt
    for row in selected:
        sid = row.get("scenario_id", "")
        scenario = scenario_map.get(sid, {})
        row["prompt"] = scenario.get("user_input", "")
        row["scenario_notes"] = scenario.get("notes", "")

    return selected


def build_seed(selected: list[dict]) -> list[dict]:
    """Convert selected rows into annotation seed format."""
    seed = []
    for i, row in enumerate(selected):
        case_id = f"drift_case_{i+1:03d}"
        seed.append({
            "case_id": case_id,
            "character_id": row.get("character_id", ""),
            "character_name": row.get("character_name", ""),
            "condition": row.get("condition", ""),
            "scenario_type": row.get("scenario_type", ""),
            "prompt": row.get("prompt", ""),
            "response": row.get("output", ""),
            "detector_version": "semantic_drift_detector_v2",
            "detector_prediction": {
                "drift_score": row.get("drift_score"),
                "risk_level": row.get("risk_level", ""),
                "axis_score": row.get("axis_score"),
                "risk_factors": row.get("risk_factors", []),
                "positive_factors": row.get("positive_factors", []),
            },
            "annotation": {
                "human_drift_label": None,
                "human_drift_score": None,
                "error_type": None,
                "notes": "",
            },
            "source": {
                "file": "full_character_benchmark_outputs.jsonl",
                "scenario_id": row.get("scenario_id", ""),
                "condition": row.get("condition", ""),
            },
        })
    return seed


def main() -> int:
    print("=" * 60)
    print("Prepare Drift Annotation Seed")
    print("=" * 60)

    if not OUTPUTS_PATH.exists():
        print(f"ERROR: Outputs file not found: {OUTPUTS_PATH}")
        print("Run: python experiments/13_full_character_benchmark_eval.py")
        return 1

    if not SCENARIOS_PATH.exists():
        print(f"ERROR: Scenarios file not found: {SCENARIOS_PATH}")
        return 1

    print(f"\nLoading: {OUTPUTS_PATH}")
    all_rows = load_jsonl(OUTPUTS_PATH)
    print(f"  Total rows: {len(all_rows)}")

    print(f"Loading: {SCENARIOS_PATH}")
    scenarios = load_jsonl(SCENARIOS_PATH)
    print(f"  Scenarios: {len(scenarios)}")

    print("\nSelecting cases...")
    selected = select_cases(all_rows, scenarios)
    print(f"  Selected: {len(selected)}")

    # Stats
    from collections import Counter
    chars = Counter(r["character_id"] for r in selected)
    conds = Counter(r["condition"] for r in selected)
    types = Counter(r["scenario_type"] for r in selected)
    print(f"  Characters: {dict(chars)}")
    print(f"  Conditions: {dict(conds)}")
    print(f"  Types: {dict(types)}")

    print(f"\nBuilding seed...")
    seed = build_seed(selected)

    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEED_PATH.open("w", encoding="utf-8") as f:
        for case in seed:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"Saved: {SEED_PATH} ({len(seed)} cases)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
