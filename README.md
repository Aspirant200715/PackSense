# PackSense

**Current phase:** package-material selection. Shelf-life prediction is
deferred. A learned material ranker will be evaluated only after genuine,
reviewed scenario/complete-structure suitability labels are available; the
existing food and material workbooks are references, not those labels. See
[material-suitability evidence intake](docs/material-suitability.md).
The [existing Kaggle notebook](notebooks/packsense-ai.ipynb) is versioned in
the repository; it audits the two reference masters and explicitly withholds
training when suitability labels, a reviewed split, and source/rights approval
are missing. An exploratory CPU material classifier is implemented behind
those gates, but has **not** been trained or validated on real labels.
Its optional offline scorer is restricted to already shortlisted, reviewed
structures and cannot alter a recommendation or release a model.

PackSense is a planned decision-support backend for selecting food packaging. It takes a structured record describing a food, its pack size, and its storage and transport conditions. It will return feasible packaging structures and specifications, rank the feasible options, and estimate shelf life only where the prediction has been validated.

**Project status:** Backend contracts, Stops 1–2 scenario ingestion/exception auditing, exact food-reference enrichment, Stop 3 evidence-gated requirement cards, sourced food/material reference imports, package-structure draft intake and review gate, guarded local Stop 4 produce checks, a limited Stop 5 transfer-budget check, a preliminary non-respiring shortlist and batch report, an experimental food-property estimator, measured-trial schema intake, a trial group-split contract, and an evidence-gated exploratory shelf-life training runner are implemented. No approved food-protection limits, review-attested complete structures, or measured trial outcomes have been supplied. No shelf-life model has been trained or validated. Full package filtering, a validated package/shelf-life model, API, and frontend are not implemented yet. The architecture and implementation sequence below guide that work; they are not claims that the system already produces validated recommendations.

The current code uses Python 3.11 or newer and a pinned XLSX reader. From the
repository root, run `python -m pip install -r requirements.txt` followed by
`python -m unittest discover -s tests -v`. The
[living implementation log](docs/implementation-log.md) tracks the current
handoff, open PR stack, evidence blockers, and update rules. See
[backend data contracts](docs/data-contracts.md) for record meanings and
[scenario ingestion](docs/ingestion.md) for the batch
audit and its limits, and [reference imports](docs/reference-imports.md) for
coverage and evidence-status limitations. [Property estimation](docs/property-estimation.md)
reports the held-out baseline comparison and when estimates are withheld.
The [material training-readiness audit](docs/material-training-readiness.md)
distinguishes sourced OTR/WVTR values from measured, condition-complete labels.
The [food-reference join](docs/enrichment.md) explains exact identity matching,
temperature exposures, and the remaining fresh-produce classification gate.
[Food requirement cards](docs/requirements.md) explain the source-scoped
protection limits and why absent evidence cannot become a numeric OTR/WVTR.
[Produce respiration correction](docs/respiration.md) records the distinct
temperature exposures and its reference-atmosphere evidence boundary.
[Local produce gas balance](docs/gas-balance.md) checks measured O2/CO2
inventory fluxes without claiming a safe MAP trajectory.
[Local produce water checks](docs/water-balance.md) combine a source-scoped
vapor ledger and measured dew-point warning with the gas audit.
[Trial intake](docs/trial-intake.md) defines the observed-outcome schema and why
passing its checks does not yet authorize model training.
[Trial split manifests](docs/split-manifest.md) define source-family-separated
train/validation/test allocation and its refusal gates; no real split exists yet.
[Shelf-life training](docs/shelf-life-training.md) documents the reviewed-trial
baseline runner, its leakage controls, and why the current reference tables
cannot train it.
[Structure catalogue intake](docs/structure-catalogue.md) defines the exact
grade/gauge join and the separate evidence review required before a package
can be recommended.
[Public catalogue candidate intake](docs/public-catalogue-intake.md) compares
manufacturer and research sources and audits a small, source-backed product
register before any exact-grade join or package approval. The batch runner can
optionally show supplier-listed food/quantity/temperature application leads;
these are not model predictions or approved recommendations.
It can also trace one selected public candidate against each genuine scenario
to report exact published-use mismatches and the evidence needed for review,
without promoting a supplier claim into an approved package.
[Complete-structure review](docs/structure-review.md) checks external review
declarations against exact draft and source identities, without treating a
passing declaration as package feasibility. Its version-2 register requires
an explicit reviewed handling-severity scope before a scenario can enter the
preliminary shortlist or the material-ranker label intake.
[Finished-package transfer checking](docs/candidate-transfer.md) is an early
Stop 5 component: it can compare an exact-scope sourced cumulative transfer
with a food budget, but cannot yet declare any complete package feasible.
[Preliminary package shortlisting](docs/basic-recommendation.md) combines
reviewed structures and exact-scope transfer evidence for a limited basic
recommendation. Its batch command reports each structured scenario and any
missing evidence without inventing a candidate; an optional flat CSV helps
review large batches alongside the detailed JSON report.
[Frontend decision JSON](docs/frontend-contract.md) projects that audited
batch into stable input-exception, evidence-gap, and preliminary-shortlist
states for frontend design. It does not expose a trained material prediction
or promote a preliminary preference into a released package.
[Film-grade reference comparison](docs/grade-reference-comparison.md) adds an
opt-in, test-condition-matched Pareto view for reviewed non-respiring food
needs. It cannot choose or certify a finished package or train a model.
The same batch can optionally attach the [local fresh-produce gas/water
diagnostics](docs/basic-recommendation.md#optional-local-fresh-produce-diagnostics)
without promoting a snapshot to a MAP approval or package recommendation.

## Why PackSense exists

Packaging requirements change with the food and the journey. A dry, oily snack may need strong oxygen and water-vapour barriers to prevent rancidity and loss of crispness. Fresh produce continues to respire, so a film that is excellent for a snack may deplete oxygen and accumulate carbon dioxide around tomatoes. Temperature, humidity, pack geometry, sealing, handling, and the required shelf life all affect the choice.

PackSense is intended to help food processors, farmers, startups, and packaging engineers compare technically suitable options. It is a decision-support tool, not a substitute for supplier confirmation, food-contact review, and trials with the actual food and distribution route.

## Scope and operating principles

- **Backend first.** Build and validate the complete batch-data pipeline before starting a frontend. Frontend work begins only when the project owner explicitly requests that phase.
- **Structured dataset input.** Records arrive through a CSV/spreadsheet, database table, or API payload. Voice input and a conversational data-entry flow are not part of the agreed pipeline.
- **Complete packages, not material-name guesses.** A recommendation identifies the pack format, layer structure, thickness, sealant, and relevant barrier and mechanical specifications. A film-grade row alone is not a finished package.
- **Temperature is explicit throughout.** Storage temperature, transport mean temperature, and the highest credible excursion are separate inputs. Material properties, produce respiration, feasibility, ranking, and shelf-life prediction must be evaluated for the applicable conditions.
- **No silent completion of critical inputs.** Missing or contradictory scenario facts produce a traceable exception. Estimated or proxy reference values remain labelled as such and cannot become measured training outcomes.
- **Safety before preferences.** Food-contact, compatibility, service-temperature, sealing, mechanical, and fresh-produce gas-safety limits are hard filters. Cost or sustainability cannot make an unsafe package feasible.
- **Evidence before confidence.** Predictions state their range, limiting failure mechanism, validation domain, and data/model version. Unsupported cases receive a warning or no numerical prediction.

## The eight-stop architecture

The backend will preserve the order and responsibilities of *PackSense Architecture in Simple Steps Final Revised*.

1. **Dataset input:** Parse each commodity and storage/transport scenario, validate the schema and units, and retain the original values.
2. **Validate and enrich:** Check ranges and cross-field consistency. Attach versioned food, material, package-structure, and compatibility reference data. Send records lacking critical facts to an exception report.
3. **Food needs:** Derive a requirement card for oxygen and moisture protection, sealing, strength, light, food contact, and service temperature before examining candidate structures.
4. **Fresh-produce path:** For respiring food, correct respiration from its measurement temperature to each exposure segment. Balance oxygen entry, carbon-dioxide exit, water loss, condensation, film transfer, and any perforations, including at the maximum excursion.
5. **Find packages:** Generate manufacturable complete structures and thicknesses. Correct material data to scenario conditions only with validated supplier data or correction models; remove candidates that fail mandatory limits.
6. **Rank:** Score only feasible candidates for protection, reliability, cost, and sustainability using a named, version-controlled scoring configuration.
7. **Predict:** Evaluate likely failure mechanisms across the temperature profile. Combine the physical baseline with a model trained on **measured** food-package-condition trials, and compare the supported shelf-life result with the requested target. A candidate that misses the target is removed or reconsidered.
8. **Output:** Write an auditable recommendation record containing the preferred complete structure, specifications, compliant alternatives, shelf-life range, operating limits, warnings, and the versions of all inputs, rules, scores, and models used.

Non-respiring foods bypass Stop 4. The same base scenario schema serves both paths, with respiration fields conditionally required for relevant fresh produce.

## Input and output contracts

Each input row is **one recommendation scenario**, not simply one food entry. The same commodity can appear in several rows for different pack sizes, temperatures, routes, or shelf-life targets.

Core scenario fields are:

```text
record_id, commodity_type, moisture_content_pct, oil_fat_content_pct, pH,
desired_shelf_life_days, storage_type, storage_temperature_c,
storage_relative_humidity_pct, transport_mode, transport_duration_hours,
transport_temperature_c, transport_max_temperature_c,
transport_handling_severity, net_pack_quantity, net_pack_quantity_unit
```

Respiring produce additionally needs `respiration_rate`, `respiration_rate_unit`, and `respiration_reference_temperature_c`. The actual schema will also define allowed categories, units, plausible ranges, source flags, and conditional requirements. In particular, `storage_type = ambient` does not replace an exact temperature, and `transport_max_temperature_c` cannot be below the transport mean.

An optional `food_reference_id` selects a specific source row when two entries
share the same commodity name. It is a join key, never an ML feature. Without
it, Stop 2 accepts only a unique exact commodity-name match.

The planned batch output includes:

- Preferred package format, layer order, total and layer thicknesses, and ranked compliant alternatives.
- OTR and WVTR at the relevant temperature and humidity, with their test conditions and correction source; sealability, sealing window, and mechanical requirements.
- For produce, supported O2/CO2 ranges, film/perforation specification, MAP suitability, water-management warnings, and the highest verified temperature.
- Predicted shelf life **only within a validated domain**, its interval, limiting failure mechanism, confidence status, and target-life decision.
- Source IDs, dataset row ID, exceptions, compatibility decisions, scoring configuration, and model/rule versions so the result can be reproduced.

## Data assets and what they can teach the model

The existing food-input workbook is a **commodity reference**: it helps describe foods, but its rows are not complete package trials or complete storage scenarios. The packaging-material workbook is a **material-grade reference**: it supplies reported properties and clearly flagged estimates, but it does not by itself establish the performance of a finished multilayer package. The backend also needs a catalogue of actual manufacturable structures and validated food-contact/compatibility evidence.

The current material-ranking target needs a separate set of genuine,
source-reviewed **scenario/complete-package suitability judgements**. The
[material-suitability intake](docs/material-suitability.md) checks their
identity and provenance fields but does not certify their scientific validity.
The deferred shelf-life target instead requires a **trial-outcomes dataset**.
One record must link a known food, complete package and gauge, pack
area/headspace/fill mass, storage and transport exposure, trial/batch/source
identifiers, a stated quality-failure criterion, and the observed time to
failure. It must record whether failure was actually observed. If the package
is still acceptable when observation ends, that observation is
*right-censored*; the last observed day is not its failure day.

`desired_shelf_life_days` is a requirement from the input scenario, **not** the observed shelf-life label. Generic storage-life guidance, proxy pH values, screening estimates of material permeability, and illustrative examples must not be converted into measured labels. A Cartesian join between the food and material sheets creates possible combinations, not real experimental outcomes.

The first validation pilots will follow the architecture's two examples: an oily dry snack and tomatoes. They exercise different limiting mechanisms. Other foods and package families will be added only as trial coverage and independent validation support them. Third-party PDFs, supplier sheets, and extracted data must retain source, conditions, and usage-rights information; they should not be committed to the repository without a rights review.

## Training and evaluation plan

The current phase's first learned task is suitability ranking **within the
hard-filtered candidate set**, provided genuine, reviewed labels become
available. OTR, WVTR, gas balance, and hard compatibility limits remain
engineering or measured-property checks. We will not train on Cartesian
food/material combinations or mistake agreement with expert labels for
experimentally proven package performance. The shelf-life training plan below
is deferred and does not block material-selection work.

For material ranking, first audit the real suitability register and review
its sources and rights. Freeze a source-family-grouped 80/20 holdout before
fitting a model or imputer. Compare a simple ranker with the existing
engineering shortlist on the untouched test groups, reporting top-k agreement,
false-suitable decisions, calibration, and food/temperature subgroup results.
Only a model that improves the baseline within a documented validation scope
may affect the ranking of already feasible structures. The current workbooks
do not yet permit this training run, including in Kaggle.

### Deferred shelf-life training

1. **Build the physical baseline.** Estimate relevant moisture and oxygen failure paths for the dry-food pilot, and temperature-dependent respiration, gas balance, water loss, and quality paths for produce. Validate each calculation against hand-worked cases and source data.
2. **Freeze the split before fitting.** Keep all measurements, replicates, and package comparisons from an independent trial/batch group together. Target an 80% development portion and a 20% untouched test portion; use group-separated validation or cross-validation only inside the 80% development portion. Since groups cannot be divided, accept only a documented group-level tolerance. Reserve additional unseen-food, unseen-grade, or external-source challenge tests when evidence permits. If coverage is too weak, report exploratory results rather than claiming generalization.
3. **Train against real outcomes.** Compare a simple family baseline and the physical baseline with a tabular model that learns residual error on measured, uncensored failure times. Use a censor-aware survival approach when including right-censored trials. Evaluate dry and fresh-produce mechanisms separately before considering a broader model.
4. **Prevent leakage.** Fit imputers, encoders, physical coefficients derived from trials, feature selectors, and hyperparameters on training folds only. Never use the untouched test set to choose features, stopping rounds, score weights, or acceptable error limits.
5. **Choose training length by validation.** The initial gradient-boosted tree model uses *boosting iterations*, not neural-network epochs. A starting ceiling of 1,000 iterations with early stopping after roughly 20 non-improving iterations on an explicitly group-held-out validation set is a tuning plan, not an accuracy promise. Record the actual selected iteration count. A neural model and GPU training are not requirements for the initial backend.
6. **Report decision-relevant metrics.** Report MAE and RMSE in days on observed failures, by food/package/temperature subgroup; compare with the physics-only baseline. Assess the probability of meeting the requested life, its calibration and false-safe rate. Report empirical coverage and width of a stated prediction interval. Use censor-aware metrics, such as a time-dependent Brier score, when censored trials are included. Automated tests should find no known mandatory-filter violations.
7. **Release only within evidence.** Predeclare acceptable error, false-safe, and interval-coverage criteria before opening the test set. Promote a learned model only if it improves the independently tested baseline and survives prospective pilot trials. If the learned correction fails, retain a separately validated baseline; otherwise withhold the numerical prediction. Out-of-domain cases must not receive unjustified precision.

Every training run will record input-data hashes, trial and split IDs, feature schema, code commit, model parameters, selected iteration count, metrics, calibration, and supported commodity/condition range. More training iterations, a GPU, or Google Colab cannot compensate for missing measured trial outcomes.

## Backend-first branch and PR sequence

Implementation began after the project owner's approval. The sequence below remains the review order; do not treat a planned branch as completed work. Each PR should include relevant tests and a reproducible command. Data fixtures must be sourced and traceable, and example outputs belong only where a working stage can produce them. Merge one reviewable change at a time.

Current priority inserts source-reviewed material-suitability intake and later
grouped ranking evaluation after candidate filtering. The shelf-life trial and
model branches listed below are deferred; the architecture's safety gates and
eventual output contract are unchanged.

1. `feat/01-contracts` — repository tooling and CI; typed input, reference, trial, and output schemas; units and schema-only tests. Any future data fixtures must be sourced and traceable.
2. `feat/02-ingestion` — Stops 1–2 batch loading, schema/range/cross-field checks, unit conversion, and exception report.
3. `feat/03-masters` — versioned food/material imports, property source flags, structure catalogue, and compatibility joins.
4. `feat/04-requirements` — Stop 3 barrier, seal, mechanical, contact, and temperature requirement calculations.
5. `feat/05-produce` — Stop 4 temperature-corrected respiration and gas/perforation balance at storage, transit, and excursion temperatures.
6. `feat/06-candidates` — Stop 5 complete-structure generation, validated property corrections, and hard-filter audit trail.
7. `feat/07-ranking` — Stop 6 deterministic scoring of feasible structures with versioned weights and sourced cost/sustainability inputs.
8. `data/08-trials` — trial-outcome import, provenance checks, event/censor flags, duplicate control, and immutable split manifest. Trial evidence collection begins earlier, alongside the engineering work.
9. `ml/09-shelf-life` — Stop 7 physical baseline, grouped training, early stopping, blind evaluation, uncertainty, and a model card.
10. `feat/10-output` — Stop 7 target-life feedback and Stop 8 auditable batch CSV/JSON outputs, alternatives, and warnings.
11. `test/11-pilot` — end-to-end dry-snack and tomato checks, prospective comparison, failure review, and backend release gate.

The first implementation PR established the contracts. Several subsequent
backend slices are merged; consult the implementation log for their exact
status. Later branches remain planned until their evidence gates are met.

## References for the training protocol

- [Grouped cross-validation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html)
- [Histogram gradient boosting and early stopping](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
- [Avoiding data leakage](https://scikit-learn.org/stable/common_pitfalls.html)
- [Right-censored outcome data](https://scikit-survival.readthedocs.io/en/stable/user_guide/00-introduction.html)
