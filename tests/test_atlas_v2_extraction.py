from __future__ import annotations

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import torch

from research_foundation.atlas_v2_extraction import (
    FrozenTextRow,
    extract_candidate_matrices,
    load_runtime_config,
    load_train_dev_text_rows,
    resolve_frozen_text_rows,
    response_input_ids,
    write_activation_artifacts,
)
from research_foundation.atlas_v2_adapter import load_activation_artifact
from research_foundation.representation_freeze import content_sha256


ROOT = Path(__file__).resolve().parents[1]
LOCAL_REVIEW = ROOT / (
    "results/local_artifacts/research_foundation/public_mapping_pilot_v0_2/"
    "pku_safe_rlhf_mapping_review_v0_2.jsonl"
)


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        self.last_messages = messages
        self.last_template_args = (tokenize, add_generation_prompt)
        return {"input_ids": [10, 11, 12], "attention_mask": [1, 1, 1]}

    def __call__(self, text, *, add_special_tokens):
        self.last_response = text
        self.last_add_special_tokens = add_special_tokens
        return {"input_ids": [20, 21]}


class FakeEmbeddings:
    weight = torch.zeros(1)


class FakeOutputs:
    def __init__(self, hidden_states):
        self.hidden_states = hidden_states


class FakeModel:
    def __init__(self):
        self.call_count = 0

    def eval(self):
        return self

    def get_input_embeddings(self):
        return FakeEmbeddings()

    def __call__(self, *, input_ids, attention_mask, output_hidden_states, use_cache):
        self.call_count += 1
        self.last_input_ids = input_ids
        seq_len = input_ids.shape[1]
        states = []
        for layer in range(4):
            values = torch.arange(seq_len * 3, dtype=torch.float32).reshape(1, seq_len, 3)
            states.append(values + layer * 100)
        return FakeOutputs(tuple(states))


class AtlasV2ExtractionTests(unittest.TestCase):
    def test_runtime_is_frozen_to_one_axis_train_dev_and_small_grid(self) -> None:
        runtime = load_runtime_config(ROOT)
        self.assertEqual(runtime["execution"]["allowed_splits"], ["train", "dev"])
        self.assertEqual(runtime["candidate_specifications"]["layers"], [8, 16, 24, 32])
        self.assertEqual(
            runtime["candidate_specifications"]["pooling"],
            ["last_response_token", "mean_response_tokens"],
        )
        self.assertEqual(runtime["model"]["quantization"], "bitsandbytes_int8")

    def test_resolver_binds_raw_text_to_frozen_hashes_and_excludes_test(self) -> None:
        prompt = "User prompt"
        response_0 = "Boundary response"
        response_1 = "Unsafe response"
        manifest = {
            "records": [
                {
                    "pair_id": "reprpair_" + "a" * 20,
                    "source_sample_id": "sample_1",
                    "axis_id": "boundary-preserving-over-accommodating",
                    "split": "train",
                    "prompt_sha256": content_sha256(prompt),
                    "responses": [
                        {
                            "sample_id": "sample_1__response_0",
                            "response_id": "response_0",
                            "pole": "boundary-preserving",
                            "content_sha256": content_sha256(response_0),
                        },
                        {
                            "sample_id": "sample_1__response_1",
                            "response_id": "response_1",
                            "pole": "over-accommodating",
                            "content_sha256": content_sha256(response_1),
                        },
                    ],
                },
                {
                    "pair_id": "reprpair_" + "b" * 20,
                    "source_sample_id": "test_sample",
                    "axis_id": "boundary-preserving-over-accommodating",
                    "split": "test",
                    "prompt_sha256": "0" * 64,
                    "responses": [],
                },
            ]
        }
        review = {
            "sample_id": "sample_1",
            "prompt": prompt,
            "response_0": response_0,
            "response_1": response_1,
            "human_review": {
                "response_annotations": [
                    {
                        "response_id": "response_0",
                        "trait_annotation": {
                            "axis_id": "boundary-preserving-over-accommodating",
                            "pole": "boundary-preserving",
                        },
                    },
                    {
                        "response_id": "response_1",
                        "trait_annotation": {
                            "axis_id": "boundary-preserving-over-accommodating",
                            "pole": "over-accommodating",
                        },
                    },
                ]
            },
        }
        rows = resolve_frozen_text_rows(manifest, [review])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.split for row in rows}, {"train"})
        review["response_0"] = "modified"
        with self.assertRaisesRegex(ValueError, "response hash mismatch"):
            resolve_frozen_text_rows(manifest, [review])

    def test_response_token_contract_has_no_terminal_special_token_or_truncation(self) -> None:
        tokenizer = FakeTokenizer()
        ids, response_start = response_input_ids(
            tokenizer, "prompt", "response", max_sequence_tokens=5
        )
        self.assertEqual(ids, [10, 11, 12, 20, 21])
        self.assertEqual(response_start, 3)
        self.assertEqual(tokenizer.last_template_args, (True, True))
        self.assertFalse(tokenizer.last_add_special_tokens)
        with self.assertRaisesRegex(ValueError, "truncation is forbidden"):
            response_input_ids(tokenizer, "prompt", "response", max_sequence_tokens=4)

    def test_fake_model_extracts_all_specs_in_one_forward_per_response(self) -> None:
        rows = [
            FrozenTextRow("s1", "p1", "train", "boundary-preserving", "p", "r"),
            FrozenTextRow("s2", "p1", "train", "over-accommodating", "p", "r"),
        ]
        model = FakeModel()
        matrices = extract_candidate_matrices(
            model,
            FakeTokenizer(),
            rows,
            layers=[0, 2],
            pooling_modes=["last_response_token", "mean_response_tokens"],
            max_sequence_tokens=16,
        )
        self.assertEqual(model.call_count, 2)
        self.assertEqual(set(matrices), {(0, "last_response_token"), (0, "mean_response_tokens"), (2, "last_response_token"), (2, "mean_response_tokens")})
        for matrix in matrices.values():
            self.assertEqual(matrix.shape, (2, 3))
            self.assertEqual(matrix.dtype, np.float32)
        self.assertGreater(
            matrices[(0, "last_response_token")][0, 0],
            matrices[(0, "mean_response_tokens")][0, 0],
        )

    def test_writer_emits_adapter_valid_train_dev_artifacts_without_raw_text(self) -> None:
        manifest_path = ROOT / "data/research_foundation/manifests/representation_family_split_v2_1.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = []
        for pair in manifest["records"]:
            if pair["split"] not in {"train", "dev"}:
                continue
            for response in pair["responses"]:
                rows.append(
                    FrozenTextRow(
                        response["sample_id"],
                        pair["pair_id"],
                        pair["split"],
                        response["pole"],
                        "not persisted prompt",
                        "not persisted response",
                    )
                )
        runtime = load_runtime_config(ROOT)
        with TemporaryDirectory() as directory:
            temp_root = Path(directory)
            required = [
                "data/research_foundation/manifests/representation_family_split_v2_1.json",
                "data/research_foundation/schemas/atlas_v2_activation_artifact_v0_1.schema.json",
                "configs/research/representation_atlas_v2_analysis_plan_v0_1.json",
                "configs/research/representation_atlas_v2_runtime_v0_1.json",
            ]
            for relative in required:
                destination = temp_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            matrices = {(8, "last_response_token"): np.zeros((38, 6), dtype=np.float32)}
            paths = write_activation_artifacts(
                temp_root,
                rows,
                manifest,
                runtime,
                matrices,
                created_at="2026-08-04T16:00:00+08:00",
            )
            artifact = load_activation_artifact(
                temp_root, paths[0], allowed_splits={"train", "dev"}
            )
            metadata_text = paths[0].read_text(encoding="utf-8")
        self.assertEqual(artifact.embeddings.shape, (38, 6))
        self.assertNotIn("not persisted", metadata_text)

    @unittest.skipUnless(LOCAL_REVIEW.exists(), "Git-ignored completed PKU review is unavailable")
    def test_local_review_resolves_exactly_38_train_dev_responses(self) -> None:
        rows, _, _ = load_train_dev_text_rows(ROOT, LOCAL_REVIEW)
        self.assertEqual(len(rows), 38)
        self.assertEqual(sum(row.split == "train" for row in rows), 22)
        self.assertEqual(sum(row.split == "dev" for row in rows), 16)
        self.assertNotIn("test", {row.split for row in rows})

    def test_tracked_candidate_summary_reports_all_specs_and_keeps_test_closed(self) -> None:
        path = ROOT / "results/summaries/atlas_v2_train_dev_candidate_summary_v0_1.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(summary["candidate_count"], 8)
        self.assertTrue(summary["all_candidates_reported"])
        self.assertEqual(summary["selection_status"], "blocked_pending_external_controls")
        self.assertFalse(summary["test_opened"])
        self.assertEqual(
            set(summary["missing_controls"]),
            {
                "surface_style_direction",
                "unrelated_trait_direction",
                "orthogonalized_target_direction",
            },
        )
        serialized = json.dumps(summary).lower()
        self.assertNotIn('"prompt"', serialized)
        self.assertNotIn('"response"', serialized)


if __name__ == "__main__":
    unittest.main()
