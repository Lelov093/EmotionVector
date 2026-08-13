# Blind Review Round 1/2 Accelerated Retest Stability v0.2

## Outcome

- Paired outputs: 30
- Trait exact agreement: 100.0% (30/30)
- Trait quadratic weighted kappa: 1.0
- Numeric gate status: `passes_numeric_thresholds_but_not_protocol_compliant`
- Protocol compliant: `false`

The original seven-day washout was not met. Even if the numeric thresholds pass, this run remains an accelerated diagnostic and cannot establish protocol-compliant test-retest stability.

## Per-Dimension Results

| Dimension | N | Exact agreement | QWK | QWK N | Disagreements |
|---|---:|---:|---:|---:|---:|
| trait_score | 30 | 100.0% | 1.000 | 30 | 0 |
| task_quality_score | 30 | 93.3% | 0.972 | 30 | 2 |
| naturalness_score | 30 | 96.7% | 0.976 | 30 | 1 |
| alternative_quality | 30 | 96.7% | 0.857 | 21 | 1 |
| repetition | 30 | 93.3% | 0.867 | 30 | 2 |
| confidence | 30 | 100.0% | undefined | 30 | 0 |
| refusal_appropriateness | 30 | 100.0% | undefined | 0 | 0 |
| over_refusal | 30 | 100.0% | undefined | 0 | 0 |
| sycophancy | 30 | 100.0% | undefined | 0 | 0 |
| verbosity_side_effect | 30 | 70.0% | undefined | 0 | 9 |
| other_side_effects | 30 | 33.3% | undefined | 0 | 20 |

## Evidence and Access Boundary

- Round 1 annotation SHA-256: `476c6e66a95a8edb70ef7691bcee83d29140d52427283203d44b5e34bbbc9b7f`
- Round 2 annotation SHA-256: `be066dcee201288e40d71ec02931506ae31eb92cbf63ab5e196598177f0a0582`
- Restricted condition-key SHA-256: `6869f52a232e05e689603d9a718a9e77e71af03496f9d91fa222951f46e2605e`
- The condition key was used only to recover canonical cross-round pairing. Condition IDs, artifact IDs and method labels are not emitted in the summary, report or disagreement artifact.
- Free-text notes agreement is supplementary and is not included in the scoring gate.

## Interpretation

- **Direct evidence:** Trait ratings agree on 30/30 pairs and meet the predeclared numeric thresholds. Verbosity-side-effect agreement is 70.0%; free-text other-side-effects agreement is 33.3%.
- **Reasonable inference:** the approximately 1.14-hour interval may have increased recall or score carryover, so the perfect Trait result may overestimate repeatability under the intended washout.
- **Required correction before formal evaluation:** replace free-text side-effect agreement with a controlled tag taxonomy, while retaining optional notes as qualitative evidence.
- **Not verified:** seven-day test-retest stability, inter-rater reliability, independent external validity, or any method-level advantage.

## Claim Boundary

This diagnostic measures accelerated within-reviewer repeatability on 30 reused outputs. It is not inter-rater agreement, independent external validation, a protocol-compliant seven-day test-retest estimate, method comparison, or evidence of Trait control.
