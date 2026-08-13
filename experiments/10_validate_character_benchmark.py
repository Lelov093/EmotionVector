"""
Phase 3.0: Character Stability Benchmark Validation

Pure JSON validation — no torch/transformers imports needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "results" / "logs"

PROFILES_PATH = RAW_DATA_DIR / "character_profiles.jsonl"
SCENARIOS_PATH = RAW_DATA_DIR / "character_stability_scenarios.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        print(f"ERROR: File not found: {path}")
        sys.exit(1)
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def validate_profiles(profiles: list[dict]) -> list[str]:
    errors = []
    profile_ids = set()
    required_fields = [
        "id", "name", "description", "core_traits", "risk_traits",
        "expected_behavior", "style_constraints", "failure_modes",
    ]
    for p in profiles:
        pid = p.get("id", "?")
        profile_ids.add(pid)
        for field in required_fields:
            if field not in p:
                errors.append(f"Profile {pid}: missing field '{field}'")
        ct = p.get("core_traits", [])
        if not isinstance(ct, list) or len(ct) < 3:
            errors.append(f"Profile {pid}: core_traits must be list of 3+ items")
        rt = p.get("risk_traits", [])
        if not isinstance(rt, list) or len(rt) < 2:
            errors.append(f"Profile {pid}: risk_traits must be list of 2+ items")
    return errors


def validate_scenarios(scenarios: list[dict], profile_ids: set[str]) -> list[str]:
    errors = []
    required_fields = [
        "id", "character_id", "scenario_type", "user_input",
        "expected_stability",
    ]
    valid_types = {"challenge", "pressure", "user_manipulation", "contradiction"}

    for s in scenarios:
        sid = s.get("id", "?")
        for field in required_fields:
            if field not in s:
                errors.append(f"Scenario {sid}: missing field '{field}'")

        cid = s.get("character_id", "")
        if cid not in profile_ids:
            errors.append(f"Scenario {sid}: character_id '{cid}' not found")

        stype = s.get("scenario_type", "")
        if stype not in valid_types:
            errors.append(f"Scenario {sid}: invalid type '{stype}'")

        if not s.get("user_input", "").strip():
            errors.append(f"Scenario {sid}: empty user_input")

    return errors


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("Phase 3.0 Character Benchmark Validation")
    print("=" * 80)

    all_errors = []

    # Load profiles
    print(f"\nLoading profiles: {PROFILES_PATH}")
    profiles = load_jsonl(PROFILES_PATH)
    print(f"Profiles: {len(profiles)}")
    for p in profiles:
        print(f"  {p['id']}: {p['name']} ({len(p.get('core_traits',[]))} core, "
              f"{len(p.get('risk_traits',[]))} risk, "
              f"{len(p.get('style_constraints',[]))} constraints, "
              f"{len(p.get('failure_modes',[]))} failure modes)")

    all_errors.extend(validate_profiles(profiles))
    profile_ids = {p["id"] for p in profiles}

    # Load scenarios
    print(f"\nLoading scenarios: {SCENARIOS_PATH}")
    scenarios = load_jsonl(SCENARIOS_PATH)
    print(f"Scenarios: {len(scenarios)}")

    print("\nBy character:")
    for pid in sorted(profile_ids):
        count = sum(1 for s in scenarios if s["character_id"] == pid)
        print(f"  {pid}: {count}")

    print("\nBy scenario type:")
    type_counts = {}
    for s in scenarios:
        t = s["scenario_type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    for t in sorted(type_counts):
        print(f"  {t}: {type_counts[t]}")

    all_errors.extend(validate_scenarios(scenarios, profile_ids))

    # Coverage
    for pid in sorted(profile_ids):
        for stype in ["challenge", "pressure", "user_manipulation", "contradiction"]:
            count = sum(
                1 for s in scenarios
                if s["character_id"] == pid and s["scenario_type"] == stype
            )
            if count < 3:
                all_errors.append(f"Coverage: {pid}/{stype} = {count} (expected 3)")

    print(f"\nValidation errors: {len(all_errors)}")
    if all_errors:
        for e in all_errors:
            print(f"  ERROR: {e}")

    # Save
    val_rows = [
        {"check": "profile_count", "expected": 3, "actual": len(profiles), "passed": len(profiles) == 3},
        {"check": "scenario_count", "expected": 36, "actual": len(scenarios), "passed": len(scenarios) == 36},
        {"check": "validation_errors", "expected": 0, "actual": len(all_errors), "passed": len(all_errors) == 0},
    ]

    val_csv = LOG_DIR / "character_benchmark_validation.csv"
    val_jsonl = LOG_DIR / "character_benchmark_validation.jsonl"

    with open(val_csv, "w", encoding="utf-8-sig") as f:
        f.write("check,expected,actual,passed\n")
        for r in val_rows:
            f.write(f"{r['check']},{r['expected']},{r['actual']},{r['passed']}\n")

    with open(val_jsonl, "w", encoding="utf-8") as f:
        for r in val_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nSaved: {val_csv}")
    print(f"Saved: {val_jsonl}")
    print("=" * 80)


if __name__ == "__main__":
    main()
