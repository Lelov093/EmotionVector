from __future__ import annotations

import argparse
import gc
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.model_loader import load_model_and_tokenizer
from backend.core.steering_engine import generate_with_activation_steering
from experiments.steering.evaluators import (
    LIMITATIONS,
    bootstrap_ci,
    build_pairwise_records,
    build_targeted_pairwise_records,
    classify_failures,
    evaluate_output,
    summarize_records,
)

DEFAULT_CACHE_DIR = Path(r"D:\AI_Models\huggingface\hub")
DEFAULT_RUN_ID = "steering_qwen3_4b_phase_c_batch1_v0_1"


def main() -> int:
    args = parse_args()
    config_path = resolve(args.config)
    config = read_yaml(config_path)
    selection = build_selection(config, args)
    validation = validate_inputs(config, selection, args)

    if args.dry_run:
        print(json.dumps({"dry_run": "PASS", **validation}, indent=2))
        return 0

    if config.get("module") == "quantization_microbench":
        return run_quantization_microbench(config, selection, args, validation)

    return run_steering(config, selection, args, validation)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase C activation steering baselines.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Limit total prompts after filtering.")
    parser.add_argument("--axes", default=None, help="Comma-separated axis ids.")
    parser.add_argument("--conditions", default=None, help="Comma-separated condition ids.")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def build_selection(config: dict, args: argparse.Namespace) -> dict:
    axes = split_arg(args.axes) or list(config["axes"])
    conditions = split_arg(args.conditions) or list(config["conditions"])
    prompts = [
        row
        for row in read_jsonl(resolve(config["prompt_set"]["path"]))
        if row["axis_id"] in axes
    ]
    if args.limit:
        prompts = prompts[: args.limit]
    return {"axes": axes, "conditions": conditions, "prompts": prompts}


def validate_inputs(config: dict, selection: dict, args: argparse.Namespace) -> dict:
    model_config_path = resolve(config["model_config"])
    vector_registry = resolve(config["vector_registry"])
    vector_artifact = resolve(config["vector_artifact"])
    split_manifest = resolve(config["split_manifest"])
    dataset_path = resolve(config["dataset_path"])
    prompt_path = resolve(config["prompt_set"]["path"])
    local_artifact_dir = resolve(args.output_dir or config["local_artifact_dir"])

    required_paths = [
        model_config_path,
        vector_registry,
        vector_artifact,
        split_manifest,
        dataset_path,
        prompt_path,
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    if not is_gitignored(local_artifact_dir):
        raise ValueError(f"Local artifact dir must be gitignored: {local_artifact_dir}")

    for output in config["tracked_outputs"].values():
        output_path = resolve(output)
        if is_gitignored(output_path):
            raise ValueError(f"Tracked output is ignored by git: {output_path}")

    vector_obj = torch.load(vector_artifact, map_location="cpu", weights_only=False)
    if vector_obj.get("run_id") != config["vector_run_id"]:
        raise ValueError(
            f"Vector artifact run_id mismatch: {vector_obj.get('run_id')} != {config['vector_run_id']}"
        )

    available_keys = set(vector_obj["vectors"].keys())
    needed_keys = []
    for axis in selection["axes"]:
        for layer in config["layers"]:
            for pooling in config["pooling_modes"]:
                for method in config["vector_methods"]:
                    needed_keys.append(vector_key(axis, layer, pooling, method))
    missing_keys = sorted(key for key in needed_keys if key not in available_keys)
    if missing_keys:
        raise KeyError(f"Missing vector keys: {missing_keys[:8]}")

    registry_rows = read_jsonl(vector_registry)
    registry_matches = [
        row
        for row in registry_rows
        if row.get("run_id") == config["vector_run_id"] and row.get("axis_id") in selection["axes"]
    ]
    if not registry_matches:
        raise ValueError("Vector registry has no matching Qwen3-4B entries for selected axes.")

    prompt_counts = {axis: 0 for axis in selection["axes"]}
    for prompt in selection["prompts"]:
        prompt_counts[prompt["axis_id"]] += 1
    min_prompts = config["prompt_set"].get("min_prompts_per_axis", 1)
    too_small = {axis: count for axis, count in prompt_counts.items() if count < min_prompts}
    if too_small and not args.limit:
        raise ValueError(f"Prompt count below required minimum: {too_small}")

    condition_matrix = config["condition_matrix"]
    unknown_conditions = [c for c in selection["conditions"] if c not in condition_matrix]
    if unknown_conditions:
        raise ValueError(f"Unknown conditions: {unknown_conditions}")

    return {
        "model_config": str(model_config_path),
        "vector_artifact": str(vector_artifact),
        "vector_keys_checked": len(needed_keys),
        "prompt_count": len(selection["prompts"]),
        "prompt_counts_by_axis": prompt_counts,
        "conditions": selection["conditions"],
        "local_artifact_dir": str(local_artifact_dir),
        "tracked_outputs": config["tracked_outputs"],
        "artifact_safety": "local artifacts ignored; tracked outputs lightweight",
    }


def run_steering(config: dict, selection: dict, args: argparse.Namespace, validation: dict) -> int:
    run_id = config.get("run_id", DEFAULT_RUN_ID)
    start = datetime.now(timezone.utc)
    wall_start = time.perf_counter()
    local_artifact_dir = resolve(args.output_dir or config["local_artifact_dir"])
    local_artifact_dir.mkdir(parents=True, exist_ok=True)
    raw_log_path = local_artifact_dir / "steering_generations.jsonl"

    model_config = read_yaml(resolve(config["model_config"]))
    local_files_only = args.local_files_only or args.no_download
    torch.manual_seed(config["generation_config"]["generation_seed"])
    random.seed(config["generation_config"]["generation_seed"])

    vector_obj = torch.load(resolve(config["vector_artifact"]), map_location="cpu", weights_only=False)
    memory_before_load = cuda_summary()
    load_start = time.perf_counter()
    if config.get("runtime_mode"):
        model, tokenizer = load_runtime_model(
            model_config["model_id"],
            config["runtime_mode"],
            local_files_only=local_files_only,
        )
    else:
        model, tokenizer = load_model_and_tokenizer(
            model_config["model_id"],
            cache_dir=str(DEFAULT_CACHE_DIR),
            local_files_only=local_files_only,
            dtype=dtype_from_config(model_config),
            device_map=model_config.get("device_map_strategy", "auto"),
        )
    load_seconds = round(time.perf_counter() - load_start, 4)
    memory_after_load = cuda_summary()

    records = []
    case_rows = []
    total = planned_generation_count(config, selection)
    generated = 0
    total_tokens = 0
    condition_runtime: dict[str, dict] = {}
    deduplicate_baselines = bool(config.get("deduplicate_baselines", False))

    with raw_log_path.open("w", encoding="utf-8") as raw_f:
        for prompt in selection["prompts"]:
            axis = prompt["axis_id"]
            if deduplicate_baselines:
                for condition in selection["conditions"]:
                    if config["condition_matrix"][condition].get("uses_activation_hook", False):
                        continue
                    for alpha in config["condition_matrix"][condition]["alphas"]:
                        generated += 1
                        print(f"[{generated}/{total}] {axis} layer=shared condition={condition} alpha={alpha}")
                        record, token_count, seconds = run_one_generation(
                            run_id=run_id,
                            model=model,
                            tokenizer=tokenizer,
                            prompt=prompt,
                            condition=condition,
                            layer="shared",
                            alpha=alpha,
                            max_new_tokens=config["generation_config"]["max_new_tokens"],
                            raw_log_path=raw_log_path,
                        )
                        total_tokens += token_count
                        add_runtime(condition_runtime, condition, seconds, token_count)
                        raw_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        records.append(record)
                        case_rows.append(light_case(record))

            for layer in config["layers"]:
                base_vector = vector_obj["vectors"][vector_key(axis, layer, "last_token", "difference_of_means")]
                random_vector = random_direction(base_vector, axis, layer)
                shuffled_vector = shuffled_direction(base_vector, axis, layer)

                for condition in selection["conditions"]:
                    if deduplicate_baselines and not config["condition_matrix"][condition].get("uses_activation_hook", False):
                        continue
                    for alpha in config["condition_matrix"][condition]["alphas"]:
                        generated += 1
                        print(f"[{generated}/{total}] {axis} layer={layer} condition={condition} alpha={alpha}")
                        gen_start = time.perf_counter()
                        output = generate_condition(
                            model=model,
                            tokenizer=tokenizer,
                            prompt=format_prompt(tokenizer, prompt_text_for_condition(axis, prompt["user_prompt"], condition)),
                            condition=condition,
                            base_vector=base_vector,
                            random_vector=random_vector,
                            shuffled_vector=shuffled_vector,
                            layer=layer,
                            alpha=float(alpha),
                            max_new_tokens=config["generation_config"]["max_new_tokens"],
                        )
                        seconds = time.perf_counter() - gen_start
                        token_count = count_tokens(tokenizer, output)
                        total_tokens += token_count
                        add_runtime(condition_runtime, condition, seconds, token_count)
                        record = {
                            "run_id": run_id,
                            "condition_id": condition,
                            "axis_id": axis,
                            "prompt_id": prompt["prompt_id"],
                            "prompt_family": prompt["prompt_family"],
                            "layer": layer,
                            "alpha": alpha,
                            "vector_method": "difference_of_means",
                            "pooling": "last_token",
                            "generation_seed": config["generation_config"]["generation_seed"],
                            "output_text": output,
                            "local_raw_log_pointer": relative(raw_log_path),
                            "generated_tokens": token_count,
                            "generation_seconds": round(seconds, 4),
                            "evaluation": {},
                        }
                        record["evaluation"] = evaluate_output(record)
                        raw_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        records.append(record)
                        case_rows.append(light_case(record))

    pairwise = build_pairwise_records(records)
    targeted_pairwise = build_targeted_pairwise_records(records)
    runtime_profile = {
        "model_load_seconds": load_seconds,
        "total_generation_seconds": round(time.perf_counter() - wall_start - load_seconds, 4),
        "total_run_seconds": round(time.perf_counter() - wall_start, 4),
        "avg_seconds_per_generation": round(sum(v["seconds"] for v in condition_runtime.values()) / max(1, generated), 4),
        "total_generated_tokens": total_tokens,
        "tokens_per_second": round(total_tokens / max(1e-9, sum(v["seconds"] for v in condition_runtime.values())), 4),
        "gpu_memory_before_load": memory_before_load,
        "gpu_memory_after_load": memory_after_load,
        "gpu_memory_after_run": cuda_summary(),
        "cpu_offload_detected": cpu_offload_detected(model),
        "model_loaded_once": True,
        "condition_runtime": condition_runtime,
        "raw_artifact_path": relative(raw_log_path),
        "deduplication_strategy": dedup_strategy(config),
        "runtime_mode": config.get("runtime_mode", {"runtime_id": "fp16_auto_offload", "quantization": "none"}),
    }
    summary = build_summary(
        config,
        records,
        pairwise,
        validation,
        start,
        local_files_only,
        run_id=run_id,
        runtime_profile=runtime_profile,
        targeted_pairwise=targeted_pairwise,
    )
    write_json(resolve(config["tracked_outputs"]["summary_json"]), summary)
    write_json(resolve(config["tracked_outputs"]["result_card_json"]), result_card(config, summary, records, pairwise))
    write_jsonl(resolve(config["tracked_outputs"]["sampled_cases_jsonl"]), case_rows)
    if "pairwise_records_jsonl" in config["tracked_outputs"]:
        write_jsonl(resolve(config["tracked_outputs"]["pairwise_records_jsonl"]), targeted_pairwise)
    if "failure_taxonomy_json" in config["tracked_outputs"]:
        write_json(resolve(config["tracked_outputs"]["failure_taxonomy_json"]), summary["failure_taxonomy"])
    if "failure_taxonomy_md" in config["tracked_outputs"]:
        write_markdown(resolve(config["tracked_outputs"]["failure_taxonomy_md"]), taxonomy_markdown(summary["failure_taxonomy"]))
    write_markdown(resolve(config["tracked_outputs"]["result_card_md"]), result_card_markdown(config, summary))
    print(json.dumps({"run": "PASS", "generation_count": len(records), "raw_log": relative(raw_log_path)}, indent=2))
    return 0


def run_quantization_microbench(config: dict, selection: dict, args: argparse.Namespace, validation: dict) -> int:
    local_artifact_dir = resolve(args.output_dir or config["local_artifact_dir"])
    local_artifact_dir.mkdir(parents=True, exist_ok=True)
    raw_log_path = local_artifact_dir / "quantization_microbench_generations.jsonl"
    model_config = read_yaml(resolve(config["model_config"]))
    vector_obj = torch.load(resolve(config["vector_artifact"]), map_location="cpu", weights_only=False)
    prompts = selection["prompts"][: config.get("microbench_prompt_count", 2)]
    local_files_only = args.local_files_only or args.no_download
    results = {}
    raw_rows = []

    for runtime in config["runtime_modes"]:
        runtime_id = runtime["runtime_id"]
        print(f"[microbench] runtime={runtime_id}")
        runtime_result = {
            "load_success": False,
            "generation_success": False,
            "hook_success": False,
            "cuda_available": torch.cuda.is_available(),
            "runtime_mode": runtime,
            "experiment_type": "fp16_vector_to_quantized_runtime_transfer"
            if runtime.get("quantization") in {"8bit", "4bit"}
            else "fp16_vector_to_fp16_runtime",
            "vram_before": cuda_summary(),
            "artifact_path": relative(raw_log_path),
        }
        try:
            load_start = time.perf_counter()
            model, tokenizer = load_runtime_model(
                model_config["model_id"],
                runtime,
                local_files_only=local_files_only,
            )
            runtime_result["load_seconds"] = round(time.perf_counter() - load_start, 4)
            runtime_result["load_success"] = True
            runtime_result["cpu_offload_detected"] = cpu_offload_detected(model)
            runtime_result["vram_after_load"] = cuda_summary()
            gen_start = time.perf_counter()
            token_count = 0
            generation_count = 0

            for prompt in prompts:
                axis = prompt["axis_id"]
                layer = config["layers"][0]
                vector = vector_obj["vectors"][vector_key(axis, layer, "last_token", "difference_of_means")]
                for condition in config["conditions"]:
                    alpha = 0 if condition == "no-steering" else 3
                    output = generate_condition(
                        model=model,
                        tokenizer=tokenizer,
                        prompt=format_prompt(tokenizer, prompt["user_prompt"]),
                        condition=condition,
                        base_vector=vector,
                        random_vector=vector,
                        shuffled_vector=vector,
                        layer=layer,
                        alpha=alpha,
                        max_new_tokens=config["generation_config"]["max_new_tokens"],
                    )
                    row = {
                        "runtime_id": runtime_id,
                        "axis_id": axis,
                        "prompt_id": prompt["prompt_id"],
                        "condition_id": condition,
                        "layer": layer,
                        "alpha": alpha,
                        "output_excerpt": output[:300],
                    }
                    raw_rows.append(row)
                    token_count += count_tokens(tokenizer, output)
                    generation_count += 1
                    if condition == "activation-steering":
                        runtime_result["hook_success"] = True

            gen_seconds = time.perf_counter() - gen_start
            runtime_result.update(
                {
                    "generation_success": True,
                    "generation_count": generation_count,
                    "generated_tokens": token_count,
                    "generation_seconds": round(gen_seconds, 4),
                    "avg_seconds_per_generation": round(gen_seconds / max(1, generation_count), 4),
                    "tokens_per_second": round(token_count / max(1e-9, gen_seconds), 4),
                    "vram_after_generation": cuda_summary(),
                    "output_sanity": "non_empty_outputs_recorded",
                    "conclusion": "use"
                    if runtime.get("quantization") in {"8bit", "4bit"}
                    else "fallback",
                }
            )
        except Exception as exc:
            runtime_result.update(
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                    "conclusion": "reject",
                }
            )
        finally:
            results[runtime_id] = runtime_result
            try:
                del model
                del tokenizer
            except UnboundLocalError:
                pass
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    write_jsonl(raw_log_path, raw_rows)
    summary = {
        "run_id": config.get("run_id", "steering_qwen3_4b_quantization_microbench_phase_c_batch2"),
        "experiment_id": config["experiment_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "model_id": model_config["model_id"],
        "axis": config["axes"],
        "layers": config["layers"],
        "conditions": config["conditions"],
        "runtimes": results,
        "selected_runtime": select_runtime(results),
        "artifact_path": relative(raw_log_path),
        "research_boundary": "Quantized runs use Phase B FP16 vectors as a transfer micro-benchmark; formal quantized-runtime evidence requires rebuilding vectors under that runtime.",
    }
    for output in config["tracked_outputs"].values():
        path = resolve(output)
        if path.suffix == ".md":
            write_markdown(path, microbench_markdown(summary))
        else:
            write_json(path, summary)
    print(json.dumps({"microbench": "DONE", "selected_runtime": summary["selected_runtime"]}, indent=2))
    return 0


def load_runtime_model(model_id: str, runtime: dict, *, local_files_only: bool):
    quantization = runtime.get("quantization", "none")
    if quantization == "none":
        return load_model_and_tokenizer(
            model_id,
            cache_dir=str(DEFAULT_CACHE_DIR),
            local_files_only=local_files_only,
            dtype=torch.float16,
            device_map="auto",
        )

    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        cache_dir=str(DEFAULT_CACHE_DIR),
        local_files_only=local_files_only,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if quantization == "8bit":
        quant_config = BitsAndBytesConfig(load_in_8bit=True)
    elif quantization == "4bit":
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        )
    else:
        raise ValueError(f"Unknown quantization mode: {quantization}")

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        cache_dir=str(DEFAULT_CACHE_DIR),
        local_files_only=local_files_only,
        device_map="auto",
        quantization_config=quant_config,
    )
    model.eval()
    return model, tokenizer


def select_runtime(results: dict) -> dict:
    for runtime_id in ["bnb_4bit", "bnb_8bit"]:
        result = results.get(runtime_id, {})
        if result.get("load_success") and result.get("generation_success") and result.get("hook_success"):
            return {"runtime": "quantized", "runtime_id": runtime_id, "reason": "load, hook, and generation succeeded"}
    return {"runtime": "fp16_auto_offload", "runtime_id": "fp16_auto_offload", "reason": "quantized runtime unavailable or rejected"}


def microbench_markdown(summary: dict) -> str:
    lines = [
        "# Phase C Batch 2 Quantization Micro-benchmark",
        "",
        f"- Model: `{summary['model_id']}`",
        f"- Selected runtime: `{summary['selected_runtime']['runtime_id']}`",
        f"- Boundary: {summary['research_boundary']}",
        "",
    ]
    for runtime_id, result in summary["runtimes"].items():
        lines.extend(
            [
                f"## {runtime_id}",
                "",
                f"- Load success: {result.get('load_success')}",
                f"- Generation success: {result.get('generation_success')}",
                f"- Hook success: {result.get('hook_success')}",
                f"- CPU offload detected: {result.get('cpu_offload_detected')}",
                f"- Tokens/sec: {result.get('tokens_per_second')}",
                f"- Avg seconds/generation: {result.get('avg_seconds_per_generation')}",
                f"- Conclusion: {result.get('conclusion')}",
                "",
            ]
        )
        if result.get("error"):
            lines.append(f"- Error: `{result['error']}`")
            lines.append("")
    return "\n".join(lines)


def run_one_generation(
    *,
    run_id: str,
    model,
    tokenizer,
    prompt: dict,
    condition: str,
    layer,
    alpha,
    max_new_tokens: int,
    raw_log_path: Path,
) -> tuple[dict, int, float]:
    start = time.perf_counter()
    output = generate_without_hook(
        model,
        tokenizer,
        format_prompt(tokenizer, prompt_text_for_condition(prompt["axis_id"], prompt["user_prompt"], condition)),
        max_new_tokens=max_new_tokens,
    )
    seconds = time.perf_counter() - start
    token_count = count_tokens(tokenizer, output)
    record = {
        "run_id": run_id,
        "condition_id": condition,
        "axis_id": prompt["axis_id"],
        "prompt_id": prompt["prompt_id"],
        "prompt_family": prompt["prompt_family"],
        "layer": layer,
        "alpha": alpha,
        "vector_method": "difference_of_means",
        "pooling": "last_token",
        "generation_seed": 20260704,
        "output_text": output,
        "local_raw_log_pointer": relative(raw_log_path),
        "generated_tokens": token_count,
        "generation_seconds": round(seconds, 4),
        "deduplicated_baseline": True,
        "evaluation": {},
    }
    record["evaluation"] = evaluate_output(record)
    return record, token_count, seconds


def prompt_text_for_condition(axis_id: str, user_prompt: str, condition: str) -> str:
    if condition == "prompt-only":
        return prompt_only_text(axis_id, user_prompt)
    return user_prompt


def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])


def add_runtime(condition_runtime: dict, condition: str, seconds: float, token_count: int) -> None:
    bucket = condition_runtime.setdefault(condition, {"generations": 0, "seconds": 0.0, "tokens": 0})
    bucket["generations"] += 1
    bucket["seconds"] = round(bucket["seconds"] + seconds, 4)
    bucket["tokens"] += token_count
    bucket["avg_seconds"] = round(bucket["seconds"] / bucket["generations"], 4)
    bucket["tokens_per_second"] = round(bucket["tokens"] / max(1e-9, bucket["seconds"]), 4)


def generate_condition(
    *,
    model,
    tokenizer,
    prompt: str,
    condition: str,
    base_vector: torch.Tensor,
    random_vector: torch.Tensor,
    shuffled_vector: torch.Tensor,
    layer: int,
    alpha: float,
    max_new_tokens: int,
) -> str:
    if condition in {"no-steering", "prompt-only"}:
        return generate_without_hook(model, tokenizer, prompt, max_new_tokens=max_new_tokens)
    if condition == "activation-steering":
        vector = base_vector
    elif condition == "random-vector":
        vector = random_vector
    elif condition == "shuffled-vector":
        vector = shuffled_vector
    else:
        raise ValueError(f"Unknown condition: {condition}")
    return generate_with_activation_steering(
        model=model,
        tokenizer=tokenizer,
        prompt=prompt,
        steering_vector=vector,
        layer_idx=layer,
        alpha=alpha,
        max_new_tokens=max_new_tokens,
        max_input_tokens=512,
        do_sample=False,
    ).strip()


def generate_without_hook(model, tokenizer, prompt: str, *, max_new_tokens: int) -> str:
    model.eval()
    input_device = model.get_input_embeddings().weight.device
    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
    encoded = {key: value.to(input_device) for key, value in encoded.items()}
    with torch.inference_mode():
        output_ids = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            repetition_penalty=1.05,
        )
    input_len = encoded["input_ids"].shape[1]
    return tokenizer.decode(output_ids[0, input_len:], skip_special_tokens=True).strip()


def format_prompt(tokenizer, user_prompt: str) -> str:
    messages = [{"role": "user", "content": user_prompt}]
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    except Exception:
        return user_prompt


def prompt_only_text(axis_id: str, user_prompt: str) -> str:
    instructions = {
        "calm-agitated": "Respond in a steady, de-escalating way while keeping the answer concrete.",
        "cautious-impulsive": "Respond by separating known facts from uncertainty and avoid unsupported conclusions.",
        "boundary-preserving-over-accommodating": "Respond while preserving appropriate boundaries and offering a useful allowed alternative.",
    }
    return f"{instructions[axis_id]}\n\nUser request: {user_prompt}"


def random_direction(vector: torch.Tensor, axis_id: str, layer: int) -> torch.Tensor:
    seed = stable_seed(axis_id, layer, "random-vector")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    return F.normalize(torch.randn(vector.shape, generator=generator, dtype=vector.dtype), p=2, dim=0)


def shuffled_direction(vector: torch.Tensor, axis_id: str, layer: int) -> torch.Tensor:
    seed = stable_seed(axis_id, layer, "shuffled-vector")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    perm = torch.randperm(vector.numel(), generator=generator)
    return F.normalize(vector.flatten()[perm].reshape_as(vector), p=2, dim=0)


def stable_seed(axis_id: str, layer: int, condition: str) -> int:
    payload = f"{axis_id}|{layer}|{condition}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % (2**31)


def build_summary(
    config: dict,
    records: list[dict],
    pairwise: list[dict],
    validation: dict,
    start,
    local_files_only: bool,
    *,
    run_id: str,
    runtime_profile: dict | None = None,
    targeted_pairwise: list[dict] | None = None,
) -> dict:
    end = datetime.now(timezone.utc)
    grouped = summarize_records(records)
    targeted_pairwise = targeted_pairwise or []
    ci_summary = bootstrap_ci(targeted_pairwise) if targeted_pairwise else {}
    failure_taxonomy = classify_failures(targeted_pairwise, config.get("runtime_benchmark_summary"))
    return {
        "run_id": run_id,
        "experiment_id": config["experiment_id"],
        "created_at": end.isoformat(),
        "git_commit": git_commit(),
        "model_id": read_yaml(resolve(config["model_config"]))["model_id"],
        "axes": config["axes"],
        "layers": config["layers"],
        "alpha_values": config["alpha_values"],
        "conditions": config["conditions"],
        "prompt_count": len({record["prompt_id"] for record in records}),
        "generation_count": len(records),
        "local_files_only": local_files_only,
        "duration_seconds": round((end - start).total_seconds(), 2),
        "cuda": cuda_summary(),
        "runtime_profile": runtime_profile or {},
        "deduplication_strategy": dedup_strategy(config),
        "evaluator_summary": grouped,
        "baseline_comparison": baseline_comparison(records),
        "pairwise_record_count": len(pairwise),
        "targeted_pairwise_record_count": len(targeted_pairwise),
        "bootstrap_ci": ci_summary,
        "side_effect_summary": side_effect_summary(records),
        "failure_cases": failure_cases(records),
        "failure_taxonomy": failure_taxonomy,
        "artifact_pointers": {
            "local_raw_generations": validation["local_artifact_dir"] + "\\steering_generations.jsonl",
            "tracked_cases": config["tracked_outputs"]["sampled_cases_jsonl"],
            "tracked_pairwise": config["tracked_outputs"].get("pairwise_records_jsonl"),
        },
        "evaluator_limitations": LIMITATIONS,
        "conclusion": config.get(
            "conclusion",
            "Qwen3-4B activation-steering run completed with prompt-only, random-vector, shuffled-vector, and no-steering baselines. Trends are preliminary and do not prove stable trait control.",
        ),
    }


def result_card(config: dict, summary: dict, records: list[dict], pairwise: list[dict]) -> dict:
    return {
        "run_id": summary["run_id"],
        "experiment_id": summary["experiment_id"],
        "git_commit": summary["git_commit"],
        "model_id": summary["model_id"],
        "axes": summary["axes"],
        "layers": summary["layers"],
        "alpha_values": summary["alpha_values"],
        "conditions": summary["conditions"],
        "prompt_count": summary["prompt_count"],
        "generation_count": summary["generation_count"],
        "runtime_profile": summary["runtime_profile"],
        "deduplication_strategy": summary["deduplication_strategy"],
        "evaluator_summary": summary["evaluator_summary"],
        "side_effect_summary": summary["side_effect_summary"],
        "baseline_comparison": summary["baseline_comparison"],
        "bootstrap_ci": summary["bootstrap_ci"],
        "failure_taxonomy": summary["failure_taxonomy"],
        "failure_cases": summary["failure_cases"],
        "limitations": [
            "Phase C slice only; no cross-model steering evidence.",
            "Evaluator is rule-based and needs human or LLM judge validation.",
            "Uses last-token difference-of-means vectors.",
            "Raw generation logs are local-only and not tracked in git.",
        ],
        "artifact_pointers": summary["artifact_pointers"],
        "pairwise_record_count": len(pairwise),
        "conclusion": summary["conclusion"],
    }


def result_card_markdown(config: dict, summary: dict) -> str:
    observations = summary["baseline_comparison"]
    lines = [
        f"# {config['experiment_id']} Result Card",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Model: `{summary['model_id']}`",
        f"- Axes: {', '.join(summary['axes'])}",
        f"- Layers: {', '.join(str(layer) for layer in summary['layers'])}",
        f"- Conditions: {', '.join(summary['conditions'])}",
        f"- Prompt count: {summary['prompt_count']}",
        f"- Generation count: {summary['generation_count']}",
        f"- Tokens/sec: {summary['runtime_profile'].get('tokens_per_second')}",
        f"- Deduplication: {summary['deduplication_strategy'].get('summary')}",
        "",
        "## Baseline Comparison",
        "",
    ]
    for key, value in sorted(observations.items()):
        lines.append(f"- `{key}`: trait delta vs no-steering = {value['trait_delta_vs_no_steering']}, usefulness delta = {value['usefulness_delta_vs_no_steering']}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- This is a first steering slice, not a stable controllability claim.",
            "- Evaluator is independent from steering projections but still heuristic.",
            "- Raw generations are stored as local-only artifacts.",
            "- Confidence intervals are bootstrap summaries over a small paired prompt sample.",
            "",
            "## Conclusion",
            "",
            summary["conclusion"],
            "",
        ]
    )
    return "\n".join(lines)


def baseline_comparison(records: list[dict]) -> dict:
    by_key: dict[tuple, list[dict]] = {}
    for record in records:
        by_key.setdefault((record["axis_id"], record["layer"], record["condition_id"], record["alpha"]), []).append(record)

    comparison = {}
    for (axis, layer, condition, alpha), items in by_key.items():
        if condition == "no-steering":
            continue
        base = by_key.get((axis, layer, "no-steering", 0), []) or by_key.get((axis, "shared", "no-steering", 0), [])
        if not base:
            continue
        key = f"{axis}|layer_{layer}|{condition}|alpha_{alpha}"
        comparison[key] = {
            "trait_delta_vs_no_steering": round(avg_trait(items) - avg_trait(base), 4),
            "usefulness_delta_vs_no_steering": round(avg_usefulness(items) - avg_usefulness(base), 4),
            "length_delta_words_vs_no_steering": round(avg_length(items) - avg_length(base), 4),
        }
    return comparison


def side_effect_summary(records: list[dict]) -> dict:
    by_condition: dict[str, list[dict]] = {}
    for record in records:
        by_condition.setdefault(record["condition_id"], []).append(record)
    return {
        condition: {
            "avg_length_words": avg_length(items),
            "avg_usefulness_score": avg_usefulness(items),
            "refusal_rate": round(
                sum(1 for item in items if item["evaluation"]["side_effects"]["refusal_behavior"]) / len(items),
                4,
            ),
        }
        for condition, items in by_condition.items()
    }


def failure_cases(records: list[dict]) -> list[dict]:
    cases = []
    for record in records:
        side = record["evaluation"]["side_effects"]
        trait_score = record["evaluation"]["trait_expression"]["trait_expression_score"] or 0
        if trait_score == 0 or side["repetition_score"] > 0.08 or side["response_usefulness_score"] == 0:
            cases.append(light_case(record))
    return cases[:24]


def light_case(record: dict) -> dict:
    return {
        "run_id": record["run_id"],
        "axis_id": record["axis_id"],
        "prompt_id": record["prompt_id"],
        "condition_id": record["condition_id"],
        "layer": record["layer"],
        "alpha": record["alpha"],
        "trait_expression_score": record["evaluation"]["trait_expression"]["trait_expression_score"],
        "uncertainty": record["evaluation"]["trait_expression"]["uncertainty"],
        "side_effects": record["evaluation"]["side_effects"],
        "output_excerpt": record["output_text"][:500],
        "local_raw_log_pointer": record["local_raw_log_pointer"],
    }


def avg_trait(records: list[dict]) -> float:
    return round(sum((record["evaluation"]["trait_expression"]["trait_expression_score"] or 0) for record in records) / len(records), 4)


def avg_usefulness(records: list[dict]) -> float:
    return round(sum(record["evaluation"]["side_effects"]["response_usefulness_score"] for record in records) / len(records), 4)


def avg_length(records: list[dict]) -> float:
    return round(sum(record["evaluation"]["side_effects"]["length_words"] for record in records) / len(records), 4)


def planned_generation_count(config: dict, selection: dict) -> int:
    dedup = bool(config.get("deduplicate_baselines", False))
    per_prompt = 0
    per_layer = 0
    for condition in selection["conditions"]:
        alphas = len(config["condition_matrix"][condition]["alphas"])
        if dedup and not config["condition_matrix"][condition].get("uses_activation_hook", False):
            per_prompt += alphas
        else:
            per_layer += alphas
    return len(selection["prompts"]) * (per_prompt + len(config["layers"]) * per_layer)


def dedup_strategy(config: dict) -> dict:
    enabled = bool(config.get("deduplicate_baselines", False))
    return {
        "enabled": enabled,
        "summary": (
            "no-steering and prompt-only generated once per prompt with layer=shared"
            if enabled
            else "all conditions generated per layer"
        ),
    }


def cpu_offload_detected(model) -> bool:
    device_map = getattr(model, "hf_device_map", {}) or {}
    return any(str(device) == "cpu" for device in device_map.values())


def taxonomy_markdown(taxonomy: dict) -> str:
    lines = ["# Phase C Batch 2 Failure Taxonomy", ""]
    for name, cases in taxonomy.items():
        lines.append(f"## {name}")
        lines.append("")
        if not cases:
            lines.append("- No cases flagged.")
        else:
            for case in cases[:20]:
                lines.append(f"- `{case}`")
        lines.append("")
    return "\n".join(lines)


def dtype_from_config(model_config: dict):
    dtype = str(model_config.get("recommended_dtype", "fp16")).lower()
    if dtype in {"fp16", "float16"}:
        return torch.float16
    if dtype in {"bf16", "bfloat16"}:
        return torch.bfloat16
    return torch.float32


def vector_key(axis: str, layer: int, pooling: str, method: str) -> str:
    return f"{axis}|layer_{layer}|{pooling}|{method}"


def split_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def resolve(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return ROOT / path


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def is_gitignored(path: Path) -> bool:
    rel = relative(path)
    result = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
    return result.returncode == 0


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def cuda_summary() -> dict:
    return {
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "memory_allocated_gb": round(torch.cuda.memory_allocated(0) / (1024**3), 4) if torch.cuda.is_available() else None,
        "memory_reserved_gb": round(torch.cuda.memory_reserved(0) / (1024**3), 4) if torch.cuda.is_available() else None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
