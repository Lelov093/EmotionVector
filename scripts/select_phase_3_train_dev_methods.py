from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import read_json
from research_foundation.phase3_selection import write_selection_lock


def main() -> int:
    lock_path, summary_path = write_selection_lock(ROOT)
    summary = read_json(summary_path)
    print(json.dumps({
        "status": summary["status"],
        "selected_specification": summary["selected_specification"],
        "quality_gate": summary["quality_gate"],
        "selection_lock": lock_path.relative_to(ROOT).as_posix(),
        "summary": summary_path.relative_to(ROOT).as_posix(),
        "held_out_test_model_openings": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
