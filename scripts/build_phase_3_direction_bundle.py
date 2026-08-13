from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import load_runtime, write_direction_bundle


def main() -> int:
    runtime = load_runtime(ROOT)
    output, metadata = write_direction_bundle(ROOT, runtime)
    print(json.dumps({
        "status": "pass",
        "direction_bundle": output.relative_to(ROOT).as_posix(),
        "metadata": metadata.relative_to(ROOT).as_posix(),
        "model_or_gpu_run": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
