# Trait Space Seed v0.1 Validation Report

- validation command: `python scripts/validate_trait_space_dataset.py --dataset data\trait_space\curated\trait_space_seed_v0_1.jsonl --manifest data\trait_space\splits\trait_space_seed_v0_1_split_manifest.json --report results\cards\trait_space_seed_v0_1_validation_report.md`
- validation timestamp: `2026-07-04T18:38:06.616917+00:00`
- dataset path: `data\trait_space\curated\trait_space_seed_v0_1.jsonl`
- manifest path: `data\trait_space\splits\trait_space_seed_v0_1_split_manifest.json`
- final status: `PASS`

## Counts

- sample count: 120
- pair count: 60
- sample split counts: `{"dev": 24, "test": 24, "train": 72}`
- pair split counts: `{"dev": 12, "test": 12, "train": 36}`

## Axis Coverage

- assertive-compliant
- boundary-preserving-over-accommodating
- calm-agitated
- cautious-impulsive
- empathetic-detached
- stable-reactive

## Leakage

- cross-split pair leakage: 0
- prompt-family holdout result: `pass`
- holdout families: `["authority_pressure", "conflict_deescalation", "escalation", "persona_attack", "sensitive_feedback", "time_pressure"]`

## Warnings

- none

## Errors

- none

## Known Limitations

- Seed scale is sufficient for Batch 2 but not enough for broad publication claims.
- Samples are initial curated seed data and still need independent human review.
- Prompt-family holdout is implemented as axis-local test-family holdout, not a full ontology-wide family benchmark.

## Batch 2 Gate

- dataset passes Batch 2 gate: yes

## Suggested Fixes

- No blocking fixes. Proceed to Batch 3 after human review planning.
