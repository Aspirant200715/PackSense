# PackSense implementation log and handoff

Last status check: 2026-09-27. This file is the living handoff for backend
work. It records what code exists, what evidence is still absent, and what
must happen before PackSense can make a defensible packaging recommendation.
It is not a validation certificate. Update the snapshot after merges and
append dated entries rather than rewriting past decisions.

## Current position

Before this branch, `main` was at `fecb787` (PR #18), following structure-review
merge `6a047ec` (PR #17), handoff merge `0bf9bd6` (PR #16), split-contract
merge `ee064da` (PR #15), and the earlier Stop 4/5 merges. This branch adds an
evidence-gated, CPU-only shelf-life regression runner; it does not fit or
validate a model without reviewed measured trials and a frozen split. The
existing backend contains the typed data
contracts, structured scenario ingestion and exception auditing, exact food
reference enrichment, food/material master imports, draft package-structure
intake, evidence-gated Stop 3 requirement cards, measured-trial *schema*
intake, an explicitly experimental moisture/fat reference estimator, guarded
Stop 4 local produce diagnostics, and a source-scoped Stop 5 transfer-budget
check, a group-separated measured-trial allocation contract, and a separate
complete-structure review gate. These are backend foundations; they do not
yet output a validated package or predicted shelf life. The unit-test
command passed 125 tests on synced `main` during
this status update.

The Stop 4 and partial Stop 5 PRs were reviewed and merged in dependency order:

1. [#9 — reviewed produce-route classification](https://github.com/Aspirant200715/PackSense/pull/9), based on `main`.
2. [#10 — source-scoped respiration temperature correction](https://github.com/Aspirant200715/PackSense/pull/10), based on #9.
3. [#11 — local produce gas-inventory balance](https://github.com/Aspirant200715/PackSense/pull/11), based on #10.
4. [#12 — local water checks and combined batch audit](https://github.com/Aspirant200715/PackSense/pull/12), retargeted from #11 to `main`.
5. [#14 — finished-package transfer-budget check](https://github.com/Aspirant200715/PackSense/pull/14), retargeted from #12 to `main`.

The Python 3.11 and 3.13 checks were green on every PR head at merge, and
each retargeted PR was mergeable with only its scoped files. There were no
submitted review, inline, or discussion comments. The green tests establish
contract and equation behavior, **not** food/package validation.

The Stop 4 calculations are guarded local diagnostics. The Q10 projection
is limited to its source reference atmosphere and validated temperatures;
CO2 evolution never becomes O2 consumption by assumption. The gas and water
ledgers use exact finished-package observations at each condition, and their
outputs never claim a safe MAP trajectory, condensation quantity, target-
life success, or a shelf-life prediction. No real reviewed route, kinetics,
finished-package gas, or finished-package water registers are bundled.

[PR #13](https://github.com/Aspirant200715/PackSense/pull/13) added this
independent log to `main`. Merged PR #14 compares a
source-reviewed cumulative finished-package transfer finding with one
applicable food budget under exact scenario and catalogue identifiers. A
within-budget result is **not** package feasibility; the report explicitly
withholds that claim.

## Evidence inventory and readiness

- The provisional food reference imports 5,000 rows. Moisture is present for
  4,888, fat for 4,766, pH for 720 (mostly proxy/range-midpoint), and CO2
  respiration for 116. These are commodity references, not recommendation
  scenarios or measured package outcomes. See
  [reference imports](reference-imports.md) for source hashes and limitations.
- The material reference imports 81 film-grade rows. Reported OTR/WVTR
  and flagged CO2TR values are grade observations at source test conditions,
  not verified finished-package performance. Only 13 CO2 observations have
  measured condition-complete training flags; 60 CO2 values are estimates.
- Kaggle kernel version 4 completed a hash-verified reference import on
  2026-09-27: 5,000/5,000 food rows and 81/81 material rows passed with no
  rejected rows. pH is present for 720 foods (709 proxy, 11 reported
  references), respiration for 116 foods, and only 13 material CO2TR rows
  have complete measured conditions. The run wrote an audit summary only;
  it did not create training labels or change training readiness.
- No approved complete package-structure catalogue is supplied. The
  [structure importer](structure-catalogue.md) creates drafts, never
  approval, from exact grade/gauge joins. The merged
  [review gate](structure-review.md) checks external declarations but cannot
  authenticate source documents or supply missing complete-structure evidence.
- No measured food–finished-package–condition trial-outcome dataset is
  supplied. The [trial intake](trial-intake.md) validates a future source
  file's *shape* and censoring flags; passing intake would not itself make
  that file suitable for model training.
- No reviewed food-failure transfer limits or complete producer-specific
  gas/water evidence registers are supplied. Current Stop 3/4 calculations
  therefore expose unknowns instead of filling safety-critical values.

**Training readiness: not ready.** Do not fit a food-to-material classifier,
train shelf life from requested life or generic storage guidance, or form
fake outcomes by joining food and material rows. No model can honestly be
called accurate from the present references alone. The reference estimator
has a separate, limited purpose; its outputs are not hard-filter evidence
or trial labels. The branch training runner is exercised only with ephemeral
`TEST_ONLY` unit fixtures; no real model artifact has been fitted.

## Next implementation and evidence gates

1. **Review real trials and freeze an actual leakage-safe split.** The
   [split-manifest contract](split-manifest.md) now checks stable source,
   trial, batch, food, and package identifiers; keeps related rows together;
   and refuses small, overlapping, or event-poor allocations. It has not
   been applied to real trials because none are supplied. Independently
   verify source evidence, rights, duplicate experiments across sources,
   complete structure joins, endpoint meaning, and group independence.
   Freeze a reviewed manifest before fitting any imputer, encoder, feature
   selector, calibration, or model. If the groups or coverage remain too
   weak, report `not_ready` instead of manufacturing an 80/20 holdout;
   keep validation internal to the development portion.
2. **Supply real pilot evidence before interpreting Stop 4 as a product
   result.** For a selected respiring food such as the planned tomato pilot,
   review exact food/form identity and independently sourced O2-consumption
   and CO2-production observations, their gas/temperature domains, finished-
   package gas and water transfer, fill mass, headspace, gas limits,
   transpiration, and humidity/surface conditions. Storage, transit, and
   excursion records must stay separate. If a required condition is absent,
   retain `unresolved`; do not substitute an analogue as a measured value.
3. **Build Stop 5 only on verified complete structures.** Record layer order,
   gauge, converter/manufacturability, seal and closure evidence, food-contact
   scope, service-temperature range, strength, and *finished-package*
   barrier/perforation data. Apply only source-validated corrections to
   scenario conditions. Implement an auditable hard-filter result for each
   structure; a grade row or draft alone cannot pass.
4. **Rank only feasible structures at Stop 6.** Version the scoring weights
   and source any cost/sustainability facts. Missing optional preference data
   should be labelled or excluded, never used to overcome a failed safety
   gate. Keep ranking distinct from the learned shelf-life model.
5. **Build and evaluate Stop 7 from independent measured trials.** Verify
   food, structure, gauge, fill/headspace/area, exposure, failure endpoint,
   source rights, batch/group ID, and observed event or right-censoring.
   Freeze a group-separated train/validation/test manifest before fitting;
   compare physical and simple baselines, then consider a residual tabular
   model with validation-based stopping. Report subgroup error, interval
   coverage, target-life calibration, false-safe decisions, and out-of-domain
   refusal. Do not choose features or thresholds on the untouched test set.
   CPU is sufficient for the first tabular baseline; GPU use is not a data
   substitute.
6. **Finish Stop 8 and pilot release.** Emit auditable preferred and
   alternative *complete* packages only after all hard checks, supported
   target-life evaluation, and source/model versions are available. Run the
   planned dry/oily snack and tomato pilots with prospective comparison.
   Frontend work remains deferred until the owner explicitly starts it.

The immediate dependency is evidence, not more training epochs. If no
approved structure or independent trials become available, engineering
modules may be tested with hand-worked **test-only** calculation cases, but
PackSense must continue to withhold a real package or shelf-life claim.

## Working rules for future contributors

- Preserve the eight-stop order in [README](../README.md) and the owner's
  *PackSense Architecture in Simple Steps Final Revised* document. The
  owner-held DOCX is not committed; the README is the repo-accessible
  architecture summary.
- Treat scenario inputs, commodity references, film-grade references,
  approved finished-package structures, and measured trial outcomes as
  different records. Keep source IDs, original conditions, basis, approval,
  and file hash with any derived value.
- Do not overwrite a source workbook to hide blanks. An estimate or proxy
  may be useful exploratory context only when labelled and validated for
  that use; it must not become a measured training label or safety pass.
- Keep PRs small and state their exact scope, test command, data additions,
  evidence limitations, and known blockers. Leave frontend changes out of
  backend PRs. Update this log in the same PR when a gate meaningfully moves.

## Append-only change entries

### 2026-09-26 — status log established

- `main`: `2fa21e3`; backend through evidence-gated Stop 3.
- Open Stop 4 stack: PRs #9–#12, unmerged at status check.
- Local verification on top branch: 95 unit tests passed. PR review/CI
  readiness was **not** assessed for this log entry.
- Evidence blockers: no reviewed Stop 4 registers, approved finished-package
  catalogue, or independent measured shelf-life trials.
- Decision: document the boundary clearly; do not train a package or
  shelf-life model from the two reference workbooks.

### 2026-09-26 — first Stop 5 transfer check opened

- Branch/PR: `feat/06-candidates`, [#14](https://github.com/Aspirant200715/PackSense/pull/14),
  based on `feat/05-produce-water` / #12; commit `63228e4`.
- Added an exact-scope cumulative whole-package transfer comparison and a
  strict register contract. Stop 3 cards now emit a scenario fingerprint for
  matching; a changed food, route, package catalogue, quantity, temperature
  envelope, or target life cannot silently reuse a value.
- No real source files, approvals, measured package transfers, trial outcomes,
  or training rows were added. Source rights were not assessed because no
  external data was imported.
- Local verification: `python -m unittest discover -s tests -q` passed 105
  tests on #14. `git diff --cached --check` passed before commit. CI and PR
  review have not been assessed; no PR was merged.
- Capability boundary: `exceeds_budget` can flag a protection failure;
  `within_budget` covers one mechanism only and never marks a package feasible
  or predicts shelf life. Approved complete structures, other hard filters,
  validated produce safety, and measured trial outcomes remain absent.
- Owner decision requested: choose whether to review and merge the open PRs
  in dependency order, or continue with additional stacked backend PRs.

### 2026-09-26 — Stop 4 and first Stop 5 slice merged

- The owner authorized review and merge. PRs #9, #10, #11, #12, and #14 were
  reviewed and merged in dependency order. Their merge commits are
  `52bec0b`, `670dc04`, `c4fbd02`, `099d3f5`, and `98a792b` respectively.
- Each PR head had successful Python 3.11 and 3.13 CI checks, a clean scoped
  diff after retargeting, and no submitted review, inline, or discussion
  comments. The top technical branch passed 105 local tests; the synced log
  branch also passed 105 local tests. No approved package or model result was
  claimed from those tests.
- No real data, source approvals, finished-package measurements, or observed
  trial labels were added. Source rights were not assessed because no new
  external dataset was imported. Training remains `not_ready`.
- Next code scope: an immutable trial split manifest and leakage checks that
  refuse to allocate a test set from too few independent measured groups.

### 2026-09-26 — reviewed-trial split contract in progress

- Branch: `data/08-grouped-splits`, based on `main` commit `d0a7149`.
  Added strict review-register and split-plan contracts, SHA-256 bindings to
  trial rows/files, source/study-family group checks, refusal diagnostics,
  and a deterministic non-overwriting allocation manifest. The audit states
  explicitly that no model was trained or validated.
- No real data, source approvals, finished-package measurements, or observed
  trial labels were added. Test-only constructed trial records exercise the
  contract; they are not training data. Source rights were not newly assessed.
- Local verification: `python -m unittest discover -s tests -q` passed 118
  tests. CI and PR review are pending at this entry. The split is **not** a
  fitted model or a demonstrated non-leaking evaluation; external review of
  shared experiments across sources remains necessary.
- Next evidence gate: reviewed independent measured trials, verified complete
  package joins, and a prospective pilot. If those are absent, training and
  shelf-life accuracy claims remain `not_ready`.

### 2026-09-26 — grouped split contract merged

- [PR #15](https://github.com/Aspirant200715/PackSense/pull/15) merged as
  `ee064da`. The scoped six-file diff had no submitted review, inline, or
  discussion comments; Python 3.11 and 3.13 CI checks both passed.
- Synced `main` passed `python -m unittest discover -s tests -q` with 118
  tests. A separate local 3.13 interpreter lacked project dependencies, so
  its collection failure was environmental; the dependency-installed 3.13
  CI check passed. The test suite uses test-only constructed trials and does
  not establish statistical performance.
- No external dataset, trial outcomes, rights decisions, package approvals,
  fitted preprocessing, model, holdout score, or shelf-life prediction were
  added. The split contract is executable, but **no actual train/validation/
  test allocation exists** until reviewed measured trials are supplied.
- Decision: keep the model-training gate closed. When evidence arrives, use
  the frozen group manifest, fit preprocessing on training folds only, select
  with validation, and evaluate the untouched test once against predeclared
  metrics and prospective pilots.

### 2026-09-26 — complete-structure review gate in progress

- Branch: `feat/06-structure-review`, based on synced `main` commit `0bf9bd6`.
  A strict review register binds a decision to the exact catalogue, material
  master, parsed construction, declared source records, food scope, and
  service-temperature range. Construction, food-contact, sealing/closure,
  mechanics, and service-temperature checks each require a source hash,
  reviewer decision, and rights-review ID. Any rejected draft, unmatched
  review, stale identity, failed check, or widened scope blocks the entire
  catalogue; no partial structure is promoted.
- No real external structure register, source documents, rights decisions,
  finished-package transfer measurements, or trial outcomes were added.
  Constructed `TEST_ONLY` cases verify the gate and are not training data.
- Local verification: `python -m unittest discover -s tests -q` passed 125
  tests. PR review and CI are pending at this entry. A passing declaration
  is review-attested, **not** independently authenticated by the code and
  **not** package feasibility or a shelf-life prediction.
- Remaining gate: obtain and externally verify actual complete-structure
  evidence, then apply scenario-specific Stop 4/5 hard checks before ranking.

### 2026-09-26 — complete-structure review gate merged

- [PR #17](https://github.com/Aspirant200715/PackSense/pull/17) merged as
  `6a047ec`. The six-file diff had no submitted review, inline, or discussion
  comments; Python 3.11 and 3.13 CI checks passed.
- Synced `main` passed `python -m unittest discover -s tests -q` with 125
  tests. The tests cover mechanical review-register validity, not the truth
  of external evidence or a real package recommendation.
- No actual review-attested structures, authenticated source documents,
  finished-package performance values, or measured food-package trial
  outcomes were added. Package feasibility and model-training readiness
  remain closed.

### 2026-09-27 — material barrier evidence readiness audit

- Branch: `data/10-material-barrier-evidence`, [PR #20](https://github.com/Aspirant200715/PackSense/pull/20), based on current `main`.
  Material reference audits now report provenance and test-condition coverage
  separately for OTR, WVTR, and CO2TR. Supplier-reported and estimated values
  cannot be mistaken for measured model targets.
- Audited the local 81-row material workbook (SHA-256
  `17e2791aacee70a1e30f6b73624c5ac2745e5feed36672a9c980499d77fd2564`):
  OTR/WVTR each have 80 supplier-reported values and one estimate, with zero
  strict measured training candidates. CO2TR has 60 estimates and 13
  measured, condition-complete declared training labels. No model was trained
  on this table; 13 rows are insufficient for credible grouped evaluation.
  The source workbook and generated audit report remain local/ignored.
- Local verification: `python -m unittest discover -s tests -q` passed 126
  tests; `python -m compileall -q packsense tests` and `git diff --check`
  passed. No real data was added to the repository.
- Remaining training gate: collect independently measured food/package trials
  for shelf-life prediction and more consistent barrier observations if a
  material-property estimator is desired. This audit does not create package
  recommendations or validate the supplier-reported references.
### 2026-09-27 — first measured-trial shelf-life training runner

- Branch: `ml/09-shelf-life-training-pipeline`,
  [PR #19](https://github.com/Aspirant200715/PackSense/pull/19), based on
  `main` at `fecb787`. Added one CPU gradient-boosting training path behind the
  existing reviewed trial/split gate. It fits only observed failure days,
  requires one failure criterion and threshold, fits preprocessing on train
  data, chooses iterations on validation, compares with a training-median
  baseline, and opens test outcomes only after that validation gate passes.
- The runner reports right-censored rows separately and never labels their
  last-observed day as failure. Test censoring is used only for a lower-bound
  consistency diagnostic. The model artifact and report bind trial, review,
  plan, and manifest hashes. Every result remains research-only and
  `model_validated=false`.
- No real trial rows, approval records, data rights, split, or model artifact
  were added. Tests use ephemeral `TEST_ONLY` fixtures in temporary storage;
  they are not a training dataset or project data asset. The reference
  workbooks still cannot train this target.
- Local verification: `python -m unittest discover -s tests -q` passed 131
  tests; `python -m compileall -q packsense tests` and `git diff --check`
  passed. Kaggle kernel version 4 validated reference imports only and did
  not train this model.
- Next evidence gate: provide independently reviewed measured trial outcomes,
  exact package joins and the reviewed group split. If those gates fail, the
  trainer must report `not_ready`; no epochs, synthetic labels, or reference
  row combinations can substitute for the missing outcomes.

### 2026-09-27 — requested 80/20 grouped holdout

- Updated PR #19's measured-trial split gate to target 80% development and
  20% untouched test groups. A validation subset is held inside development
  for iteration selection; the final exploratory fit uses all development
  groups before the test is opened once. Whole source/study/batch families
  remain indivisible, so the audited group-level tolerance is 75–85% / 15–25%.
- Aligned the experimental food-property evaluator to the same 80/20
  development/test convention, with calibration kept inside development.
- No new food, material, or trial data was added and no real model was fit.
  All 131 local tests pass, including grouped split and holdout ratio checks;
  CI for the prior PR head passed Python 3.11 and 3.13 before this update.
- Remaining hard blocker for shelf-life learning is a reviewed measured
  trial-outcome table with exact food/package/storage linkage and observed
  failure or right-censoring. Reference-property workbooks are not labels for
  shelf-life or package-selection outcomes.

### 2026-09-27 — withdrawn measured-quality candidate files

- Branch: `data/21-public-quality-audit`, [PR #22](https://github.com/Aspirant200715/PackSense/pull/22),
  based on `main` at `7cce752`.
  The owner withdrew the 672-row raw quality CSV and 72-row package CSV.
  The earlier trial-audit, Kaggle metadata, and preprocessing experiments on
  this branch were fully reverted. This slice records the exclusion decision
  in the trial-intake guide; no CSV data, importer, training labels, or model
  artifacts are added.
- The existing food and material workbooks remain reference masters, not
  observed shelf-life outcomes. A future trial source still needs independent
  source, rights, package, endpoint, and grouping review before split/training.
- This is a documentation-only decision record. No training or prediction
  was run. `py -3.11 -m unittest discover -s tests -q` passed all 132 tests;
  `git diff --check` passed. CI and review status belong to the PR head.

### 2026-09-27 — real food-property experiment on analytical labels

- Ran the existing CPU property estimator on the local 5,000-food workbook
  with source SHA-256 `76c5f78c6f6a0ef3c1e5bed7baa442ac9275146198be7de22bbdfe5ef80ccd9f`.
  Labels were restricted to USDA `A` analytical derivations. This is a narrow
  moisture/fat reference-value task, not a shelf-life or packaging model.
- Moisture: 1,628 train, 619 calibration, 463 test rows across 344/87/108
  independent groups. Test MAE/RMSE were 12.95/17.60 percentage points,
  versus 16.86/25.47 for the group-median baseline. The wide 33.32-point
  calibration radius limits use to screening; 110/112 missing values passed
  the code's estimate gates.
- Fat: 1,680/643/291 rows across 332/84/104 groups. Model MAE 6.56 was worse
  than baseline MAE 6.35, so no estimates were emitted; RMSE was better but
  does not override the predeclared MAE refusal gate.
- The 80/20 convention is enforced by independent groups. Due to unequal
  family sizes, row shares differ (fat test rows were 11.1%); this is
  explicitly reported and is not an 80/20 row-level split. The evaluation is
  exploratory, not a pristine external challenge set. Local reports are
  ignored under `outputs/` and were not committed.
- No material model or shelf-life model was trained. The available 81-row
  material master has only 13 complete measured CO2-condition records and 60
  estimated CO2 values, so it remains a reference source, not a trustworthy
  supervised target table.

### 2026-09-27 — preliminary package shortlist

- Branch: `feat/07-basic-recommendation`, based on `main` at `7cce752` (PR
  [#21](https://github.com/Aspirant200715/PackSense/pull/21), open for review).
  Added a basic source-gated shortlist for confirmed non-respiring
  foods. It requires all three reviewed oxygen/moisture decisions, an exact
  food-scope and temperature-matched reviewed complete structure, and exact
  scenario-matched whole-package transfer evidence. Any approved-limit
  exceedance excludes that structure. A unique preliminary preference uses
  only the lowest worst-case fraction of oxygen/moisture budget consumed;
  cost, sustainability, and light protection are not ranked.
- The output carries the scenario/food-master identities, structure/review
  hashes, layer details, source locators, transfer checks, warnings, and
  explicit `package_feasible=false` / `shelf_life_predicted=false` flags.
  Respiring foods remain gated behind a validated complete Stop 4 path.
- No real data or model-training records were added. The supplied 5,000-food
  and 81-grade masters still have no reviewed complete-structure catalogue,
  approved food-protection assessment register, or scenario-matched
  whole-package transfer register, so current project data cannot produce a
  real shortlist. Unit fixtures are `TEST_ONLY` and are not training data.
- Local verification: `py -3.11 -m unittest discover -s tests -v` passed all
  139 tests; `py -3.11 -m compileall -q packsense tests` and `git diff --check`
  passed. PR #21's head at `1cd6292` passed Python 3.11 and 3.13 CI; no
  review had been submitted at the time of this update.
- Remaining gates: source-reviewed food limits, real reviewed package
  constructions, whole-package measurements across the stated temperature/RH
  profile, and later cost/sustainability evidence for full Stop 6 ranking.
  Shelf-life training remains dependent on independent measured trial outcomes.

### 2026-09-27 — structured preliminary recommendation batch

- Continued on `feat/07-basic-recommendation` in [PR #21](https://github.com/Aspirant200715/PackSense/pull/21).
  Added a backend JSON batch command joining scenario audit, exact food
  reference, reviewed route, food protection assessment, complete-structure
  review, and scenario-matched whole-package transfer evidence. Every input
  row becomes an exception, `not_ready`, or preliminary shortlist result.
  Summary counts expose input issues, requirement gaps, and screening reasons.
- The food master at SHA-256
  `a79069a9bc293753eb610b47979d9eff8df2cb9a776387114eccf60a919efafc`
  imported 5,000/5,000 rows; the material master at SHA-256
  `17e2791aacee70a1e30f6b73624c5ac2745e5feed36672a9c980499d77fd2564`
  imported 81/81 rows. These read-only checks did not create a scenario batch
  or training labels. No reviewed protection, route, structure, or whole-pack
  transfer register was supplied, so a real shortlist remains unavailable.
  The excluded 672-row and 72-row quality CSVs were not used.
- Local verification: `py -3.11 -m unittest discover -s tests -q` passed all
  143 tests; compileall, `git diff --check`, and the batch CLI help check
  passed. New PR-head CI and review are checked separately on GitHub.
- Remaining gates: a real structured scenario batch and source-reviewed food
  limits, route decisions, package constructions, and matched package transfer
  measurements. Shelf-life training still needs independent measured trials;
  no shelf-life model was fitted by this change.

### 2026-09-27 — preliminary batch CSV summary

- Branch: `feat/08-batch-summary`, [PR #23](https://github.com/Aspirant200715/PackSense/pull/23),
  based on PR #21 at `c3fd1c0`. Added an optional one-row-per-scenario CSV
  beside the detailed JSON report. The summary preserves input exceptions,
  missing evidence,
  storage/transit/excursion temperatures, target life, eligible IDs, and
  preliminary structure details. It leaves unsupported fields blank and
  always marks package feasibility and shelf-life prediction false.
- The exporter rejects inconsistent claims and protects external text from
  spreadsheet formula interpretation. The JSON remains the source-level
  audit record. No source data, synthetic training observations, model fit,
  or performance claim was added.
- Local verification: `py -3.11 -m unittest discover -s tests -q` passed 147
  tests; compileall, `git diff --check`, and CLI help passed. CI and review
  will be checked on the pushed PR head.
- Remaining gates are unchanged: reviewed scenario/package evidence for real
  recommendations and independent measured trial outcomes for shelf-life
  training. The CSV is an output view, not a training dataset.

### 2026-09-27 — direct shortlist review-integrity gate

- Branch: `feat/09-review-integrity`, [PR #24](https://github.com/Aspirant200715/PackSense/pull/24),
  based on PR #23 at `af70eb8`.
  Direct callers of the recommendation function now receive `not_ready`
  before candidate screening if a supposedly approved in-memory structure
  audit has invalid version bindings, duplicate structure IDs, missing or
  failed required checks, inconsistent review IDs, or mismatched
  construction/food-contact source IDs or an invalid package shape. This
  closes a bypass of the structure-review builder's checks; it does not
  authenticate external evidence.
- Updated `TEST_ONLY` fixtures to carry the same five-check attestation
  shape as the production review builder. Added adversarial tests for
  incomplete and inconsistent attestations. No source data, synthetic
  training observations, model fit, or accuracy claim was added.
- Local verification: `py -3.11 -m unittest discover -s tests -q` passed 149
  tests; compileall and `git diff --check` passed. The separate local Python
  3.13 environment lacks `openpyxl`, so its test discovery stopped at import;
  dependency-installed PR CI is the 3.13 verification. CI and review will be
  checked on the pushed PR head.
- Remaining gates are unchanged: reviewed real scenario/food/package evidence
  for a shortlist and independent measured trials for shelf-life training.

### 2026-09-27 — merged recommendation stack and trial reference-link gate

- Merged PRs #22, #21, #23, and #24 into `main` in that order; stacked PRs
  #23 and #24 were retargeted to `main` after their parent merged. The final
  merge is `03cd09b`. Main passed Python 3.11/3.13 CI and 149 local tests.
- Branch: `ml/10-trial-reference-join`, [PR #25](https://github.com/Aspirant200715/PackSense/pull/25),
  based on `03cd09b`. Before any split or exploratory shelf-life fit, each
  measured trial must now resolve to an
  exact food reference and a complete, review-attested package in the
  versioned catalogue/material master. Trial review identity, food scope,
  grades, and storage/transport service-temperature coverage are checked.
  A failed link returns `not_ready` with row-level reason codes and no model.
  Artifacts record all four reference hashes in addition to trial/split IDs.
- The [Mendeley smoked-food package-level dataset](https://data.mendeley.com/datasets/tvsw53j89z/1)
  is genuine measured longitudinal quality data, but its publisher says
  processing-run identifiers were not retained and it is not a commercial
  shelf-life validation dataset. The [R3PACK snack dataset](https://zenodo.org/records/21396864)
  contains simulations, not observed trial outcomes. Neither was imported or
  relabelled as a PackSense shelf-life target. The withdrawn 672/72 CSVs remain
  excluded. No source data, synthetic training labels, model fit, or
  performance claim was added.
- Local verification: `py -3.11 -m unittest discover -s tests -q` passed 150
  tests, including exact-join refusal cases; compileall, CLI help, and
  `git diff --check` passed. PR CI is checked separately. The only ML run to
  date remains the separate, exploratory food-property experiment, not a
  package/shelf-life model.
- Remaining gates: an independently reviewed measured trial table with exact
  food/package/condition linkage and adequate independent failure groups,
  followed by 80/20 group allocation, baseline comparison, blind evaluation,
  and prospective validation. Human source and rights review cannot be
  replaced by matching IDs in code.

### 2026-09-27 — material-selection priority and label intake

- Owner scope decision: prioritize package-material selection and defer
  shelf-life prediction. The final eight-stop architecture is preserved;
  a future learned ranker can operate only after hard candidate filters.
  Desired shelf-life days remains a scenario requirement, not a training label.
- Reviewed recent history: PRs #21, #22, #23, and #24 are merged. PR #25 is
  the only open PR; it concerns shelf-life trial-reference linkage and is
  deliberately left unmerged while that work is deferred. Its Python 3.11
  and 3.13 checks were green at review. The current branch starts from
  `main` at `03cd09b`, not from PR #25.
- Branch: `feat/material-suitability-intake`, [PR #26](https://github.com/Aspirant200715/PackSense/pull/26).
  Added a strict, source-versioned
  food-scenario/complete-structure suitability-label intake. It records
  explicit suitable/unsuitable decisions and source-family IDs, rejects
  duplicate or mismatched pairs, and checks reviewed food scope and all
  exposure temperatures. It does not certify evidence or fit a model.
- The existing Kaggle notebook was pulled and inspected. It has two cells,
  runs the reference-master audit from backend commit `fecb787`, and has no
  material-suitability labels or model training. The two reference workbooks
  are attached; the withdrawn quality CSVs were not used.
- No real source labels, complete package catalogue, or scenario-matched
  transfer data were added. Unit fixtures are `TEST_ONLY` and are not training
  observations. Current real-data recommendation and supervised ML remain
  `not_ready` until those sources are reviewed and joined.
- Local verification: `python -m unittest discover -s tests -q` passed 155
  tests; `python -m compileall -q packsense tests`, `git diff --check`, and
  the label-intake CLI help check passed. PR CI and review are separate.
- Next: review a real suitability source set and freeze a group-held-out
  split before updating the Kaggle notebook to train a material ranker.

### 2026-09-27 — material split and Kaggle preflight

- PR #26 was reviewed for scope and CI, had no submitted review comments,
  passed Python 3.11/3.13 checks, and merged to `main` at `f0fd088`. PR #25
  remains open and unmerged because shelf-life training is deferred.
- Branch: `ml/material-split-preflight`, [PR #27](https://github.com/Aspirant200715/PackSense/pull/27),
  based on the updated `main`. Added
  a predeclared material-suitability split plan validator. It rejects source-
  family overlap, source IDs assigned to different families, foods crossing
  partitions, missing classes, insufficient independent groups, and large
  deviations from the requested 80/20 holdout. The manifest contains frozen
  label/group IDs and source hashes, not food rows or fitted parameters.
- Versioned the existing Kaggle notebook and metadata in `notebooks/`. The
  notebook still imports only the two hash-checked food/material reference
  workbooks using the older pinned backend bundle. A material-model preflight
  now lists missing real suitability inputs and modules and writes
  `model_trained=false`; it does not fit a model or claim accuracy.
- No real suitability labels, scenario batch, reviewed package catalogue,
  source approvals, or model artifact were added. Withdrawn quality CSVs
  remain excluded. Split unit fixtures are `TEST_ONLY`, not training data.
- Local verification: `python -m unittest discover -s tests -q` passed 161
  tests; `python -m compileall -q packsense tests`, notebook code-cell
  compilation, split CLI help, and `git diff --check` passed.
- Kaggle notebook version 5 was pushed to the existing kernel and completed.
  Its output imported 5,000/5,000 food and 81/81 material reference rows,
  listed the missing label/split/scenario/structure files and newer backend
  modules, and reported `status=not_ready`, `model_trained=false`.
- PR CI and review are checked on the pushed head separately.

### 2026-09-27 — guarded material-model runner and Kaggle source refresh

- PR #27 passed CI and was merged to `main` as `2d619fc`. Deferred shelf-life
  PR #25 remains open and unmerged; it is outside the current material task.
- Branch: `ml/material-training-runner`, based on that merge. Source commit
  `7301542` adds a CPU regularized-logistic exploratory classifier behind the
  suitability-intake, independent human source/rights approval, and frozen
  source/food-disjoint split gates. It excludes food, scenario, structure,
  source, and review IDs from features, fits preprocessing on train only,
  selects regularization on validation, and opens test only if validation
  Brier score beats a training-prevalence baseline. It does not release a
  package recommendation or shelf-life claim.
- The private Kaggle backend-source dataset was refreshed from exact source
  commit `7301542` with a per-file SHA-256 manifest. Kaggle reports it ready
  and lists 25 package Python files, including `material_model.py`, plus the
  manifest. No raw food/material data or withdrawn 672/72 CSVs were uploaded
  in this source bundle.
- Kaggle notebook version 6 completed with the refreshed bundle. It verified
  all 25 source files, accepted 5,000/5,000 food and 81/81 material reference
  rows, and wrote `not_ready`/`model_trained=false` with no backend modules
  missing and all six real training files missing. No fit, test metric, or
  model artifact exists. PR CI remains a separate check.
- The imported food reference has pH for 720/5,000 rows: 709 proxy and 11
  reported-reference values. This is a coverage/evidence limit, not a reason
  to generate pH labels or claim broad model generalization.
- Local verification: 165 unit tests passed; package/test compile checks and
  `git diff --check` passed. No real suitability labels, approved split,
  scenario batch, reviewed structure catalogue, or model artifact were added.
  Test fixtures are guardrail checks, never fitted training data.

### 2026-09-27 — optional film-grade reference comparison

- Branch: `feat/grade-reference-comparison`, [PR #31](https://github.com/Aspirant200715/PackSense/pull/31),
  based on `main` at `c2e2b70`.
  Added an opt-in, laboratory-condition Pareto comparison for sourced film
  grades after the existing reviewed non-respiring route and food-protection
  gates. It uses only active oxygen/moisture mechanisms, excludes estimated or
  incomplete grade observations, and compares grades only within exact
  property-specific test temperature, RH, method, and unit cohorts.
- The supplied 81-row material workbook imported with zero rejected rows.
  A **TEST_ONLY** card used for a read-only coverage check found 71 grades in
  three multi-grade cohorts, one singleton, and nine grades without complete
  comparable OTR/WVTR evidence. These counts do not constitute real-food
  choices or a training evaluation. No data file, suitability label, scenario
  batch, or approved package structure was added to the repository.
- The comparison cannot choose a preferred grade, extrapolate to scenario
  temperature/RH, alter the existing package recommendation, set package
  feasibility, or claim a trained model. The real-data training gate remains
  `not_ready`; the 80/20 split is inapplicable without genuine labels.
- Local verification: 170 unit tests passed under Python 3.11 and in an
  isolated Python 3.13 environment with pinned requirements; package/test
  compilation, CLI help, and `git diff --check` passed. PR CI and review are
  separate.

### 2026-09-27 — local produce diagnostics in the recommendation batch

- Branch: `feat/produce-batch-diagnostics`, [PR #32](https://github.com/Aspirant200715/PackSense/pull/32),
  based on the open grade-reference
  comparison branch. An opt-in path now attaches the existing Stop-4 local
  gas/water audit to each exact scenario row in the recommendation JSON.
  The route, kinetics, gas, and water register hashes remain separate, and
  absent source evidence stays unresolved.
- A produce audit result never changes the ordinary package shortlist or
  grade reference comparison. The batch marks `produce_safety_certified=false`
  and `produce_diagnostic_structure_review_joined=false`; no local gas/water
  snapshot approves a complete package, dynamic MAP trajectory, or shelf life.
- No real scenario, source register, package observation, training label, or
  model artifact was added. New test observations are `TEST_ONLY` fixtures and
  are not training data. Real package-material learning remains `not_ready`.
- Local verification: 173 unit tests passed under Python 3.11 and isolated
  Python 3.13 with pinned requirements; compile checks, CLI help, and
  `git diff --check` passed. PR CI and review are separate.

### 2026-09-27 — exact produce-observation catalogue binding

- Continued on `feat/produce-batch-diagnostics` (PR #32). Version-2 gas and
  water observation registers now require an exact structure-catalogue SHA-256;
  version-1 registers remain readable as unbound local diagnostics.
- The recommendation batch checks each observed produce structure against the
  reviewed catalogue, current material-master version, exact food scope,
  service-temperature envelope, all three exposure phases, observation
  catalogue hashes, and resolved local condition checks. It reports per-
  structure binding gaps and aggregate counts. This is an identity/scope
  join only; the ordinary recommendation still blocks respiring produce and
  `produce_safety_certified` stays false. Observed initial O2/CO2 limit
  breaches are separately counted and listed by phase without declaring the
  package universally unsuitable.
- No genuine scenarios, complete-package observations, suitability labels,
  training data, or model artifact were added. New tests use `TEST_ONLY`
  observations, never training records. Legacy and changed-hash evidence is
  verified to remain unbound. Local Python 3.11 verification passed 180
  tests, compileall, and `git diff --check`. System Python 3.13 lacks the
  pinned project dependencies, so its full-suite result awaits dependency-
  installed CI. Source authenticity still requires external review.

### 2026-09-27 — public package-catalogue candidate pilot

- Branch: `data/catalogue-evidence-pilot`, based on merged `main` at
  `c2e2b70`. Compared research, supplier-film, finished-pouch, and
  produce-bag sources against the existing Stop 2/5 structure requirements.
- Added `data/public_catalogue_candidates.v1.json`: nine selected real
  supplier product claims from four directly accessible sources (The
  Packaging Lab v3.4, two Kuraray Plantic pages, and Sumitomo P-Plus).
  Catalogue SHA-256 at intake: `a6f55f0e73fe3b146d7f05d77c93918dd54e5754167caad574c4d66e7dda43af`.
  Supplier rights review remains pending. No source document or workbook was
  overwritten or bundled; the existing 81-row material master was compared
  read-only and had no manufacturer overlap with the candidate suppliers.
- Added a strict, offline candidate audit, tests, comparison guide, and
  README link. It preserves supplier units and test conditions, separates
  narrow produce/quantity/temperature applications from broad claims, and
  marks six P-Plus gauge interpretations for supplier confirmation. It
  reports three OTR/WVTR claim records, six exact produce-use records, no
  CO2TR, no verified service limit, zero approved structures, and zero
  suitability training labels. PouchDirect was held because its TDS returned
  HTTP 403 on direct retrieval; ePoP pairings remain research leads rather
  than finished-package tests.
- Local verification: 177 Python 3.11 unit tests passed; package/test compile
  checks and `git diff --check` passed. CI and independent source/rights
  review remain separate. No model was trained, no Kaggle data was changed,
  and no package was released as a recommendation.
- Next promotion work is exact grade/gauge identification, reviewed contact
  and service-temperature documents, complete-package transfer and seal
  evidence, and produce SKU-level O2/CO2 measurements. The candidate
  catalogue must not be loaded as a `StructureDraft` or training register.
- Same branch/PR #29 follow-up: added optional supplier-application lookup to
  the existing recommendation batch JSON. It checks exact supplier food names,
  quantities (with g/kg conversion), storage and conservative full-duration
  transit excursions. A `, raw` food-reference name is a review-needed name
  variant, not an approved identity match; processed variants are not mapped.
  Inner liners, broad film claims, missing source rights and package-level
  evidence stay visibly unresolved. The shortlist status and preference are
  unchanged; no material model was fitted. The 5,000-row workbook has zero
  populated scenario operating-condition rows, so no real batch result was
  invented. Local test suite had 185 passing tests; both Python CI checks
  passed for PR #29 head `cbf5a49`.

### 2026-09-27 — exploratory material-score boundary

- Branch/PR: `feat/model-score-boundary` / #30, stacked on PR #29 head `cbf5a49` so
  the source-catalogue PR can remain open for review. No additional supplier
  documents, workbook values, scenario rows, suitability labels, or Kaggle
  training data were created or changed.
- Corrected training-report semantics: a held-out test sets `model_evaluated`,
  not `model_validated`, and reports whether its Brier score beats the constant
  training-prevalence baseline. Release remains withheld even if that metric
  improves. The checked source hashes are retained for offline comparison.
- Added a separate exploratory scorer for only engineering-eligible, exact
  reviewed structures. It refuses source, scenario, review, transfer, class,
  and probability mismatches and never changes the shortlist preference or
  reports package feasibility. Test-only estimator fixtures exercise guards;
  no real model was fit, scored, serialized, or deployed.
- Local verification: 191 Python 3.11 tests passed, compilation and diff checks
  passed. Both Python 3.11 and 3.13 CI checks passed for the initial PR #30
  head `7de9808`; later heads require their own CI checks.
- Follow-up on the same PR: the trainer now rechecks in-memory source-family,
  source-ID, food, normalized commodity, and scenario separation before any
  fit, even when handed an allocation marked prepared. Validation and test
  reports add strict within-scenario ranking diagnostics only for explicitly
  judged suitable/unsuitable alternatives; no absent pair becomes a negative.
  Ties are reported conservatively and an unjudgeable partition says
  `not_evaluable`. These checks do not change the withheld release status.
  Local Python 3.11 verification passed 193 tests, compileall, and diff checks.
  No real suitability label, model fit, or Kaggle dataset was added.
- Further same-PR evaluation slice: optional, offline engineering-shortlist
  comparison now cross-tabs only explicit reviewed scenario/structure labels
  against eligible, excluded, unresolved, and missing candidate states. It
  refuses stale source/review/fingerprint bindings and does not infer negative
  labels from absent candidates. It cannot prove that baseline evidence was
  independent of the judgements; no model selection or recommendation changes.
  The batch now places its scenario-file SHA-256 on each shortlist, and both
  the exploratory scorer and baseline comparison check that source version;
  row fingerprints alone do not identify a complete batch revision.
  Local Python 3.11 verification passed 195 tests; no real model fit occurred.
- Further same-PR decision-boundary slice (base `498d153`): changed the
  preliminary engineering preference from a scalar worst-case transfer score
  to non-dominated comparison across each source-limited mechanism. Oxygen
  versus moisture trade-offs and exact ties now stay as unpreferred shortlists;
  a unique dominating candidate can still be preliminary preferred. The
  reported worst-case fraction remains diagnostic, and `protection_rank` now
  denotes a Pareto layer. The report contract is `basic-recommendation-v2`.
  No food/material mapping, scenario, measurement, label, or Kaggle dataset
  was added. Local Python 3.11 and 3.13 suites passed 197 tests each;
  compileall and diff checks passed. CI and PR review remain pending, and
  neither model training nor package certification occurred.

### 2026-09-27 — reviewed handling-scope gate

- Branch: `feat/handling-scope-gate`, based on merged `main` at `6517eae`.
  The existing structure review could carry a passing mechanical check without
  saying whether its source covered the scenario's low, medium, or high
  transport handling severity. Review register schema version 2 now requires
  `max_reviewed_handling_severity`; legacy version-1 registers remain readable
  but have unknown handling scope.
- The preliminary non-respiring shortlist now marks a missing scope unresolved
  and excludes a structure whose reviewed maximum is below the scenario
  severity. The suitability-label intake applies the same bound before a
  label can enter the exploratory ranker. Direct in-memory attestations are
  checked for invalid severity types. Neither a passing declaration nor the
  ordinal comparison authenticates mechanical testing or certifies a package.
- No real structure reviews, scenario rows, measured package transfers,
  suitability labels, or model artifacts were added. All new cases are
  `TEST_ONLY` guardrails. Real-data training and package release remain
  `not_ready`; source documents, rights, route/pack-mass applicability, and
  independent outcomes still require review.
- Local verification: 214 Python unit tests passed; compile and diff checks
  passed. PR CI and external evidence review remain separate.

### 2026-09-27 — exact PouchDirect SKU 179 candidate

- Branch: `data/pouchdirect-sku179-candidate`, based on `main` at `cb76843`.
  The supplier's direct SKU 179 TDS became accessible through its own product
  page, resolving the earlier HTTP 403 intake hold for this one sheet. One
  source and one candidate were added to the separate public-claim register;
  the register now has five sources and ten candidates. Catalogue SHA-256:
  `103af32842aee9845f3dcc3a7ff74edc564e81931a45f5915ae6657f963b071f`.
  The candidate JSON is pinned to LF on checkout so its raw-byte source hash
  is reproducible across Windows and Linux.
- The source states a 12/12/80 µm PET/metallized-PET/LLDPE stand-up pouch,
  104 µm total gauge, ≥20 N/15 mm seal strength, and laboratory-conditioned
  OTR/WVTR **indicative** ranges. The intake now accepts a sourced seal-
  strength claim when its process-temperature range is absent, without
  inventing that range. It flags the indicative barrier as not measured
  complete-package transfer. No food-specific use, verified service limit,
  reviewed conformity declaration, exact material-grade join, source rights
  approval, or scenario outcome was supplied.
- The candidate remains unapproved and cannot enter the structure catalogue,
  supplier-application lookup, suitability labels, shortlist, or model fit.
  The TDS's 60-month packaging-product storage life is not food shelf life. No other
  manufacturer record, food reference, or Kaggle input changed.
- Local verification: 216 Python tests, compilation, catalogue audit, and
  diff check passed. CI and independent document/rights review are separate.

### 2026-09-27 — one-candidate pilot evidence trace

- Continued on `data/pouchdirect-sku179-candidate` (PR #34). The batch now
  accepts `--pilot-candidate-id` with the public candidate register and
  attaches an exact candidate/source evidence trace to each valid scenario.
  Unknown IDs fail; invalid scenario rows stay exceptions. Published
  food/quantity/temperature matches are visible but never become approvals.
  The separate public-candidate promotion gaps are reused without altering
  structure review, recommendation, or model-training gates.
- A primary [peanut-kernel comparison](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0190377)
  provides real food/package research evidence, but its experimental
  PET/AL/PA/PE bag cannot be identified as PouchDirect SKU 179. No result,
  food limit, or package property was borrowed across those structures.
  The repository still has no genuine fully specified pilot scenario, reviewed
  package, food-protection assessment, or measured complete-package transfer.
- Tests use only `TEST_ONLY` scenario objects. No source workbook, Kaggle
  input, training label, or model artifact changed. Local verification:
  221 Python tests passed; compile, CLI, and diff checks are recorded with
  this PR. CI and independent source review remain separate.

### 2026-09-27 — versioned frontend decision output

- PR #34 merged at `0f98eb5`. Branch `feat/frontend-decision-contract` adds a
  read-only projection from the audited batch JSON to `frontend-decision-v1`.
  It exposes input exceptions, evidence gaps, and the narrow preliminary
  shortlist as separate frontend states, with source hashes and temperature
  exposures. It refuses contradictory claims of package feasibility, shelf
  life, or a preferred structure outside the eligible shortlist.
- The projection has `recommended_structure_id`, `material_prediction`, and
  `predicted_shelf_life_days` null in every row; its model status is
  `not_deployed`. The material trainer and Kaggle preflight remain gated by
  missing genuine scenario/structure labels, a frozen independent split, and
  source/rights approval. No estimator, score, data row, or synthetic training
  record was created. The frontend can use the contract without presenting an
  experimental result as a validated prediction.
- Local verification: 226 Python tests, compileall, and diff check passed.
  PR CI and review are separate.

### 2026-09-27 — static frontend decision workspace

- PR #35 merged at `5e30498`. Branch `feat/frontend-workspace` adds a
  dependency-free, responsive browser UI for the existing
  `frontend-decision-v1` contract: overview, searchable/paginated records,
  eight-stop pipeline explanation, and source-hash inspection. The report is
  imported from a local JSON file into browser memory; there is no live API,
  bundled example dataset, or generated packaging claim.
- The audited batch now includes a compact `scenario` summary of validated
  input values for each interpretable row. The frontend projection carries
  this summary and leaves it `null` for exceptions or legacy reports. It lets
  the UI show the actual commodity, food properties, pack quantity, and route
  context without repeating the source workbook or inferring a value.
- The UI rejects files that claim a deployed model, released recommendation,
  package feasibility, material prediction, or shelf-life prediction under
  this preliminary contract. It displays a shortlist only as preliminary.
  No real data, suitability labels, estimator, or training result changed;
  material-model release remains `not_ready`.
- Local verification: 226 Python tests, seven Node contract tests, Python
  compilation, JavaScript syntax checks, a Python-to-JavaScript contract
  round-trip, and local HTTP responses passed. Visual browser QA could not
  be completed because no browser surface was available to the UI-check tool.
  PR CI and independent review remain separate.

### 2026-09-27 — frontend process studio and theme revision

- Continued on `feat/frontend-workspace` (PR #36). Replaced the repeated
  pipeline cards with an eight-stage interactive walkthrough, including
  separate non-respiring and fresh-produce explanations, step controls and
  playback. An actual-report mode traces one imported decision row through
  the existing evidence gates without performing a new screen. The backend
  projection now includes the requirement card's route status and candidate-
  screening permission so that trace does not infer either from composition.
- Restyled the workspace in dark navy/cobalt glass surfaces with a reversible
  light theme, clearer IBM Plex typography and responsive process rail. The
  browser stores only the theme choice; report import remains local and in
  memory. Online fonts have system fallbacks. No real food data, packaging
  outcomes, suitability labels, estimator or model artifact were changed.
- A follow-up frontend pass puts recorded food, pack quantity, requested life
  and the full temperature-phase summary above the actual trace, with
  composition, respiration and candidate-state counts at the relevant stages.
  Missing facts remain explicitly unreported, and importing from the trace
  returns to that view. The stage counter follows navigation, and the active
  stage centers in the mobile rail. No values are estimated in the browser.
- Local verification: 227 scoped Python tests and 14 Node tests passed, along
  with JavaScript syntax and diff checks. A local headless browser rendered
  dark, light and mobile views; route switching, the actual-mode empty state,
  and a `TEST_ONLY` report import/trace produced no browser exceptions. The
  real package recommendation and material prediction gates remain withheld.

### 2026-09-28 — connected decision workspace and introductory map

- Continued on `feat/frontend-workspace` for PR #36. Replaced the global left
  sidebar with an accessible top icon navigation, added an introductory
  four-stop decision map, and made the eight-stage pipeline a horizontal,
  clickable process track. The layout uses restrained navy/cobalt glass
  surfaces, DM Sans for readable headings, and dark/light themes. Mobile
  navigation and stage centering were checked at a true 390 px viewport.
- Added a localhost-only Python web service. `GET /api/status` exposes whether
  a source batch or audited report is configured. `GET /api/report` projects
  an operator-selected audited batch, and `POST /api/run` invokes the existing
  recommendation-batch CLI for operator-selected scenario and reference
  files. Browser requests cannot choose source paths or submit scenario rows.
  The existing projection and evidence gates remain authoritative; no model
  prediction or package release is introduced.
- No new food/package data, suitability labels, measured outcomes, estimates,
  or model artifacts were added. The supplied food and material masters are
  still reference inputs, not a scenario batch or supervised labels. A real
  scenario batch must be configured to run the pipeline from the UI. Reviewed
  complete-package outcomes are still required for a trustworthy trained
  material predictor.
- Local verification: 233 Python tests, 14 Node contract tests, compilation,
  JavaScript syntax, diff check, local API checks, and a headless-browser
  mobile interaction check passed. The browser check covers the intro map,
  selected-stage visibility, route switching, empty actual-trace state, top
  navigation, theme toggle, and absence of JavaScript exceptions. PR CI and
  independent review remain separate.

### 2026-09-28 — focused introduction and guided-flow polish

- Continued on `feat/frontend-workspace` for PR #36. Made the introduction a
  separate first screen. Its main Explore action enters the pipeline and
  starts a guided tour; selecting a decision-path stop opens that stage. A
  visible play/pause control, progress indicator and connected stage track
  make movement through the eight checks explicit. Reduced-motion settings
  disable automatic playback.
- Slimmed the workspace navigation and compacted the walkthrough for desktop
  and mobile, reducing the need to scroll between steps. The overview now
  shows a deliberate no-report state instead of empty metrics. Results use
  count-bearing status filters, and detailed issues, exposures, and structure
  checks are expandable. The real backend contract and source boundary were
  not changed; no result is invented for an unconfigured batch.
- Browser smoke checks the intro-to-tour path, automatic advancement,
  stage selection, empty states, filters, disclosures, and return to the
  introduction at desktop and 390 px mobile sizes. Its report object is
  explicitly `TEST_ONLY` UI test data, never training data. No real source
  row, suitability label, prediction model or release gate changed. Local
  verification: 233 Python tests, 14 Node tests, JavaScript syntax and diff
  checks, and sequential headless-browser smoke at 390 px and 1440 px passed.
  PR CI and independent review remain separate.

### 2026-09-28 — overview empty-state refinement

- Continued on `feat/frontend-workspace` for PR #36. Replaced the large,
  repetitive empty Overview with one compact panel: live local-backend status,
  direct actions, and four labeled, clickable decision checkpoints. The
  status strip also exposes the existing Run action when a scenario batch is
  operator-configured. On mobile, the checkpoints form a concise two-column
  layout that fits without horizontal overflow or an extra long scroll.
- No report or recommendation is shown until genuine configured sources run
  or an audited report is opened. No data, backend contracts, prediction
  logic, suitability labels, or release gates changed. Browser smoke now
  checks the integrated status and checkpoint navigation; the imported
  report used by that test remains `TEST_ONLY` UI data.

### 2026-09-28 — one connection-status source

- Continued on `feat/frontend-workspace` for PR #36. Removed the redundant
  backend banner and empty-Overview status strip. The top bar is now the one
  visible connection-status location across workspace views, including on
  mobile; it distinguishes connected, offline, running, and report-load error
  states. Its tooltip retains the configuration detail without repeating it
  in the page body. The existing top-bar Run action remains visible only for
  an operator-configured scenario batch.
- The Overview keeps its compact method actions and clickable checkpoints.
  No backend API, source data, report projection, training artifact, or
  release gate changed. Browser smoke now verifies that the single indicator
  is visible and that neither Overview state duplicates the status message.

### 2026-09-28 — reconcile the trial-reference gate with current main

- PR #36 merged to `main` at `90a93c7`. PR #25's
  `ml/10-trial-reference-join` branch was then synchronized with that main.
  The only conflicts were the README project-status paragraph and this
  historical log; both were reconciled to retain the current frontend and
  material-selection scope alongside the exact trial-reference join gate.
- The trial gate still only refuses unlinked measured trials before a split
  or exploratory shelf-life fit. Shelf-life prediction remains deferred; no
  measured trial dataset, suitability label, model artifact, or prediction
  claim was added by the integration.
- The combined worktree passed 234 Python tests, 14 Node tests, Python
  compilation, JavaScript syntax, and diff checks. PR CI is checked on the
  pushed head separately.

### Template for the next entry

Add a dated heading, then record:

- Branch/PR and base commit; what changed in this slice.
- Source files/IDs, review status, data hashes, and rights check if data
  changed. State explicitly when no real data was added.
- Reproducible local tests and CI result, separately.
- New validated capability, remaining gaps, and any changed release gate.
- Owner decision required, if any. Never silently turn a planned step into
  a completed one.
