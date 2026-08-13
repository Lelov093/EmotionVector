# Blind Human Review Pilot Packet v0.1

- status: `prepared_not_annotated`
- source: `data/evaluation/human_review/phase_e_review_subset_ai_preannotated_v0_1.jsonl`
- items: 12
- blind outputs: 36
- axes: `["analytical-intuitive", "assertive-compliant", "boundary-preserving-over-accommodating", "calm-agitated", "cautious-impulsive", "concise-expressive", "confident-uncertain", "empathetic-detached", "reflective-impulsively-answering", "stable-reactive", "supportive-critical", "warm-cold"]`
- randomization seed: `20260803`
- restricted condition key: `results/local_artifacts/research_foundation/blind_review_pilot_condition_key_v0_1.jsonl` (gitignored local artifact; do not share with reviewers)
- heuristic scores included: false
- LLM Judge outputs included: false
- AI preannotations included: false
- independent human annotations completed: 0

## Intended Use

Rubric-comprehension and agreement pilot only. Existing Phase E outputs are reused to test the blind-review workflow; this packet is not a frozen confirmatory test set.

## Human Requirement

At least two independent human reviewers must score the packet without access to the condition key, repository method metadata, heuristic scores, Judge outputs or AI preannotations. A third human adjudicator is required for defined disagreements.

## Claim Boundary

Packet preparation is not human annotation, evaluator calibration, agreement evidence or proof of Trait control.
