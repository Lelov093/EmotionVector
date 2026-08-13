# Automatic Evaluator Calibration v0.1

## Scope

This is a minimal calibration of already-produced heuristic and LLM Judge signals against the frozen single-researcher blind pilot. Round 1 is the primary reference; accelerated Round 2 is sensitivity evidence only. AI preannotations are excluded from the human reference.

## Heuristic vs Human Round 1

| Signal | Type | N | Result |
|---|---|---:|---|
| trait_expression | ordinal | 30 | exact 26.7%; MAE 1.133; Spearman -0.301625; QWK -0.100592 |
| response_quality | ordinal | 30 | exact 33.3%; MAE 1.100; Spearman 0.139873; QWK 0.012158 |
| usefulness | ordinal | 30 | exact 33.3%; MAE 1.133; Spearman 0.054643; QWK -0.044776 |
| repetition | ordinal | 30 | exact 40.0%; MAE 0.600; Spearman -0.212351; QWK -0.067194 |
| over_refusal | binary | 30 | accuracy 76.7%; balanced accuracy undefined |
| sycophancy | binary | 30 | accuracy 100.0%; balanced accuracy undefined |
| verbosity_warning | binary | 30 | accuracy 36.7%; balanced accuracy 0.423077 |

## LLM Judge Pairwise Check

- Existing judged pairs: 12; matched to the blind pilot: 10.
- Agreement with human task-quality preference on non-ties: 0.75 (N=4; human ties=6).
- Agreement with human Trait preference on non-ties: 0.666667 (N=3; human ties=7).
- Preferred-output judgments are holistic, so neither comparison is a construct-identical gold-label test.

## Decision

- Heuristic: retain only for triage, error sampling and sensitivity analysis; always report human results separately.
- LLM Judge: retain only as an exploratory pairwise review aid and disagreement sampler.
- Neither evaluator may replace human annotation, select a model alone, or establish Trait control.
- No formal automatic-evaluator pass/fail gate is claimed because none was preregistered.

## Claim Boundary

Calibration is limited to 30 reused outputs and one researcher. Round 2 is an accelerated sensitivity check. The results define auxiliary uses only and do not validate either evaluator as a human substitute.
