from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_atlas_v2_adapter")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    payload = {
        "status": "pass" if result.wasSuccessful() else "fail",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "fixture": "deterministic_synthetic_activation_arrays_only",
        "frozen_test_opened": False,
        "model_or_gpu_used": False,
        "claim_boundary": (
            "This validates artifact contracts, train/dev integration, selection locking, and "
            "test-once guard behavior using temporary synthetic arrays. It is not model or "
            "representation evidence."
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
