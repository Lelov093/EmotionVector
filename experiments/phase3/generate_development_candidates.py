from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
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
from research_foundation.phase3_runtime import (
    build_development_blind_packet,
    content_sha256,
    file_sha256,
    load_runtime,
    validate_development_outputs,
    validate_local_data,
)


def load_base(runtime: dict[str, Any]):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    model_cfg = runtime["model"]
    common = {
        "cache_dir": model_cfg["cache_root"],
        "revision": model_cfg["revision"],
        "local_files_only": model_cfg["local_files_only"],
    }
    tokenizer = AutoTokenizer.from_pretrained(model_cfg["model_id"], **common)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_cfg["model_id"],
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        ),
        device_map=model_cfg["device_map"],
        dtype=torch.float16,
        **common,
    )
    model.eval()
    return model, tokenizer


def format_prompt(tokenizer, prompt: str) -> str:
    try:
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )


def generate_plain(model, tokenizer, prompt: str, generation: dict[str, Any]) -> str:
    import torch

    encoded = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=False,
    )
    if encoded["input_ids"].shape[1] > generation["max_input_tokens"]:
        raise ValueError("development prompt exceeds frozen input limit; truncation is forbidden")
    device = model.get_input_embeddings().weight.device
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        output = model.generate(
            **encoded,
            max_new_tokens=generation["max_new_tokens"],
            do_sample=generation["do_sample"],
            repetition_penalty=generation["repetition_penalty"],
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(output[0, encoded["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def validate_formatted_prompt(tokenizer, prompt: str, max_input_tokens: int) -> None:
    token_ids = tokenizer(prompt, truncation=False)["input_ids"]
    if len(token_ids) > max_input_tokens:
        raise ValueError("development prompt exceeds frozen input limit; truncation is forbidden")


def record_for(row: dict[str, Any], condition: str, output: str, seconds: float) -> dict[str, Any]:
    return {
        "record_type": "phase_3_development_candidate_output_v0_1",
        "candidate_id": row["candidate_id"],
        "final_isolation_family_id": row["final_isolation_family_id"],
        "prompt_sha256": row["prompt_sha256"],
        "condition_id": condition,
        "output_text": output,
        "output_sha256": content_sha256(output),
        "generation_seconds": seconds,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_exclusive_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def generate(runtime: dict[str, Any], development: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import torch
    from peft import PeftModel

    generation = runtime["development_generation"]
    direction_path = ROOT / runtime["direction_source"]["output_path"]
    direction_metadata = json.loads((ROOT / runtime["direction_source"]["metadata_path"]).read_text(encoding="utf-8"))
    if direction_metadata["artifact_sha256"] != file_sha256(direction_path):
        raise ValueError("direction bundle hash mismatch")
    with np.load(direction_path) as payload:
        target = torch.tensor(np.asarray(payload["target"], dtype=np.float32))
    records: list[dict[str, Any]] = []
    base, tokenizer = load_base(runtime)
    for row in development:
        formatted = format_prompt(tokenizer, row["prompt"])
        validate_formatted_prompt(tokenizer, formatted, generation["max_input_tokens"])
        started = time.perf_counter()
        output = generate_plain(base, tokenizer, formatted, generation)
        records.append(record_for(row, "base", output, time.perf_counter() - started))
        for condition, alpha in generation["alpha_by_condition"].items():
            started = time.perf_counter()
            output = generate_with_activation_steering(
                model=base,
                tokenizer=tokenizer,
                prompt=formatted,
                steering_vector=target,
                layer_idx=runtime["direction_source"]["layer"],
                alpha=alpha,
                max_new_tokens=generation["max_new_tokens"],
                max_input_tokens=generation["max_input_tokens"],
                do_sample=generation["do_sample"],
                repetition_penalty=generation["repetition_penalty"],
            ).strip()
            records.append(record_for(row, condition, output, time.perf_counter() - started))
    del base
    gc.collect()
    torch.cuda.empty_cache()

    for checkpoint_id in runtime["qlora"]["checkpoint_ids"]:
        base, tokenizer = load_base(runtime)
        adapter_path = ROOT / runtime["qlora"]["adapter_root"] / checkpoint_id
        model = PeftModel.from_pretrained(base, adapter_path, local_files_only=True)
        model.eval()
        condition = f"qlora_{checkpoint_id}"
        for row in development:
            started = time.perf_counter()
            output = generate_plain(model, tokenizer, format_prompt(tokenizer, row["prompt"]), generation)
            records.append(record_for(row, condition, output, time.perf_counter() - started))
        del model, base
        gc.collect()
        torch.cuda.empty_cache()
    validate_development_outputs(records, development, generation["candidate_condition_ids"])
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate frozen Phase 3 development selection candidates.")
    parser.add_argument("--execute", action="store_true", help="Required acknowledgement that this command performs GPU inference.")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to run model inference without --execute")
    runtime = load_runtime(ROOT)
    _, development = validate_local_data(ROOT, runtime)
    records = generate(runtime, development)
    generation = runtime["development_generation"]
    write_exclusive_jsonl(ROOT / generation["output_path"], records)
    packet, condition_key = build_development_blind_packet(records, development, seed=2026080477)
    write_exclusive_jsonl(ROOT / generation["blind_packet_path"], packet)
    write_exclusive_jsonl(ROOT / generation["condition_key_path"], condition_key)
    print(json.dumps({
        "status": "pass",
        "development_prompts": len(development),
        "condition_outputs": len(records),
        "blind_outputs": len(condition_key),
        "held_out_test_accessed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
