# Measured-trial split manifest

This backend slice allocates **measured trial outcomes**, not food-reference or
material-reference rows. It is the gate after [trial intake](trial-intake.md)
and before any trial-derived imputer, coefficient, model, calibration, or
performance metric. A guarded shelf-life training runner now consumes this
manifest, but no trial-outcome dataset or split manifest is bundled and no
real model has been trained. The code does **not** train a packaging selector.

## What must be reviewed first

Run trial intake on a CSV or an explicitly named XLSX worksheet. Every row
must pass the trial schema. A human evidence review must then verify the
source record, data-use rights, actual measured failure endpoint, complete
finished-package identity, and independence/duplicate relationships. The
review JSON records **IDs of those external decisions**; non-empty IDs alone
cannot prove their authenticity or that the package catalogue joins pass.
Do not generate approval IDs merely to make the splitter accept a file.

The review register has exactly these top-level fields:

```text
schema_version: 1
trial_source_sha256: lowercase SHA-256 of the exact trial CSV/XLSX file
reviews: one object per accepted trial, with exactly:
  trial_id, trial_digest, independence_group_id,
  evidence_review_id, rights_review_id, endpoint_review_id,
  structure_review_id, independence_review_id
```

`trial_digest` is the SHA-256 of PackSense's canonical parsed trial entry,
including row number, source locator, physical context, and observed or
right-censored outcome. It binds a review to a specific accepted row, not
just a trial ID. The independence group is a reviewed source/study family.
To list the IDs and digests for an intake-clean file without inventing review
decisions, run this from the repository root (adjust the path and `sheet_name`
for XLSX):

```python
from packsense.trials import audit_trial_outcomes
from packsense.splits import trial_digest

audit = audit_trial_outcomes("PATH_TO_MEASURED_TRIALS.csv")
assert not audit.issues
for entry in audit.entries:
    print(entry.outcome.trial_id, trial_digest(entry))
```

PowerShell's `Get-FileHash PATH_TO_MEASURED_TRIALS.csv -Algorithm SHA256`
gives the file hash for the register. Hash the completed review JSON in the
same way for the plan, using lowercase hex characters in both files.
Replicates, related batches, reused experiments, and all rows from one
`source_id` must stay in one group. When a source contains more than one
otherwise-independent experiment, conservatively keep the whole source in
one partition. Cross-source reuse still requires human duplicate review;
textual equality checks cannot establish independence.

The plan JSON has exactly:

```text
schema_version: 1
plan_id: non-empty versioned identifier
trial_source_sha256: same trial-file SHA-256
review_register_sha256: SHA-256 of the exact review JSON bytes
train_groups: array of reviewed independence_group_id values
validation_groups: array of reviewed independence_group_id values
test_groups: array of reviewed independence_group_id values
```

Specify the group allocation before fitting or examining model errors. A
changed trial file invalidates the review and plan hashes; a changed review
file invalidates the plan hash. The manifest records the exact source, review,
and plan hashes and its own content hash. Files are created at new paths and
not overwritten by the command, but repository/data governance must still
preserve the original files and their review evidence.

## Allocation command and refusal rules

```powershell
python -m packsense.splits PATH_TO_MEASURED_TRIALS.csv --reviews REVIEW.json --plan PLAN.json --report NEW_AUDIT.json --manifest NEW_MANIFEST.json
```

For a multi-sheet XLSX file, add `--sheet SHEET_NAME`. `--report` is required
even when the allocation is refused; `--manifest` is optional for audit-only
checks. The command exits 0 only when an allocation is prepared, 1 when the
data/plan fail its gates, and 2 on input/output errors. It never overwrites
an existing report or manifest. A failed allocation writes only the audit,
not a manifest.

Allocation is refused when there are rejected or unreviewed trial rows,
stale hashes/digests, missing or extra groups, a source/trial group/batch
spread across independence groups, or a group appearing in more than one
partition. The predeclared **minimum allocation check** is at least 8
training, 2 validation, and 2 test independent groups. The target is an
80% development portion and 20% untouched test portion. Whole-group
constraints allow a documented tolerance of 75–85% development and 15–25%
test groups. Validation groups must represent 10–25% of development groups;
they are used internally for model selection, then training and validation
groups are combined to fit the final model before the test is opened.
At least 4/2/2 groups must contain an **observed failure** in those
partitions. At least one exact `food_id` must have observed failures in
all three partitions. Right-censored observations are counted separately,
never re-labelled as failures.

These are minimum checks to avoid a patently invalid split, **not** a claim
of sufficient statistical power, representative food/structure/temperature
coverage, or training readiness. `supported_food_ids` only identifies food
IDs with event presence in each partition; it is not an authorization to
predict for them. The audit reports group and row fractions separately so a
few very large groups cannot be mistaken for balanced row coverage. Study-
family grouping may make the minimum impossible with
today's evidence, in which case the correct result is `not_ready`.

## How to use the partitions later

- Fit every imputer, encoder, scaler, feature selector, trial-derived physical
  coefficient, and model inside the **80% development** portion. Validation
  groups stay within that portion; use grouped cross-validation there when
  sample size permits.
- Use internal validation for stopping, model comparison, interval/calibration work,
  and a predeclared promotion decision. Do not search the untouched test
  partition for features, thresholds, or favourable subgroups.
- Open the test partition once for the frozen model and predeclared metrics.
  Report observed-event error and censor-aware evaluation separately, with
  food, structure, temperature, source, and failure-mechanism coverage.
  Do not treat a right-censored day as a known failure time.
- Evaluate dry and respiring-produce mechanisms separately. A real-world
  prospective pilot and release checks are still required before a package
  recommendation or shelf-life claim.

`allocation_prepared` means only that this deterministic group assignment
passed its mechanical checks. `model_trained` and `model_validated` remain
false. The current repo has no measured outcomes and therefore no real split,
fitted model, holdout score, or claimed prediction accuracy.
