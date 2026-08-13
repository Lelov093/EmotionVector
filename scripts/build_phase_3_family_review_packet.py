from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_data_contract import write_phase_3_family_candidates


def main() -> None:
    manifest = write_phase_3_family_candidates(ROOT)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "candidate_count": len(manifest["records"]),
                "local_review_packet": manifest["local_review_packet"]["path"],
                "model_or_gpu_run": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
