# PackSense decision workspace

This is the build-free MVP frontend for the existing Python decision pipeline.
It opens on a separate, responsive introduction with a layered-package
schematic. The drawing explains the method; it is not a simulated result.
When real food and material reference masters are configured, **Evaluate a
food** is the primary action. Otherwise **Explore PackSense** is primary and
starts the eight-stage guided tour. Four linked decision-path stops can also
open a specific stage on wider screens. A prominent play/pause control,
progress indicator, and clickable connected stage track show how the process
advances. A three-phase map (add data → follow checks → read output) and subtle
moving indicators make the progression visible without changing any result.
The same play/pause control can advance through an **actual reported row** after one is loaded;
it only plays back the report and performs no new inference. With reduced
motion enabled, the tour waits for a manual click instead of auto-playing.

The workspace has a compact empty overview with four clickable checkpoints,
an **Evaluate a food** form when the two reference masters are configured,
searchable decision records with status filters, expandable evidence details,
an actual trace for one audited
scenario, and source-hash inspection. Long record details are collapsed until
requested. The walkthrough explains the logic; it does **not** calculate a
packaging answer. An actual trace only displays values in a backend report.
The top bar is the single connection-status display; it shows Connected,
Offline, Running, or a report-loading error as appropriate.

The app uses a light color scheme throughout. The Results tab loads two saved,
source-backed demo decisions when no user report is open. They are actual
batch-engine `not_ready` results with illustrative operating inputs, not
predictions or package approvals. A user submission or imported report replaces
the demo. DM Sans and IBM Plex Mono are fetched from Google Fonts when online;
system fonts are used offline. Report contents are not sent to the font host.

For the hosted evaluation form backed by the supplied reference workbooks, see
the [deployment guide](../docs/deployment.md).

## Run locally

From the repository root, start the connected local app:

```powershell
python -m packsense.web_server --port 4173
```

Open `http://127.0.0.1:4173/`. With no scenario sources configured, the
backend reports that it is online but cannot run a batch. You can still open
an already projected `frontend-decision-v1` JSON file in the browser.

To open an existing **audited batch report** automatically:

```powershell
python -m packsense.web_server --batch-report path/to/batch-report.json
```

To inspect real manufacturer-listed package uses **without making up a
scenario**, configure only the reviewed research catalogue:

```powershell
python -m packsense.web_server --port 4182 --public-candidates data/public_catalogue_candidates.v1.json
```

The introduction then offers **View published package uses**. The Overview
shows the nine standalone food/pack-size/temperature applications in the
current catalogue with product codes and direct manufacturer source links.
The Overview can search those returned source uses and compare two published
food, fill, pack format, storage and excursion claims side by side. This is
source discovery, not a suitability score or a recommendation; different
foods' listed uses are not interchangeable. The compact **Review updates**
control reflects only the current backend, catalogue or decision-report
state. Report items open the corresponding status-filtered records; it does
not simulate notifications or report unobserved packaging outcomes.
The box inner liner is omitted because it is not a standalone package. This
view does not run the suitability model, predict a material, or approve a
package. All nine applications are source claims with rights review pending.
The local API is `GET /api/published-applications`; its response carries the
catalogue SHA-256 and explicit false prediction/approval flags. A real
scenario batch is still needed to compare an actual food and journey with a
published use.

To evaluate **one food without preparing a spreadsheet**, configure the food
and material reference workbooks when starting the local server:

```powershell
python -m packsense.web_server --port 4173 --food-master "path/to/food-master.xlsx" --material-master "path/to/material-master.xlsx" --public-candidates "data/public_catalogue_candidates.v1.json"
```

`--public-candidates` is optional. The introduction and top navigation then
show **Evaluate a food**. Search the exact food-reference name or ID, select
a complete row, and enter your own target shelf life, storage temperature and
humidity, transport conditions, handling severity, and net quantity. No
browser Excel upload is needed. The food's moisture, fat, pH, and available
reference respiration come from the configured source workbook; the form
shows the pH evidence basis and citations. A row with missing basic source
properties is visible in search but cannot be submitted. A source-reference
property is not a measurement of the user's batch; the submitted operating
conditions are not independently verified measurements either.

The form sends one bounded JSON scenario to `POST /api/evaluate`. The backend
validates the selected food ID and reference hash, rejects extra fields,
creates a temporary one-row scenario, and runs the existing audited batch
pipeline. The temporary file is removed after the run. The result appears in
Results and the recorded Pipeline trace; it may be an input exception,
**Needs evidence**, or a preliminary shortlist. Entering a desired shelf
life supplies a target, not a predicted shelf life. There is no deployed
material-prediction model or released package recommendation. Only the
backend operator configures reference files and optional evidence registers.

To run a real scenario batch from operator-selected source files:

```powershell
python -m packsense.web_server --scenarios path/to/scenarios.csv --food-master path/to/food-master.xlsx --material-master path/to/material-master.xlsx
```

The app then shows **Run configured batch**. Clicking it invokes the existing
`packsense.recommendation_batch` CLI and projects its audited output through
`packsense.frontend_contract`. The scenario and master paths are set at server
startup, not supplied by the browser. The backend's optional evidence-register
arguments (for example `--route-register`, `--structures`, and
`--structure-reviews`) are also accepted by the web server and forwarded to
the same CLI. Run `python -m packsense.web_server --help` for the full list.
The supplied food and material masters are reference data; they are **not** a
scenario batch. The saved demo has two explicitly specified scenarios in
[`data/demo_scenarios.v1.json`](../data/demo_scenarios.v1.json); the app never
infers a scenario from a food-reference row.

The Pipeline page plays a conceptual input-to-output tour or a trace of a
loaded report. A square moves between stops on a single eight-step timeline
while playback runs; its scene explains the input, PackSense check and
output. Pause or select any step to inspect it. Reduced-motion settings
disable the moving marker. The conceptual tour does not generate a package
result.

The Pipeline page has a compact **How to run a real scenario batch** section.
It links to `/api/scenario-template`, a blank CSV header generated directly
from the backend's required, optional respiration, and reference-key columns.
No example food or fabricated values are inserted. Fill genuine scenario
rows, then start the backend with their file path and the two reference
workbooks. When the service is configured, **Run configured batch** appears
both in that section and in the top bar. When the report arrives, play its
actual trace or open Results and Evidence. Source files remain selected at
backend startup, not uploaded through the browser.

To inspect source-linked supplier applications for those same real scenario
rows, also pass `--public-candidates data/public_catalogue_candidates.v1.json`.
The Results inspector now separates two evidence tiers. **Source-listed
options** show manufacturer-published food, fill, storage, and excursion
conditions, with exact-condition matches apart from related raw-food names
that still need identity review. Differing uses stay collapsible and are not
presented as matches. **Engineering shortlist** shows only reviewed complete
structures that passed the backend's narrow protection screen, or states why
that screen is not ready. The actual pipeline trace counts supplier uses at
package screening. These are **research leads only**. Even an exact-condition
supplier use retains pending rights and independent food-contact, complete-
package transfer, sealing, handling, and suitability blockers. This change
does not populate the material-prediction field or change a row's recommendation
status. The browser still receives no source paths; the one-scenario form
submits only the selected food-reference ID and user-entered conditions.

The local service binds only to `127.0.0.1`, checks the request host and
origin, accepts no browser-supplied source paths or master data, limits a
form submission to 8 KB, and runs one backend evaluation at a time. It is a
local development MVP, not a public deployment.

Alternatively, project a batch report yourself and open that JSON through
the **Open report** button:

```powershell
python -m packsense.frontend_contract path/to/batch-report.json --output path/to/frontend-decisions.json
```

The browser import expects the **projected** JSON, not the raw batch report.
It rejects an unknown contract version or claims of a deployed material model,
package feasibility, or predicted shelf life. A preliminary shortlist is a
screened engineering candidate, not a validated ML recommendation.

Run the UI tests with `npm test` inside `web/` (Node 18 or newer; no install
step). Run the local API tests with
`python -m pytest tests/test_interactive.py tests/test_web_server.py`.
The optional headless browser test `node web/tests/browser-intake-smoke.mjs`
requires a locally running master-configured service and Chrome DevTools;
its entered conditions are explicitly test-only and are never training data.
The optional `node web/tests/browser-reconnect-smoke.mjs` uses a local
catalogue-configured service and Chrome DevTools to verify recovery after
several temporary gateway errors without reloading the page.
