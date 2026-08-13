# Phase D Batch 3 Dataset and Generation Audit

- Dataset rows: 84
- Eval pairs: 24
- Generation rows audited: 120
- Exact duplicate SFT responses: 0
- Near-duplicate SFT response pairs: 3
- Batch2 failure records: 71
- Additional training decision: skip

## Main Findings

- v0.2 remains synthetic and visibly templated.
- The phrase `The request asks me to` is a major synthetic-style marker in adapter outputs.
- Refusal/boundary phrasing is dense enough to require human review before further SFT.
- No train/dev/test scenario leakage was detected by split-scoped scenario ids.

```json
{
  "created_at": "2026-07-04T12:21:24.065858+00:00",
  "dataset_rows": 84,
  "eval_pair_rows": 24,
  "generation_rows": 120,
  "pairwise_rows": 120,
  "split_counts": {
    "train": 60,
    "dev": 12,
    "test": 12
  },
  "prompt_family_counts": {
    "role_pressure": 11,
    "jailbreak_like_request": 11,
    "unreasonable_request": 11,
    "persona_attack": 11,
    "privacy_pressure": 10,
    "professional_advice_pressure": 10,
    "emotional_dependency": 10,
    "accuracy_pressure": 10
  },
  "exact_duplicate_responses": 0,
  "near_duplicate_pairs": 3,
  "templated_phrase_hits": {
    "The request asks me to": 84,
    "If you want, I can help": 84,
    "I cannot": 74,
    "I should not": 31
  },
  "excessive_refusal_hits": {
    "cannot": 74,
    "can't": 12,
    "will not": 7,
    "should not": 31
  },
  "excessive_apology_hits": {
    "sorry": 0,
    "apologize": 0
  },
  "excessive_hedging_hits": {
    "maybe": 0,
    "perhaps": 0,
    "might": 0
  },
  "train_dev_test_leakage_risk": {},
  "generation_failure_tags": {
    "low_usefulness": 96,
    "over_refusal_risk": 68,
    "safe_alternative_missing": 3,
    "too_generic_or_short": 9,
    "repetition": 49,
    "repeats_user_request": 19,
    "synthetic_style_marker": 22
  },
  "batch2_failure_records": 71,
  "clean_training_candidate_count": 0,
  "additional_training_decision": "skip",
  "additional_training_reason": "Batch 3 intentionally skipped additional training because no reviewed clean train set exists; Phase D closure prioritizes evidence cleanup and claim boundary over adding another noisy adapter."
}
```
