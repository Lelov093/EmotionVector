from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTE = (
    "User reported the AI preannotations were basically accepted. "
    "This is secondary review acceptance, not independent from-scratch human annotation."
)


def main() -> int:
    args = parse_args()
    subset = read_jsonl(resolve(args.subset))
    filled = {r["review_item_id"]: r for r in read_jsonl(resolve(args.filled))}
    if len(subset) != 36 or len(filled) != 36:
        raise SystemExit(f"Expected 36 subset and 36 filled rows, got {len(subset)} and {len(filled)}")

    merged = []
    for row in subset:
        if row["review_item_id"] not in filled:
            raise SystemExit(f"Missing preannotation for {row['review_item_id']}")
        item = dict(row)
        ai = filled[row["review_item_id"]]["ai_preannotation"]
        if ai.get("status") != "pre_labeled":
            raise SystemExit(f"AI preannotation is not pre_labeled for {row['review_item_id']}")
        item["ai_preannotation"] = ai
        item["human_review"] = {
            **row.get("human_review", {}),
            "reviewer": "user_secondary_review",
            "review_status": "secondary_review_broadly_accepted",
            "correction_level": "minor_or_none",
            "correction_notes": NOTE,
            "reviewed_at": utcnow(),
        }
        item["human_annotation_type"] = "ai_preannotation_with_user_secondary_review"
        item["independent_human_annotation"] = False
        item["human_verified_from_scratch"] = False
        item["user_secondary_reviewed"] = True
        merged.append(item)

    write_jsonl(resolve(args.output), merged)
    write_card(resolve(args.card), merged)
    write_status(resolve(args.status_json), resolve(args.status_md), merged)
    print(json.dumps({"merge": "PASS", "items": len(merged), "axes": len({r["axis_id"] for r in merged})}, indent=2))
    return 0


def write_card(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "# Phase E Review Subset AI-preannotated v0.1\n\n"
        f"- items: {len(rows)}\n"
        f"- axes: {len({r['axis_id'] for r in rows})}\n"
        f"- ai_preannotation_status: {dict(Counter(r['ai_preannotation']['status'] for r in rows))}\n"
        "- user_secondary_review_status: secondary_review_broadly_accepted\n"
        "- independent_human_annotation: false\n"
        "- human_verified_from_scratch: false\n",
        encoding="utf-8",
    )


def write_status(json_path: Path, md_path: Path, rows: list[dict]) -> None:
    status = {
        "created_at": utcnow(),
        "item_count": len(rows),
        "axes_covered": sorted({r["axis_id"] for r in rows}),
        "ai_preannotation_status": dict(Counter(r["ai_preannotation"]["status"] for r in rows)),
        "user_secondary_review_status": "secondary_review_broadly_accepted",
        "correction_level": "minor_or_none",
        "human_annotation_type": "ai_preannotation_with_user_secondary_review",
        "independent_human_annotation": False,
        "human_verified_from_scratch": False,
        "user_secondary_reviewed": True,
        "notes": NOTE,
    }
    write_json(json_path, status)
    md_path.write_text(
        "# Phase E User Secondary Review Status v0.1\n\n"
        f"- item_count: {status['item_count']}\n"
        "- ai_preannotation: completed\n"
        "- user_secondary_review_status: secondary_review_broadly_accepted\n"
        "- correction_level: minor_or_none\n"
        "- independent_human_annotation: false\n"
        "- human_verified_from_scratch: false\n\n"
        f"{NOTE}\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--subset", default="data/evaluation/human_review/phase_e_review_subset_v0_1.jsonl")
    p.add_argument("--filled", default="data/evaluation/human_review/phase_e_ai_preannotation_filled_v0_1.jsonl")
    p.add_argument("--output", default="data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl")
    p.add_argument("--card", default="data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.card.md")
    p.add_argument("--status-json", default="data/evaluation/human_review/phase_e_user_secondary_review_status_v0_1.json")
    p.add_argument("--status-md", default="data/evaluation/human_review/phase_e_user_secondary_review_status_v0_1.md")
    return p.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
