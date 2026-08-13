# Public Mapping Family-Isolated Split v2 Candidate Report

## Outcome

- Completed human-review records: 124.
- Decisions: 76 `accept`, 22 `reject`, 21 `ambiguous`, 5 `needs_rewrite`.
- Export-eligible candidates: 112, comprising 39 EmpatheticDialogues responses and 73 mapped PKU-SafeRLHF responses.
- Atomic five-family allocation units: 32.
- Connected components under task/scenario/template/semantic isolation: 5.
- Deterministic candidate allocation: train 79, dev 16, test 17.
- Status: `generated_not_frozen`. This is an eligibility and split-feasibility pilot, not a training set or independent test set.

## Leakage Evidence

The following cross-split checks passed with zero detected conflicts:

- exact content hash;
- normalized content hash;
- token 3-gram near duplicate at Jaccard >= 0.90;
- source sample lineage;
- task family;
- scenario family;
- prompt template;
- semantic cluster.

Raw prompts and responses were hashed in memory and are not included in the tracked evidence.

## Unresolved Validity Limits

- `source_family_id` is preserved as immutable provenance but is not component-isolated. Enforcing source-wide isolation collapses the pilot to two components and makes train/dev/test impossible. PKU source families therefore overlap splits, and source-family generalization cannot be claimed.
- Dev and test contain only `boundary-preserving-over-accommodating`. The `empathetic-detached`, `supportive-critical` and `warm-cold` candidates form one connected component and occur only in train.
- Consequently, this candidate cannot support cross-split evaluation for all mapped Trait axes. The limitation is structural and must not be hidden by ID-level reassignment.
- PKU remains primarily evidence for `boundary-preserving-over-accommodating`; the split does not establish support for `assertive-compliant` or `cautious-impulsive`.
- `same_axis_not_opposite` pairs remain ineligible as representation contrasts even if their individual responses are retained as mapping candidates.

## Recommendation

Keep the candidate unfrozen. Accept it only as evidence that task/scenario/template/semantic leakage can be controlled in the current pilot. Do not spend time forcing axis-balanced splits from these 112 candidates; that would require either breaking family isolation or collecting new family-diverse examples. For the next research stage, use the current pilot to define data gaps, while building representation experiments from separately held-out and purpose-built samples.
