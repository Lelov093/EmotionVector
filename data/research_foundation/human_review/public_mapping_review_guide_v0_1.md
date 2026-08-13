# Public Dataset Trait-Mapping Pilot Review Guide v0.1

## Scope

The two local JSONL packets are a single-researcher eligibility pilot, not training data and not a formal test set. Raw text stays under Git-ignored `results/local_artifacts/`. The tracked manifest contains only source locators, hashes, source labels and machine-proposed family fields.

## Review Decisions

For every row, set `human_review.mapping_decision` to exactly one of:

- `accept`: the sample is usable for the stated narrow pilot role;
- `reject`: the sample is irrelevant, low quality, unsafe to reuse, duplicated, template-dominated or otherwise unsuitable;
- `ambiguous`: the mapping cannot be decided consistently from the available context;
- `needs_rewrite`: the underlying scenario may be useful, but the original wording must not be reused directly.

Do not accept a sample merely because its source label appears related to a Trait. Emotion labels and safety preferences are auxiliary source signals, not Trait gold labels.

## Family Fields

For accepted rows, fill all five human family fields. Group samples by the underlying task and situation, not by row ID. Shared slot-filled or paraphrased templates receive the same `prompt_template_id`. Near-identical meanings receive the same `semantic_cluster_id`. If this cannot be done confidently, use `ambiguous` rather than inventing a formal family.

## EmpatheticDialogues

Review whether the candidate response actually expresses one of `empathetic-detached`, `warm-cold` or `supportive-critical` while remaining natural and relevant. The source emotion context is a scenario cue only.

## PKU-SafeRLHF

The packet may contain harmful requests or responses. Do not redistribute or quote its raw text in reports. For each response choose exactly one behavior label:

`reasonable_accept`, `reasonable_refusal`, `clarification`, `alternative`, `unsafe_compliance`, `over_refusal`, or `other`.

Safety and helpfulness preferences are not personality labels. Accept a Trait mapping only when the response behavior supplies a defensible narrow signal; otherwise reject or mark ambiguous.

## Validation

After filling both packets, run:

```powershell
python scripts\validate_public_dataset_mapping_review.py `
  results\local_artifacts\research_foundation\public_mapping_pilot_v0_1\empathetic_dialogues_mapping_review_v0_1.jsonl `
  results\local_artifacts\research_foundation\public_mapping_pilot_v0_1\pku_safe_rlhf_mapping_review_v0_1.jsonl
```

Validation checks completeness and allowed values; it does not certify mapping validity.
