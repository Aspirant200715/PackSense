# PackSense decision workspace

A dependency-free frontend for the backend's `frontend-decision-v1` JSON. It
provides an overview, searchable and paginated decision records, an eight-step
pipeline explanation, and source-hash inspection. It imports a local file into
browser memory; it does not upload or persist the report. No demonstration
food/package rows or model predictions are bundled.

From the repository root:

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory web
```

Open `http://localhost:4173` and import a JSON file produced by:

```powershell
python -m packsense.frontend_contract batch-report.json --output frontend-decisions.json
```

The backend batch report is **not** the file to import; project it first.
Run UI contract tests with `npm test` inside `web/` (Node 18 or newer). No
`npm install` step is needed. Python backend tests remain separate.

The app refuses an unknown contract version, inconsistent rows, and any
report that claims a deployed model, package feasibility, material prediction,
or shelf-life prediction in this preliminary contract. A shortlist is clearly
marked preliminary. This is a static file viewer, not a live HTTP API or a
trained recommendation model.
