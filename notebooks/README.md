# Kaggle notebook handoff

`packsense-ai.ipynb` and `kernel-metadata.json` are the version-controlled
source for the existing [PackSense Kaggle notebook](https://www.kaggle.com/code/aspirant200715/packsense-ai).
The notebook is a **reference preprocessing and evidence-gated exploratory
material-training workflow**, not a trained recommendation model. Version 5
completed on 2026-09-27; version 6 completed on the same date and pins source
commit `7301542`.

The notebook now pins backend source commit `7301542` and verifies the
attached source bundle against a SHA-256 manifest. It also verifies the two
reference workbook hashes before importing 5,000 food and 81 material rows.
Those files live in Kaggle input datasets, not this repository. Do not commit
private data or the withdrawn 672/72 quality CSVs here.

The notebook writes `reference_import_summary.json` and
`material_training_preflight.json`. With current attachments the latter returns
`not_ready`/`model_trained=false` because genuine suitability labels, a
predeclared split plan, a scenario batch, reviewed complete structures, and a
source/rights approval are absent. If all inputs are attached, it audits them
and invokes the guarded CPU trainer; only aggregate diagnostics are written to
`material_training_result.json`. It must not create labels by joining the food
and material masters. No model artifact is published by this public notebook.

The source bundle must be refreshed from the exact pinned source commit and
verified after upload. Keep the 80/20 split manifest frozen before fitting any
preprocessing or model. Never report a test metric from a `not_ready`
preflight. See [material suitability](../docs/material-suitability.md) for the
six required inputs and the human approval boundary.

With Kaggle CLI configured, push this reviewed notebook source using:

```powershell
kaggle kernels push --path notebooks
kaggle kernels status aspirant200715/packsense-ai
```

The Kaggle run and output must be checked separately from repository CI.
