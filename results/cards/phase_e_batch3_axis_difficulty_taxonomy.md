# Phase E Batch 3 Axis Difficulty Taxonomy

| axis | difficulty | base_strength | prompt_only_effect | steering_signal | disagreement_level | main_failure_modes | recommended_next |
|---|---|---:|---|---|---|---|---|
| analytical-intuitive | hard | True | weak | unavailable | medium | prompt_only_more_abstract, prompt_only_axis_leakage, prompt_only_concept_error | tighten prompt-only instruction and check style leakage |
| assertive-compliant | hard | False | moderate | mixed | medium | output_truncated, no_clear_difference, steering_not_above_base, selected_steering_stronger | rerun a small subset with higher max_new_tokens before final claims |
| boundary-preserving-over-accommodating | hard | False | strong | weak | high | prompt_only_stronger, legal_boundary, appropriate_refusal, user_controlled_storage | treat prompt-only as a strong baseline for this axis |
| calm-agitated | hard | False | strong | weak | medium | output_truncated, no_clear_difference, steering_not_above_base, steering_not_above_prompt_only | rerun a small subset with higher max_new_tokens before final claims |
| cautious-impulsive | hard | False | strong | weak | high | prompt_only_stronger, steering_not_above_prompt_only | treat prompt-only as a strong baseline for this axis |
| concise-expressive | hard | False | strong | unavailable | high | prompt_only_stronger, concise | treat prompt-only as a strong baseline for this axis |
| confident-uncertain | easy | False | strong | unavailable | low | prompt_only_stronger, identical_outputs | treat prompt-only as a strong baseline for this axis |
| empathetic-detached | hard | False | strong | weak | high | output_truncated, selected_steering_overcomforting, steering_not_above_prompt_only, decision_bias | rerun a small subset with higher max_new_tokens before final claims |
| reflective-impulsively-answering | easy | True | moderate | unavailable | low | base_stronger, prompt_only_overly_poetic, base_irrelevant, prompt_only_meta_style | tighten prompt-only instruction and check style leakage |
| stable-reactive | hard | True | weak | mixed | medium | meta_style, selected_steering_not_above_base, selected_steering_stronger, prompt_only_over_refusal | retain in final review set and calibrate with human review |
| supportive-critical | hard | False | strong | unavailable | high | base_underanswers, prompt_only_assumes_missing_artifact, prompt_only_stronger, mild_overagreement | treat prompt-only as a strong baseline for this axis |
| warm-cold | hard | True | moderate | unavailable | medium | prompt_only_over_warm, sycophancy_or_over_accommodation, prompt_only_stronger | retain in final review set and calibrate with human review |
