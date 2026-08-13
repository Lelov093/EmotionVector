from __future__ import annotations

from collections import defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable


REVIEW_DECISIONS = {"accept", "reject", "ambiguous", "needs_rewrite"}
PKU_BEHAVIORS = {
    "reasonable_accept",
    "reasonable_refusal",
    "clarification",
    "alternative",
    "unsafe_compliance",
    "over_refusal",
    "other",
}


def stable_digest(*parts: object) -> str:
    payload = "\u241f".join(str(part) for part in parts)
    return sha256(payload.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            # ensure_ascii prevents Unicode line separators inside source text
            # from becoming ambiguous record boundaries in review artifacts.
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            yield line_number, payload


def _rank(seed: int, sample_key: str) -> str:
    return stable_digest(seed, sample_key)


def build_empathetic_candidates(
    split_paths: dict[str, Path], seed: int, per_context: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    transitions_by_context: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_split, path in sorted(split_paths.items()):
        conversations: dict[str, list[dict[str, str]]] = defaultdict(list)
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                conversations[row["conv_id"]].append(row)
        for conv_id, turns in conversations.items():
            ordered = sorted(turns, key=lambda row: int(row["utterance_idx"]))
            if len(ordered) < 2:
                continue
            previous, response = ordered[0], ordered[1]
            context = response["context"].strip().casefold()
            source_key = f"{source_split}:{conv_id}:{response['utterance_idx']}"
            transitions_by_context[context].append(
                {
                    "source_split": source_split,
                    "conv_id": conv_id,
                    "response_utterance_idx": int(response["utterance_idx"]),
                    "context": context,
                    "situation_prompt": response["prompt"],
                    "user_utterance": previous["utterance"],
                    "candidate_response": response["utterance"],
                    "source_key": source_key,
                }
            )

    selected: list[dict[str, Any]] = []
    for context, candidates in sorted(transitions_by_context.items()):
        ranked = sorted(candidates, key=lambda row: _rank(seed, row["source_key"]))
        selected.extend(ranked[:per_context])

    review_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for source in sorted(selected, key=lambda row: (row["context"], _rank(seed, row["source_key"]))):
        content_hash = stable_digest(
            source["situation_prompt"], source["user_utterance"], source["candidate_response"]
        )
        sample_id = f"edmap_{content_hash[:16]}"
        proposed = {
            "source_family_id": "empathetic_dialogues_d8b80665",
            "task_family_id": "empathetic_response",
            "scenario_family_id": f"emotion_context_{source['context'].replace(' ', '_')}_pending_human",
            "prompt_template_id": "natural_dialogue_unknown_pending_human",
            "semantic_cluster_id": f"pending_human_{sample_id}",
            "assignment_status": "machine_proposed_pending_human",
        }
        review_rows.append(
            {
                "record_type": "public_mapping_review",
                "dataset_id": "empathetic_dialogues",
                "sample_id": sample_id,
                "source_locator": {
                    "source_split": source["source_split"],
                    "conv_id": source["conv_id"],
                    "response_utterance_idx": source["response_utterance_idx"],
                },
                "source_context_label": source["context"],
                "situation_prompt": source["situation_prompt"],
                "user_utterance": source["user_utterance"],
                "candidate_response": source["candidate_response"],
                "content_sha256": content_hash,
                "candidate_trait_axes": ["empathetic-detached", "warm-cold", "supportive-critical"],
                "proposed_family_assignment": proposed,
                "human_review": {
                    "mapping_decision": None,
                    "primary_trait_axis": None,
                    "trait_pole": None,
                    "task_family_id": None,
                    "scenario_family_id": None,
                    "prompt_template_id": None,
                    "semantic_cluster_id": None,
                    "quality_flags": [],
                    "notes": "",
                },
            }
        )
        manifest_rows.append(
            {
                "sample_id": sample_id,
                "source_locator": review_rows[-1]["source_locator"],
                "source_context_label": source["context"],
                "content_sha256": content_hash,
                "candidate_trait_axes": review_rows[-1]["candidate_trait_axes"],
                "proposed_family_assignment": proposed,
                "human_review_status": "pending",
            }
        )
    summary = {
        "candidate_count": len(review_rows),
        "context_count": len({row["source_context_label"] for row in review_rows}),
        "per_context_target": per_context,
        "source_split_counts": _count_nested(review_rows, "source_locator", "source_split"),
    }
    return review_rows, manifest_rows, summary


def build_pku_candidates(
    model_paths: dict[str, Path], seed: int, mixed_per_model: int, both_safe_per_model: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    available: dict[str, dict[str, int]] = {}
    for model_family, path in sorted(model_paths.items()):
        strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line_number, row in iter_jsonl(path):
            safe0 = bool(row["is_response_0_safe"])
            safe1 = bool(row["is_response_1_safe"])
            if safe0 != safe1:
                stratum = "mixed_safety"
            elif safe0 and safe1:
                stratum = "both_safe"
            else:
                stratum = "both_unsafe"
            row = dict(row)
            row["_line_number"] = line_number
            row["_model_family"] = model_family
            row["_stratum"] = stratum
            strata[stratum].append(row)
        available[model_family] = {key: len(value) for key, value in sorted(strata.items())}
        for stratum, limit in (("mixed_safety", mixed_per_model), ("both_safe", both_safe_per_model)):
            ranked = sorted(
                strata[stratum],
                key=lambda row: _rank(
                    seed,
                    f"{model_family}:{row['_line_number']}:{row.get('response_0_sha256')}:{row.get('response_1_sha256')}",
                ),
            )
            if len(ranked) < limit:
                raise ValueError(f"{model_family}/{stratum} has {len(ranked)} rows, requires {limit}")
            selected.extend(ranked[:limit])

    review_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for source in sorted(selected, key=lambda row: (row["_model_family"], row["_stratum"], row["_line_number"])):
        content_hash = stable_digest(source["prompt"], source["response_0"], source["response_1"])
        sample_id = f"pkumap_{content_hash[:16]}"
        proposed = {
            "source_family_id": f"pku_safe_rlhf_f4b036fc_{source['_model_family'].casefold().replace('-', '_')}",
            "task_family_id": "safety_helpfulness_preference",
            "scenario_family_id": f"safety_scenario_unknown_pending_human_{sample_id}",
            "prompt_template_id": "source_prompt_unknown_pending_human",
            "semantic_cluster_id": f"pending_human_{sample_id}",
            "assignment_status": "machine_proposed_pending_human",
        }
        source_locator = {
            "model_family": source["_model_family"],
            "source_split": "train",
            "lf_record_number": source["_line_number"],
        }
        review_rows.append(
            {
                "record_type": "public_mapping_review",
                "dataset_id": "pku_safe_rlhf",
                "sample_id": sample_id,
                "content_warning": "Safety research source may contain harmful requests or responses; do not redistribute raw text.",
                "source_locator": source_locator,
                "prompt": source["prompt"],
                "response_0": source["response_0"],
                "response_1": source["response_1"],
                "source_labels": {
                    "is_response_0_safe": source["is_response_0_safe"],
                    "is_response_1_safe": source["is_response_1_safe"],
                    "better_response_id": source["better_response_id"],
                    "safer_response_id": source["safer_response_id"],
                    "sampling_stratum": source["_stratum"],
                },
                "content_sha256": content_hash,
                "candidate_trait_axes": [
                    "boundary-preserving-over-accommodating",
                    "assertive-compliant",
                    "cautious-impulsive",
                ],
                "proposed_family_assignment": proposed,
                "human_review": {
                    "mapping_decision": None,
                    "primary_trait_axis": None,
                    "response_0_behavior": None,
                    "response_1_behavior": None,
                    "task_family_id": None,
                    "scenario_family_id": None,
                    "prompt_template_id": None,
                    "semantic_cluster_id": None,
                    "quality_flags": [],
                    "notes": "",
                },
            }
        )
        manifest_rows.append(
            {
                "sample_id": sample_id,
                "source_locator": source_locator,
                "source_label_summary": review_rows[-1]["source_labels"],
                "response_sha256": [source.get("response_0_sha256"), source.get("response_1_sha256")],
                "content_sha256": content_hash,
                "candidate_trait_axes": review_rows[-1]["candidate_trait_axes"],
                "proposed_family_assignment": proposed,
                "human_review_status": "pending",
            }
        )
    summary = {
        "candidate_count": len(review_rows),
        "selected_stratum_counts": _count_nested(review_rows, "source_labels", "sampling_stratum"),
        "selected_model_family_counts": _count_nested(review_rows, "source_locator", "model_family"),
        "available_source_strata": available,
        "excluded_from_pilot": ["both_unsafe"],
    }
    return review_rows, manifest_rows, summary


def _count_nested(rows: list[dict[str, Any]], parent: str, field: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row[parent][field])] += 1
    return dict(sorted(counts.items()))


def validate_completed_review(rows: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            errors.append(f"row {index}: missing sample_id")
            continue
        if sample_id in seen:
            errors.append(f"{sample_id}: duplicate sample_id")
        seen.add(sample_id)
        review = row.get("human_review")
        if not isinstance(review, dict):
            errors.append(f"{sample_id}: missing human_review")
            continue
        if review.get("mapping_decision") not in REVIEW_DECISIONS:
            errors.append(f"{sample_id}: invalid or missing mapping_decision")
        if row.get("dataset_id") == "pku_safe_rlhf":
            for field in ("response_0_behavior", "response_1_behavior"):
                if review.get(field) not in PKU_BEHAVIORS:
                    errors.append(f"{sample_id}: invalid or missing {field}")
        if review.get("mapping_decision") == "accept":
            for field in (
                "primary_trait_axis",
                "task_family_id",
                "scenario_family_id",
                "prompt_template_id",
                "semantic_cluster_id",
            ):
                if not review.get(field):
                    errors.append(f"{sample_id}: accepted mapping missing {field}")
    return errors
