# Preliminary package shortlist

`packsense.recommendation.screen_package_candidates` implements the first
basic recommendation slice after the architecture's food-needs and
package-review gates. It is a conservative shortlist for confirmed
non-respiring foods, not an AI model and not a finished package certification.

## Evidence required

The function returns `not_ready` unless the scenario's requirement card has
source-reviewed decisions for oxygen ingress, moisture gain, and moisture
loss, and its food route is confirmed non-respiring. It also requires an
approved structure-review audit tied to the current material master. Each
candidate must have an exact reviewed commodity scope, service-temperature
coverage across the storage, transit, and maximum-excursion envelope, and
applicable whole-package transfer evidence for every source-limited mechanism.
That evidence must match the exact scenario fingerprint, package, quantity,
target period, temperature envelope, and transport-humidity scope.

Before considering candidates, the direct function also checks the
in-memory review attestation's internal bindings. Its catalogue and register
hashes must match the parent audit; structure IDs must be unique; and each
structure must carry all five passing evidence checks with matching review
IDs and construction/food-contact source IDs. A broken binding returns
`not_ready` with a `structure_review_*` reason and no candidates. This is a
consistency guard, not authentication of the underlying documents or proof
that a human reviewer actually approved them. The direct path also rejects
an invalid package shape, such as a missing sealant layer or service range.

An absent or mismatched limit/measurement remains unresolved. A transfer above
its source-approved food budget excludes that structure. Supplier grade OTR or
WVTR values are not substituted for finished-package transfer measurements.
Evidence is keyed to its exact scenario, structure, and catalogue so records
from other scenarios cannot be borrowed. The system does not combine foods and
material grades into synthetic trials.

## Preliminary preference

When candidates pass those gates and have comparable numeric, source-approved
transfer budgets, the function compares their budget use separately for each
source-limited oxygen/moisture mechanism. A candidate is preferred only when
it is the unique non-dominated choice: no rival has lower transfer on one
mechanism without losing on another. For example, if one package admits less
oxygen but more water than another, both stay in the shortlist without a
forced preference. Exact ties also remain unpreferred. `protection_rank` is
the non-dominated layer (1 is the frontier), not a weighted score; the
worst-case budget-utilization fraction is retained only as a diagnostic.
Where numeric budgets are unavailable or incomparable, no preference is made.
The output preserves source locators and review hashes. This is not a weighted
Stop 6 ranking: cost and sustainability are not in the current material master
and are not ranked. Light sensitivity is reported as an open warning.

The output always sets `package_feasible` and `shelf_life_predicted` to false.
It does not calculate MAP gas composition, approve produce films, predict
shelf life, or replace food-contact and supplier review. Respiring produce
remains out of this first slice until its complete Stop 4 gas/water safety
path is validated for the candidate package and exposure profile.

## Current data readiness

The supplied food workbook imports 5,000 source rows and the supplied material
workbook imports 81 grade rows. There is no reviewed complete-structure
catalogue, no approved food-protection assessment register, and no
scenario-matched whole-package transfer register in the repository. The
current real-data pipeline therefore correctly returns `not_ready`; the test
fixtures marked `TEST_ONLY` exercise code paths only and are not training data.

To obtain a real shortlist, collect and review complete package construction
records (including layer order, gauges, sealant, converter, and format),
food-contact/seal/mechanical/service-temperature evidence, exact food and
condition-specific protection limits, and whole-package transfer results.
The final architecture's later shelf-life prediction still needs independent
measured food-package trials with failure criteria and observed or
right-censored outcomes.

## Structured batch run

`packsense.recommendation_batch` connects scenario ingestion, exact food
reference enrichment, food requirement cards, complete-structure review, and
the shortlist in one JSON report. A scenario CSV/XLSX must contain actual
pack size, requested life, and storage/transport conditions as described in
[scenario ingestion](ingestion.md). The 5,000-row food workbook is a reference
master; it is not a completed scenario batch.

```powershell
New-Item -ItemType Directory -Force outputs | Out-Null
py -3.11 -m packsense.recommendation_batch scenarios.csv --food-master food.xlsx --material-master materials.xlsx --report outputs/batch-recommendations.json --summary-csv outputs/batch-summary.csv
```

The reviewed registers can be supplied with `--route-register`,
`--assessments`, `--structures`, `--structure-reviews`, and `--transfers`.
`--public-candidates data/public_catalogue_candidates.v1.json` optionally
adds source-linked supplier application leads to each valid scenario's JSON
row. These leads never become eligible structures or change `not_ready` into
a recommendation; see [public catalogue intake](public-catalogue-intake.md).
The structure catalogue and its review register must be supplied together;
transfer evidence requires both. The command never creates missing evidence
from material-grade OTR/WVTR or from the requested shelf life.

The report contains one result per input row: `exception` for invalid or
unmatched scenarios, `not_ready` with specific evidence gaps, or
`preliminary_shortlist` with the screened structures. It includes source
hashes, source-row numbers, requirement cards, review and transfer evidence,
summary counts, and explicit false package-feasibility and shelf-life flags.
Each recommendation also carries the source scenario-file SHA-256, separate
from its row-level scenario fingerprint, so later offline comparisons can
reject a stale batch version.
An existing output path is never overwritten. Exit code 1 means the report
contains input exception rows; code 2 means input or output creation failed.
`not_ready` is an expected report result and does not itself make the command
fail.

The optional CSV is a one-row-per-input review summary. It carries the input
row and food-reference row, storage/transport/excursion temperatures, desired
shelf life, issue and evidence-gap codes, eligible structure IDs, and a
preliminary preferred format and total layer thickness only when supported.
Missing values stay blank. Every row states that package feasibility and
shelf life were not established. The CSV also repeats the three input hashes
so it can be traced back to the source workbooks and scenario batch. The JSON
report remains the detailed record for source locators, individual transfer
checks, layer order, and all candidate reasons. The CSV is a decision report,
not a model-training dataset; external text is protected against spreadsheet
formula interpretation when opened in Excel.

## Optional local fresh-produce diagnostics

The batch can attach the existing Stop-4 local gas/water audit to the same
per-scenario JSON report. This is an evidence-gap and instantaneous-condition
view, **not** a fresh-produce package shortlist or MAP safety result:

```powershell
py -3.11 -m packsense.recommendation_batch scenarios.csv --food-master food.xlsx --material-master materials.xlsx --route-register reviewed-routes.json --produce-diagnostics --kinetics-register reviewed-kinetics.json --gas-observations reviewed-gas.json --water-observations reviewed-water.json --report new-batch.json
```

Only `--route-register` is mandatory with `--produce-diagnostics`; absent
kinetics or observations remain explicit unresolved states. The detailed row
adds `produce_local_diagnostics`, keyed to the same exact scenario row and
record ID. The top-level report retains hashes of each supplied register,
unresolved and warning counts, and `produce_safety_certified: false`. The
optional CSV and ordinary `recommendation` object do not change. When a
reviewed package catalogue is supplied, the batch now separately audits
whether each local gas and water observation belongs to the **exact reviewed
catalogue version**, food scope, and service-temperature range. This requires
version-2 gas and water registers with `structure_catalogue_sha256` on every
storage, transport, and excursion observation. Legacy version-1 observations
remain usable as local diagnostics but cannot pass this identity join. Each
observed structure reports `structure_review_binding.status` and explicit
reason codes; the batch reports bound/unresolved counts. A true
`produce_diagnostic_structure_review_joined` means internal identity and
scope checks passed for all observed structures, **not** MAP safety or package
approval. Missing observations, unreviewed structures, a changed catalogue,
or out-of-scope conditions leave the binding unresolved. The ordinary
recommendation remains `not_ready` for respiring produce, and an apparently
clear local gas/water snapshot still cannot prove a safe trajectory or the
requested shelf life.

An initial O₂/CO₂ limit breach measured in an observation is explicitly
reported as `observed_initial_gas_limit_violation`, with affected phases and
a batch count. This flag describes that observed starting state, not a
universal judgement about the package or another MAP gas fill. A successful
catalogue identity join cannot erase the breach or turn the package into an
approved recommendation.

For fresh produce, respiration and gas transfer change with temperature,
food mass and package surface area; a local balance cannot be extrapolated
across distribution without validated dynamics. See the
[USDA-ARS MAP review](https://www.ars.usda.gov/research/publications/publication/?seqNo115=222384)
and the [gas](gas-balance.md) and [water](water-balance.md) audit contracts.
