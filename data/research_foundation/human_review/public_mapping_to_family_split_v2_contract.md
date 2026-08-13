# Public Mapping v0.2 → Family Split v2 Conversion Contract

## Authority and Field Ownership

- `source_family_id` is derived by the packet generator from pinned provenance. It is read-only and is checked against the tracked v0.2 manifest.
- `proposed_family_assignment` contains machine suggestions for task, scenario, template and semantic families. It is never authoritative.
- `human_review.reviewed_family_assignment` contains the four reviewable family fields. A human may confirm, replace or leave them unset according to the decision rules.
- The complete allocation unit is the union of the provenance-derived source family and the four accepted human-reviewed families.

## Decision Conversion

- `accept`: eligible for conversion after all required labels and family fields validate.
- `reject`: never converted.
- `ambiguous`: never converted; it remains evidence of unresolved mapping uncertainty.
- `needs_rewrite`: the original sample is never converted. Its `sample_id`, source locator, content hash, source family, defensible Trait label, scenario family and rewrite notes preserve lineage. Any later rewrite must be a new sample with explicit `derived_from` lineage and must undergo a new review.

## PKU Pair Handling

Each mapped response becomes a separate candidate ID suffixed with `__response_0` or `__response_1`. Both retain the same five-family allocation unit. `pair_contrast.status=valid_single_axis` is valid only when the two response annotations use the same registry axis and its two opposite poles. Other contrast statuses cannot be reported as a valid representation pair.

## Split Allocation

`reviewed_family_candidates_v2()` computes an atomic `allocation_unit_id` from all five family fields. Allocation then forms connected components across the human-reviewed `task_family_id`, `scenario_family_id`, `prompt_template_id` and `semantic_cluster_id`: units sharing any one of these family values must remain in the same split. A later allocation manifest assigns train/dev/test/excluded by connected component, never by sample ID. `source_family_id` remains immutable provenance, but source-wide component isolation is not imposed in the pilot because it collapses the accepted data to two components and makes a three-way split impossible; any source-family overlap is reported explicitly and prevents silent claims of source-isolated generalization. `family_split_records_v2()` rejects missing or invalid unit assignments and emits records matching `family_split_v2.schema.json`.

The split builder must not run until all 124 mapping records validate and a family-level allocation manifest plus leakage evidence exist. Creating the contract does not create or freeze a split.
