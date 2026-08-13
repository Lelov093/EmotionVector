# Data, model, and artifact licenses

The root Apache-2.0 license applies to EmotionVector's original source code and
documentation unless a file says otherwise. It does not replace the licenses or
terms of third-party datasets, models, or content derived from them.

This file records the release boundary; it is not legal advice.

## Model

### Qwen3-4B-Instruct-2507

- Source: <https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507>
- Project revision: `cdbee75f17c01a7cc42f958dc650907174af0554`
- Upstream license: Apache-2.0
- Release policy: model weights and Hugging Face caches are not distributed by
  this repository. Users must obtain them from the upstream source and comply
  with its license and terms.

Older historical experiments also reference Qwen-family checkpoints. Their
model identifiers and revisions remain in the corresponding configs and result
cards; no checkpoint weights are included here.

## Public datasets

### EmpatheticDialogues

- Source: <https://huggingface.co/datasets/facebook/empathetic_dialogues>
- Project-pinned metadata revision:
  `d8b8066548b8bc2bb36af41f878f1ec5f03badd2`
- Upstream license recorded by the project: CC-BY-NC-4.0
- Project use: non-commercial research eligibility, mapping, and provenance
  work only.

### PKU-SafeRLHF

- Source: <https://huggingface.co/datasets/PKU-Alignment/PKU-SafeRLHF>
- Project-pinned metadata revision:
  `f4b036fc262da341565c0d01b2e8cf47d386921e`
- Upstream license recorded by the project: CC-BY-NC-4.0
- Project use: non-commercial safety, refusal-side-effect, and
  boundary-preservation research only.

The raw upstream datasets are intentionally excluded from Git. Tracked public
mapping manifests contain provenance, source locators, hashes, eligibility
decisions, and family metadata rather than a redistribution of the raw corpora.
See:

- `data/research_foundation/manifests/public_dataset_downloads_v0_1.json`
- `data/research_foundation/manifests/public_dataset_use_decisions_v0_1.json`
- `data/research_foundation/manifests/public_mapping_pilot_v0_2.json`

Do not treat Apache-2.0 as permission to use CC-BY-NC-4.0 material for a
commercial purpose. Preserve upstream attribution and review the applicable
license before redistributing any source-derived content.

## Project-created research data and outputs

The repository tracks small curated datasets, model-output result cards,
aggregate summaries, schemas, and review metadata needed to explain the
research record. Some artifacts may reflect or be derived from third-party
dataset examples even when raw text is not included. Their use remains subject
to the relevant upstream terms and the claim boundaries in the accompanying
data cards and reports.

Large or sensitive local artifacts are not part of the public release,
including raw downloaded datasets, activation arrays, model adapters, complete
condition keys, local databases, API credentials, and full runtime logs.

Before republishing a tracked data or result file outside this repository,
inspect its provenance fields and upstream source terms. No warranty is made
that every research artifact is suitable for commercial reuse.
