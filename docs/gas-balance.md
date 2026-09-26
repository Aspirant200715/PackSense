# Stop 4: local produce gas-inventory balance

`packsense.gas_balance` calculates one **local** O2/CO2 balance for an exact
food, recommendation record, finished package, and exposure temperature. It
does not model a changing MAP atmosphere or certify that the gas composition
stays safe throughout storage. The approach follows published headspace
material balances that separate produce respiration from film transfer
([fresh-produce MAP mass-balance study](https://www.sciencedirect.com/science/article/pii/092552149400053U),
[dynamic gas-exchange model](https://www.sciencedirect.com/science/article/pii/S0925521498000581)).

The function needs **separate measured** O2-consumption and CO2-production
kinetic evidence from the temperature-correction stage. Both must match the
food, exact starting gas mixture, and exposure temperature; the scenario's
declared respiration observation must also match the corresponding source
rate. It also needs the fill mass, headspace amount, initial and external gas
compositions, signed O2/CO2 transfer observed for the finished package at
those exact conditions, and sourced food gas limits. A transfer value can
include perforations or a closure only when the finished-package measurement
actually includes them. No grade-level film rate is silently promoted to a
finished-package transfer rate.

For each gas, the output reports the initial inventory in mmol and the
instantaneous net inventory change in mmol/h:

```text
O2 net  = signed package O2 transfer inward − produce O2 consumption
CO2 net = signed package CO2 transfer inward + produce CO2 production
```

The conversion from mg/kg/h to mmol/kg/h uses the [NIST O2 molecular
mass](https://webbook.nist.gov/cgi/cbook.cgi?Name=O2) and [NIST CO2
molecular mass](https://webbook.nist.gov/cgi/cbook.cgi?ID=C124389&Units=CAL).
The result includes source/approval IDs and flags an *initial* O2 or CO2 limit
violation. It also flags adverse species-inventory movement when a starting
gas concentration is already at a limit. These are local diagnostics only:
total gas moles, respiration, permeability, condensation, and gas gradients
can change, so one slope cannot prove a safe trajectory or shelf life.
Every report says `gas_safety_certified: false` and
`shelf_life_predicted: false`.

The optional source register parser accepts JSON with exactly
`schema_version: 1` and an `observations` array. Each observation has the
fields of `FinishedPackageGasObservation` in `packsense/gas_balance.py`:
exact record/food/structure IDs, phase, temperature, fill mass, headspace,
inside/outside gas compositions, signed finished-package transfers, food gas
limits, source IDs/locator, structure and source approval IDs, and evidence
bases. Transfer must be `measured` or `validated_correction`; gas limits must
be `measured`. Duplicate record/structure/phase keys are rejected.

`audit_gas_profile` requires a separate observation for storage, transport,
and the maximum excursion. A missing phase, mismatched quantity or
temperature, or out-of-scope kinetics produces an explicit unresolved result.
The maximum excursion has unknown duration and therefore cannot be converted
into a cumulative exposure. No real approved finished-package gas
observations are bundled. The test cases verify equations only and are not
training rows or recommended packages.
