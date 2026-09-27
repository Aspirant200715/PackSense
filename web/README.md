# PackSense decision workspace

A build-free frontend for the backend's `frontend-decision-v1` JSON. It
provides an overview, searchable and paginated decision records, an interactive
eight-step pipeline walkthrough, a trace of one imported decision row, and
source-hash inspection. The walkthrough can follow either a reviewed
non-respiring route or a fresh-produce route and can be played step by step.
It is an explanation, not a computed recommendation. The actual trace uses
only fields in the imported report and does not run a new screen or predictor.
No demonstration food/package rows or model predictions are bundled.

The workspace defaults to a dark theme and has a light-mode toggle. The theme
choice alone is stored in browser local storage. A report is read into browser
memory; it is not uploaded or persisted. IBM Plex fonts load from Google Fonts
when available; system fallbacks are used offline. No report contents are sent
to the font provider.

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
