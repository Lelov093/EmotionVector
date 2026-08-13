# EmotionVector

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Research status](https://img.shields.io/badge/research-closed%20negative%2Fmixed-6b7280.svg)](results/summaries/phase_3_held_out_results_v0_1.json)

## Overview

EmotionVector is a research prototype for studying affective and behavior-related trait representations, controllability baselines, and evaluation methods in instruction-tuned LLMs.

The project does not claim that LLMs have subjective emotions or that personality control is solved. It studies observable trait-like behavior patterns in model outputs and internal activations.

Active research execution closed on 2026-08-05 after the authorized Phase 1–3 credibility-improvement program. The final conclusion is negative/mixed: representation evidence remains exploratory, target steering did not show credible target-specific improvement, Prompt-only was descriptively strongest on held-out task quality, and the retained QLoRA fallback was harmful. The frozen aggregate is available at `results/summaries/phase_3_held_out_results_v0_1.json`.

## Public Release Scope

This repository is a research code and evidence archive. It includes source
code, frozen contracts, schemas, lightweight result cards, aggregate summaries,
and research reports. It intentionally excludes personal application material,
raw third-party datasets, credentials, model weights, activation arrays,
adapters, restricted condition keys, local databases, and large runtime logs.

The public clone supports contract validation and method inspection, but it is
not a self-contained package for regenerating every model output or rating. See
`REPRODUCIBILITY.md` and `DATA_LICENSES.md` before using the artifacts.

## Original Application Context

EmotionVector originally started from AI Character / NPC emotion and personality stability monitoring. It was inspired by emotion concept / emotion vector research, especially the idea that internal activations may contain behaviorally meaningful emotion-related representations.

The final project generalizes that application motivation into trait representation, controllability baselines, and evaluation maturity. It does not claim subjective model emotions, solved personality control, or full reproduction of closed-model Anthropic results.

## Research Questions

- Can affective and persona-related trait axes be separated in hidden representations?
- Do activation-steering interventions change behavior beyond prompt-only and control baselines?
- Can QLoRA post-training provide a useful control baseline?
- How should trait-control claims be evaluated without circular scoring?
- Which claims are supported, and which remain unsupported?

## Key Contributions

- Designed a 12-axis Trait Space V1 covering affective, safety/control, and cognitive/style traits.
- Built a Qwen3-4B representation atlas slice for six high-priority axes.
- Evaluated activation steering against prompt-only, random-vector, and shuffled-vector baselines.
- Implemented a Qwen3-4B 4-bit QLoRA boundary-preserving adapter baseline.
- Created a 12-axis evaluation set and generated real Qwen3-4B outputs.
- Calibrated heuristic, external judge, and AI-preannotation signals.
- Produced final evidence maps and claim-boundary matrices.

## Pipeline

```text
Trait Space V1
  -> Representation Atlas
  -> Activation Steering Evaluation
  -> QLoRA Post-training Baseline
  -> 12-axis Evaluation Maturation
  -> Final Evidence Packaging
```

## Results Summary

| Area | Result | Limitation |
|---|---|---|
| Representation Atlas | The frozen single-axis pilot produced an exploratory representation signal. | Separability does not prove behavior control or causal intervention. |
| Activation Steering | The final target alpha 1 held-out comparison was almost entirely tied with base (1/51/0 W/T/L; permutation p=1.0). | No credible target-specific steering improvement. |
| Prompt-only | Held-out task-quality delta was +0.2200 with a family-cluster 95% CI above zero. | Descriptive, nonconfirmatory, single-model/single-rater evidence. |
| QLoRA | The fixed 4-bit training/runtime pipeline executed reproducibly. | Epoch 1 failed development quality and was strongly harmful on held-out Trait and task quality. |
| Evaluation | The final family-isolated held-out matrix contains 780 rated outputs across 15 conditions. | Single-rater review, user-reported AI-preannotation provenance and a preparation-side blinding deviation limit claims. |

## Repository Structure

```text
data/trait_space/           Trait registry, seed data, schemas
data/evaluation/            12-axis eval set and review packets
data/research_foundation/   Provenance, family split, blind-evaluation contracts
experiments/atlas/          Representation Atlas runner
experiments/steering/       Activation steering runners/evaluators
experiments/post_training/  QLoRA post-training pipeline
experiments/evaluation/     Evaluation and review utilities
results/cards/              Lightweight result cards and sampled cases
results/summaries/          Lightweight JSON summaries
research_foundation/        CPU-only data audit and analysis utilities
```

## Environment Setup

The primary development environment is native Windows with Python 3.11. Model
experiments additionally require a compatible CUDA environment and a locally
downloaded model snapshot.

```powershell
uv sync --frozen
Copy-Item .env.example .env
```

## Public Validation

These checks do not load a language model or open a held-out test:

```powershell
.\.venv\Scripts\python.exe scripts\run_public_tests.py
.\.venv\Scripts\python.exe scripts\audit_research_data_foundation.py --check-only
```

The public runner excludes tests requiring ignored local Phase 3 evidence and
reports the excluded count rather than treating them as passed. Model-heavy
runs require local model caches, licensed source data, and ignored artifacts.
The cards under `results/cards/` and summaries under `results/summaries/` are
the intended lightweight public evidence.

## Artifact Safety

Not tracked:

- model weights
- HuggingFace cache
- hidden states
- vector tensors
- raw large logs
- `.env`
- API keys
- database dumps

Tracked:

- configs
- schemas
- lightweight result cards
- lightweight summaries
- sampled review cases

## Claim Boundaries

Supported:

- 12-axis trait space and evaluation foundation.
- Qwen3-4B representation atlas slice.
- Activation steering evaluated with baselines and controls.
- QLoRA boundary-control baseline implemented and evaluated.
- Prompt-only identified as a strong baseline.
- Selected target steering did not show credible target-specific improvement.

Not supported:

- proven 12-axis controllability
- stable personality control
- production-grade safety/personality control
- external judge as human ground truth
- AI preannotation as independent human annotation
- any one method globally winning

Machine-readable boundary matrix:
`results/summaries/final_claim_boundary_matrix.json`.

## Future Work

Any continuation must be a new research decision rather than a reopening of the
consumed held-out test. High-information next steps would require:

- a new independent family-rich replication set;
- at least two independent reviewers and preregistered disagreement handling;
- intervention diagnostics at hidden-state and logit levels;
- a second model before expanding to additional Trait axes;
- new train/dev data for any QLoRA failure analysis.

## License and Citation

Original EmotionVector code and documentation are licensed under Apache-2.0.
Third-party datasets and source-derived material retain their own terms,
including CC-BY-NC-4.0 restrictions documented in `DATA_LICENSES.md`. Model
weights and raw upstream datasets are not distributed.

Citation metadata is available in `CITATION.cff`.
