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
split validator can then freeze an approximately 80/20 group-separated holdout
before fitting any encoder, imputer, model, or scoring weight. It must compare
against the existing engineering shortlist and report false-suitable errors,
top-k agreement, calibration, and subgroup behavior. Results on expert labels
measure agreement with those reviewers, not experimentally proven package
performance. Weak coverage means `not_ready`, not a training run or accuracy
claim.

The Kaggle notebook pins a reviewed backend source commit, audits the two
reference workbooks, and then checks for six separate training inputs. The
current attached datasets contain **none** of those training inputs, so no
material model has been fit. The CPU baseline is regularized logistic
regression, selected on a separate validation partition; its solver iteration
cap is not a neural-network epoch count. No test score or accuracy is reported
when the gate is not ready.

## Frozen material split

`packsense.material_split` accepts a separate, predeclared JSON plan with
exactly `schema_version: 1`, `plan_id`, `suitability_register_sha256`, and
`train_groups`, `validation_groups`, `test_groups` arrays. Group IDs refer to
the source-family IDs in the approved suitability register. The plan is
hashed, so a later training run can identify the exact holdout allocation.
There is no search over split seeds after seeing model scores.

The validator refuses a plan if the label intake has rejected rows, the
register hash differs, a group is missing/unknown/repeated across partitions,
one source ID appears in multiple source families, or the same food reference
or normalized commodity name appears in more than one partition. Each partition must have explicit suitable
and unsuitable judgements from independent source families. The code floor is
8/2/2 source families for train/validation/test, with at least 2/1/1 families
per decision. The test rows must comprise 15–25% of labels and validation
15–25% of the remaining development labels; whole groups take precedence over
an exact row ratio. These are **minimum software checks, not proof of external
validity**. Near-duplicate foods with different names and unseen-structure
generalization still require a separate challenge audit.

```powershell
python -m packsense.material_split labels.json --plan material-split-plan.json --scenarios scenarios.csv --food-master food.xlsx --material-master materials.xlsx --structures structures.json --structure-reviews reviews.json --report new-material-split-audit.json
```

A passing report contains the frozen label IDs per partition, source hashes,
plan hash, and manifest hash. It never exports raw workbook or source text,
trains a model, or certifies suitability. An empty real register returns
`not_ready`.

## Exploratory model gate

`packsense.material_model` accepts the audited label register, frozen split,
enriched scenarios, reviewed complete structures, and grade references. It
uses food composition, pH, temperature/humidity, transport, desired life,
pack quantity, layer-family sequence, and structure geometry. Food IDs,
structure IDs, source/review IDs, and the judgement are excluded from model
features. It fits imputation, encoding, scaling, and a regularized logistic
classifier on **train only**. The trainer independently rechecks source-family,
source-ID, food-reference, normalized commodity-name, and scenario separation
across the supplied in-memory partitions before fitting; a forged or stale
allocation cannot silently bypass these leakage boundaries. Validation
chooses the regularization strength;
the test partition is opened only if validation Brier score beats a constant
training-prevalence baseline. Test reporting includes suitable precision and
recall, unsuitable recall, false-suitable count/rate, average precision, and
Brier score. A passing score is agreement with reviewed judgements, not proof
of safe packaging or readiness to deploy. The estimator is not serialized or
connected to the recommendation engine.

Validation and test reports also include a conservative within-scenario
ranking diagnostic: among scenarios with **explicit suitable and unsuitable
judgements for different packages**, it reports strict top-choice hit rate,
pairwise ordering, and score ties. A top-score tie that includes an unsuitable
package is not counted as a hit. If no scenario has both decisions, the
ranking result is `not_evaluable`, not zero or an invented accuracy. These
metrics cover only judged alternatives and do not treat unlabelled packages
as negatives or establish performance on the full candidate catalogue.

Training additionally requires an explicit independent source/rights approval.
The notebook expects `material-training-approval.json` with exactly:

```json
{
  "schema_version": 1,
  "suitability_register_sha256": "<SHA-256 of the exact label JSON>",
  "split_plan_sha256": "<SHA-256 of the exact split-plan JSON>",
  "source_documents_checked": true,
  "label_decisions_checked": true,
  "data_use_rights_checked": true,
  "approver_id": "<real reviewer ID>",
  "approval_scope": "exploratory_material_training"
}
```

The approval records a human decision; the code cannot verify that the review
actually happened. Attach it only after reviewing the original findings,
decision criteria, independent source families, and usage rights. The other
five required files are `material-suitability-labels.json`,
`material-split-plan.json`, `material-scenarios.csv`,
`material-structures.json`, and `material-structure-reviews.json`. The
notebook reports `not_ready` while any are missing, preserving the reference
import results without inventing labels or fitting a model.

### Offline candidate-score boundary

After a genuine, reviewed register eventually passes the frozen split and the
exploratory validation/test sequence, `score_exploratory_candidates` can compare
the model's uncalibrated score for a **reviewed suitability judgement** on structures
that already passed the engineering shortlist. It refuses mismatched food,
scenario fingerprint, master/catalogue/review hashes, missing grade identities,
unresolved transfer checks, a failed held-out Brier baseline, or invalid model
probabilities. It never scores supplier-application leads or bypasses the hard
food-contact, temperature, gas, barrier, seal, and handling gates. It returns a
separate offline report, never changes the engineering preference, and does
not produce a deployable model artifact.

The training report now distinguishes `model_evaluated` from `model_validated`.
An exploratory held-out test can set the former to true, but keeps the latter
false and release withheld. Even a test Brier score better than the constant
training-prevalence baseline is evidence about agreement with reviewed labels,
not proof that the package is safe or suitable in operation. With the current
real files this scoring path remains `not_ready`; no real suitability register,
reviewed structure catalogue, split, or trained estimator is present.
