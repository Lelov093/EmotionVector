from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_readiness import audit_phase_3_readiness  # noqa: E402


DEFAULT_OUTPUT = Path("results/summaries/phase_3_readiness_audit_v0_1.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Phase 3 protocol and data readiness without model execution")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = audit_phase_3_readiness(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_status": result["execution_status"],
        "phase_3_completion_estimate": result["phase_3_completion_estimate"],
        "gates": result["gates"],
        "model_or_gpu_run": result["model_or_gpu_run"],
        "output": output.relative_to(ROOT).as_posix(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
