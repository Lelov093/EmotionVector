from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.steering_engine import generate_with_activation_steering
from experiments.phase3.generate_development_candidates import format_prompt, generate_plain, load_base
from research_foundation.phase3_runtime import file_sha256
from research_foundation.phase3_test_runtime import (
    build_test_blind_packet,
    load_held_out_pairs_after_opening,
    load_held_out_runtime,
    prompt_only_user_content,
    validate_test_outputs,
)
from research_foundation.representation_freeze import content_sha256


def _record(row: dict[str, Any], condition: str, output: str, seconds: float) -> dict[str, Any]:
    return {
        "record_type": "phase_3_test_candidate_output_v0_1",
        "candidate_id": row["candidate_id"],
        "final_isolation_family_id": row["final_isolation_family_id"],
        "prompt_sha256": row["prompt_sha256"],
        "condition_id": condition,
        "output_text": output,
        "output_sha256": content_sha256(output),
        "generation_seconds": seconds,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _exclusive_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def generate(runtime: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import torch
    from peft import PeftModel

    torch.manual_seed(runtime["generation"]["framework_seed"])
    generation = runtime["generation"]
    bundle_cfg = runtime["direction_bundle"]
    if file_sha256(ROOT / bundle_cfg["path"]) != bundle_cfg["sha256"]:
        raise ValueError("direction bundle hash mismatch before held-out generation")
    with np.load(ROOT / bundle_cfg["path"]) as payload:
        vectors = {
            key: torch.tensor(np.asarray(payload[key], dtype=np.float32))
            for key in bundle_cfg["required_vector_keys"]
        }

    model, tokenizer = load_base(runtime)
    records: list[dict[str, Any]] = []
    for row in rows:
        formatted = format_prompt(tokenizer, row["prompt"])
        started = time.perf_counter()
        output = generate_plain(model, tokenizer, formatted, generation)
        records.append(_record(row, "base", output, time.perf_counter() - started))

        prompt_only = format_prompt(tokenizer, prompt_only_user_content(runtime, row["prompt"]))
        started = time.perf_counter()
        output = generate_plain(model, tokenizer, prompt_only, generation)
        records.append(_record(row, "prompt_only", output, time.perf_counter() - started))

        for condition, vector_key in runtime["condition_registry"]["steering_vector_by_condition"].items():
            started = time.perf_counter()
            output = generate_with_activation_steering(
                model=model,
                tokenizer=tokenizer,
                prompt=formatted,
                steering_vector=vectors[vector_key],
                layer_idx=bundle_cfg["layer"],
                alpha=bundle_cfg["alpha"],
                max_new_tokens=generation["max_new_tokens"],
                max_input_tokens=generation["max_input_tokens"],
                do_sample=generation["do_sample"],
                repetition_penalty=generation["repetition_penalty"],
            ).strip()
            records.append(_record(row, condition, output, time.perf_counter() - started))

    adapter = PeftModel.from_pretrained(
        model,
        ROOT / runtime["qlora_adapter"]["adapter_path"],
        local_files_only=True,
    )
    adapter.eval()
    for row in rows:
        started = time.perf_counter()
        output = generate_plain(adapter, tokenizer, format_prompt(tokenizer, row["prompt"]), generation)
        records.append(_record(row, "qlora", output, time.perf_counter() - started))
    validate_test_outputs(records, rows, runtime["condition_registry"]["condition_ids"])
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate all frozen Phase 3 held-out conditions after the access event.")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to run held-out model/GPU inference without --execute")
    runtime = load_held_out_runtime(ROOT, require_unopened=False)
    rows = load_held_out_pairs_after_opening(ROOT, runtime)
    records = generate(runtime, rows)
    artifacts = runtime["artifacts"]
    _exclusive_jsonl(ROOT / artifacts["candidate_outputs_path"], records)
    packet, key = build_test_blind_packet(records, rows, seed=artifacts["packet_randomization_seed"])
    _exclusive_jsonl(ROOT / artifacts["blind_packet_path"], packet)
    _exclusive_jsonl(ROOT / artifacts["condition_key_path"], key)
    print(json.dumps({
        "status": "complete",
        "held_out_pairs": len(rows),
        "conditions": len(runtime["condition_registry"]["condition_ids"]),
        "outputs": len(records),
        "blind_outputs": len(key),
        "test_openings": 1,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
