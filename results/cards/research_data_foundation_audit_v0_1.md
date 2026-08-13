# Research Data Foundation Audit v0.1

## Scope

Existing tracked local data only. No public dataset download, model run, embedding deduplication or human annotation was performed.

## Summary

- datasets audited: 5
- datasets with blockers: 5
- blocker counts: `{"exact_text_leakage_across_splits": 2, "family_or_group_leakage_across_splits": 5, "missing_v2_family_fields": 5, "repeated_template_phrase": 2}`

## Dataset Evidence

### trait_space_seed_v0_1

- path: `data/trait_space/curated/trait_space_seed_v0_1.jsonl`
- SHA-256: `93a32975e3c5f8fb4d2292e946948640bbc6f162ef7eb9d67f882e10cdbabca2`
- rows: 120
- splits: `{"dev": 24, "test": 24, "train": 72}`
- formal use status: `historical_candidate_pool_only`
- duplicate IDs: 0
- v2 family coverage: `{"prompt_template_id": 0.0, "scenario_family_id": 0.0, "semantic_cluster_id": 0.0, "source_family_id": 0.0, "task_family_id": 0.0}`
- cross-split exact text duplicates: `{"text": 0}`
- legacy group leaks: `{"pair_id": 0, "prompt_family": 10, "scenario_id": 0}`
- template phrase rows: `{}`
- semantic duplicate check: `not_run`
- blockers:
  - `missing_v2_family_fields` (direct): `["source_family_id", "task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id"]`
  - `family_or_group_leakage_across_splits` (direct): `{"prompt_family": 10}`

### trait_eval_12axis_v0_1

- path: `data/evaluation/trait_eval_12axis_v0_1.jsonl`
- SHA-256: `1f91046c51839f4a91304871cc235bb83f62e7643ea2442c40a583d971be0cbb`
- rows: 120
- splits: `{"dev": 48, "test": 72}`
- formal use status: `historical_evaluation_candidate_only`
- duplicate IDs: 0
- v2 family coverage: `{"prompt_template_id": 0.0, "scenario_family_id": 0.0, "semantic_cluster_id": 0.0, "source_family_id": 0.0, "task_family_id": 0.0}`
- cross-split exact text duplicates: `{"user_prompt": 0}`
- legacy group leaks: `{"prompt_family": 44, "scenario_id": 0}`
- template phrase rows: `{"Draft the assistant's response": 1, "Write the assistant response": 3}`
- semantic duplicate check: `not_run`
- blockers:
  - `missing_v2_family_fields` (direct): `["source_family_id", "task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id"]`
  - `family_or_group_leakage_across_splits` (direct): `{"prompt_family": 44}`
  - `repeated_template_phrase` (direct): `{"Write the assistant response": 3}`

### boundary_preserving_sft_v0_1

- path: `data/post_training/boundary_preserving_sft_v0_1.jsonl`
- SHA-256: `422f75796f66f9af512b45144cf8c8c9c9ebb95b00fecf0b5c5296f1bff5c363`
- rows: 10
- splits: `{"dev": 2, "test": 2, "train": 6}`
- formal use status: `retired_from_formal_training`
- duplicate IDs: 0
- v2 family coverage: `{"prompt_template_id": 0.0, "scenario_family_id": 0.0, "semantic_cluster_id": 0.0, "source_family_id": 0.0, "task_family_id": 0.0}`
- cross-split exact text duplicates: `{"instruction": 1, "response": 0, "user_prompt": 0}`
- legacy group leaks: `{"pair_id": 0, "prompt_family": 2, "scenario_id": 0}`
- template phrase rows: `{"Respond in a boundary-preserving way": 0}`
- semantic duplicate check: `not_run`
- blockers:
  - `missing_v2_family_fields` (direct): `["source_family_id", "task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id"]`
  - `exact_text_leakage_across_splits` (direct): `{"instruction": 1}`
  - `family_or_group_leakage_across_splits` (direct): `{"prompt_family": 2}`

### boundary_preserving_sft_v0_2

- path: `data/post_training/boundary_preserving_sft_v0_2.jsonl`
- SHA-256: `c7ff360c559da5ca119b9d3de50cb4c341ec10f0b5e0ffecc86cc0c102e29c01`
- rows: 84
- splits: `{"dev": 12, "test": 12, "train": 60}`
- formal use status: `retired_from_formal_training`
- duplicate IDs: 0
- v2 family coverage: `{"prompt_template_id": 0.0, "scenario_family_id": 0.0, "semantic_cluster_id": 0.0, "source_family_id": 0.0, "task_family_id": 0.0}`
- cross-split exact text duplicates: `{"instruction": 1, "response": 0, "user_prompt": 24}`
- legacy group leaks: `{"pair_id": 0, "prompt_family": 8, "scenario_id": 0}`
- template phrase rows: `{"If you want, I can help": 84, "Respond in a boundary-preserving way": 84, "The request asks me to": 84}`
- semantic duplicate check: `not_run`
- blockers:
  - `missing_v2_family_fields` (direct): `["source_family_id", "task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id"]`
  - `exact_text_leakage_across_splits` (direct): `{"instruction": 1, "user_prompt": 24}`
  - `family_or_group_leakage_across_splits` (direct): `{"prompt_family": 8}`
  - `repeated_template_phrase` (direct): `{"If you want, I can help": 84, "Respond in a boundary-preserving way": 84, "The request asks me to": 84}`

### phase_e_review_subset_ai_preannotated_v0_1

- path: `data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl`
- SHA-256: `17c6a99354ef0c115d4a924694b4353b739eaf85114677aca29d09f930158af3`
- rows: 36
- splits: `{"dev": 24, "test": 12}`
- formal use status: `auxiliary_calibration_only_not_independent_human_annotation`
- duplicate IDs: 0
- v2 family coverage: `{"prompt_template_id": 0.0, "scenario_family_id": 0.0, "semantic_cluster_id": 0.0, "source_family_id": 0.0, "task_family_id": 0.0}`
- cross-split exact text duplicates: `{"user_prompt": 0}`
- legacy group leaks: `{"prompt_family": 11}`
- template phrase rows: `{}`
- semantic duplicate check: `not_run`
- blockers:
  - `missing_v2_family_fields` (direct): `["source_family_id", "task_family_id", "scenario_family_id", "prompt_template_id", "semantic_cluster_id"]`
  - `family_or_group_leakage_across_splits` (direct): `{"prompt_family": 11}`

## Not Yet Verified

- Human-valid task/scenario/template/semantic family assignments.
- Embedding-based semantic deduplication and human cluster adjudication.
- Independent human blind evaluation or annotation agreement.
- Suitability of any public dataset for formal Trait mapping.

## Claim Boundary

This audit identifies structural risks in existing artifacts. It does not certify a v2 split, independent human annotation, semantic deduplication, or research validity.
