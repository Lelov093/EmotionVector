# Single-Researcher Condition-Blind Evaluation Protocol v0.2

## Status and Replacement

This protocol supersedes v0.1 for the current one-person project. The user approved the rubric and the single-researcher constraint on 2026-08-03. No annotation round has started.

## What “Blind” Means Here

- Codex prepares randomized blind IDs and keeps the condition key under Git-ignored `results/local_artifacts/`.
- The researcher sees prompts, axis definitions, output text and rubric anchors, but not method names, condition IDs, heuristic scores, LLM Judge outputs or generation order.
- Because the researcher knows the project and may recognize output styles, this is condition blinding, not a guarantee of complete researcher blinding.
- AI may prepare packets and validate missing fields. AI ratings do not count as human ratings.

## Two-Round Single-Researcher Procedure

1. Complete round 1 without opening the condition key or previous automated scores.
2. Freeze the round-1 annotation file and record its SHA-256.
3. Wait at least seven days. Do not consult round-1 scores during the washout.
4. Complete independently randomized round 2 using the same rubric.
5. Freeze round 2 before joining the two rounds through the restricted canonical output key.
6. Report per-dimension exact agreement and, for ordinal dimensions, quadratic weighted Cohen’s kappa where defined.

This measures within-reviewer test-retest stability. It does not measure inter-rater agreement, remove researcher expectancy effects, or constitute independent external evaluation.

## Dimensions

Rate each output separately for target Trait expression, task quality/helpfulness, naturalness, refusal appropriateness, over-refusal, sycophancy/over-accommodation, clarification or alternative quality, repetition/template artifacts, verbosity side effects, other side effects and confidence. Trait scores must not absorb task quality or safety.

## Stability Gate

- The core Trait dimension requires exact agreement of at least 70% and quadratic weighted kappa of at least 0.67 when kappa is defined.
- A core dimension below either threshold requires rubric revision and a fresh pilot; it cannot support confirmatory claims.
- Passing this gate supports only the statement that one researcher applied the rubric with acceptable test-retest stability in this packet.
- Report every dimension separately. Do not average dimensions to conceal instability.

## Randomization and Access Control

- Round-specific seeds and script revision are recorded.
- Blind IDs do not encode axis, method, alpha, adapter, seed or model identity.
- Round-1 and round-2 blind IDs differ; the canonical output mapping exists only in the restricted key.
- Any accidental unblinding or consultation of prior scores is logged. The affected round is repeated with fresh IDs after a new washout.

## Claim Boundary

This protocol cannot support claims of independent human validation, inter-rater reliability, population-level evaluator agreement or Trait control. Negative results do not lower the completion gate.
