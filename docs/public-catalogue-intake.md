# Public package-catalogue comparison and candidate intake

The first source-backed candidate register is
[`data/public_catalogue_candidates.v1.json`](../data/public_catalogue_candidates.v1.json).
It contains **thirteen selected product records from five directly accessible
supplier sources**. These are traceable claims, not approved complete
structures, food/package suitability labels, measured trial outcomes, or
model-training rows. No values were filled from polymer-family averages.

The register is intentionally separate from the strict
[complete-structure catalogue](structure-catalogue.md). Its supplier products
cannot yet pass that importer: no disclosed layer can be joined to an exact
manufacturer-grade ID in the current 81-row material master, and missing
construction, service, contact, or finished-package transfer evidence cannot
be supplied by matching a generic polymer name. A read-only comparison found
**zero manufacturer-name overlap** between the pilot's four suppliers and
the nine manufacturers in the current 81-row material master; polymer-level
similarity was not treated as a grade match. `claimed_food_scope` records
only a manufacturer's broad wording; `applications` records the narrower
quantity and temperature conditions expressly listed for a SKU.

## Source comparison and intake decision

- **ePoP research database — use for food requirements and design leads, not
  as commercial SKU labels.** The [open Access prototype](https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi%3A10.57745%2FMEBZF0)
  was inspected read-only: its food, requirement, material, and tray/lid tables
  contain 28, 26, 37, and 20 rows respectively. The 20 tray/lid rows are
  candidate pairings, not independent tests of sealed complete packages.
  Its Etalab Open License 2.0 is documented by the publisher. Relevant
  food-limit records may be curated into Stop 3 only with their food,
  temperature, RH, criterion, units, and source context preserved.
- **PouchDirect SKU 179 — included as one unapproved finished-pouch lead.**
  The supplier's [exact two-page TDS](https://www.pouchdirect.com/amfile/file/download/file/1877/product/179/)
  became directly accessible through its [red stand-up pouch listing](https://www.pouchdirect.com/stand-up-pouches/standup-pouch-red).
  It identifies a 120 × 200 + {40 + 40} mm pouch with 12 µm PET / 12 µm metallized PET /
  80 µm LLDPE, a 104 µm total gauge, and a ≥20 N/15 mm seal-strength claim.
  It supplies OTR 0.5–5 at 23°C/50% RH and WVTR 0.5–3 at 38°C/90% RH in
  cm³/m²/day and g/m²/day respectively. The TDS explicitly calls both
  barrier ranges *indicative structure-type values* that may vary; they are
  not measured transfer results for this finished pouch or this food. Its
  direct-food-contact statement is a claim, while the separate Declaration
  of Conformity is available per invoice and has not been reviewed. No
  food-specific application, numerical service-temperature envelope,
  sealing-process temperature, or handling-strength scope is supplied.
  The TDS's 60-month shelf life is a packaging-product storage claim, not a
  measured shelf life for food packed in it. Source rights remain pending.
- **The Packaging Lab laminate — included as one film candidate.** The
  directly accessible [v3.4 specification](https://www.thepkglab.com/1799044271/Handler/CSSOverride/GetImage/4/PkgLab-spec_ThickCLRMatteBOPP_v3.pdf)
  states three layers, gauges, typical OTR/WVTR, seal strength, sealing
  temperature and a material food-contact claim. It does not state OTR/WVTR
  test temperature or humidity, nor a food-service temperature. Its 10–26°C
  storage range is for the *unused film*. The newer v3.4 sheet identifies
  the inside as EVOH PE; the older v3.0 sheet should not be copied instead.
- **Kuraray PLANTIC — included as two component candidates.**
  [FX](https://plantic.kuraray.com/en/products/plantic-fx-flexible/) publishes
  a PE/Plantic/PE film and OTR/WVTR at specified laboratory conditions, but
  its 90–300 µm figure is for the Plantic layer, not a complete film gauge.
  [R+](https://plantic.kuraray.com/en/products/plantic-rplus-rigid-map/)
  publishes barrier tests for 450 µm tray/base material and says sealing
  requires a compatible PE lid. No tested, identified tray/lid combination
  or finished-package gas transfer is supplied. The 450 µm test value was
  not extrapolated to the product's full 250–700 µm gauge range.
- **Sumitomo P-Plus — included as nine narrow produce-bag candidates.** The
  [standard-bag list](https://www.sumibe.co.jp/product/p-plus/business/standard/index.html)
  supplies exact SKU, produce, fill amount, bag gauge and dimensions, and
  recommended storage temperature; several rows also state a limited warm
  excursion. Those temperature ranges are *use instructions*, not an
  independently verified material service limit. The list does not provide
  per-SKU O₂/CO₂ transfer, construction or seal strength. Its PK601 apple
  product is explicitly an inner liner, not a standalone package. The
  three added rows are EY8K3 (500 g edamame), VY7K4 (500 g broccoli), and
  HY8K7 (200 g spinach); all three list 1–10°C storage and an up-to-25°C,
  eight-hour excursion. These are separate SKUs, not interchangeable sizes
  of an established suitability result. The first value in each published
  three-part bag-size expression is interpreted
  as a gauge in millimetres; the supplier should confirm this interpretation
  before approval. The
  [manufacturer's adoption guidance](https://www.sumibe.co.jp/product/p-plus/business/introduction/index.html)
  calls for pre-use evaluation because cultivar, weight and distribution
  conditions affect the perforation design.
- **Amcor LifeSpan — use as a supplier inquiry and application lead.** Its
  [fruit](https://www.amcor.com/lifespan/fruit-applications) and
  [vegetable](https://www.amcor.com/lifespan/vegetable-applications) pages
  describe produce-specific masses and temperatures, but public pages lack
  an exact SKU construction and O₂/CO₂ transfer series. No LifeSpan product
  was converted into a training label or numerical permeability row.
- **Jindal and Oben — material-grade enrichment, not complete structures.**
  [Jindal's current film portfolio](https://www.jindalfilms.com/wp-content/uploads/2026/04/Product-Portfolio-Flexpack-04-2026_.pdf)
  and [Oben's catalogue](https://www.obengroup.com/wp-content/uploads/2024/06/Catalog-Films-0624.pdf)
  list real film grades and gauges. The existing material master already has
  ten Jindal Films observations, but none establishes a multilayer finished
  package. They were not duplicated as package candidates.
- **Sealed Air Darfresh 10K — hold for a specified carrier.** The
  [manufacturer's sheet](https://www.sealedair.com/content/dam/food-packaging-materials/vacuum-skin-packaging/darfresh-10k-otr/Darfresh_10K_NA_SellSheet_2020.pdf)
  reports a finished-package OTR claim for a specific seafood vacuum-skin
  application, but permits multiple bottom carriers. Without one exact
  carrier and full construction, it is not a single transferable package
  record and is not a fresh-produce MAP candidate.

Public availability does not itself establish permission for bulk database
reuse. All manufacturer sources in the pilot retain `rights_review_status:
pending`. Their claims need a document and rights review before use beyond
this internal research intake.

## Audit and next promotion work

### Supplier application lookup in batch reports

The existing batch command can now read this register alongside the food and
material workbooks:

```powershell
py -3.11 -m packsense.recommendation_batch scenarios.csv --food-master food.xlsx --material-master materials.xlsx --public-candidates data/public_catalogue_candidates.v1.json --report outputs/new-batch-report.json
```

For each valid scenario it adds `supplier_application_lookup` to the JSON
report. The lookup compares only supplier-listed food, pack quantity, storage
temperature, and transit temperature/duration. `g` and `kg` are converted
exactly. Food names are matched case/whitespace-insensitively. A food-master
name of the form `broccoli, raw` versus a supplier's `broccoli` is shown only
as an **unreviewed name variant**. A single colour-qualified form such as
`asparagus, green, raw` is also exposed as an unreviewed lead, never an exact
identity match; arbitrary middle qualifiers are not accepted, so
cooked, frozen, and other forms are not silently mapped to a fresh-food
application. A supplier-listed warm excursion
is checked conservatively against the full transport duration. The box-inner
liner remains flagged as incomplete without its outer package. Products with
no exact food application, including the broad PLANTIC component claims, are
not turned into matches.

This lookup is a research aid, not an ML classifier, score, approved structure,
or material recommendation. Even a food/quantity/temperature match cannot
establish food-contact scope, source rights, service limits, gas balance,
whole-package OTR/CO2TR/WVTR, target-life performance, or handling strength.
It leaves the existing recommendation status and preferred structure unchanged.
The Results UI groups these leads into listed-condition matches, related raw-food
names that still require identity review, and out-of-scope uses. A separate
engineering tier displays only candidates from the existing complete-structure
screen; supplier-listed products cannot be promoted into it by this grouping.
The real 5,000-food workbook has no actual scenario pack quantities or exposure
inputs; a separate genuine scenario batch is still required to exercise this
lookup. No scenarios or labels were generated from the food workbook.

Run the deterministic intake audit from the repository root:

```powershell
py -3.11 -m packsense.catalogue_candidates data/public_catalogue_candidates.v1.json
```

The audit checks unique source/product IDs, supported units, physical ranges,
paired test conditions, exact food scope and temperature fields. It reports
coverage and per-candidate blockers. It always reports zero approved packages
and zero suitability labels. The audit does **not** authenticate URLs, prove
scientific applicability or turn a manufacturer claim into a measured result.

## One-candidate pilot evidence trace

When an actual, fully specified scenario batch is available, select **one**
public product ID for a row-level evidence trace:

```powershell
py -3.11 -m packsense.recommendation_batch scenarios.csv --food-master food.xlsx --material-master materials.xlsx --public-candidates data/public_catalogue_candidates.v1.json --pilot-candidate-id POUCHDIRECT-SKU179 --report new-pilot-audit.json
```

Each valid row then has `pilot_candidate_audit`: the exact candidate/source
identity, any supplier-listed food/quantity/temperature application matches,
and the independently reviewed evidence still required for promotion. Invalid
scenario rows retain an input exception and have no pilot audit. An unknown
product ID is rejected. The trace cannot create a `StructureDraft`, review
declaration, package-transfer observation, suitability label, or recommendation.
It leaves the ordinary shortlist untouched. For SKU 179, it will report **no
published food-specific application** and flag the indicative barrier values;
the separate supplier listing's food-grade and filling-temperature claims are
not a complete service, migration, or food-specific performance approval.

An [open peer-reviewed peanut-kernel packaging study](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0190377)
reports a real 10 kg food/package comparison, but its experimental
PET/AL/PA/PE bag is **not** PouchDirect SKU 179. It also does not disclose a
complete scenario-specific transport history, exact component grades, or the
supplier review packet required by our structure gate. Its findings must not
be transferred to SKU 179 by polymer-family resemblance or inserted into the
material-training register as a joined outcome.

The next usable tranche should focus on two bounded families:

1. For the dry-food laminate or pouch route, obtain an exact converter and
   grade/gauge stack; current, food- and jurisdiction-specific contact
   documents; service temperatures; seal/handling tests; and complete-package
   OTR/WVTR with test conditions and package geometry. Where a source gives
   only a film result, do not scale it into a pouch result without validation.
2. For the produce route, obtain P-Plus SKU construction, measured whole-bag
   O₂ and CO₂ transfer over the listed temperature range and allowed
   excursion, seal/closure evidence, food-contact scope, and trial data for
   the exact produce quantity. Do not assume one vegetable's bag works for
   another.
3. Join only exact disclosed component grades to the material master. Add a
   new sourced grade row when the supplier identifies a grade absent from the
   81-row master; do not equate “PET” or “PE” with an unrelated manufacturer's
   grade at the same gauge. Then run the existing structure-review and
   finished-package transfer gates before any release claim.
4. Keep the Kaggle training gate closed until independent scenario/structure
   suitability decisions with both suitable and unsuitable examples have
   been reviewed, rights-cleared, and split by source family and food before
   fitting. These ten candidate records are **not** those decisions.
