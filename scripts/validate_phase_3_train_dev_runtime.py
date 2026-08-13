from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import derive_direction_bundle, load_runtime, validate_local_data


def main() -> int:
    runtime = load_runtime(ROOT)
    train, development = validate_local_data(ROOT, runtime)
    bundle, metadata = derive_direction_bundle(ROOT, runtime)
    print(json.dumps({
        "status": "pass",
        "train_rows": len(train),
        "train_families": len({row["final_isolation_family_id"] for row in train}),
        "development_pairs": len(development),
        "development_families": len({row["final_isolation_family_id"] for row in development}),
        "direction_dimension": metadata["dimension"],
        "direction_count": len(bundle),
        "test_rows_used": metadata["test_rows_used"],
        "model_or_gpu_run": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
