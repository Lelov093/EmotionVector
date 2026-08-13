# Representation Atlas Regression Result Card

- run_id: `representation_atlas_regression_qwen2_5_1_5b_v0_1`
- experiment_id: `representation_atlas.regression_qwen2_5_1_5b.phase_b`
- model: `Qwen/Qwen2.5-1.5B-Instruct` (`regression`)
- dataset: `trait_space_seed_v0_1`
- axes: `calm-agitated, boundary-preserving-over-accommodating, cautious-impulsive`
- layers: `[8, 16, 24]`
- pooling: `['last_token', 'mean_all_tokens']`
- sample count: 60
- split used: `{"dev": 12, "test": 12, "train": 36}`
- best test pairwise contrast accuracy: 1.0
- local vector artifact: `results\local_artifacts\representation_atlas\regression_qwen2_5_1_5b\representation_atlas_regression_qwen2_5_1_5b_v0_1\vectors.pt`
- vector registry: `results/summaries/vector_registry.jsonl`

## Limitations

- Regression validation only; Qwen2.5-1.5B is not the main research model.
- No probe training or bootstrap confidence intervals in this Batch 3 runner.
- Hidden states are not tracked; only vector metadata and metrics are tracked.
