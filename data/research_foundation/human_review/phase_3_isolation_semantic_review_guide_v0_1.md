# Phase 3 Isolation Semantic-Merge Review Guide v0.1

## Purpose

The `isolation_family_id` is a split-ownership key, not a Trait label and not a broad topical category. Candidates that express materially the same prompt intent, paraphrase, request pattern or answerable task must share one reviewed isolation family even when wording differs. Broad source/task/scenario/template/semantic fields remain provenance or stratification metadata and must not be copied mechanically into this ID.

The packet contains 240 prompts: the unchanged confirmed 180 cohort plus the new 60-candidate expansion. Mechanical exact, normalized and token 3-gram checks currently propose singleton components. Singleton status is provisional and does not establish semantic independence.

## Decisions

- `confirm`: the prompt remains its own isolation family after comparison with semantically similar prompts.
- `merge`: identify every known candidate with the same underlying prompt intent. All members of a merge group must receive the same reviewed `p3iso_...` ID.
- `exclude`: the prompt cannot be assigned reliably or creates unresolved leakage risk; it cannot enter any split.

Every completed row requires `reviewer_id`, timezone-aware `reviewed_at`, a reviewed isolation ID for `confirm`/`merge`, and notes for consequential merges or exclusions. Do not split paraphrases merely to meet 40/15/40. Review completion does not allocate train/dev/test; allocation occurs only after transitive merge closure and all eligibility gates pass.
