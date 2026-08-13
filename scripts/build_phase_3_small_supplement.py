from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_small_supplement import write_small_supplement


if __name__ == "__main__":
    result = write_small_supplement(ROOT)
    print(json.dumps({"status": result["status"], "candidate_count": len(result["records"]),
                      "full_review_packet": result["local_review_packet"]["path"],
                      "isolation_review_packet": result["local_isolation_review_packet"]["path"],
                      "model_or_gpu_run": False}, indent=2))
