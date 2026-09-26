# Stop 3: food protection requirement cards

This stage runs after the exact food-reference join and **before** any package
structure is considered. It records the supplied shelf-life target, fill
quantity, storage RH, handling severity, and the minimum/maximum of the
storage, transport, and maximum-excursion temperatures. It does not average
these temperatures. The individual exposure records also remain in the card.
Transport RH and excursion duration remain unknown.

Run a batch with the same scenario and one-sheet food-reference files accepted
by Stop 2:

```text
python -m packsense.requirements path/to/scenarios.csv path/to/food.xlsx --report path/to/new-requirements.json
python -m packsense.requirements path/to/scenarios.csv path/to/food.xlsx --assessments path/to/reviewed-assessments.json --report path/to/new-requirements.json
python -m packsense.requirements path/to/scenarios.csv path/to/food.xlsx --route-register path/to/reviewed-routes.json --report path/to/new-requirements.json
```

The optional JSON register is a **manually reviewed collection of source
findings**, not a generated food-material training table. Its top-level keys
are exactly `schema_version` (integer `1`) and `assessments` (an array). Every
assessment needs these exact fields:

```text
food_reference_id, mechanism, decision, max_cumulative_transfer,
transfer_unit, pack_quantity, pack_quantity_unit,
valid_temperature_min_c, valid_temperature_max_c,
valid_rh_min_pct, valid_rh_max_pct, assessment_rationale,
source_id, source_locator, approval_id, evidence_basis
```

`mechanism` is `oxygen_ingress`, `moisture_gain`, or `moisture_loss`.
`decision` is `limit` or `not_required`. An absent assessment means
**unassessed**, never “not required.” A `limit` needs a positive cumulative
transfer bound for the exact food and fill quantity: `mmol_o2_per_pack` for
oxygen, or `g_h2o_per_pack` for moisture. A `not_required` decision has null
transfer and unit fields and still needs a source, rationale, and approval.
The register accepts only `measured` or `validated_correction` evidence
bases. Estimated and supplier-reported values cannot authorize a food
protection limit. The external review behind `approval_id` must actually
establish that the stated failure criterion and full scope are transferable;
the program cannot verify that scientific judgment from an ID string.

The scenario quantity is canonicalized to `g` or `mL`; the assessment must
match both quantity and unit. Every exposure temperature, including the
maximum excursion, must fall inside the validated range. Storage RH must be
inside the validated RH range. Because transport RH is absent from the
scenario schema, a narrower RH range cannot be assumed to cover transport;
the finding must explicitly have been reviewed for the full 0–100% RH range.
An out-of-scope finding stays in the register but is **not** applied to the
card. Duplicate assessments for the same food/mechanism are rejected rather
than silently resolved.

For an applicable cumulative limit, the card divides the allowed total by
the *requested* shelf-life days and reports an average per-pack budget in
`mmol_o2/pack/day` or `g_h2o/pack/day`. This is a screening budget, **not** a
measured shelf-life outcome, material OTR/WVTR, or a package permeability
target. Package area, driving gradients, headspace, food sorption/oxidation
behavior, and verified condition corrections are still needed before one can
translate it into a structure-specific limit. Published packaging-design
methods likewise begin with food-specific allowable gas/moisture gain or loss,
shelf life, storage conditions, and food sorption behavior before calculating
required film permeance ([Noriega et al.](https://journals.sagepub.com/doi/10.1177/8756087913484920)).

The card also records explicit gaps for light-sensitivity assessment, seal
integrity, mechanical verification at the supplied handling severity, and
food-contact compatibility. It does not treat pH or moisture content alone
as microbial-safety clearance. Respiring foods retain a pending Stop 4 gas
balance; foods without respiration evidence remain `unclassified` unless an
exact reviewed route register confirms them as non-respiring. Candidate screening remains
disabled by this stage, even if a barrier assessment exists, until the later
mandatory checks are implemented and supported.

The report includes scenario and food-master hashes, an optional assessment
register hash, the requirement rule version, source and approval IDs for
applied findings, and row-level exceptions. Reports are written only to a
new path. Exit code 0 means every input row reached a requirement card,
**not** that the cards are complete or that a package is feasible; 1 means
some scenario rows were exceptions, and 2 means an input/report error.

No reviewed food-protection assessment register is included in the
repository. The supplied food and material reference workbooks do not by
themselves establish cumulative food-failure transfer limits. Thus current
real-data cards will expose gaps rather than fabricated barrier targets.
