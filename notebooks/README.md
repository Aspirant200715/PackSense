# Kaggle notebook handoff

`packsense-ai.ipynb` and `kernel-metadata.json` are the version-controlled
source for the existing [PackSense Kaggle notebook](https://www.kaggle.com/code/aspirant200715/packsense-ai).
The notebook is a **reference preprocessing and material-training preflight**,
not a trained recommendation model. Version 5 completed on 2026-09-27.

The notebook currently pins backend source commit `fecb787` and verifies the
attached source bundle against a SHA-256 manifest. It also verifies the two
reference workbook hashes before importing 5,000 food and 81 material rows.
Those files live in Kaggle input datasets, not this repository. Do not commit
private data or the withdrawn 672/72 quality CSVs here.

Version 5 writes `reference_import_summary.json` and
`material_training_preflight.json`. The latter explicitly returns
`not_ready`/`model_trained=false` because no genuine suitability register,
predeclared split plan, scenario batch, reviewed complete-structure catalogue,
or current backend bundle is attached. It must not create labels by joining
the food and material masters.

After the relevant backend PRs are reviewed and merged, refresh the Kaggle
source bundle from the exact merge commit, publish a new manifest, update the
notebook's pinned commit, and verify all hashes before running label intake or
training. Keep the 80/20 split manifest frozen before fitting preprocessing or
a model. Never report a test metric from a `not_ready` preflight.

With Kaggle CLI configured, push this reviewed notebook source using:

```powershell
kaggle kernels push --path notebooks
kaggle kernels status aspirant200715/packsense-ai
```

The Kaggle run and output must be checked separately from repository CI.
