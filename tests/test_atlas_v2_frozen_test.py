from __future__ import annotations

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from research_foundation.atlas_v2_adapter import load_activation_artifact
from research_foundation.atlas_v2_extraction import (
    FrozenTextRow,
    load_test_runtime_config,
    resolve_frozen_text_rows,
    write_test_activation_artifact,
)
from research_foundation.representation_freeze import content_sha256


ROOT = Path(__file__).resolve().parents[1]


class AtlasV2FrozenTestTests(unittest.TestCase):
    def test_tracked_frozen_result_preserves_pilot_and_causal_boundaries(self) -> None:
        result = json.loads(
            (ROOT / "results/summaries/atlas_v2_frozen_test_result_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        axis = result["axis_results"][0]
        self.assertEqual(axis["status"], "exploratory")
        self.assertEqual(axis["pair_count"], 7)
        self.assertEqual(axis["permutation"]["p_value"], 0.5)
        self.assertEqual(len(axis["null_distributions"]), 2)
        self.assertEqual(len(axis["controls"]), 4)
        self.assertEqual(len(axis["probes"]), 3)
        self.assertEqual(result["evidence_type"], "representation_evidence_only")
        serialized = json.dumps(result).lower()
        self.assertNotIn('"prompt"', serialized)
        self.assertNotIn('"response"', serialized)

    def test_runtime_is_fixed_to_single_selected_test_specification(self) -> None:
        runtime = load_test_runtime_config(ROOT)
        self.assertEqual(runtime["execution"]["allowed_splits"], ["test"])
        self.assertEqual(runtime["execution"]["test_openings"], 1)
        self.assertEqual(
            runtime["representation_specification"],
            {
                "layer": 24,
                "pooling": "last_response_token",
                "dimension": 2560,
                "array_dtype": "float32",
            },
        )

    def test_explicit_test_resolution_uses_only_test_rows(self) -> None:
        manifest = {
            "records": [
                {
                    "pair_id": "reprpair_" + "a" * 20,
                    "source_sample_id": "test_sample",
                    "axis_id": "boundary-preserving-over-accommodating",
                    "split": "test",
                    "prompt_sha256": content_sha256("prompt"),
                    "responses": [
                        {"sample_id": "s0", "response_id": "response_0", "pole": "boundary-preserving", "content_sha256": content_sha256("positive")},
                        {"sample_id": "s1", "response_id": "response_1", "pole": "over-accommodating", "content_sha256": content_sha256("negative")}
                    ]
                }
            ]
        }
        review = {
            "sample_id": "test_sample", "prompt": "prompt", "response_0": "positive", "response_1": "negative",
            "human_review": {"response_annotations": [
                {"response_id": "response_0", "trait_annotation": {"axis_id": "boundary-preserving-over-accommodating", "pole": "boundary-preserving"}},
                {"response_id": "response_1", "trait_annotation": {"axis_id": "boundary-preserving-over-accommodating", "pole": "over-accommodating"}}
            ]}
        }
        rows = resolve_frozen_text_rows(manifest, [review], allowed_splits=("test",))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.split for row in rows}, {"test"})

    def test_writer_creates_non_overwritable_test_only_artifact(self) -> None:
        manifest = json.loads((ROOT / "data/research_foundation/manifests/representation_family_split_v2_1.json").read_text(encoding="utf-8"))
        rows = [
            FrozenTextRow(response["sample_id"], pair["pair_id"], "test", response["pole"], "not persisted", "not persisted")
            for pair in manifest["records"] if pair["split"] == "test"
            for response in pair["responses"]
        ]
        runtime = load_test_runtime_config(ROOT)
        event = {
            "planned_test_activation_path": runtime["artifact_policy"]["array_path"],
            "model": {
                "model_id": runtime["model"]["model_id"], "revision": runtime["model"]["revision"],
                "dtype": runtime["model"]["load_dtype"], "quantization": runtime["model"]["quantization"]
            }
        }
        with TemporaryDirectory() as directory:
            temp_root = Path(directory)
            for relative in (
                "data/research_foundation/schemas/atlas_v2_activation_artifact_v0_1.schema.json",
                "configs/research/representation_atlas_v2_analysis_plan_v0_1.json",
            ):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            matrix = np.zeros((14, 2560), dtype=np.float32)
            metadata_path = write_test_activation_artifact(temp_root, rows, manifest, runtime, event, matrix)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["splits"], ["test"])
            self.assertNotIn("not persisted", json.dumps(metadata))
            with self.assertRaises(FileExistsError):
                write_test_activation_artifact(temp_root, rows, manifest, runtime, event, matrix)


if __name__ == "__main__":
    unittest.main()
