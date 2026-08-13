# Representation Atlas Main Result Card

- run_id: `representation_atlas_main_qwen3_4b_v0_1`
- experiment_id: `representation_atlas.main_qwen3_4b.phase_b`
- model: `Qwen/Qwen3-4B-Instruct-2507` (`main`)
- dataset: `trait_space_seed_v0_1`
- axes: `calm-agitated, empathetic-detached, assertive-compliant, boundary-preserving-over-accommodating, cautious-impulsive, stable-reactive`
- layers: `[8, 16, 24, 32]`
- pooling: `['last_token', 'mean_all_tokens']`
- sample count: 120
- split used: `{"dev": 24, "test": 24, "train": 72}`
- best test pairwise contrast accuracy: 1.0
- local vector artifact: `results\local_artifacts\representation_atlas\main_qwen3_4b\representation_atlas_main_qwen3_4b_v0_1\vectors.pt`
- vector registry: `results/summaries/vector_registry.jsonl`

## Limitations

- First Qwen3-4B main-model Representation Atlas evidence on curated seed data.
- No activation steering or post-training claim is made from this run.
- No probe training or bootstrap confidence intervals in this Batch 4 runner.
- Curated seed data is not yet an independently human-reviewed benchmark.
- Hidden states are not tracked; only vector metadata and metrics are tracked.
