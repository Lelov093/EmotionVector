"""Run tests that are self-contained in a public EmotionVector clone.

The excluded modules validate hash-bound Phase 3 evidence intentionally kept
under ``results/local_artifacts``. They remain part of the full local suite and
must not be treated as passing when those artifacts are absent.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


LOCAL_EVIDENCE_MODULES = {
    "test_phase_3_held_out_analysis",
    "test_phase_3_held_out_runtime",
    "test_phase_3_independent_review",
    "test_phase_3_isolation_audit",
    "test_phase_3_readiness",
    "test_phase_3_researcher_02_review",
    "test_phase_3_runtime",
    "test_phase_3_selection",
    "test_phase_3_small_supplement",
    "test_phase_3_split_freeze",
}


def iter_cases(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_cases(item)
        else:
            yield item


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    discovered = unittest.defaultTestLoader.discover(str(root / "tests"))
    public_cases = []
    excluded_cases = []

    for case in iter_cases(discovered):
        module_name = case.__class__.__module__.removeprefix("tests.")
        if module_name in LOCAL_EVIDENCE_MODULES:
            excluded_cases.append(case)
        else:
            public_cases.append(case)

    print(
        f"Public suite: {len(public_cases)} tests; "
        f"excluded local-evidence tests: {len(excluded_cases)}"
    )
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(public_cases))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
