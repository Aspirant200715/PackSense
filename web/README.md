# PackSense decision workspace

This is the build-free MVP frontend for the existing Python decision pipeline.
It opens on a separate introduction. **Explore PackSense** enters the workspace
and starts the eight-stage guided tour; the four decision-path stops can also
open a specific stage. A prominent play/pause control, progress indicator, and
clickable connected stage track show how the process advances. A three-phase
map (add data → follow checks → read output) and subtle moving indicators
make the progression visible without changing any result. The same play/pause
control can advance through an **actual reported row** after one is loaded;
it only plays back the report and performs no new inference. With reduced
motion enabled, the tour waits for a manual click instead of auto-playing.

The workspace has a compact empty overview with four clickable checkpoints,
searchable decision records with status filters, expandable evidence details,
an actual trace for one audited
scenario, and source-hash inspection. Long record details are collapsed until
requested. The walkthrough explains the logic; it does **not** calculate a
packaging answer. An actual trace only displays values in a backend report.
The top bar is the single connection-status display; it shows Connected,
Offline, Running, or a report-loading error as appropriate.

The app defaults to dark mode and has a light-mode toggle. Only the theme is
stored in browser local storage. No demonstration rows or predictions are
bundled. DM Sans and IBM Plex Mono are fetched from Google Fonts when online;
system fonts are used offline. Report contents are not sent to the font host.

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
scenario batch. No scenario file is bundled or inferred from them.

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
The Results inspector then shows published product uses and their food,
quantity, storage and transit mismatches; the actual pipeline trace counts
them at package screening. These are **research leads only**. Even a matching
supplier use retains pending rights and independent food-contact, complete-
package transfer, sealing, handling and suitability blockers. It never
populates the material-prediction field or changes a row's recommendation
status. The browser still receives no source paths or editable scenario rows.

The local service binds only to `127.0.0.1`, checks the request host and
origin, accepts no browser-supplied source paths or row data, and runs one
batch at a time. It is a local development MVP, not a public deployment.

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
step). Run the local API tests with `python -m pytest tests/test_web_server.py`.
