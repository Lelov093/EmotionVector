from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_split_freeze import write_phase_3_split_freeze


if __name__ == "__main__":
    print(json.dumps(write_phase_3_split_freeze(ROOT), indent=2, sort_keys=True))
