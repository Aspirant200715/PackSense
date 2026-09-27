# Shelf-life training baseline

`packsense.shelf_life_model` is the first executable Stop 7 training path. It
uses the measured-trial intake, externally reviewed trial register, and frozen
group split contract. It is a CPU research baseline, not a package selector,
production prediction endpoint, or safety approval.

## Evidence required

The command requires a CSV or one selected XLSX sheet that passes
[`trial-intake.md`](trial-intake.md), plus the review register and split plan
described in [`split-manifest.md`](split-manifest.md). It also requires the
food and material reference masters, a complete-structure catalogue, and its
review register. Before any split or fit, each trial must join to one exact
food and review-attested complete structure, the stated catalogue version and
structure review, and a structure whose food scope, grades, and service
temperature cover the trial. Broken links produce `not_ready`, without a
split or model. These joins do not authenticate the underlying documents.

The current food and material workbooks are reference masters, not trial
labels, and cannot be used as substitutes. The split builder must return
`allocation_prepared`; otherwise the command writes a `not_ready` report and
does not fit a model.

The selected outcome is `observed_days` only for rows where
`failure_observed=true`. Every row must use the same recorded failure
criterion and threshold. Right-censored rows remain in the split and are
reported, but this initial regressor excludes them from fitting and error
metrics. It also reports whether test predictions fall below a censored
observation's known minimum life. That diagnostic is not a survival-analysis
metric. Do not describe this baseline as censor-aware.

## Features and leakage controls

The initial feature set is limited to the exact food ID, complete structure ID
and catalogue version; fill mass, package area and headspace; storage
temperature and relative humidity; and the available transport mean, maximum
temperature and duration. Trial IDs, batch/source/group identifiers,
locators, observed days, failure flags, failure mechanisms, and endpoint text
are not model features. The endpoint must be uniform across the training file.

Missing optional numeric inputs are imputed using training rows only. Features
that are entirely missing in training are omitted and recorded. Categorical
encoding is fitted on the development data and ignores unseen categories.
The model therefore has no validated basis for predicting a new food or
structure. The pre-fit reference join is an identity/scope gate, not yet an
expanded model feature join. This first feature set does not yet use food
composition, respiration, approved structure layers, or measured
finished-package barrier properties. Results must remain limited to
represented evidence.

The predeclared split targets 80% development and 20% untouched test by
independence group. The development portion contains disjoint train and
validation groups; because groups are indivisible, the split contract allows
75–85% development and 15–25% test, with validation comprising 10–25% of
development groups. The candidate is fit on the training groups, and the
number of boosting iterations is chosen using validation MAE against a
training-median baseline. If it does not beat that baseline, the test is not
opened and no model artifact is written. If it does, preprocessing and the
selected model are refit on all development groups; only then are test metrics
computed once. The test results are exploratory. The module never marks the
model validated or produces a `ShelfLifeResult`.

## Run

From the repository root, with the project environment installed:

```powershell
python -m packsense.shelf_life_model MEASURED_TRIALS.csv `
  --reviews REVIEW_REGISTER.json `
  --plan SPLIT_PLAN.json `
  --food-master FOOD_MASTER.xlsx `
  --material-master MATERIAL_MASTER.xlsx `
  --structures STRUCTURE_CATALOGUE.json `
  --structure-reviews STRUCTURE_REVIEW_REGISTER.json `
  --report NEW_TRAINING_REPORT.json `
  --model NEW_MODEL.joblib
```

For XLSX, also supply `--sheet "Worksheet name"`. Output paths must be new;
existing reports and model files are preserved. The report records the trial,
food, material, structure, review, plan and manifest hashes, selected
boosting iteration, baseline and candidate metrics, feature fields, censor
counts, software version, and limitations. The model artifact includes the
fitted preprocessing and regressor with those source/split hashes. Treat
Joblib artifacts as trusted Python objects and load only files produced by
the controlled PackSense pipeline.

The default ceiling is 1,000 boosting iterations with validation early
stopping after 20 non-improving iterations. These are tree iterations, not
neural-network epochs. CPU execution is the default; no GPU or neural network
is required.

## Release boundary

This code does not authenticate source documents, approvals, or data-use
rights. Human review IDs are only structurally checked. The first release
candidate must still be compared with a physical/simple baseline, evaluated
on independent data, checked by food/structure/temperature/failure mechanism,
and prospectively piloted. A good score on the frozen test set alone does not
authorize package recommendations or shelf-life claims. Censor-aware survival
training, richer source-backed physical features, uncertainty intervals, and
release thresholds remain future work.
