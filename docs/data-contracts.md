# Backend data contracts

This document describes the first implementation PR. It fixes the names and
meaning of records passed between the eight architecture stops. It does **not**
claim that ingestion, package filtering, recommendation, or ML training works.

## Four different record types

1. A `ScenarioInput` is one food, pack size, shelf-life target, storage, and
   transport case. The target is a requirement, not a training label.
2. A `FoodReference` is a commodity master row. Its properties can be missing
   or sourced from a broader food form. It cannot stand in for a scenario.
3. A `MaterialGrade` is a supplier film/grade row with measurements and source
   conditions. A `PackageStructure` separately describes a manufacturable
   stack, contact layer, and compatible food scope. A grade is not an approved
   package.
4. A `TrialOutcome` is a measured food-package-condition trial. It has an
   independent group and batch ID, failure criterion, observed duration, and
   `failure_observed` flag. If no failure occurred by the final observation,
   that duration is censored, not the failure time.

`RecommendationRecord` is the eventual Stop 8 output. An exception or
no-feasible-package result cannot contain a preferred package or shelf-life
claim. A validated-pilot result requires both a package and a supported life
result with interval, mechanism, model version, and validation scope. The
package specification has an optional produce-gas record for sourced O2/CO2
limits, MAP suitability, and any perforation pattern.

## Scenario input contract

The exact required and conditional column names live in
`packsense/units.py`. Numeric percentages are 0–100 values. Temperature is in
degrees Celsius, life in days, transport duration in hours, and pack quantity
has its own declared unit. `storage_type` is a category, never a substitute
for `storage_temperature_c`. In Stop 2, the commodity master decides whether
the three respiration columns are required; the input must not be guessed.

The current food sheet reports some respiration rates as **CO2 evolution in
`mg CO2/kg/h`**, with a reference temperature. This is not an O2 uptake
measurement. Stop 4 needs a sourced respiratory quotient or independent O2
evidence before converting between them. The architecture examples supply
temperature and shelf-life-target scenarios, not validated food properties.

`food_reference_id` is an optional traceability key for Stop 2. A unique exact
commodity name can be resolved without it; a duplicated name cannot. The
food master has 87 duplicated exact names in the supplied 5,000-row version,
so a first-match join would attach the wrong source to some cases.

## Observed source coverage at contract design

The two available 5,000-row food workbook versions each have 720 populated
`pH` cells. The later USDA-handbook-enriched version has 116 respiration rows
versus 84 in the earlier online-enriched version. In both, the 11 scenario
columns from `desired_shelf_life_days` through `net_pack_quantity_unit` have
zero populated data rows. They are commodity references, not 5,000 complete
recommendation cases. A future importer must preserve blank values and report
coverage rather than populate them with invented operating conditions.

The available material workbook has 81 grade rows. Its CO2 training flag is
true on 13 rows and false on 68. Many other CO2 values are explicitly
estimated; all require original test-condition and source-status checks. The
presence of a supplier food-contact statement does not establish compliance
of a finished multilayer package. Neither workbook provides measured
food-package shelf-life trial outcomes.

Source workbooks and third-party PDFs are not committed to this repository.
Their hashes, row IDs, provenance, data-use rights, and excluded/estimated
value counts must be recorded before these references can be used by a
recommendation run or model fit. No food property, material performance value,
or recommendation threshold is hardcoded in the runtime package.

## Tests and review gate

No example food, material, package, or trial rows are committed in this PR.
The tests check schema structure and field meaning without fabricating records.
They do not establish parser behavior, model accuracy, or recommendation safety.

Review the exact scenario columns, units, controlled categories, conditional
respiration rule, food/material source mappings, and output status meanings.
Any contract change should have a test and an explanation of how existing
source rows are migrated.
