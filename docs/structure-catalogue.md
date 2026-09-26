# Package structure catalogue intake

Stop 2 needs a separate catalogue of actual package constructions. A row in
the material workbook describes one grade or film observation; it does not
prove that a particular layer stack can be made, sealed, used in food contact,
or operated at the scenario temperature. The supplied PS2 assets contain no
verified complete-structure catalogue, so this importer creates **no**
package records from the material sheet by itself.

`packsense.structures` reads a JSON catalogue and joins each proposed layer
to an exact material-master ID and thickness. JSON is used because layer
order is nested data. It is not another food-training worksheet. Run:

```text
py -3.11 -m packsense.structures PATH_TO_CATALOGUE.json --materials PATH_TO_MATERIAL_MASTER.xlsx
```

Use `--sheet` only if the material master has multiple worksheets and
`--report NEW_REPORT.json` for the full audit. Both source file hashes appear
in the report. An invalid material master stops the join.

## Catalogue shape

The top-level JSON object has exactly `catalogue_version` and `structures`.
The latter is an array with one object per complete package draft. Each draft
requires `structure_id`, `pack_format`, ordered `layers`,
`sealant_grade_id`, `converter`, `forming_method`, `closure_type`,
`structure_source_id`, `structure_source_locator`,
`food_contact_evidence_id`, `food_contact_evidence_locator`,
`compatible_food_scope`, `service_temperature_min_c`, and
`service_temperature_max_c`.

Each layer has exactly `grade_id`, `thickness_um`, `role`, and
`is_food_contact`. Layer order is outermost to innermost. For this first
flexible-package contract, exactly the innermost layer is food-contact and
has the `sealant` role; the `sealant_grade_id` must identify it. The gauge
must match the referenced material-grade observation exactly. A different
gauge needs its own sourced grade observation or a later validated gauge
correction; the importer does not extrapolate one.

`compatible_food_scope` is a non-empty list of explicit food scopes. Wildcard
claims such as `all_foods` are refused. A source locator may identify a
supplier specification or controlled laboratory record; merely supplying a
locator does not prove its contents. Duplicate structure IDs, missing or
extra keys, unknown grade IDs, non-finite values, reversed service limits,
and invalid contact/sealant order are rejected with per-row issues. Drafts
using grades with estimated barrier observations are counted separately.

## Approval boundary

The importer returns `StructureDraft` records, **not** the verified
`PackageStructure` objects required by candidate generation. Its report
always states `approved_package_structures: 0`. An engineering evidence
review must independently confirm the source, actual layer construction,
converter capability, contact scope, closure and seal performance, service
limits, and finished-package OTR/WVTR at known test conditions. A supplier's
grade-level food-contact statement is not a finished-package approval.

Only after that evidence and the relevant scenario-condition correction are
available may Stop 5 promote and filter a structure. Temperature correction,
produce gas balance, hard filters, ranking, and shelf-life prediction are not
implemented by this intake. Its test-only identifiers are validation fixtures,
not catalogue entries or training data.
