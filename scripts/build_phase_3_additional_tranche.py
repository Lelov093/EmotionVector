from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_additional_tranche import write_phase_3_additional_tranche


def main() -> int:
    manifest = write_phase_3_additional_tranche(ROOT)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "candidate_count": len(manifest["records"]),
                "full_review_packet": manifest["local_review_packet"]["path"],
                "isolation_review_packet": manifest["local_isolation_review_packet"]["path"],
                "model_or_gpu_run": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
