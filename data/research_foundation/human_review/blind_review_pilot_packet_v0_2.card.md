# Single-Researcher Condition-Blind Pilot Packet v0.2

- status: `prepared_not_annotated`
- source: `data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl`
- items per round: 12
- blind outputs per round: 30
- review rounds: 2
- axes: `["analytical-intuitive", "assertive-compliant", "boundary-preserving-over-accommodating", "calm-agitated", "cautious-impulsive", "concise-expressive", "confident-uncertain", "empathetic-detached", "reflective-impulsively-answering", "stable-reactive", "supportive-critical", "warm-cold"]`
- round 1 randomization seed: `20260803`
- round 2 randomization seed: `20260804`
- restricted condition key: `results/local_artifacts/research_foundation/blind_review_pilot_condition_key_v0_2.jsonl` (gitignored local artifact; do not share with reviewers)
- heuristic scores included: false
- LLM Judge outputs included: false
- AI preannotations included: false
- single-researcher annotations completed: 0

## Intended Use

Rubric-comprehension and within-reviewer stability pilot only. Existing Phase E outputs are reused to test the blind-review workflow; this packet is not a frozen confirmatory test set.

## Human Requirement

The same researcher completes round 1 without access to the condition key, then completes independently randomized round 2 after a minimum seven-day washout without consulting round-1 scores. This estimates test-retest stability only; it is not inter-rater agreement or independent external evaluation.

## Claim Boundary

Packet preparation is not human annotation, evaluator calibration, stability evidence or proof of Trait control.
