from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import jsonschema
import numpy as np

from research_foundation.atlas_v2_adapter import (
    ANALYSIS_PLAN_PATH,
    DATASET_MANIFEST_PATH,
    REQUIRED_CONTROL_IDS,
    RUNTIME_CONFIG_PATH,
    build_test_access_event,
    build_train_dev_evidence,
    create_selection_lock,
    file_sha256,
    load_activation_artifact,
)
from research_foundation.representation_freeze import canonical_content_sha256


ROOT = Path(__file__).resolve().parents[1]


def make_artifact(directory: Path, splits: tuple[str, ...]) -> tuple[Path, dict]:
    manifest = json.loads((ROOT / DATASET_MANIFEST_PATH).read_text(encoding="utf-8"))
    plan = json.loads((ROOT / ANALYSIS_PLAN_PATH).read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / RUNTIME_CONFIG_PATH).read_text(encoding="utf-8"))
    rng = np.random.default_rng(20260804 + len(splits))
    records = []
    vectors = []
    for pair in manifest["records"]:
        if pair["split"] not in splits:
            continue
        for response in pair["responses"]:
            vector = rng.normal(scale=0.12, size=6)
            vector[0] += 2.0 if response["pole"] == "boundary-preserving" else -2.0
            records.append(
                {
                    "sample_id": response["sample_id"],
                    "pair_id": pair["pair_id"],
                    "split": pair["split"],
                    "pole": response["pole"],
                    "row_index": len(records),
                }
            )
            vectors.append(vector)
    array_path = directory / ("_".join(splits) + ".npz")
    np.savez_compressed(array_path, embeddings=np.asarray(vectors, dtype=np.float32))
    relative_array_path = array_path.resolve().relative_to(ROOT.resolve()).as_posix()
    metadata = {
        "artifact_version": "atlas_v2_activation_artifact_v0_1",
        "created_at": "2026-08-04T12:00:00+08:00",
        "dataset": {
            "manifest_path": DATASET_MANIFEST_PATH,
            "manifest_sha256": canonical_content_sha256(manifest),
        },
        "analysis_plan": {
            "path": ANALYSIS_PLAN_PATH,
            "sha256": canonical_content_sha256(plan),
        },
        "runtime_config": {
            "path": RUNTIME_CONFIG_PATH,
            "sha256": canonical_content_sha256(runtime),
        },
        "model": {
            "model_id": "synthetic/no-model",
            "revision": "synthetic-v0",
            "dtype": "float32",
            "quantization": None,
        },
        "representation_spec": {
            "layer": 3,
            "pooling": "last_non_padding_token",
            "dimension": 6,
            "array_dtype": "float32",
        },
        "splits": list(splits),
        "records": records,
        "array_artifact": {
            "path": relative_array_path,
            "sha256": file_sha256(array_path),
            "format": "npz",
            "embedding_key": "embeddings",
        },
        "claim_boundary": "Synthetic arrays only; no model or representation evidence.",
    }
    metadata_path = directory / ("_".join(splits) + ".metadata.json")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path, metadata


class AtlasV2AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        local_root = ROOT / "results/local_artifacts"
        local_root.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(dir=local_root)
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_train_dev_artifact_has_exact_frozen_coverage_and_no_raw_text(self) -> None:
        metadata_path, metadata = make_artifact(self.directory, ("train", "dev"))
        artifact = load_activation_artifact(
            ROOT, metadata_path, allowed_splits={"train", "dev"}
        )
        self.assertEqual(artifact.embeddings.shape, (38, 6))
        forbidden_keys = {"prompt", "response_text", "output_text", "raw_text"}

        def assert_no_raw_text_keys(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(forbidden_keys & set(value))
                for nested in value.values():
                    assert_no_raw_text_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_no_raw_text_keys(nested)

        assert_no_raw_text_keys(metadata)

    def test_rejects_unauthorized_test_and_incomplete_coverage(self) -> None:
        test_path, _ = make_artifact(self.directory, ("test",))
        with self.assertRaisesRegex(ValueError, "unauthorized splits"):
            load_activation_artifact(ROOT, test_path, allowed_splits={"train", "dev"})
        metadata_path, metadata = make_artifact(self.directory, ("train", "dev"))
        metadata["records"].pop()
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "shape does not match"):
            load_activation_artifact(ROOT, metadata_path, allowed_splits={"train", "dev"})

    def test_train_dev_evidence_recovers_synthetic_signal_without_test(self) -> None:
        metadata_path, _ = make_artifact(self.directory, ("train", "dev"))
        artifact = load_activation_artifact(
            ROOT, metadata_path, allowed_splits={"train", "dev"}
        )
        evidence = build_train_dev_evidence(
            artifact,
            seed=47,
            bootstrap_iterations=200,
            permutation_iterations=200,
        )
        self.assertFalse(evidence["test_opened"])
        self.assertGreater(evidence["direction_equivalence_cosine"], 1.0 - 1e-12)
        self.assertGreater(evidence["dev_analysis"]["auroc"], 0.95)
        self.assertEqual(len(evidence["null_distributions"]["random_isotropic_direction"]), 20)
        self.assertEqual(len(evidence["null_distributions"]["shuffled_label_direction"]), 20)
        self.assertEqual(
            evidence["null_comparisons"]["random_isotropic_auroc"]["null_count"], 20
        )
        self.assertLess(
            evidence["available_controls"]["sign_flipped_target_direction"]["auroc"],
            0.05,
        )
        self.assertIn(
            "orthogonalized_target_direction",
            evidence["required_external_controls_not_fabricated"],
        )

    def test_selection_lock_requires_complete_controls(self) -> None:
        metadata_path, _ = make_artifact(self.directory, ("train", "dev"))
        artifact = load_activation_artifact(
            ROOT, metadata_path, allowed_splits={"train", "dev"}
        )
        with self.assertRaisesRegex(ValueError, "complete frozen control registry"):
            create_selection_lock(
                ROOT,
                artifact,
                activation_metadata_relative_path="results/local_artifacts/train_dev.metadata.json",
                candidate_results_sha256="a" * 64,
                control_plan_path="configs/research/representation_atlas_v2_control_plan_v0_1.json",
                control_plan_sha256="c" * 64,
                control_results_path="results/local_artifacts/control_results.json",
                control_results_sha256="d" * 64,
                selected_threshold=0.0,
                probe_regularization_c=1.0,
                completed_control_ids=REQUIRED_CONTROL_IDS[:-1],
                locked_at="2026-08-04T12:30:00+08:00",
            )
        lock = create_selection_lock(
            ROOT,
            artifact,
            activation_metadata_relative_path="results/local_artifacts/train_dev.metadata.json",
            candidate_results_sha256="a" * 64,
            control_plan_path="configs/research/representation_atlas_v2_control_plan_v0_1.json",
            control_plan_sha256="c" * 64,
            control_results_path="results/local_artifacts/control_results.json",
            control_results_sha256="d" * 64,
            selected_threshold=0.0,
            probe_regularization_c=1.0,
            completed_control_ids=REQUIRED_CONTROL_IDS,
            locked_at="2026-08-04T12:30:00+08:00",
        )
        self.assertEqual(lock["test_opening_status"], "locked_not_opened")

    def test_test_access_is_single_and_binds_future_artifact(self) -> None:
        train_path, _ = make_artifact(self.directory, ("train", "dev"))
        artifact = load_activation_artifact(
            ROOT, train_path, allowed_splits={"train", "dev"}
        )
        lock = create_selection_lock(
            ROOT,
            artifact,
            activation_metadata_relative_path="results/local_artifacts/train_dev.metadata.json",
            candidate_results_sha256="b" * 64,
            control_plan_path="configs/research/representation_atlas_v2_control_plan_v0_1.json",
            control_plan_sha256="c" * 64,
            control_results_path="results/local_artifacts/control_results.json",
            control_results_sha256="d" * 64,
            selected_threshold=0.0,
            probe_regularization_c=1.0,
            completed_control_ids=REQUIRED_CONTROL_IDS,
            locked_at="2026-08-04T12:30:00+08:00",
        )
        test_path, test_metadata = make_artifact(self.directory, ("test",))
        with self.assertRaisesRegex(ValueError, "recorded test-opening event"):
            load_activation_artifact(ROOT, test_path, allowed_splits={"test"})
        event = build_test_access_event(
            ROOT,
            lock,
            selection_lock_path="results/local_artifacts/selection_lock.json",
            planned_test_activation_path=test_metadata["array_artifact"]["path"],
            model=test_metadata["model"],
            representation_spec=test_metadata["representation_spec"],
            prior_events=[],
            opened_at="2026-08-04T13:00:00+08:00",
            operator_id="synthetic-validator",
        )
        loaded = load_activation_artifact(
            ROOT, test_path, allowed_splits={"test"}, test_access_event=event
        )
        self.assertEqual(loaded.embeddings.shape, (14, 6))
        with self.assertRaisesRegex(ValueError, "second opening"):
            build_test_access_event(
                ROOT,
                lock,
                selection_lock_path="results/local_artifacts/selection_lock.json",
                planned_test_activation_path=test_metadata["array_artifact"]["path"],
                model=test_metadata["model"],
                representation_spec=test_metadata["representation_spec"],
                prior_events=[event],
                opened_at="2026-08-04T13:01:00+08:00",
                operator_id="synthetic-validator",
            )
        mismatched_event = deepcopy(event)
        mismatched_event["representation_spec"]["layer"] = 4
        with self.assertRaisesRegex(ValueError, "representation specification mismatch"):
            load_activation_artifact(
                ROOT,
                test_path,
                allowed_splits={"test"},
                test_access_event=mismatched_event,
            )

    def test_test_event_schema_rejects_untracked_path(self) -> None:
        schema = json.loads(
            (ROOT / "data/research_foundation/schemas/atlas_v2_test_access_event_v0_1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "event_version": "atlas_v2_test_access_event_v0_1",
                    "planned_test_activation_path": "outside/test.npz",
                },
                schema,
            )


if __name__ == "__main__":
    unittest.main()
