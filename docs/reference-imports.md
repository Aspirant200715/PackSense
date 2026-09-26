# Sourced reference imports

The food and material workbooks are imported **separately**. Food rows do not
become recommendation scenarios, and material-grade rows do not become
finished packages or measured food-package trials. Imports are read-only;
they retain source URLs, test conditions, basis text, row numbers, and a
SHA-256 version of each source file. Formula cells, duplicate IDs, invalid
units/ranges, and incomplete respiration observations are rejected with row
issues. No raw third-party workbook is committed.

```text
python -m packsense.masters food path/to/food.xlsx
python -m packsense.masters material path/to/materials.xlsx
```

`--sheet` selects a sheet when needed. `--report new-path.json` saves the
coverage and exception report without overwriting an existing file. The
importer accepts the USDA-Handbook-enriched food workbook as the provisional
food reference version because it contains more sourced respiration rows than
the earlier online-enriched version. This choice does not imply that its
contents are product-specific measurements.

The USDA-Handbook-enriched food workbook (SHA-256
`76c5f78c6f6a0ef3c1e5bed7baa442ac9275146198be7de22bbdfe5ef80ccd9f`)
imports 5,000 of 5,000 rows. Moisture is present for 4,888, fat for 4,766,
pH for 720 (709 proxy/range-midpoint and 11 reported references, not product
measurements), and CO2 respiration for 116.

The CO2-enriched material workbook (SHA-256
`17e2791aacee70a1e30f6b73624c5ac2745e5feed36672a9c980499d77fd2564`)
imports 81 of 81 rows. OTR and WVTR are present for all 81, but complete test
conditions are available for 72 of each. CO2TR is present for 80: 60 are
estimated, 13 have a measured condition-complete CO2 training flag, and seven
other supplier values lack complete test conditions.

`pH_evidence` keeps proxy and reported-reference values distinct from absent
values. No pH in this version is silently labelled as a measurement of the
exact listed food. The composition-method code and source citation stay with
each food row; those codes are not interpreted as analytical measurements
without a source codebook. Similar-food proxies may be used as lower-trust
reference features only with an explicit donor, food-form match, citation,
and review; they cannot replace a missing scenario choice or observed trial
outcome. A conservative exact-token-and-food-group scan found no additional
blank-pH rows that could be filled from a pH-bearing row without relaxing the
food-form match, so this import adds **zero new pH estimates**.

Supplier grade OTR/WVTR figures remain at their reported test temperature and
humidity. CO2 estimates preserve their analogue/source basis and are not
equivalent to supplier-measured values. A CO2 grade training flag is about
grade permeability, **not** a shelf-life label. Seven additional supplier
CO2 values lack complete test conditions; they are not condition-controlled
training labels. Food-contact statements and supplier application text are
retained as evidence, not accepted as finished-package compatibility approval.
No complete structure catalogue or measured food-package-condition trial
outcomes were present in the supplied workbooks. Accordingly this stage does
not issue a material recommendation or train the shelf-life model.
