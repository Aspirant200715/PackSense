# Stop 4: temperature-scoped produce respiration

This slice corrects a source-matched respiration measurement to the separate
storage, transport, and maximum-excursion temperatures. It requires the
exact food to have a reviewed `confirmed_respiring` route. It does not infer
that CO2 evolution equals O2 consumption, turn a CO2 rate into an O2 rate,
or treat a reference-atmosphere rate as a MAP safety result.

```text
python -m packsense.respiration path/to/scenarios.csv path/to/food.xlsx --route-register path/to/reviewed-routes.json --kinetics-register path/to/reviewed-kinetics.json --report path/to/new-report.json
```

The kinetics JSON has exactly `schema_version: 1` and a `kinetics` array.
Each entry needs `food_reference_id`, `measured_rate`, `rate_unit`,
`reference_temperature_c`, `q10`, `valid_temperature_min_c`,
`valid_temperature_max_c`, `reference_o2_pct`, `reference_co2_pct`,
`rate_source_id`, `q10_source_id`, `source_locator`, `approval_id`,
`rate_basis`, and `q10_basis`. The rate basis must be `measured`; Q10 must
be `measured` or `validated_correction`. Estimated labels are rejected.
The rate unit identifies `mg CO2/kg/h` or `mg O2/kg/h`. Each food/gas-rate
pair may appear only once. The measured rate, unit, and reference temperature
must match the scenario's stated observation; the source review behind the
approval ID must establish the food form and Q10 applicability.
Confirmed non-respiring rows are marked `not_applicable`; unclassified or
unsupported respiring rows remain unresolved.

The calculation is `rate(T) = measured_rate × Q10^((T − Tref)/10)`.
It runs only inside the validated temperature range and **at the source's
reference O2/CO2 atmosphere**. Q10 alone supplies no response to changing
headspace gases. An out-of-range excursion returns a null rate with an
explicit reason, not an extrapolation. The maximum excursion remains a
safety-check condition with unknown duration. Every output preserves its
gas species, source IDs, approval ID, phase, and input hashes.

Temperature and gas composition both affect produce respiration, so a
single temperature multiplier does not replace a gas-dependent model
([Hertog et al., dynamic gas-exchange model](https://www.sciencedirect.com/science/article/pii/S0925521498000581)).
Measurements of fresh-cut produce can report O2 consumption and CO2
production separately across temperature and time
([time-and-temperature study of selected fresh-cut produce](https://www.sciencedirect.com/science/article/abs/pii/S0925521413000355)).
No reviewed Q10 findings or synthetic training rows are bundled. Passing
this stage does not authorize a package recommendation or shelf-life claim.
