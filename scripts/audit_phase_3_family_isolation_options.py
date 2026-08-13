from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_isolation_audit import write_phase_3_family_isolation_options_audit


def main() -> int:
    result = write_phase_3_family_isolation_options_audit(ROOT)
    print(
        json.dumps(
            {
                "status": result["status"],
                "frozen_component_count": result["conclusion"]["frozen_contract_component_count"],
                "identity_upper_bound_train_after_heldout": result["conclusion"][
                    "maximum_train_after_heldout_reservation"
                ],
                "model_or_gpu_run": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
