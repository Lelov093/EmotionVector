from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/research/phase_3_researcher_02_review_contract_v0_3.json"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    source = read_jsonl(ROOT / contract["artifacts"]["source_packet"])
    if len(source) != 52 or sum(len(item["blind_outputs"]) for item in source) != 780:
        raise ValueError("source packet is incomplete")
    packet = [{**item, "reviewer_id": "researcher_02"} for item in source]
    packet_path = ROOT / contract["artifacts"]["review_packet"]
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    with packet_path.open("x", encoding="utf-8") as handle:
        for item in packet:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    rows = []
    for item in packet:
        for output in item["blind_outputs"]:
            rows.append({
                "review_item_id": item["review_item_id"], "candidate_id": item["candidate_id"],
                "final_isolation_family_id": item["final_isolation_family_id"], "axis_id": item["axis_id"],
                "user_prompt": item["user_prompt"], "blind_output_id": output["blind_output_id"],
                "output_text": output["output_text"], "reviewer_id": "researcher_02",
                "trait_score_0_to_4": "", "task_quality_score_0_to_4": "", "naturalness_score_0_to_4": "",
                "refusal_appropriateness": "", "over_refusal_true_false": "",
                "sycophancy_or_over_accommodation_true_false": "", "alternative_quality": "",
                "repetition_0_to_2": "", "other_side_effects_pipe_separated": "",
                "confidence_low_medium_high": "", "notes": "", "reviewed_at_timezone_aware": "",
            })
    sheet_path = ROOT / contract["artifacts"]["review_sheet"]
    with sheet_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    compliance = {
        "record_version": "phase_3_researcher_02_compliance_record_v0_3",
        "reviewer_id": "researcher_02",
        "record_basis": "user_confirmed_in_chat",
        "personal_name_recorded": False,
        "reviewer_signature_recorded": False,
        "checks": {
            "human_reviewer": "compliant",
            "not_researcher_01": "compliant",
            "not_automated_agent": "compliant",
            "aggregate_condition_diagnostics_not_seen": "compliant",
            "condition_key_or_per_item_mapping_not_accessed": "compliant",
            "rating_not_started_before_guide_and_packet_freeze": "compliant"
        },
        "claim_boundary": "User-confirmed compliance record only; not a reviewer-signed attestation."
    }
    (ROOT / contract["artifacts"]["compliance_record"]).write_text(json.dumps(compliance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "researcher_02_materials_prepared", "review_rows": 780, "compliance": "user_confirmed", "condition_key_accessed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
