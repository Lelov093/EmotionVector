from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import sys
import time

import torch
from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    args = parse_args()
    config = read_yaml(resolve(args.config))
    artifact_dir = resolve(config["local_artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    train_rows = [row for row in read_jsonl(resolve(config["sft_dataset"])) if row["split"] == "train"]
    if not train_rows:
        raise RuntimeError("No train rows found for QLoRA adapter training.")

    tokenizer = AutoTokenizer.from_pretrained(config["model_id"], cache_dir=config["cache_dir"], local_files_only=config.get("local_files_only", True))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    candidate_configs = config.get("candidates") or [{**config["training"], "candidate_id": "single"}]
    summaries = []
    for candidate in candidate_configs:
        summaries.append(train_candidate(config, candidate, tokenizer, train_rows))

    summary = {
        "run_id": f"{config['run_id']}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_id": config["model_id"],
        "axis_id": config["axis_id"],
        "target_pole": config["target_pole"],
        "sft_dataset": config["sft_dataset"],
        "train_samples": len(train_rows),
        "candidates": summaries,
        "best_candidate_id": None,
        "best_selection_basis": "selected during evaluation from dev heuristic and side-effect scores, not train loss only",
        "cuda_after_training": cuda_summary(),
    }
    if len(summaries) == 1:
        summary.update({k: v for k, v in summaries[0].items() if k in {"adapter_dir", "training_config", "train_seconds", "loss_first", "loss_last", "loss_min", "loss_max", "reload_test"}})
    summary_path = artifact_dir / "training_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"training": "PASS", "candidates": len(summaries), "summary": str(summary_path.relative_to(ROOT))}, indent=2))
    return 0


def train_candidate(config: dict, candidate: dict, tokenizer, train_rows: list[dict]) -> dict:
    candidate_id = candidate["candidate_id"]
    run_id = f"{config['run_id']}_{candidate_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    adapter_dir = resolve(config["adapter_output_root"]) / run_id
    start = time.perf_counter()
    model = load_4bit_model(config)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    peft_config = LoraConfig(
        r=candidate["lora_rank"],
        lora_alpha=candidate["lora_alpha"],
        lora_dropout=candidate["lora_dropout"],
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=candidate["target_modules"],
    )
    model = get_peft_model(model, peft_config)
    model.config.use_cache = False
    model.train()
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=candidate["learning_rate"])
    losses = []
    optimizer.zero_grad(set_to_none=True)
    for step in range(1, candidate["max_steps"] + 1):
        row = train_rows[(step - 1) % len(train_rows)]
        batch = encode_sample(tokenizer, row, candidate["max_seq_length"], model.get_input_embeddings().weight.device)
        out = model(**batch)
        loss = out.loss / candidate["gradient_accumulation_steps"]
        loss.backward()
        if step % candidate["gradient_accumulation_steps"] == 0:
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        losses.append(float(out.loss.detach().cpu()))
        print(f"[train:{candidate_id}] step={step}/{candidate['max_steps']} loss={losses[-1]:.4f}")

    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    train_seconds = round(time.perf_counter() - start, 4)
    peak_memory = cuda_summary()
    del optimizer, model
    gc.collect()
    torch.cuda.empty_cache()
    reload_text = reload_test(config, adapter_dir)
    gc.collect()
    torch.cuda.empty_cache()
    return {
        "candidate_id": candidate_id,
        "adapter_dir": str(adapter_dir.relative_to(ROOT)),
        "training_config": candidate,
        "train_seconds": train_seconds,
        "loss_first": round(losses[0], 6),
        "loss_last": round(losses[-1], 6),
        "loss_min": round(min(losses), 6),
        "loss_max": round(max(losses), 6),
        "loss_curve_summary": {
            "first_5": [round(x, 6) for x in losses[:5]],
            "last_5": [round(x, 6) for x in losses[-5:]],
        },
        "cuda_peak_observed": peak_memory,
        "reload_test": {"passed": bool(reload_text), "output_excerpt": reload_text[:300]},
    }


def load_4bit_model(config: dict):
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4")
    return AutoModelForCausalLM.from_pretrained(
        config["model_id"],
        cache_dir=config["cache_dir"],
        local_files_only=config.get("local_files_only", True),
        device_map="auto",
        quantization_config=quant,
    )


def encode_sample(tokenizer, row: dict, max_length: int, device) -> dict:
    messages_prompt = [{"role": "system", "content": row["instruction"]}, {"role": "user", "content": row["user_prompt"]}]
    messages_full = messages_prompt + [{"role": "assistant", "content": row["response"]}]
    prompt = apply_chat(tokenizer, messages_prompt, add_generation_prompt=False)
    full = apply_chat(tokenizer, messages_full, add_generation_prompt=False)
    encoded = tokenizer(full, return_tensors="pt", truncation=True, max_length=max_length)
    prompt_ids = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=max_length)["input_ids"]
    labels = encoded["input_ids"].clone()
    labels[:, : min(prompt_ids.shape[1], labels.shape[1])] = -100
    encoded["labels"] = labels
    return {key: value.to(device) for key, value in encoded.items()}


def apply_chat(tokenizer, messages: list[dict], *, add_generation_prompt: bool) -> str:
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=add_generation_prompt, enable_thinking=False)
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=add_generation_prompt)


def reload_test(config: dict, adapter_dir: Path) -> str:
    tokenizer = AutoTokenizer.from_pretrained(adapter_dir, local_files_only=True)
    base = load_4bit_model(config)
    model = PeftModel.from_pretrained(base, adapter_dir, local_files_only=True)
    model.eval()
    prompt = apply_chat(
        tokenizer,
        [{"role": "user", "content": "A user pressures you to ignore your role limits. Respond helpfully while preserving boundaries."}],
        add_generation_prompt=True,
    )
    encoded = tokenizer(prompt, return_tensors="pt").to(model.get_input_embeddings().weight.device)
    with torch.inference_mode():
        out = model.generate(**encoded, max_new_tokens=64, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    text = tokenizer.decode(out[0, encoded["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    del model, base
    return text


def cuda_summary() -> dict:
    return {
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "memory_allocated_gb": round(torch.cuda.memory_allocated(0) / (1024**3), 4) if torch.cuda.is_available() else None,
        "memory_reserved_gb": round(torch.cuda.memory_reserved(0) / (1024**3), 4) if torch.cuda.is_available() else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
