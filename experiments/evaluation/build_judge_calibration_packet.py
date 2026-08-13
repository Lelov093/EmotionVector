from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    args = parse_args()
    rows = read_jsonl(resolve(args.dataset))
    packet = []
    per_axis: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        count = per_axis.get(row["axis_id"], 0)
        if count >= args.per_axis:
            continue
        per_axis[row["axis_id"]] = count + 1
        packet.append(
            {
                "judge_item_id": f"phase_e_b1_{len(packet) + 1:03d}",
                "eval_id": row["eval_id"],
                "axis_id": row["axis_id"],
                "comparison_type": "target_reference vs contrast_reference",
                "user_prompt": row["user_prompt"],
                "output_a": target_reference(row),
                "output_b": contrast_reference(row),
                "reference_only": True,
                "source": "trait_eval_12axis_v0_1_reference_calibration",
                "human_annotated": False,
                "created_at": now,
            }
        )
    write_jsonl(resolve(args.output), packet)
    print(json.dumps({"packet_rows": len(packet), "axes": len(per_axis)}, indent=2))
    return 0


def target_reference(row: dict) -> str:
    return f"A strong response should express {row['target_pole']} behavior: {row['expected_behavior']} It should stay useful and avoid avoidable side effects."


def contrast_reference(row: dict) -> str:
    return f"A weak response would drift toward {row['contrast_pole']} behavior, ignore the prompt-specific risk, and trade response quality for shallow trait wording."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/evaluation/trait_eval_12axis_v0_1.jsonl")
    parser.add_argument("--output", default="results/cards/phase_e_batch1_judge_calibration_packet.jsonl")
    parser.add_argument("--per-axis", type=int, default=2)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
