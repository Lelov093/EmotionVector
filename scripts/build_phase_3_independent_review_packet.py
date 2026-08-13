from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import read_json, read_jsonl
from research_foundation.representation_freeze import canonical_content_sha256


CONTRACT = "configs/research/phase_3_independent_blind_review_amendment_v0_2.json"
SCHEMA = "data/research_foundation/schemas/phase_3_independent_blind_review_amendment_v0_2.schema.json"


def write_jsonl_exclusive(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    contract = read_json(ROOT / CONTRACT)
    jsonschema.validate(contract, read_json(ROOT / SCHEMA))
    for key, relative in contract["bound_evidence"].items():
        if key.endswith("_path"):
            expected = contract["bound_evidence"][key.removesuffix("_path") + "_sha256"]
            if canonical_content_sha256(read_json(ROOT / relative)) != expected:
                raise ValueError(f"amendment evidence hash mismatch: {key}")
    execution = read_json(ROOT / contract["bound_evidence"]["held_out_execution_path"])
    if execution["blind_review"]["human_annotations_completed"] != 0:
        raise ValueError("independent packet must be frozen before any human rating")
    source = read_jsonl(ROOT / contract["artifacts"]["source_packet"])
    if len(source) != 52 or sum(len(item["blind_outputs"]) for item in source) != 780:
        raise ValueError("source blind packet is incomplete")
    packet = [{**item, "reviewer_id": "independent_reviewer_01"} for item in source]
    packet_path = ROOT / contract["artifacts"]["independent_packet"]
    write_jsonl_exclusive(packet_path, packet)
    rows = []
    for item in packet:
        for output in item["blind_outputs"]:
            rows.append({
                "review_item_id": item["review_item_id"], "candidate_id": item["candidate_id"],
                "final_isolation_family_id": item["final_isolation_family_id"], "axis_id": item["axis_id"],
                "user_prompt": item["user_prompt"], "blind_output_id": output["blind_output_id"],
                "output_text": output["output_text"], "reviewer_id": "independent_reviewer_01",
                "trait_score_0_to_4": "", "task_quality_score_0_to_4": "", "naturalness_score_0_to_4": "",
                "refusal_appropriateness": "", "over_refusal_true_false": "",
                "sycophancy_or_over_accommodation_true_false": "", "alternative_quality": "",
                "repetition_0_to_2": "", "other_side_effects_pipe_separated": "",
                "confidence_low_medium_high": "", "notes": "", "reviewed_at_timezone_aware": "",
            })
    sheet = ROOT / contract["artifacts"]["independent_review_sheet"]
    with sheet.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    attestation = {
        "attestation_version": "phase_3_independent_reviewer_attestation_v0_2",
        "reviewer_id": "independent_reviewer_01", "status": "pending_human_signature_before_first_rating",
        "human_name_or_pseudonym": "", "signed_at": "",
        "has_seen_aggregate_condition_diagnostics": None,
        "has_accessed_condition_key_or_per_item_mapping": None,
        "confirms_no_rating_started_before_signature": None,
    }
    (ROOT / contract["artifacts"]["reviewer_attestation"]).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "prepared_pending_independent_reviewer_attestation", "packet_items": 52, "review_rows": 780, "condition_key_accessed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
