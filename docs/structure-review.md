# Complete-structure review gate

The [structure importer](structure-catalogue.md) produces drafts, not usable
packages. This next Stop 2/5 gate reads a **separate human review register**
for each complete construction. It binds decisions to the exact catalogue,
material-master file, and parsed draft. The supplied PS2 food and material
workbooks do not contain such a register; this repository bundles no real
review-attested structure.

Run from the repository root:

```powershell
python -m packsense.structure_review PATH_TO_CATALOGUE.json --materials PATH_TO_MATERIAL_MASTER.xlsx --reviews PATH_TO_REVIEWS.json --report NEW_AUDIT.json
```

Use `--sheet` when the material workbook has multiple sheets. The audit
reports `not_approved` and exits 1 when any draft or review fails; malformed
inputs exit 2. An output report is optional and is created only at a new
path. The parser never fills a missing decision, source, or temperature
range. Every item in the catalogue must pass for the catalogue-level
`review_attested` status; partial promotion is withheld.

## Review register contract

The JSON top level has exactly `schema_version` (`1` or `2`), `catalogue_sha256`,
`material_master_sha256`, `catalogue_version`, and `reviews`. Those identifiers
must match the two imported files and catalogue version exactly. Each review
has exactly:

```text
structure_id, draft_digest, review_id, reviewer_id,
reviewed_food_scope, service_temperature_min_c,
service_temperature_max_c, checks
```

Version 2 additionally requires `max_reviewed_handling_severity` on every
review, with exactly `low`, `medium`, or `high`. This is the highest handling
severity that the reviewer found supported by the cited mechanical evidence;
it is not inferred from a passing `mechanical` check. Version-1 registers
still parse for provenance auditing, but their handling scope is unknown and
they cannot make a scenario candidate shortlist-eligible or supply a label
to the suitability ranker intake. The audit reports how many attested
structures declare this scope.

`draft_digest` is the lowercase SHA-256 from
`packsense.structure_review.draft_digest(draft)` on the accepted
`StructureDraft`. It includes the layer sequence, exact grade IDs and gauges,
converter, closure, source references, food scope, and service limits. For an
intake-clean catalogue, the following prints identities and digests without
creating approval decisions:

```python
from packsense.masters import load_material_grades
from packsense.structure_review import draft_digest
from packsense.structures import audit_structure_catalogue

materials = load_material_grades("PATH_TO_MATERIAL_MASTER.xlsx")
assert not materials.issues
audit = audit_structure_catalogue(
    "PATH_TO_CATALOGUE.json",
    grades={entry.grade.material_id: entry.grade for entry in materials.entries},
    material_master_sha256=materials.source_sha256,
)
assert not audit.issues
for draft in audit.entries:
    print(draft.structure_id, draft_digest(draft))
```

Each review contains exactly one check of each kind: `construction`,
`food_contact`, `seal_closure`, `mechanical`, and `service_temperature`. Each
check has exactly `kind`, `source_id`, `source_locator`, `source_sha256`,
`review_id`, `rights_review_id`, and `decision` (`pass` or `fail`). A check's
source hash is the lowercase SHA-256 of the underlying reviewed document or
controlled record, not of the JSON field. The construction and food-contact
checks must cite the exact source IDs and locators already named in the
draft. Missing, duplicate, unrelated, or failed checks prevent attestation.

`reviewed_food_scope` must be an explicit, nonempty subset of the draft's
scope; a wildcard cannot become an approval. The reviewed service-temperature
range may narrow the draft's range but cannot widen it. A later scenario
check must still cover storage, transit, and excursions within that range.
The scenario's handling severity must be no higher than the version-2
reviewed scope. A missing scope remains unresolved; a lower reviewed scope
excludes the candidate for that scenario. A severity label does not itself
prove drop, compression, puncture, or seal performance at the actual pack
mass and route; the reviewer must verify the cited tests.
The review register's file hash is included in the audit for traceability.

## What passing means—and does not mean

`review_attested` means the declared reviewer and source records pass the
software's identity, completeness, hash-format, scope, and decision checks.
The software cannot authenticate external documents, verify a rights review,
or determine whether a food-contact certificate actually covers a food,
temperature, and jurisdiction. A responsible reviewer must do that work
outside the parser. Do not create placeholder IDs or hash arbitrary text to
make a production record pass.

The result exposes a `ReviewAttestedStructure` with the narrower food and
temperature scope and all review hashes. It is **not** a scenario-feasible
package. Estimated film-grade barrier values remain labelled; they are not
promoted into finished-package OTR, CO2TR, or WVTR. The existing
[finished-package transfer check](candidate-transfer.md) still needs
independent, exact-scenario measured or validated-correction evidence. Seal
window, handling strength, complete Stop 4 produce safety, all applicable
food-protection mechanisms, and shelf-life validation are later gates.
Every report therefore sets `package_feasible: false` and
`shelf_life_predicted: false`.
