from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import random
import sys
import time
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.phase3_runtime import (
    RUNTIME_PATH,
    build_response_only_example,
    file_sha256,
    load_runtime,
    validate_local_data,
)
from research_foundation.representation_freeze import canonical_content_sha256


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def tree_manifest(path: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": item.relative_to(ROOT).as_posix(),
            "bytes": item.stat().st_size,
            "sha256": file_sha256(item),
        }
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]


def load_model_and_tokenizer(runtime: dict[str, Any]):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
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
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_cfg["model_id"],
        quantization_config=quantization,
        device_map=model_cfg["device_map"],
        dtype=torch.float16,
        **common,
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    qlora = runtime["qlora"]
    model = get_peft_model(
        model,
        LoraConfig(
            r=qlora["lora_rank"],
            lora_alpha=qlora["lora_alpha"],
            lora_dropout=qlora["lora_dropout"],
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=qlora["target_modules"],
        ),
    )
    model.config.use_cache = False
    return model, tokenizer


def tensorize(example: dict[str, list[int]], device):
    import torch

    return {
        key: torch.tensor([value], dtype=torch.long, device=device)
        for key, value in example.items()
    }


def train(runtime: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    import torch
    import transformers
    import peft

    qlora = runtime["qlora"]
    seed = qlora["seed"]
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    model, tokenizer = load_model_and_tokenizer(runtime)
    device = model.get_input_embeddings().weight.device
    examples = [
        build_response_only_example(tokenizer, row, qlora["max_sequence_tokens"])
        for row in rows
    ]
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=qlora["learning_rate"],
    )
    adapter_root = ROOT / qlora["adapter_root"]
    if adapter_root.exists() and any(adapter_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite existing Phase 3 adapter directory: {adapter_root}")
    adapter_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    epoch_summaries = []
    optimizer.zero_grad(set_to_none=True)
    model.train()
    for epoch in range(1, qlora["epochs"] + 1):
        order = list(range(len(examples)))
        random.Random(seed + epoch).shuffle(order)
        losses = []
        for position, row_index in enumerate(order, start=1):
            output = model(**tensorize(examples[row_index], device))
            raw_loss = output.loss
            (raw_loss / qlora["gradient_accumulation_steps"]).backward()
            losses.append(float(raw_loss.detach().cpu()))
            if position % qlora["gradient_accumulation_steps"] == 0 or position == len(order):
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            print(f"[phase3-qlora] epoch={epoch}/{qlora['epochs']} row={position}/{len(order)} loss={losses[-1]:.6f}")
        checkpoint_id = qlora["checkpoint_ids"][epoch - 1]
        checkpoint_path = adapter_root / checkpoint_id
        model.save_pretrained(checkpoint_path)
        tokenizer.save_pretrained(checkpoint_path)
        epoch_summaries.append({
            "checkpoint_id": checkpoint_id,
            "adapter_path": checkpoint_path.relative_to(ROOT).as_posix(),
            "mean_loss": float(np.mean(losses)),
            "first_loss": losses[0],
            "last_loss": losses[-1],
            "artifact_manifest": tree_manifest(checkpoint_path),
        })
    summary = {
        "summary_version": "phase_3_qlora_training_summary_v0_1",
        "created_at": utcnow(),
        "runtime_path": RUNTIME_PATH,
        "runtime_sha256": canonical_content_sha256(runtime),
        "model": runtime["model"],
        "train_rows": len(rows),
        "train_families": len({row["final_isolation_family_id"] for row in rows}),
        "epochs": epoch_summaries,
        "elapsed_seconds": time.perf_counter() - started,
        "software": {"torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__},
        "cuda": {
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(0) if torch.cuda.is_available() else None,
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(0) if torch.cuda.is_available() else None,
        },
        "held_out_test_accessed": False,
        "claim_boundary": "Training completion is pipeline evidence only; checkpoint quality is not selected until condition-blind development review.",
    }
    summary_path = ROOT / qlora["training_summary_path"]
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    del optimizer, model
    gc.collect()
    torch.cuda.empty_cache()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen Phase 3 train-only QLoRA recipe.")
    parser.add_argument("--execute", action="store_true", help="Required acknowledgement that this command performs GPU training.")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to train without --execute")
    runtime = load_runtime(ROOT)
    train_rows, _ = validate_local_data(ROOT, runtime)
    summary = train(runtime, train_rows)
    print(json.dumps({
        "status": "pass",
        "epochs": len(summary["epochs"]),
        "train_rows": summary["train_rows"],
        "held_out_test_accessed": False,
        "summary": runtime["qlora"]["training_summary_path"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
