# Measured trial-outcome intake

This is an early, limited part of the planned `data/08-trials` work. It reads a
CSV or one explicitly selected XLSX worksheet containing **observed**
food-package-condition trials. It does not create trial data, fit a model,
certify a source, or claim that a package is safe.

Run `py -3.11 -m packsense.trials PATH_TO_TRIALS.csv` to see a summary. Use
`--report NEW_REPORT.json` to save row-level exceptions without overwriting an
existing report. There is no supplied trial-outcome file in the current PS2
assets; the food and material workbooks must not be passed in as trial labels.

## Withdrawn quality CSVs

The project owner withdrew `packsense_public_measured_quality_raw_672.csv`
and `packsense_public_measured_quality_packages_72.csv` from this work. Their
rows are not accepted trial outcomes and must not enter the split manifest,
shelf-life trainer, or package recommendation inputs. Earlier experiments on
the `data/21-public-quality-audit` branch were reverted. The final branch
adds no data importer, quality labels, model artifact, or training result.
Any later measured-trial source must pass the intake and independent evidence
review described below before training.

## Required columns and meaning

The exact CSV/XLSX header is `TRIAL_REQUIRED_COLUMNS` in
`packsense/trials.py`. The trial, group, batch, and source IDs identify an
independent experiment and its provenance. `source_locator` points to the
underlying document or laboratory record; a non-empty locator is necessary
but **not** proof that the source is authentic. `evidence_basis` must be
`measured_trial`. `food_id`, `structure_id`, and
`structure_catalogue_version` are join keys to verified reference records,
not model features copied from a food/material cross product.

The physical context is `fill_mass_g`, `package_area_m2`, `headspace_ml`,
`storage_temperature_c`, and `storage_relative_humidity_pct`. `observed_days`
is time from the trial's defined start to last observation. When
`failure_observed=true`, that day is the observed failure event. When false,
the observation is **right-censored**; the food was still acceptable at that
time, and the day must not be used as an uncensored failure label.
`failure_criterion` and `failure_threshold` must state the measurable endpoint
used in both cases. The criterion cannot be replaced by a generic product
storage recommendation.

Optional columns are `failure_mechanism`, `exposure_profile_id`, and the
complete trio `transport_temperature_c`, `transport_max_temperature_c`,
`transport_duration_hours`. A profile ID can point to more detailed recorded
temperature history when the constant values are inadequate. Numeric units
are fixed by the column names. Partial transport exposure, invalid physical
ranges, non-finite values, formulas, duplicate trial IDs, and a batch assigned
to different split groups within one source are rejected with row reasons.
Unknown columns are rejected; in particular, `desired_shelf_life_days` is a
scenario requirement and is **not** a permissible trial-outcome column.

## What the audit does not establish

`schema_valid_rows` means only that rows satisfy this intake contract. Before
training, a separate evidence review must verify each source, endpoint,
independent trial/batch grouping, data-use rights, food identity, finished
package structure and gauge, exposure record, and duplicate experiments
across sources. The structure catalogue is not yet available, so those joins
cannot pass today. The report deliberately says `training_readiness` is
`no_valid_trials`, `no_observed_failures`, or `not_assessed`; it never says
"ready". No split or metric may be claimed from intake alone.

The [split-manifest contract](split-manifest.md) can prepare a group-separated
train/validation/test allocation only after trial/source/rights/endpoint and
independence reviews are recorded. It does not establish training readiness.
Freeze the reviewed allocation **before** fitting imputation, physical
coefficients, model, or calibration. Evaluate dry and fresh-produce mechanisms
separately. Use uncensored failures for an initial regression comparison and
a censor-aware method for right-censored evidence. The untouched test set and
a prospective pilot remain separate release gates.
