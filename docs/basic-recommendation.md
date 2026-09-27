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

An absent or mismatched limit/measurement remains unresolved. A transfer above
its source-approved food budget excludes that structure. Supplier grade OTR or
WVTR values are not substituted for finished-package transfer measurements.
Evidence is keyed to its exact scenario, structure, and catalogue so records
from other scenarios cannot be borrowed. The system does not combine foods and
material grades into synthetic trials.

## Preliminary preference

When multiple candidates pass those gates and have comparable numeric,
source-approved transfer budgets, the function can identify a preliminary preference by the
lowest worst-case fraction of the approved oxygen/moisture budget consumed.
The output names this ranking basis and preserves source locators and review
hashes. A tied shortlist, or candidates with no comparable budget, has no
preferred structure. Eligible candidates include their protection rank and
budget-utilization value. This is not a weighted
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
