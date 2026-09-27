# Material-reference training readiness

The material workbook is a sourced grade-reference master. It is not a
finished-package catalogue or a food-to-package outcome dataset. The import
audit now reports the evidence basis of OTR, WVTR, and CO2TR separately from
whether each row merely contains a value. A strict measured candidate also
needs its original test temperature, relative humidity, method, and source.

## Audit of the current workbook

Workbook SHA-256:
`17e2791aacee70a1e30f6b73624c5ac2745e5feed36672a9c980499d77fd2564`

- OTR: 81 values; 80 supplier-reported and 1 estimated. 72 have complete
  temperature, humidity, and method context. There are **0 strict measured
  training candidates**.
- WVTR: the same evidence counts as OTR: 80 supplier-reported, 1 estimated,
  72 complete test contexts, and **0 strict measured training candidates**.
- CO2TR: 80 values; 60 estimated and 20 marked measured. Only 13 rows carry
  the explicit training-label flag and pass the complete measured-context
  checks. Seven measured rows lack a complete training context.

These counts are from the imported 81-row workbook, not new observations.
Supplier-reported OTR/WVTR values can remain useful, source-attributed design
references, but the current training policy does not relabel them as measured
outcomes. The 13 CO2TR candidates are too few and too narrow for a robust
group-separated predictive model; no material-property model was fit from
this workbook. The 60 CO2TR estimates are not model targets.

Even a future grade-property model would estimate a material-grade property,
not recommend a food package. Recommendation and shelf-life training still
require independently measured food/package/storage trials and exact finished
package structures. A grade-level barrier value cannot silently stand in for
finished-package performance.

## Reproduce the evidence audit

```powershell
python -m packsense.masters material MATERIAL_WORKBOOK.xlsx --report NEW_REPORT.json
```

The report includes value counts, evidence-basis counts, complete-context
counts, and strict measured candidates for each barrier property. It does not
fit a model or alter the workbook. Output paths must be new. Test-only
objects in unit tests exercise the evidence counter; they are never model-fit
data.

## What would make a barrier-property experiment defensible

Collect additional authentic source records with grade identity, value and
unit, original test method, temperature, humidity, source locator, and the
evidence basis retained. Keep repeated observations and lots from one
manufacturer or study together during splitting. Before fitting, select one
clearly defined property target and compare the model with a simple baseline
on an untouched group-held-out test set. If the independent groups or matched
test conditions are insufficient, retain the records as references and
report `not_ready`; do not fill gaps with estimates or cross-product labels.
