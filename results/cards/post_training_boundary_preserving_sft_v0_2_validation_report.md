# Post-training Dataset Validation

- Dataset: `data\post_training\boundary_preserving_sft_v0_2.jsonl`
- Rows: 84
- Passed: True
- Split counts: {'train': 60, 'dev': 12, 'test': 12}
- Prompt families: {'role_pressure': 11, 'jailbreak_like_request': 11, 'unreasonable_request': 11, 'persona_attack': 11, 'privacy_pressure': 10, 'professional_advice_pressure': 10, 'emotional_dependency': 10, 'accuracy_pressure': 10}

## Errors

- None

## Warnings

- length_words min/avg/max: 40/47.61/57
- refusal_inflation: 93 hits, per_sample=1.1071
- excessive_apology: 0 hits, per_sample=0.0
- hedging: 0 hits, per_sample=0.0
- boundary_phrase_overuse: 24 hits, per_sample=0.2857
- source_distribution: {'synthetic_derived_task_family_expansion': 84}
