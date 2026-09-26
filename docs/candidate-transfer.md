# Stop 5: finished-package transfer-budget check

This is the first narrow Stop 5 calculation. It compares an independently
reviewed **cumulative whole-package transfer** finding with an applicable
food-protection budget from Stop 3. It does not generate structures from film
grades, convert a laboratory OTR/WVTR value into a package transfer, or claim
that any package is feasible. The material and food reference workbooks contain
no qualifying whole-package findings, so this repository bundles none.

Use `packsense.candidate_transfer.parse_transfer_register(raw_bytes)` to read
a separately reviewed JSON register. It requires exactly `schema_version: 1`
and `observations`, an array. Each observation has these fields:

```text
record_id, food_reference_id, structure_id, structure_catalogue_sha256,
scenario_fingerprint,
mechanism, cumulative_transfer, transfer_unit, target_days,
pack_quantity, pack_quantity_unit, valid_temperature_min_c,
valid_temperature_max_c, valid_rh_min_pct, valid_rh_max_pct,
source_id, source_locator, approval_id, evidence_basis,
correction_model_id, correction_model_version
```

The `scenario_fingerprint` is emitted on each Stop 3 requirement card. It binds
the source finding to the exact food, fill quantity, shelf-life target, storage
and transit temperatures, maximum excursion, storage RH, transport duration,
transport mode, and handling severity. The reviewer must verify that the
source finding really covers the **complete** exposure profile. A matching
hash or approval ID alone cannot prove that scientific fact.
`structure_catalogue_sha256` binds the finding to the exact catalogue file
used for the named complete structure; supply the current catalogue hash to
the check, rather than trusting an ID that could be reused after a revision.

The allowed mechanisms and units match Stop 3: `oxygen_ingress` uses
`mmol_o2_per_pack`; `moisture_gain` and `moisture_loss` use
`g_h2o_per_pack`. The cumulative transfer may be zero; the period and pack
quantity must be positive. `evidence_basis` must be `measured` or
`validated_correction`, not estimated or an unreviewed supplier claim.
Corrected values also need a named, versioned correction model; measured
values use null for those two fields.
The package-source locator and approval ID are mandatory, but authenticity
and usage rights still need an external review. No test-only values in the
unit suite are source data or training outcomes.

Call `check_transfer_budget(card, structure_id, mechanism, evidence,
structure_catalogue_sha256=current_catalogue_hash)` for an
individual comparison. A missing food limit, missing package observation,
changed scenario, wrong food or structure, different pack size/target period,
or temperature envelope that excludes any exposure returns `unresolved`.
Because the current input contract has no transit RH, a source must explicitly
cover the full 0–100% RH range before this check can compare a transfer; it
must not borrow the storage RH for transport. A Stop 3 `not_required` finding
remains a sourced food decision, not an inference from missing package data.

An exact-scope value above the cumulative budget returns `exceeds_budget`:
the structure fails this protection check. A value at or below it returns
`within_budget` **for this mechanism only**. Every report still sets
`package_feasible: false` and `shelf_life_predicted: false`. Complete-structure
approval, food contact, seal integrity, handling strength, service temperature,
light sensitivity, and all other protection mechanisms remain separate gates.
For respiring produce, the local Stop 4 gas and water ledgers are not a
validated time-dependent safety proof, so this check cannot promote a produce
candidate. Ranking and shelf-life learning remain later stops.
