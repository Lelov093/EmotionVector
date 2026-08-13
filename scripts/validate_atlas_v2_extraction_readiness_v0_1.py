from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.atlas_v2_extraction import load_train_dev_text_rows  # noqa: E402


REVIEW = ROOT / (
    "results/local_artifacts/research_foundation/public_mapping_pilot_v0_2/"
    "pku_safe_rlhf_mapping_review_v0_2.jsonl"
)


def main() -> int:
    rows, _, runtime = load_train_dev_text_rows(ROOT, REVIEW)
    model = runtime["model"]
    cache_root = Path(model["cache_root"])
    model_cache = cache_root / ("models--" + model["model_id"].replace("/", "--"))
    revision = model["revision"]
    snapshot = model_cache / "snapshots" / revision
    ref_path = model_cache / "refs" / "main"
    errors = []
    if not ref_path.is_file() or ref_path.read_text(encoding="utf-8").strip() != revision:
        errors.append("local main ref does not match frozen revision")
    config_path = snapshot / "config.json"
    if not config_path.is_file():
        errors.append("frozen model snapshot config.json is missing")
        model_shape = None
    else:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        model_shape = {
            "model_type": config.get("model_type"),
            "hidden_size": config.get("hidden_size"),
            "num_hidden_layers": config.get("num_hidden_layers"),
        }
        if model_shape != {"model_type": "qwen3", "hidden_size": 2560, "num_hidden_layers": 36}:
            errors.append("local model architecture differs from frozen readiness audit")
    weight_files = sorted(snapshot.glob("model-*.safetensors"))
    if len(weight_files) != 3:
        errors.append("expected three local safetensors shards")
    weight_gib = sum(path.stat().st_size for path in weight_files) / (1024**3)
    payload = {
        "status": "pass" if not errors else "fail",
        "model_id": model["model_id"],
        "revision": revision,
        "model_shape": model_shape,
        "weight_shards": len(weight_files),
        "weight_gib": round(weight_gib, 3),
        "train_responses": sum(row.split == "train" for row in rows),
        "dev_responses": sum(row.split == "dev" for row in rows),
        "test_opened": False,
        "model_loaded": False,
        "gpu_used": False,
        "errors": errors,
        "claim_boundary": "Read-only cache and train/dev readiness validation; no model execution.",
    }
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
