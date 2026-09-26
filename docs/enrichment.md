# Exact food-reference enrichment

This Stop 2 extension joins each schema-valid scenario to one accepted food
master row. It preserves the supplied scenario values, master row number,
source hash, and pH reference evidence. It does not replace a scenario food
property with a proxy value, infer a transport condition, or make a material
recommendation.

Run it on a scenario CSV/XLSX and the one-sheet food reference workbook:

```text
python -m packsense.enrichment path/to/scenarios.csv path/to/food.xlsx
python -m packsense.enrichment path/to/scenarios.xlsx path/to/food.xlsx --scenario-sheet "Scenarios" --report path/to/new-audit.json
```

The JSON report gives source hashes, exception counts, row IDs, match IDs, and
reasons, without copying raw food-property values. It must be written to a
new path. Exit code 0 means all rows were enriched, 1 means some rows are
exceptions, and 2 means an input file cannot be interpreted.

Without `food_reference_id`, a match requires the same commodity name after
case and whitespace normalization. Fuzzy, prefix, and food-family matches are
not accepted. If two source rows share that name, the row is an exception
until the dataset supplies an explicit `food_reference_id`; that ID must also
agree with the name. The supplied 5,000-food workbook (SHA-256
`76c5f78c6f6a0ef3c1e5bed7baa442ac9275146198be7de22bbdfe5ef80ccd9f`)
contains 87 duplicated names, covering 174 rows. This is why source-row
identity cannot be guessed from display text.

The in-memory exposure profile contains normal storage, normal transport,
and the transport maximum as three separate records. The specified storage
humidity stays with storage; transit humidity is unknown. Transport duration
is supplied, but neither actual storage duration nor excursion duration is
available. The shelf-life target is not substituted for measured storage
duration, and the maximum is a safety-check condition, not a time-weighted
average segment.

If the matched food row reports respiration, the scenario must provide its
rate, unit, and measurement temperature. If neither row reports respiration,
the produce route remains `unclassified`, not automatically
`non_respiring`. A trusted commodity classification is still needed before
Stop 4 can be skipped. Reported reference pH, especially proxy or range
midpoint pH, is retained as reference evidence only; the scenario pH has no
measurement provenance in the current input contract. These facts cannot
support automatic microbial-safety or MAP claims at this stage.

This branch remains CPU-only. The separate experimental moisture estimator
may provide labelled exploratory values, but its wide intervals do not
qualify it to silently fill a hard packaging requirement. Packaging-choice
and shelf-life training still require measured food-package-condition trials.
