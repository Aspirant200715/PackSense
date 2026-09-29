# Catalogue deployment

The first hosted PackSense release shows source-backed manufacturer-listed
applications only. It makes no food-specific packaging recommendation and does
not run the evaluation form. The Python service serves both `web/` and `/api/`
from one origin, so there is no separate frontend URL or CORS setting.

## Deploy on Render

1. In Render, choose **New → Blueprint** and connect the GitHub repository
   `Aspirant200715/PackSense`. A fork is unnecessary when your GitHub account
   can authorize Render to access this private repository. Select `main` and
   apply the repository's `render.yaml`.
2. The Blueprint installs only the catalogue service's dependency, uses
   Python 3.13 from `.python-version`, and starts the app on Render's `PORT`.
   Render supplies `RENDER_EXTERNAL_HOSTNAME`; the Blueprint sets
   `PACKSENSE_BIND_HOST=0.0.0.0`. No secret or database connection is needed.
3. Check `/healthz` for `{"status":"ok"}`, `/api/status` for
   `"mode":"published_catalogue"` and `"can_evaluate":false`, then open the
   root page and confirm that the published applications load. The browser
   should show **Connected** and supplier-listed uses, with no evaluation
   action. The deployment uses the catalogue file committed in `data/`.

The Blueprint uses Render's free service for an initial trial. Choose a paid
service before treating availability as production critical. To attach a
custom domain, configure it in Render and add its bare hostname (without
`https://`) to `PACKSENSE_PUBLIC_HOSTNAMES`; separate multiple hostnames with
commas. Redeploy after changing this variable.

## Data and release boundary

The first release is read-only. Catalogue entries live in
`data/public_catalogue_candidates.v1.json`; there are no user records or
server-side writes, so a database would add no useful capability yet.
Supabase MCP access in Codex is only a developer tool connection and does not
give the deployed app a database or environment variables.

Before enabling the evaluation form, supply approved food and material master
files and review the evidence gates documented in this repository. At that
stage, design authenticated backend endpoints, add a managed PostgreSQL
database (Supabase or Render Postgres), apply versioned migrations, and keep
database credentials in the hosting platform's server-side environment. Do
not expose a service-role key in frontend JavaScript. The current browser
form and batch pipeline are not configured for a public multi-user service.

The catalogue's source-rights review status is still `pending`. Resolve that
review before a general public launch. The UI identifies applications as
published supplier uses, not approved packages or predictions.
