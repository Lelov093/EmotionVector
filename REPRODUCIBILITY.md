# Reproducibility and evidence levels

EmotionVector is a research archive with partial public reproducibility. It
separates lightweight tracked evidence from large, sensitive, or
license-constrained local artifacts.

## What a public clone can verify

- JSON schemas, manifests, hashes, split contracts, and claim boundaries.
- CPU-oriented data-foundation and statistical unit tests.
- The implementation of representation statistics, direction controls,
  activation steering, QLoRA preparation, selection locks, and held-out
  aggregation.
- Tracked result summaries and phase reports.
- The fact that the released analysis contracts and summaries are internally
  consistent where all required tracked inputs are available.

## What a public clone cannot reproduce by itself

- Original public-dataset downloads under `data/external/`.
- Local Hugging Face model caches or model weights.
- Hidden-state arrays, steering-vector tensors, and QLoRA adapters.
- Complete local review packets, restricted condition keys, and raw runtime
  logs under `results/local_artifacts/`.
- The complete Phase 2 or Phase 3 model execution without separately obtaining
  the pinned model, licensed source data, and required local artifacts.

The tracked Phase 3 held-out result is therefore an evidence summary, not a
self-contained replication package. The project does not claim that a fresh
clone can independently regenerate all 780 outputs or ratings.

## Validation tiers

### Tier 1: public contract validation

```powershell
python scripts/run_public_tests.py
python scripts/audit_research_data_foundation.py --check-only
```

The public runner explicitly excludes modules that require private, hash-bound
Phase 3 evidence and reports the excluded count. It does not report those tests
as passed. Other failures should be treated as release blockers.

### Tier 2: local frozen-artifact validation

With the original hash-bound files restored under `results/local_artifacts/`,
run `python -m unittest discover -s tests -p "test_*.py" -v`. The selection,
readiness, and held-out analysis modules can then verify the frozen research
record. Do not overwrite or reopen a consumed held-out test merely to obtain a
clean rerun.

### Tier 3: new independent replication

A scientific replication requires a new independent family-isolated dataset,
a newly frozen analysis contract, reviewer design, model/runtime provenance,
and a held-out test that has not been used for selection. Reusing the current
opened test for tuning would not be a valid replication.

## Environment

- Primary research environment: native Windows, Python 3.11.
- Main frozen model: `Qwen/Qwen3-4B-Instruct-2507` at revision
  `cdbee75f17c01a7cc42f958dc650907174af0554`.
- Model-heavy runs require a compatible CUDA environment and sufficient local
  storage. Frozen configs may preserve machine-local cache paths as provenance;
  new runs should use `HF_HUB_CACHE` or an explicit local configuration.

See `results/summaries/phase_3_held_out_results_v0_1.json` for the frozen
aggregate and `DATA_LICENSES.md` for data and model terms. Internal project
planning, progress, application, and narrative-report directories are not part
of the GitHub release.
