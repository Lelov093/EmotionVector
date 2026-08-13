# Boundary-preserving SFT v0.1 Dataset Card

- Source: `data/trait_space/curated/trait_space_seed_v0_1.jsonl`
- Axis: `boundary-preserving-over-accommodating`
- Target pole: `boundary-preserving`
- Sample count: 10
- Split counts: {'train': 6, 'dev': 2, 'test': 2}
- Transformation: formatting conversion from positive-pole trait samples into instruction-response SFT records.
- Leakage prevention: source pair-level splits are preserved; no negative-pole over-accommodating responses are used as SFT targets.
- Intended use: first QLoRA pilot adapter training for Phase D Batch 1.
- Not intended claim: this tiny dataset does not establish stable trait control or publication-scale post-training evidence.
- Limitation: only seed-scale curated positives are used; train split has 6 samples.
