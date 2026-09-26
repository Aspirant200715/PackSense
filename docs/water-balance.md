# Stop 4: local produce water and condensation checks

`packsense.water_balance` extends the exact-condition produce audit with
measured transpiration, measured respiratory water release, signed finished-
package water transfer, any measured sorbent uptake, headspace water content,
external RH, measured headspace dew point, and the coldest measured internal
surface temperature. The food, scenario record, package, fill mass,
temperature, and storage RH must agree with the enriched scenario. Transit
and excursion humidity are **not** inferred from storage RH; each needs its
own observed package condition. Missing observations stay unresolved.

Run the source-linked batch audit with the scenario and food master plus the
four reviewed JSON registers:

```text
python -m packsense.produce_audit path/to/scenarios.csv path/to/food.xlsx --route-register path/to/routes.json --kinetics-register path/to/kinetics.json --gas-observations path/to/gas.json --water-observations path/to/water.json --report path/to/new-produce-audit.json
```

The batch report retains source-file hashes and exact record/structure keys.
Exit code 0 means all rows reached local checks or were confirmed
non-respiring; it is **not** a package-safety approval. Exit code 1 means
missing evidence, an exception, or a warning needs attention. Exit code 2
means a malformed input or report-path error. The output file must be new.

The local ledger is:

```text
headspace vapor input before condensation (g/h)
  = produce transpiration + respiratory water
    + signed package water transfer inward − sorbent uptake
```

The result also compares the coldest internal surface with the **measured**
headspace dew point. A surface at or below the dew point produces a
`surface_at_or_below_measured_dew_point` warning. This is a condensation
possibility at that observed condition, not a measured condensate mass. A
positive local vapor input is another warning, not proof of later
condensation. Published experimental models likewise couple transpiration,
package water transfer, temperature, humidity, and condensation rather than
inferring it from commodity moisture percentage alone
([humidity-absorbing tray model and validation](https://www.sciencedirect.com/science/article/pii/S0260877418303947),
[condensation dynamics study](https://www.sciencedirect.com/science/article/pii/S026087741200581X)).

The optional JSON parser accepts exactly `schema_version: 1` and an
`observations` array with the fields of `FinishedPackageWaterObservation` in
`packsense/water_balance.py`. Every value must be tied to the exact
record/food/finished-package/phase; the register retains source IDs, locator,
approval ID, and measured basis. Estimates and unvalidated corrections are
not accepted by this first water-observation contract. Duplicate
record/structure/phase observations are rejected. No sorbent requires zero
uptake; a present sorbent still needs a sourced uptake measurement, which
may itself be zero.

`audit_water_profile` reports storage, transit, and excursion separately.
`combine_produce_profile` pairs these results with the gas-balance audit for
the same record, structure, and phase. It never promotes the two local
diagnostics into a safety certificate or shelf-life estimate. Full product
weight loss, dynamic headspace RH, condensation quantity, gas-safety
trajectory, and requested-life success still require validated time-dependent
models and trials. No real finished-package water observations or synthetic
training data are included here.
