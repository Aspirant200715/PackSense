# Experimental food-property estimation

This Stop-2 extension estimates **missing reference moisture or fat only**.
It is not a food-to-package model, a shelf-life model, or a replacement for a
product measurement. `pH` is deliberately excluded from training: the 720
populated source values are proxy/range-midpoint or reported reference values,
not observed pH labels for the exact listed products. Respiration is also
excluded because the 116 available values are sparse CO2-evolution references
at stated temperatures, not a broadly validated temperature-response model.

The fixed first candidate trains only on nutrient rows whose source derivation
code is `A` (analytical), as defined in the
[USDA FoodData Central field dictionary](https://fdc.nal.usda.gov/portal-data/external/dataDictionary).
This is an analytical derivation status for a reference value, not proof of a
measurement from the exact product and batch being packaged. Other reported
composition values remain imported references but are not training labels in
this experiment.

The estimator uses character n-gram TF-IDF of food name and group followed by
ridge regression. Related food-name prefixes stay together in a
reproducible group split. It reserves 20% of independent groups as an
untouched test set; within the remaining 80% development portion, separate
calibration groups set a 90% absolute-residual interval. The vectorizer and
regressor are fitted only on the remaining development training families.
Untouched test families evaluate error and interval coverage.
The comparison baseline is the food-group median fitted on training rows only.
No test values, missing rows, package data, desired-life targets, or proxy pH
values are used to fit the model. Train/calibration/test groups are
approximately 64/16/20 (80% development and 20% untouched test); row counts
differ because whole families stay together. Ridge has no neural-network
epochs.

Run one target at a time:

```text
python -m packsense.property_estimation path/to/food.xlsx --target moisture_content_pct
python -m packsense.property_estimation path/to/food.xlsx --target oil_fat_content_pct
```

The optional `--estimates-report new-path.json` saves labelled estimates for
missing rows only when the model beats the baseline on test MAE. An estimate
is withheld if its raw predicted percentage is outside 0–100 or its interval
spans the entire 0–100 range; neither case is converted to a plausible zero.
The command never overwrites a file or fills the original workbook. Every estimate carries the
source hash, model version, interval, and
`experimental_model_estimate_not_measurement` basis. These values must not
satisfy food-contact, gas-safety, or shelf-life hard filters.

On the USDA-Handbook-enriched workbook (SHA-256
`76c5f78c6f6a0ef3c1e5bed7baa442ac9275146198be7de22bbdfe5ef80ccd9f`),
the `A`-only held-out evaluation found:

- Moisture: 4,888 source values, including 2,710 `A`-coded training/evaluation
  labels; 112 missing. Test MAE was 12.22 percentage points for the model
  versus 17.77 for the group-median baseline. The 90% calibration radius was
  still 31.30 points, with 92.2% empirical coverage on the test rows. The
  108 of 112 missing rows receive optional experimental estimates; four are
  withheld by the physical-range/information gate. These are not precise
  composition results.
- Fat: 4,766 source values, including 2,614 `A`-coded labels; 234 missing.
  Test MAE was 6.62 points versus 6.43 for the baseline. The model therefore
  withholds fat estimates. Its calibration radius was 12.84 points, with
  89.3% empirical test coverage.

These figures are from one family-held-out split of analytical-derivation
reference values, not independent laboratory validation. An earlier exploratory
run included all reported composition values; its test results were inspected
before the source-code restriction was applied. Thus the current test is not
a pristine external challenge set. Further model selection must use new
development folds and a separate new blind/external evaluation, not tune
repeatedly on the test rows already inspected.
Food-group and name-prefix grouping reduces near-duplicate leakage but does
not prove independence across all related foods. No claim of perfect material
prediction is supported by these metrics.

Method references: [grouped splitting](https://scikit-learn.org/1.8/modules/generated/sklearn.model_selection.GroupShuffleSplit.html),
[TF-IDF features](https://scikit-learn.org/1.8/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html),
[ridge regression](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.Ridge.html),
and [leakage prevention](https://scikit-learn.org/1.8/common_pitfalls.html).
