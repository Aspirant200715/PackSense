# Film-grade barrier reference comparison

`packsense.grade_reference.compare_grade_barriers` is an optional, laboratory-
condition comparison alongside the existing eight-stop recommendation report.
It is useful when a real scenario has an exact, reviewed non-respiring route and
source-reviewed oxygen and/or moisture protection findings. It does **not**
train a food-to-material classifier, establish package suitability, or change
the package recommendation status.

Run it from the repository root using a genuine scenario batch and the existing
food/material references:

```powershell
py -3.11 -m packsense.recommendation_batch scenarios.csv --food-master food.xlsx --material-master materials.xlsx --route-register reviewed-routes.json --assessments reviewed-assessments.json --compare-grade-references --report new-comparison.json
```

The opt-in result is `rows[*].grade_reference_comparison` in the detailed JSON.
Invalid scenario rows have `null` there. With no reviewed food findings or no
confirmed non-respiring route, it returns `not_ready`. The ordinary
`rows[*].recommendation` and one-row-per-scenario CSV are unchanged.

For each source-limited food mechanism, lower reported film OTR or WVTR is a
directional comparison objective. The tool does **not** divide a food's
cumulative oxygen/moisture budget by a film's area-rate value: package area,
driving gradients, complete construction, and verified temperature/RH
corrections are not available from the two master workbooks. Estimated,
unknown, missing-condition, missing-method, and missing-source observations
are excluded from numerical comparison.

Grades are placed in the same cohort only when every active property's unit,
test temperature, test RH, and method match exactly. The code finds a Pareto
front within each cohort: no other grade in that cohort has an equal or lower
value for every active property and a strictly lower value for at least one.
Singleton cohorts are reported separately, not promoted to a one-grade
"winner." The front does not rank different cohorts, assign a preferred
material, or extrapolate laboratory values to storage or transport conditions.
The output preserves source URLs, source workbook hash and row, scenario hash,
and food-limit source IDs.

The current 81-row material workbook imports without rejected rows. A
read-only check using **TEST_ONLY** oxygen and moisture objectives found 71
grades in three multi-grade cohorts, one singleton, and nine without complete
comparable OTR/WVTR evidence. These are coverage counts, not real-food
recommendations. No real reviewed food assessments, scenario batch, or
finished-package verification was created in this change.

`scenario_condition_performance_verified`, `finished_package_verified`,
`material_suitability_established`, `model_trained`, and `package_feasible`
remain false. A supplier film grade is not a tested whole package, and
supplier-reported values are not independent experimental training labels.
