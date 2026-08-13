from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_additional_review import import_confirmed_additional_reviews


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("family_prereview", type=Path)
    parser.add_argument("isolation_prereview", type=Path)
    args = parser.parse_args()
    result = import_confirmed_additional_reviews(ROOT, args.family_prereview, args.isolation_prereview)
    print(json.dumps({"status": result["status"], "family_counts": result["family_counts"],
                      "isolation_counts": result["isolation_counts"], "disjoint_gate_audit": result["disjoint_gate_audit"],
                      "model_or_gpu_run": False}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
