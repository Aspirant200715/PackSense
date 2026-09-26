# Scenario ingestion and exception audit

This stage implements Stops 1–2 for **scenario tables**. It does not join food
or material references, approve a package, train a model, or infer a missing
operating condition. A row reported as `schema_valid` has passed input syntax
checks only; it is not recommendation-ready.

Install the pinned reader and run the checks:

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m packsense.ingestion path/to/scenarios.xlsx --sheet "Sheet 1"
```

CSV and XLSX are supported. A one-sheet XLSX needs no `--sheet`. The source is
read-only. The command prints a summary and exits with code 1 if any rows are
rejected, 2 if the file/header cannot be interpreted, or 0 if all rows pass.
Use `--report path/to/new-report.json` to save all row-level exceptions. The
report must be a new file; an existing file is never overwritten. It contains
record IDs, issue codes and fields, counts, and the SHA-256 of the source, but
not a copy of the food data. The in-memory audit retains each original row
alongside its normalized form or exceptions.

Required columns have the exact spellings in `packsense/units.py`. The three
respiration columns may be omitted together. If provided, their values must
be complete and carry either `mg CO2/kg/h` or `mg O2/kg/h`; CO2 evolution is
**not** silently converted to O2 consumption. Percentages are 0–100, pH is
0–14, temperatures are Celsius, shelf life is days, duration is hours, and
pack quantity is converted from kg to g or L to mL. The original value and
unit remain in the in-memory raw row. Formula cells, duplicate IDs, missing
required values, nonfinite/out-of-range numbers, and contradictory maximum
temperatures are exceptions. No ambient or chilled temperature is assumed.

The optional `food_reference_id` column is accepted as a source-row key. The
later Stop 2 join validates it against the food master and checks that its
commodity name agrees with the scenario. It is not used to infer missing
storage, transit, pack-size, or target-life values.

The collected 5,000-food workbook can be passed to this command to audit its
**scenario completeness**, but it must not be interpreted as 5,000 completed
scenarios. In the USDA-Handbook-enriched version audited for this change
(SHA-256 `76c5f78c6f6a0ef3c1e5bed7baa442ac9275146198be7de22bbdfe5ef80ccd9f`),
all 5,000 rows are rejected as scenarios because the target life, operating
temperatures, humidity, transport details, and pack quantity are absent. Its
food-property columns remain useful as a separately imported reference.
Extra reference columns are listed as ignored, never silently used as scenario
facts. Proxy food properties may be attached later with their donor and source
recorded, but they must not replace absent scenario choices or become measured
trial outcomes.
