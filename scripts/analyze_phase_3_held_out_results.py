from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_heldout_analysis import write_results  # noqa: E402


def main() -> int:
    output = write_results(ROOT)
    result = json.loads(output.read_text(encoding="utf-8"))
    print(json.dumps({
        "status": result["status"],
        "output": output.relative_to(ROOT).as_posix(),
        "coverage": result["coverage"],
        "primary_target_summary": result["primary_target_summary"],
        "claim_boundary": result["claim_boundary"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
