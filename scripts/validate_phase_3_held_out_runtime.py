from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_test_runtime import load_held_out_runtime


def main() -> int:
    runtime = load_held_out_runtime(ROOT, require_unopened=True)
    print(json.dumps({
        "status": "pass",
        "conditions": len(runtime["condition_registry"]["condition_ids"]),
        "held_out_families": runtime["test_data"]["family_count"],
        "held_out_pairs": runtime["test_data"]["pair_count"],
        "expected_outputs": runtime["condition_registry"]["expected_output_count"],
        "selected_target_alpha": runtime["selected_methods"]["target_steering_alpha"],
        "selected_qlora_checkpoint": runtime["selected_methods"]["qlora_checkpoint_id"],
        "qlora_quality_gate_passed": runtime["selected_methods"]["qlora_quality_gate_passed"],
        "held_out_test_opened": False,
        "model_or_gpu_run": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
