# PackSense decision workspace

This is the build-free MVP frontend for the existing Python decision pipeline.
It has an interactive introductory map, an eight-stage walkthrough, searchable
decision records, an actual trace for one audited scenario, and source-hash
inspection. The walkthrough explains the logic; it does **not** calculate a
packaging answer. An actual trace only displays values in a backend report.

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
