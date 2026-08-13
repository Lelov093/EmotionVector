from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def select_axis_balanced(rows: list[dict], max_items: int) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["axis_id"]].append(row)
    selected: list[dict] = []
    for axis_id in sorted(grouped):
        selected.append(sorted(grouped[axis_id], key=lambda item: item["review_item_id"])[0])
        if len(selected) == max_items:
            break
    return selected


def build_packet(
    rows: list[dict], seed: int, max_items: int, review_round: int = 1
) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    selected = select_axis_balanced(rows, max_items)
    packet: list[dict] = []
    condition_key: list[dict] = []
    for item_index, source in enumerate(selected, start=1):
        blind_outputs: list[dict] = []
        for condition_name, output in source["outputs"].items():
            if not isinstance(output.get("text"), str) or not output["text"].strip():
                continue
            blind_output_id = f"bo_{rng.getrandbits(64):016x}"
            canonical_output_id = "co_" + sha256(
                f"{source['review_item_id']}:{condition_name}".encode("utf-8")
            ).hexdigest()[:16]
            blind_outputs.append(
                {
                    "blind_output_id": blind_output_id,
                    "output_text": output["text"],
                }
            )
            condition_key.append(
                {
                    "record_type": "restricted_condition_key",
                    "blind_output_id": blind_output_id,
                    "condition_id": output.get("condition", condition_name),
                    "artifact_id": source["review_item_id"],
                    "canonical_output_id": canonical_output_id,
                    "review_round": review_round,
                }
            )
        if len(blind_outputs) < 2:
            continue
        rng.shuffle(blind_outputs)
        packet.append(
            {
                "record_type": "review_item",
                "review_item_id": f"blind_pilot_v02_r{review_round}_{item_index:03d}",
                "prompt_id": source["eval_id"],
                "axis_id": source["axis_id"],
                "target_pole": source["target_pole"],
                "contrast_pole": source["contrast_pole"],
                "user_prompt": source["user_prompt"],
                "blind_outputs": blind_outputs,
                "rubric_version": "blind_evaluation_protocol_v0_2",
                "review_round": review_round,
            }
        )
    return packet, condition_key


def write_card(
    path: Path, round_1: list[dict], round_2: list[dict], seed: int, source: str, key_path: str
) -> None:
    axes = sorted({item["axis_id"] for item in round_1})
    output_count = sum(len(item["blind_outputs"]) for item in round_1)
    text = f"""# Single-Researcher Condition-Blind Pilot Packet v0.2

- status: `prepared_not_annotated`
- source: `{source}`
- items per round: {len(round_1)}
- blind outputs per round: {output_count}
- review rounds: 2
- axes: `{json.dumps(axes)}`
- round 1 randomization seed: `{seed}`
- round 2 randomization seed: `{seed + 1}`
- restricted condition key: `{key_path}` (gitignored local artifact; do not share with reviewers)
- heuristic scores included: false
- LLM Judge outputs included: false
- AI preannotations included: false
- single-researcher annotations completed: 0

## Intended Use

Rubric-comprehension and within-reviewer stability pilot only. Existing Phase E outputs are reused to test the blind-review workflow; this packet is not a frozen confirmatory test set.

## Human Requirement

The same researcher completes round 1 without access to the condition key, then completes independently randomized round 2 after a minimum seven-day washout without consulting round-1 scores. This estimates test-retest stability only; it is not inter-rater agreement or independent external evaluation.

## Claim Boundary

Packet preparation is not human annotation, evaluator calibration, stability evidence or proof of Trait control.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a method-blind human-review pilot packet from existing outputs.")
    parser.add_argument(
        "--input",
        default="data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl",
    )
    parser.add_argument(
        "--packet",
        default="data/research_foundation/human_review/blind_review_pilot_packet_v0_2_round_1.jsonl",
    )
    parser.add_argument(
        "--round-2-packet",
        default="data/research_foundation/human_review/blind_review_pilot_packet_v0_2_round_2.jsonl",
    )
    parser.add_argument(
        "--card",
        default="data/research_foundation/human_review/blind_review_pilot_packet_v0_2.card.md",
    )
    parser.add_argument(
        "--condition-key",
        default="results/local_artifacts/research_foundation/blind_review_pilot_condition_key_v0_2.jsonl",
    )
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--max-items", type=int, default=12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_rows = read_jsonl(ROOT / args.input)
    round_1, key_1 = build_packet(source_rows, args.seed, args.max_items, review_round=1)
    round_2, key_2 = build_packet(source_rows, args.seed + 1, args.max_items, review_round=2)
    if not round_1 or not round_2:
        raise ValueError("No review items were selected")
    write_jsonl(ROOT / args.packet, round_1)
    write_jsonl(ROOT / args.round_2_packet, round_2)
    write_jsonl(ROOT / args.condition_key, key_1 + key_2)
    write_card(ROOT / args.card, round_1, round_2, args.seed, args.input, args.condition_key)
    print(
        json.dumps(
            {
                "items_per_round": len(round_1),
                "blind_outputs_per_round": len(key_1),
                "review_rounds": 2,
                "single_researcher_annotations": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
