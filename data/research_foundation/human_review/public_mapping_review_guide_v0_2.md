# Public Dataset Trait-Mapping Review Guide v0.2

## Status

This guide and schema v0.2 supersede v0.1 for formal human review. The untouched v0.1 packets remain local historical artifacts and must not be migrated or treated as completed annotations.

## Field Ownership

- `source_family_id` is read-only provenance produced by the generator. Do not edit it; the validator compares it with the tracked manifest.
- `proposed_family_assignment` is a machine suggestion only. Never copy it mechanically.
- `human_review.reviewed_family_assignment` contains exactly four human-reviewable fields: task, scenario, prompt-template and semantic-cluster family.
- The later split allocation unit combines the immutable source family with the four accepted reviewed families.

## Mapping Decisions

Every completed decision must record `reviewer_id` and an ISO-8601 `reviewed_at` timestamp with timezone. The single-researcher workflow does not remove annotation provenance requirements.

### `accept`

- EmpatheticDialogues: provide one registry-valid `trait_annotation` and all four reviewed family fields.
- PKU-SafeRLHF: label both response behaviors, provide at least one registry-valid response Trait annotation, set a non-ambiguous pair contrast status, and fill all four reviewed family fields.
- Acceptance does not imply the PKU pair is a valid contrast. Only `valid_single_axis` has that meaning.

### `needs_rewrite`

- Preserve a defensible axis/pole, `scenario_family_id`, source lineage and non-empty `rewrite_notes`.
- For PKU, label both response behaviors and the pair contrast status.
- The original prompt/response text is permanently excluded from split export. A later rewrite must receive a new sample ID, explicit `derived_from` lineage and a fresh review.

### `ambiguous`

- Use when the mapping cannot be resolved consistently.
- Explain the uncertainty in `notes`. Do not invent family IDs to force acceptance.

### `reject`

- Supply at least one controlled `quality_flag` or an explanatory note.
- Rejected records never enter split export.

## Axis and Pole

Axis–pole validity is loaded directly from `data/trait_space/axis_registry.yaml`; the mapping schema does not duplicate the Trait ontology. An axis must also belong to the row’s `candidate_trait_axes`.

## PKU Response and Pair Labels

Each response has one behavior and an optional paired `axis_id`/`pole`. The pair status is exactly one of:

- `valid_single_axis`: same registry axis and its two opposite poles;
- `same_axis_not_opposite`: same axis but not opposite poles;
- `multi_axis`: the responses map to different axes;
- `insufficient_trait_evidence`: fewer than two defensible response Trait labels;
- `ambiguous`: the contrast cannot be resolved; this is incompatible with `accept`.

Safety/helpfulness source labels are auxiliary evidence, not Trait labels.

## Quality Flags

Allowed values are:

`keyword_leakage`, `length_mismatch`, `task_answer_mismatch`, `confound_risk`, `unsafe_content`, `too_subtle`, `too_obvious`, `exact_duplicate`, `near_duplicate`, `template_dominated`, `insufficient_context`, `source_label_only`, `multi_axis_confound`, `poor_response_quality`, `other`.

Use `notes` when `other` is selected. Flags must be unique.

## Validation

```powershell
python scripts\validate_public_dataset_mapping_review_v2.py `
  results\local_artifacts\research_foundation\public_mapping_pilot_v0_2\empathetic_dialogues_mapping_review_v0_2.jsonl `
  results\local_artifacts\research_foundation\public_mapping_pilot_v0_2\pku_safe_rlhf_mapping_review_v0_2.jsonl
```

Validation checks schema-relevant conditions, immutable provenance, axis–pole legality, PKU contrast semantics and packet completeness. It does not certify the researcher’s substantive judgment.
