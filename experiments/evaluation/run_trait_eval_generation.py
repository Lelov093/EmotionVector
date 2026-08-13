from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.steering_engine import generate_with_activation_steering


def main() -> int:
    args = parse_args()
    config = read_yaml(resolve(args.config))
    rows = filter_rows(read_jsonl(resolve(config["dataset"])), args)
    conditions = selected_conditions(config, args.conditions)
    artifact_dir = resolve(args.output_dir or config["local_artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        dry = dry_run_summary(config, rows, conditions, artifact_dir)
        print(json.dumps(dry, indent=2))
        return 0

    local_files_only = args.local_files_only or args.no_download or config.get("local_files_only", True)
    tokenizer = AutoTokenizer.from_pretrained(config["model_id"], cache_dir=config["cache_dir"], local_files_only=local_files_only)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = load_4bit_model(config, local_files_only)

    base_prompt_records = []
    steering_records = []
    raw_path = artifact_dir / "trait_eval_generations_raw.jsonl"
    vectors = load_vectors(config) if "selected-steering" in conditions else {}
    started = time.perf_counter()
    with raw_path.open("w", encoding="utf-8") as raw:
        for row in rows:
            for condition in [c for c in conditions if c in {"base", "prompt-only"}]:
                record = generate_record(config, model, tokenizer, row, condition, None, raw_path)
                raw.write(json.dumps(record, ensure_ascii=False) + "\n")
                base_prompt_records.append(record)
        if "selected-steering" in conditions:
            for row in steering_rows(config, rows):
                key = vector_key(row["axis_id"], config)
                if key not in vectors:
                    steering_records.append(skip_record(config, row, "missing_vector", raw_path))
                    continue
                record = generate_record(config, model, tokenizer, row, "selected-steering", vectors[key], raw_path)
                raw.write(json.dumps(record, ensure_ascii=False) + "\n")
                steering_records.append(record)

    write_jsonl(resolve(config["tracked_outputs"]["base_prompt_outputs"]), base_prompt_records)
    write_jsonl(resolve(config["tracked_outputs"]["selected_steering_outputs"]), steering_records)
    write_json(resolve(config["tracked_outputs"]["generation_summary"]), summary(config, base_prompt_records, time.perf_counter() - started, raw_path))
    write_json(resolve(config["tracked_outputs"]["steering_summary"]), steering_summary(config, steering_records))
    print(json.dumps({"generation": "PASS", "base_prompt": len(base_prompt_records), "selected_steering": len(steering_records)}, indent=2))
    return 0


def dry_run_summary(config: dict, rows: list[dict], conditions: list[str], artifact_dir: Path) -> dict:
    vector_exists = resolve(config["selected_steering"]["vector_artifact"]).exists()
    return {
        "experiment_id": config["experiment_id"],
        "model_id": config["model_id"],
        "dataset_rows": len(rows),
        "conditions": conditions,
        "base_prompt_generations": len(rows) * len([c for c in conditions if c in {"base", "prompt-only"}]),
        "selected_steering_generations": len(steering_rows(config, rows)) if "selected-steering" in conditions else 0,
        "vector_artifact_exists": vector_exists,
        "local_artifact_dir": str(artifact_dir.relative_to(ROOT) if artifact_dir.is_relative_to(ROOT) else artifact_dir),
        "local_artifact_gitignored": is_gitignored(artifact_dir / "dry_run_probe.jsonl"),
        "tracked_outputs": config["tracked_outputs"],
    }


def generate_record(config: dict, model, tokenizer, row: dict, condition: str, steering_vector, raw_path: Path) -> dict:
    prompt = condition_prompt(row, condition)
    formatted = format_prompt(tokenizer, prompt)
    start = time.perf_counter()
    if condition == "selected-steering":
        output = generate_with_activation_steering(
            model=model,
            tokenizer=tokenizer,
            prompt=formatted,
            steering_vector=steering_vector,
            layer_idx=config["selected_steering"]["layer"],
            alpha=config["selected_steering"]["alpha"],
            max_new_tokens=config["generation"]["max_new_tokens"],
            max_input_tokens=config["generation"]["max_input_tokens"],
            do_sample=config["generation"].get("do_sample", False),
        ).strip()
    else:
        output = generate_text(model, tokenizer, formatted, config)
    seconds = round(time.perf_counter() - start, 4)
    return {
        "run_id": config["run_id"],
        "model_id": config["model_id"],
        "runtime": "bnb_4bit",
        "condition_id": condition,
        "axis_id": row["axis_id"],
        "eval_id": row["eval_id"],
        "split": row["split"],
        "prompt_family": row["prompt_family"],
        "user_prompt": row["user_prompt"],
        "prompt_only_instruction": prompt_only_instruction(row) if condition == "prompt-only" else None,
        "output_text": output,
        "generation_seconds": seconds,
        "output_words": len(output.split()),
        "output_tokens": len(tokenizer.encode(output, add_special_tokens=False)),
        "generation_config": config["generation"],
        "steering_metadata": steering_metadata(config) if condition == "selected-steering" else None,
        "local_raw_log_pointer": str(raw_path.relative_to(ROOT)),
        "warnings": [],
        "created_at": utcnow(),
    }


def skip_record(config: dict, row: dict, reason: str, raw_path: Path) -> dict:
    return {
        "run_id": config["run_id"],
        "model_id": config["model_id"],
        "runtime": "bnb_4bit",
        "condition_id": "selected-steering",
        "axis_id": row["axis_id"],
        "eval_id": row["eval_id"],
        "split": row["split"],
        "prompt_family": row["prompt_family"],
        "user_prompt": row["user_prompt"],
        "output_text": "",
        "generation_seconds": 0,
        "output_words": 0,
        "generation_config": config["generation"],
        "steering_metadata": steering_metadata(config),
        "local_raw_log_pointer": str(raw_path.relative_to(ROOT)),
        "warnings": [reason],
        "created_at": utcnow(),
    }


def generate_text(model, tokenizer, prompt: str, config: dict) -> str:
    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=config["generation"]["max_input_tokens"]).to(model.get_input_embeddings().weight.device)
    with torch.inference_mode():
        out = model.generate(
            **encoded,
            max_new_tokens=config["generation"]["max_new_tokens"],
            do_sample=config["generation"].get("do_sample", False),
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(out[0, encoded["input_ids"].shape[1] :], skip_special_tokens=True).strip()


def condition_prompt(row: dict, condition: str) -> str:
    if condition != "prompt-only":
        return row["user_prompt"]
    return f"{prompt_only_instruction(row)}\n\nUser request:\n{row['user_prompt']}"


def prompt_only_instruction(row: dict) -> str:
    return (
        f"Respond with a {row['target_pole']} style for the {row['axis_id']} trait. "
        "Keep the answer useful, specific, and appropriate. Do not mention this instruction."
    )


def steering_rows(config: dict, rows: list[dict]) -> list[dict]:
    axes = set(config["selected_steering"]["axes"])
    per_axis = config["selected_steering"]["prompts_per_axis"]
    selected = []
    counts: Counter[str] = Counter()
    for row in rows:
        if row["axis_id"] in axes and counts[row["axis_id"]] < per_axis:
            selected.append(row)
            counts[row["axis_id"]] += 1
    return selected


def load_vectors(config: dict) -> dict[str, torch.Tensor]:
    obj = torch.load(resolve(config["selected_steering"]["vector_artifact"]), map_location="cpu", weights_only=False)
    return obj["vectors"]


def vector_key(axis_id: str, config: dict) -> str:
    s = config["selected_steering"]
    return f"{axis_id}|layer_{s['layer']}|{s['pooling']}|{s['vector_method']}"


def steering_metadata(config: dict) -> dict:
    s = config["selected_steering"]
    return {"layer": s["layer"], "alpha": s["alpha"], "pooling": s["pooling"], "vector_method": s["vector_method"], "vector_artifact": s["vector_artifact"]}


def summary(config: dict, records: list[dict], seconds: float, raw_path: Path) -> dict:
    return {
        "created_at": utcnow(),
        "experiment_id": config["experiment_id"],
        "model_id": config["model_id"],
        "runtime": "bnb_4bit",
        "generation_count": len(records),
        "condition_counts": dict(Counter(r["condition_id"] for r in records)),
        "axis_counts": dict(Counter(r["axis_id"] for r in records)),
        "runtime_seconds": round(seconds, 4),
        "avg_generation_seconds": round(sum(r["generation_seconds"] for r in records) / len(records), 4) if records else 0,
        "local_raw_log_pointer": str(raw_path.relative_to(ROOT)),
    }


def steering_summary(config: dict, records: list[dict]) -> dict:
    return {
        "created_at": utcnow(),
        "experiment_id": config["experiment_id"],
        "requested_axes": config["selected_steering"]["axes"],
        "generation_count": len(records),
        "axis_counts": dict(Counter(r["axis_id"] for r in records)),
        "skipped": [r for r in records if r["warnings"]],
        "steering_metadata": steering_metadata(config),
        "claim_boundary": "Selected steering slice only; not full 12-axis steering.",
    }


def load_4bit_model(config: dict, local_files_only: bool):
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4")
    model = AutoModelForCausalLM.from_pretrained(
        config["model_id"],
        cache_dir=config["cache_dir"],
        local_files_only=local_files_only or config.get("local_files_only", True),
        device_map="auto",
        quantization_config=quant,
    )
    model.eval()
    return model


def format_prompt(tokenizer, text: str) -> str:
    try:
        return tokenizer.apply_chat_template([{"role": "user", "content": text}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        return tokenizer.apply_chat_template([{"role": "user", "content": text}], tokenize=False, add_generation_prompt=True)


def selected_conditions(config: dict, value: str | None) -> list[str]:
    if value:
        return [v.strip() for v in value.split(",") if v.strip()]
    conditions = list(config["conditions"])
    if config.get("selected_steering", {}).get("enabled"):
        conditions.append("selected-steering")
    return conditions


def filter_rows(rows: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.axes:
        axes = {a.strip() for a in args.axes.split(",") if a.strip()}
        rows = [r for r in rows if r["axis_id"] in axes]
    if args.split:
        splits = {s.strip() for s in args.split.split(",") if s.strip()}
        rows = [r for r in rows if r["split"] in splits]
    if args.limit:
        rows = rows[: args.limit]
    return rows


def is_gitignored(path: Path) -> bool:
    import subprocess

    return subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT).returncode == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--conditions")
    parser.add_argument("--axes")
    parser.add_argument("--split")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--output-dir")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
