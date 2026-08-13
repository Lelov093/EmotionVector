from __future__ import annotations

import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import load_runtime, read_jsonl


OUTPUT = "results/local_artifacts/research_foundation/phase_3/phase_3_development_blind_review_sheet_v0_1.csv"


def main() -> int:
    runtime = load_runtime(ROOT)
    packet_path = ROOT / runtime["development_generation"]["blind_packet_path"]
    packet = read_jsonl(packet_path)
    rows = []
    for item in packet:
        for output in item["blind_outputs"]:
            rows.append({
                "review_item_id": item["review_item_id"],
                "candidate_id": item["candidate_id"],
                "final_isolation_family_id": item["final_isolation_family_id"],
                "axis_id": item["axis_id"],
                "user_prompt": item["user_prompt"],
                "blind_output_id": output["blind_output_id"],
                "output_text": output["output_text"],
                "reviewer_id": "researcher_01",
                "trait_score_0_to_4": "",
                "task_quality_score_0_to_4": "",
                "naturalness_score_0_to_4": "",
                "refusal_appropriateness": "",
                "over_refusal_true_false": "",
                "sycophancy_or_over_accommodation_true_false": "",
                "alternative_quality": "",
                "repetition_0_to_2": "",
                "other_side_effects_pipe_separated": "",
                "confidence_low_medium_high": "",
                "notes": "",
                "reviewed_at_timezone_aware": "",
            })
    output_path = ROOT / OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite review sheet: {output_path}")
    with output_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"status": "prepared_not_reviewed", "rows": len(rows), "condition_fields_included": False, "output": OUTPUT}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
