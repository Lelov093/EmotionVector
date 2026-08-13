from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import torch
import yaml
from huggingface_hub import snapshot_download
from transformers import AutoConfig

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.activation_collector import get_pooled_activations
from backend.core.model_loader import load_model_and_tokenizer, load_tokenizer
from backend.core.vector_builder import l2_normalize


DEFAULT_CACHE_DIR = Path(os.environ.get("HF_HUB_CACHE") or r"D:\AI_Models\huggingface\hub")


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def model_cache_path(model_id: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / ("models--" + model_id.replace("/", "--"))


def load_inputs(config_path: Path) -> tuple[dict, dict, dict, list[dict], dict]:
    config = read_yaml(config_path)
    model_config = read_yaml(ROOT / config["model_config"])
    registry = read_yaml(ROOT / config.get("axis_registry", "data/trait_space/axis_registry.yaml"))
    dataset = read_jsonl(ROOT / config["dataset_path"])
    manifest = json.loads((ROOT / config["split_manifest"]).read_text(encoding="utf-8"))
    return config, model_config, registry, dataset, manifest


def registry_axes(registry: dict) -> dict[str, dict]:
    axes = {}
    for group in registry.get("groups", {}).values():
        for axis in group.get("axes", []):
            axes[axis["axis_id"]] = axis
    return axes


def selected_axes(config: dict, axes_arg: str | None) -> list[str]:
    if axes_arg:
        return [axis.strip() for axis in axes_arg.split(",") if axis.strip()]
    axes = config["axes"]
    return axes.get("regression_slice") or axes.get("first_execution_slice") or axes.get("design_scope")


def dry_run(config_path: Path, args: argparse.Namespace) -> dict:
    config, model_config, registry, dataset, manifest = load_inputs(config_path)
    axis_map = registry_axes(registry)
    axes = selected_axes(config, args.axes)
    splits = [args.split] if args.split else ["train", "dev", "test"]
    errors = []
    warnings = []

    for axis in axes:
        if axis not in axis_map:
            errors.append(f"axis not in registry: {axis}")
    for split in splits:
        if split not in {"train", "dev", "test"}:
            errors.append(f"unsupported split: {split}")
    if sorted(manifest["axes_included"]) != sorted({row["axis_id"] for row in dataset}):
        warnings.append("manifest axes cover the dataset slice, not the full 12-axis ontology")
    local_artifact_dir = ROOT / args.output_dir if args.output_dir else ROOT / config["local_artifact_dir"]
    tracked_outputs = [ROOT / output for output in config.get("tracked_summary_outputs", [])]
    if "results/local_artifacts" not in local_artifact_dir.as_posix():
        errors.append(f"local artifact dir must stay under results/local_artifacts: {local_artifact_dir}")
    for output in tracked_outputs:
        output.parent.mkdir(parents=True, exist_ok=True)

    return {
        "passed": not errors,
        "mode": "dry_run",
        "config": str(config_path),
        "model_id": model_config["model_id"],
        "dataset_samples": len(dataset),
        "axes": axes,
        "splits": splits,
        "layers": config["layers"]["candidate_layers"],
        "pooling_modes": config["pooling_modes"],
        "vector_methods": config["vector_methods"],
        "local_artifact_dir": str(local_artifact_dir),
        "tracked_outputs": [str(path) for path in tracked_outputs],
        "errors": errors,
        "warnings": warnings,
    }


def run_atlas(config_path: Path, args: argparse.Namespace) -> dict:
    config, model_config, registry, dataset, manifest = load_inputs(config_path)
    axis_map = registry_axes(registry)
    axes = selected_axes(config, args.axes)
    splits = [args.split] if args.split else ["train", "dev", "test"]
    rows = [row for row in dataset if row["axis_id"] in axes and row["split"] in splits]
    if args.limit:
        rows = rows[: args.limit]
    layers = config["layers"]["candidate_layers"]
    pooling_modes = config["pooling_modes"]
    run_id = run_id_for(model_config)
    local_artifact_dir = ROOT / (args.output_dir or config["local_artifact_dir"]) / run_id
    local_artifact_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = DEFAULT_CACHE_DIR
    local_only = args.local_files_only or args.no_download or not args.allow_download
    model, tokenizer = load_model_and_tokenizer(
        model_config["model_id"],
        cache_dir=str(cache_dir),
        local_files_only=local_only,
        device_map=model_config.get("device_map_strategy", "auto"),
    )

    activations: dict[str, dict[tuple[int, str], torch.Tensor]] = {}
    for idx, row in enumerate(rows, 1):
        print(f"[atlas] extracting {idx}/{len(rows)} {row['sample_id']}")
        activations[row["sample_id"]] = get_pooled_activations(
            model=model,
            tokenizer=tokenizer,
            text=row["text"],
            layer_indices=layers,
            pooling_modes=pooling_modes,
            max_length=int(model_config.get("default_context_length", 512)),
        )

    metrics = {}
    vector_entries = []
    vector_tensors = {}
    for axis in axes:
        axis_rows = [row for row in rows if row["axis_id"] == axis]
        for layer in layers:
            for pooling in pooling_modes:
                for method in config["vector_methods"]:
                    direction = build_direction(axis_rows, activations, layer, pooling, method)
                    key = f"{axis}|layer_{layer}|{pooling}|{method}"
                    vector_tensors[key] = direction
                    split_metrics = score_axis(axis_rows, activations, direction, layer, pooling)
                    metrics[key] = split_metrics
                    vector_entries.append({
                        "run_id": run_id,
                        "experiment_id": config["experiment_id"],
                        "model_id": model_config["model_id"],
                        "dataset_version": config["dataset_version"],
                        "axis_id": axis,
                        "layer": layer,
                        "pooling": pooling,
                        "vector_method": method,
                        "artifact_pointer": str((local_artifact_dir / "vectors.pt").relative_to(ROOT)),
                        "metrics": split_metrics,
                        "created_at": now(),
                    })

    torch.save({"run_id": run_id, "vectors": vector_tensors}, local_artifact_dir / "vectors.pt")
    write_vector_registry(ROOT / "results/summaries/vector_registry.jsonl", run_id, vector_entries)
    card = result_card(run_id, config, model_config, axes, layers, pooling_modes, rows, metrics, local_artifact_dir)
    write_json(ROOT / f"results/cards/{run_id}.json", card)
    write_markdown_card(ROOT / f"results/cards/{run_id}.md", card)
    return card


def run_id_for(model_config: dict) -> str:
    if model_config.get("role") == "main":
        return "representation_atlas_main_qwen3_4b_v0_1"
    return "representation_atlas_regression_qwen2_5_1_5b_v0_1"


def build_direction(rows: list[dict], activations: dict, layer: int, pooling: str, method: str) -> torch.Tensor:
    train_rows = [row for row in rows if row["split"] == "train"]
    pos = [row for row in train_rows if row["positive_negative_pair_role"] == "positive"]
    neg = [row for row in train_rows if row["positive_negative_pair_role"] == "negative"]
    if method == "difference_of_means":
        pos_mean = torch.stack([activations[row["sample_id"]][(layer, pooling)] for row in pos]).mean(dim=0)
        neg_mean = torch.stack([activations[row["sample_id"]][(layer, pooling)] for row in neg]).mean(dim=0)
        return l2_normalize(pos_mean - neg_mean)
    if method == "direct_contrast_axis":
        by_pair = defaultdict(dict)
        for row in train_rows:
            by_pair[row["pair_id"]][row["positive_negative_pair_role"]] = row
        diffs = []
        for pair in by_pair.values():
            diffs.append(
                activations[pair["positive"]["sample_id"]][(layer, pooling)]
                - activations[pair["negative"]["sample_id"]][(layer, pooling)]
            )
        return l2_normalize(torch.stack(diffs).mean(dim=0))
    raise ValueError(f"unsupported vector method: {method}")


def score_axis(rows: list[dict], activations: dict, direction: torch.Tensor, layer: int, pooling: str) -> dict:
    result = {}
    train_scores = projections([row for row in rows if row["split"] == "train"], activations, direction, layer, pooling)
    threshold = (mean([score for _, role, score in train_scores if role == "positive"]) + mean([score for _, role, score in train_scores if role == "negative"])) / 2
    for split in ("train", "dev", "test"):
        split_rows = [row for row in rows if row["split"] == split]
        scores = projections(split_rows, activations, direction, layer, pooling)
        pos_scores = [score for _, role, score in scores if role == "positive"]
        neg_scores = [score for _, role, score in scores if role == "negative"]
        pairs = defaultdict(dict)
        for pair_id, role, score in scores:
            pairs[pair_id][role] = score
        pair_correct = sum(1 for pair in pairs.values() if pair.get("positive", -math.inf) > pair.get("negative", math.inf))
        sample_correct = sum(
            1 for _, role, score in scores
            if (score >= threshold and role == "positive") or (score < threshold and role == "negative")
        )
        result[split] = {
            "samples": len(split_rows),
            "pairs": len(pairs),
            "positive_mean_projection": mean(pos_scores),
            "negative_mean_projection": mean(neg_scores),
            "separability_margin": mean(pos_scores) - mean(neg_scores),
            "pairwise_contrast_accuracy": pair_correct / len(pairs) if pairs else None,
            "threshold_accuracy": sample_correct / len(scores) if scores else None,
            "direction_consistency": mean(pos_scores) > mean(neg_scores),
        }
    return result


def projections(rows: list[dict], activations: dict, direction: torch.Tensor, layer: int, pooling: str) -> list[tuple[str, str, float]]:
    return [
        (
            row["pair_id"],
            row["positive_negative_pair_role"],
            float(torch.dot(activations[row["sample_id"]][(layer, pooling)], direction).item()),
        )
        for row in rows
    ]


def mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def write_vector_registry(path: Path, run_id: str, entries: list[dict]) -> None:
    existing = []
    if path.exists():
        existing = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [entry for entry in existing if entry.get("run_id") != run_id]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in kept + entries:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def result_card(run_id: str, config: dict, model_config: dict, axes: list[str], layers: list[int], pooling_modes: list[str], rows: list[dict], metrics: dict, local_artifact_dir: Path) -> dict:
    split_counts = Counter(row["split"] for row in rows)
    return {
        "run_id": run_id,
        "experiment_id": config["experiment_id"],
        "git_commit": git_commit(),
        "model_id": model_config["model_id"],
        "model_role": model_config["role"],
        "dataset_version": config["dataset_version"],
        "axis_ids": axes,
        "layers": layers,
        "pooling": pooling_modes,
        "vector_methods": config["vector_methods"],
        "sample_count": len(rows),
        "split_used": dict(split_counts),
        "metrics": metrics,
        "confidence_intervals": None,
        "artifacts": {
            "local_vector_tensor": str((local_artifact_dir / "vectors.pt").relative_to(ROOT)),
            "tracked_vector_registry": "results/summaries/vector_registry.jsonl",
        },
        "limitations": limitations_for(model_config),
        "failure_cases": failure_cases(metrics),
        "created_at": now(),
        "reproducibility_metadata": {
            "config": config["experiment_id"],
            "local_files_only": True,
            "cache_dir": str(DEFAULT_CACHE_DIR),
        },
    }


def failure_cases(metrics: dict) -> list[dict]:
    failures = []
    for key, split_metrics in metrics.items():
        for split, values in split_metrics.items():
            if values["pairwise_contrast_accuracy"] is not None and values["pairwise_contrast_accuracy"] < 1.0:
                failures.append({"metric_key": key, "split": split, "pairwise_contrast_accuracy": values["pairwise_contrast_accuracy"]})
    return failures[:20]


def limitations_for(model_config: dict) -> list[str]:
    if model_config.get("role") == "main":
        return [
            "First Qwen3-4B main-model Representation Atlas evidence on curated seed data.",
            "No activation steering or post-training claim is made from this run.",
            "No probe training or bootstrap confidence intervals in this Batch 4 runner.",
            "Curated seed data is not yet an independently human-reviewed benchmark.",
            "Hidden states are not tracked; only vector metadata and metrics are tracked.",
        ]
    return [
        "Regression validation only; Qwen2.5-1.5B is not the main research model.",
        "No probe training or bootstrap confidence intervals in this runner.",
        "Hidden states are not tracked; only vector metadata and metrics are tracked.",
    ]


def write_markdown_card(path: Path, card: dict) -> None:
    best = summarize_metrics(card["metrics"])
    title = "Representation Atlas Main Result Card" if card["model_role"] == "main" else "Representation Atlas Regression Result Card"
    lines = [
        f"# {title}",
        "",
        f"- run_id: `{card['run_id']}`",
        f"- experiment_id: `{card['experiment_id']}`",
        f"- model: `{card['model_id']}` (`{card['model_role']}`)",
        f"- dataset: `{card['dataset_version']}`",
        f"- axes: `{', '.join(card['axis_ids'])}`",
        f"- layers: `{card['layers']}`",
        f"- pooling: `{card['pooling']}`",
        f"- sample count: {card['sample_count']}",
        f"- split used: `{json.dumps(card['split_used'], sort_keys=True)}`",
        f"- best test pairwise contrast accuracy: {best}",
        f"- local vector artifact: `{card['artifacts']['local_vector_tensor']}`",
        f"- vector registry: `{card['artifacts']['tracked_vector_registry']}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in card["limitations"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_metrics(metrics: dict) -> float:
    vals = [m["test"]["pairwise_contrast_accuracy"] for m in metrics.values() if m.get("test")]
    return max(vals) if vals else 0.0


def readiness_check(model_config_path: Path, args: argparse.Namespace) -> dict:
    model_config = read_yaml(model_config_path)
    model_id = model_config["model_id"]
    cache_dir = DEFAULT_CACHE_DIR
    before = model_cache_path(model_id, cache_dir).exists()
    downloaded = False
    errors = []
    snapshot_path = None
    tokenizer_result = "not_attempted"
    config_result = "not_attempted"
    model_load_result = "not_attempted"
    gpu_before = gpu_snapshot()

    try:
        if args.allow_download and not before:
            snapshot_path = snapshot_download(model_id, cache_dir=str(cache_dir), local_files_only=False)
            downloaded = True
        elif before:
            snapshot_path = str(model_cache_path(model_id, cache_dir))
    except Exception as exc:
        errors.append(f"download failed: {exc}")

    try:
        AutoConfig.from_pretrained(model_id, cache_dir=str(cache_dir), local_files_only=not args.allow_download)
        config_result = "pass"
    except Exception as exc:
        config_result = f"fail: {exc}"
        errors.append(config_result)

    try:
        load_tokenizer(model_id, cache_dir=str(cache_dir), local_files_only=not args.allow_download)
        tokenizer_result = "pass"
    except Exception as exc:
        tokenizer_result = f"fail: {exc}"
        errors.append(tokenizer_result)

    if args.attempt_model_load:
        try:
            load_model_and_tokenizer(model_id, cache_dir=str(cache_dir), local_files_only=not args.allow_download)
            model_load_result = "pass"
        except Exception as exc:
            model_load_result = f"fail: {exc}"
            errors.append(model_load_result)

    size_gb = dir_size_gb(model_cache_path(model_id, cache_dir)) if model_cache_path(model_id, cache_dir).exists() else None
    conclusion = "ready for Batch 4" if not errors and tokenizer_result == "pass" and config_result == "pass" else "not ready"
    if not errors and model_load_result == "not_attempted":
        conclusion = "partially ready"
    gpu_after = gpu_snapshot()
    report = {
        "model_id": model_id,
        "local_availability_before_check": before,
        "downloaded": downloaded,
        "cache_path": str(model_cache_path(model_id, cache_dir)),
        "snapshot_path": snapshot_path,
        "cache_size_gb_estimate": size_gb,
        "tokenizer_load_result": tokenizer_result,
        "model_config_load_result": config_result,
        "full_model_load_result": model_load_result,
        "dtype_quantization_attempted": "fp16 with device_map auto" if args.attempt_model_load else "config/tokenizer only",
        "gpu_before": gpu_before,
        "gpu_after": gpu_after,
        "torch_cuda_available": torch.cuda.is_available(),
        "conclusion": conclusion,
        "errors": errors,
        "created_at": now(),
    }
    readiness_json = ROOT / "results/cards/qwen3_4b_gpu_readiness_report.json"
    write_json(readiness_json, report)
    write_readiness_markdown(ROOT / "results/cards/qwen3_4b_gpu_readiness_report.md", report)
    return report


def gpu_snapshot() -> dict:
    if not torch.cuda.is_available():
        return {"cuda_available": False}
    free, total = torch.cuda.mem_get_info()
    return {
        "cuda_available": True,
        "device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0),
        "memory_free_mib": round(free / 1024 / 1024, 1),
        "memory_total_mib": round(total / 1024 / 1024, 1),
        "memory_allocated_mib": round(torch.cuda.memory_allocated() / 1024 / 1024, 1),
        "memory_reserved_mib": round(torch.cuda.memory_reserved() / 1024 / 1024, 1),
    }


def write_readiness_markdown(path: Path, report: dict) -> None:
    lines = [
        "# Qwen3-4B GPU Readiness Report",
        "",
        f"- model_id: `{report['model_id']}`",
        f"- local availability before check: {report['local_availability_before_check']}",
        f"- downloaded: {report['downloaded']}",
        f"- cache path: `{report['cache_path']}`",
        f"- cache size GB: {report['cache_size_gb_estimate']}",
        f"- tokenizer load: `{report['tokenizer_load_result']}`",
        f"- config load: `{report['model_config_load_result']}`",
        f"- full model load: `{report['full_model_load_result']}`",
        f"- dtype/device map: `{report['dtype_quantization_attempted']}`",
        f"- GPU before: `{json.dumps(report['gpu_before'], sort_keys=True)}`",
        f"- GPU after: `{json.dumps(report['gpu_after'], sort_keys=True)}`",
        f"- conclusion: `{report['conclusion']}`",
        "",
        "## Errors",
        "",
    ]
    lines.extend([f"- {error}" for error in report["errors"]] or ["- none"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dir_size_gb(path: Path) -> float:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return round(total / (1024 ** 3), 3)


def git_commit() -> str:
    import subprocess

    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--split")
    parser.add_argument("--axes")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--output-dir")
    parser.add_argument("--readiness-check", action="store_true")
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--attempt-model-load", action="store_true")
    args = parser.parse_args()

    if args.readiness_check:
        report = readiness_check(ROOT / args.model_config, args)
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if report["conclusion"] in {"ready for Batch 4", "partially ready"} else 1

    if not args.config:
        parser.error("--config is required unless --readiness-check is used")
    if args.dry_run:
        result = dry_run(ROOT / args.config, args)
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if result["passed"] else 1
    result = run_atlas(ROOT / args.config, args)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
