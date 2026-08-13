# Trait Space Seed v0.1 Dataset Card

## Dataset Name

`trait_space_seed_v0_1`

## Version

`trait_space_seed_v0_1`

## Purpose

This dataset is the first curated seed slice for Phase B Representation Atlas work. It supplies controlled contrastive response texts for the six high-priority Trait Space V1 axes while preserving the full 12-axis research ontology in the registry.

## Axes Covered

- `calm-agitated`
- `empathetic-detached`
- `assertive-compliant`
- `boundary-preserving-over-accommodating`
- `cautious-impulsive`
- `stable-reactive`

The remaining six Trait Space V1 axes are not removed; they remain scheduled for later expansion.

## Counts

- Samples: 120
- Contrastive pairs: 60
- Per axis: 10 pairs / 20 samples
- Split: train 36 pairs / 72 samples, dev 12 pairs / 24 samples, test 12 pairs / 24 samples

## Construction Principles

- Each pair shares the same scenario and task objective.
- Positive and negative pole samples are intended to vary the target trait, not answer correctness.
- Texts are response texts suitable for later representation extraction.
- Source is marked as curated seed data, not placeholder or schema sample data.
- Each sample includes confound notes for later human review.

## Split Summary

The split is pair-level and axis-balanced: each axis has 6 train pairs, 2 dev pairs, and 2 test pairs. Test uses axis-local prompt-family holdout families that do not appear in train.

## Known Limitations

- This is seed-scale data, not a publication-scale benchmark.
- It was initially curated by Codex and still needs independent human review.
- Prompt-family holdout is axis-local; broader cross-family robustness should be added before strong generalization claims.
- Some axes naturally overlap with politeness, refusal, confidence, warmth, and verbosity; these are recorded as confounds rather than hidden.

## Confound Controls

- Pair-level task and scenario are fixed.
- Split is kept at pair level to prevent contrastive leakage.
- Length-control and task-answer equivalence groups are recorded.
- Confound notes are required on every sample.

## Leakage Prevention

- No pair crosses train/dev/test.
- Holdout families are absent from train and appear in test.
- The validation gate checks axis coverage, 6/2/2 pair balance, duplicate text, placeholder tokens, pair consistency, and manifest consistency.

## Intended Use

- Representation Atlas hidden-state extraction.
- Layer-wise separability checks.
- Vector construction experiments.
- Dataset validation and annotation workflow development.

## Non-goals

- Not a model experiment result.
- Not an activation steering result.
- Not a dashboard data source by itself.
- Not evidence that the model has subjective emotion.
- Not a final human-reviewed benchmark.

## Artifact Safety

This tracked file contains only lightweight text data. It does not include hidden states, vector tensors, model outputs, model weights, cache files, logs, or DB dumps.

## Why This Is Real Seed Data

The rows are complete response texts with stable IDs, pair IDs, splits, prompt families, poles, source metadata, annotator metadata, confound notes, and quality flags. They are intended to be consumed by later Representation Atlas extraction rather than merely demonstrating schema shape.
