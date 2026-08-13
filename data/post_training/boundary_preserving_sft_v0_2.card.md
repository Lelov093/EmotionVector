# Boundary-preserving SFT v0.2 Dataset Card

- Source dataset: `data/trait_space/curated/trait_space_seed_v0_1.jsonl`
- Axis: `boundary-preserving-over-accommodating`
- Target pole: `boundary-preserving`
- SFT sample count: 84
- Split counts: {'train': 60, 'dev': 12, 'test': 12}
- Prompt family counts: {'role_pressure': 11, 'jailbreak_like_request': 11, 'unreasonable_request': 11, 'persona_attack': 11, 'privacy_pressure': 10, 'professional_advice_pressure': 10, 'emotional_dependency': 10, 'accuracy_pressure': 10}
- Eval pairs: 24
- Preference candidates: 24
- Human annotated: false for every generated record.
- Generator: deterministic task-family expansion from Phase B trait seed examples.
- Negative over-accommodating responses: used only in eval/preference files, never as SFT targets.
- Leakage prevention: scenario ids are split-scoped and pair ids do not cross train/dev/test.
- Intended use: Phase D Batch 2 QLoRA boundary-preserving adapter candidates.
- Limitation: this is still synthetic/derived data, not a human-labeled publication-scale post-training corpus.
