# Material-suitability learning: evidence intake

The current implementation priority is **package-material selection**. Shelf-life
prediction is deferred. The eight-stop architecture still applies: explicit
temperatures and food needs precede candidate filtering; food-contact, gas,
barrier, seal, mechanical, and service-temperature checks remain hard gates.
A future learned model may rank only candidates that pass those gates. It may
not turn a material-grade name into an approved finished package.

The 5,000-food and 81-grade workbooks are input references, **not** food-package
choice labels. A food/material Cartesian join, supplier application text,
retail packaging occurrence, or a generic permitted-material list does not
establish that a package is suitable for a specific scenario. The withdrawn
672-row and 72-row quality CSVs must not be used.

`packsense.material_suitability` is the first intake for independently sourced,
reviewed scenario/complete-structure judgements. It checks schema, hashes,
exact food identity, reviewed structure identity, explicit food scope, and
service-temperature coverage. It does **not** authenticate cited documents,
re-evaluate experimental findings, prove package safety, fit a model, or create
negative examples from absent pairs. The present repository includes no real
suitability register.

## Register contract

Supply a UTF-8 JSON object with exactly these top-level fields:

```text
schema_version = 1
scenario_sha256, food_master_sha256, material_master_sha256,
structure_catalogue_sha256, structure_review_sha256, labels
```

`labels` is an array with exactly one record per explicitly judged
`scenario_record_id`/`structure_id` pair. Every record has:

```text
label_id, scenario_record_id, food_reference_id, structure_id,
decision, evidence_basis, source_family_id, source_id, source_locator,
source_finding, decision_criterion, review_id, reviewer_id,
rights_review_id, rationale
```

`decision` is `suitable` or `unsuitable`; uncertainty must remain outside the
binary training set. `evidence_basis` is `measured_comparison` or
`independent_expert_assessment`. The source must **explicitly** support the
stated decision for the food, package, and conditions; the curator records its
specific finding and criterion, and an independent reviewer checks the
interpretation and usage rights. Merely finding that a package was used or
legally permitted is not enough. `source_family_id` groups related reports
and replicates for a future leakage-safe split. Distinct IDs or review text
are not proof that the source or review is genuine.

The complete structure must already be present in a source-backed catalogue
and pass the separate structure-review intake. A judgement for a different
food reference, a changed source version, an out-of-scope food, or any storage,
transport, or maximum-excursion temperature outside the structure's reviewed
service range is rejected. Multiple or conflicting decisions for one exact
scenario/structure pair are rejected instead of silently resolved.

Run the intake after preparing the scenario batch, masters, catalogue, and
review register:

```powershell
python -m packsense.material_suitability labels.json --scenarios scenarios.csv --food-master food.xlsx --material-master materials.xlsx --structures structures.json --structure-reviews reviews.json --report new-label-audit.json
```

The report gives accepted/rejected counts, label balance, distinct food and
structure coverage, independent source-family count, and reason codes. Exit
code 1 means row-level rejected labels; 2 means an input or version error.
Existing reports are never overwritten. No raw private workbook or label
content is exported to the report. `training_ready` remains false because
source review and a frozen independent split are outside this intake.

## Training gate and Kaggle

This audit is **necessary but not sufficient** for training. Before using
Kaggle, a reviewer must verify the actual source documents, label meaning,
rights, independence of source families, and coverage of both decisions. The
training code will then freeze an approximately 80/20 group-separated holdout
before fitting any encoder, imputer, model, or scoring weight. It must compare
against the existing engineering shortlist and report false-suitable errors,
top-k agreement, calibration, and subgroup behavior. Results on expert labels
measure agreement with those reviewers, not experimentally proven package
performance. Weak coverage means `not_ready`, not a training run or accuracy
claim.

The existing Kaggle notebook currently imports the two reference workbooks
with a pinned older backend bundle; it contains no suitability labels and has
not trained a material model. Its next version must pin the reviewed backend
commit and attach a versioned suitability register separately. No model is
fit until those checks pass. CPU is sufficient for the initial tabular model;
boosted trees use validated boosting iterations rather than arbitrary neural
network epochs.
