# PackSense deployment

The first hosted evaluation is an evidence audit, not a released packaging
recommendation or a trained shelf-life prediction. A valid submission can
return `not_ready` when complete-structure, transfer, or trial evidence is
missing. The two supplied workbooks contain reference foods and film grades,
not approved finished packages or suitability labels.

## Architecture

- **Supabase Postgres** stores an immutable, private versioned pair of the
  approved food and material workbooks. `packsense_private` is outside the
  exposed API schemas. The backend verifies both SHA-256 hashes at startup.
- **Render** runs the Python backend and `/api/` endpoints. It reads the
  active workbook pair from Postgres into private temporary files and serves
  the existing evidence-gated evaluation. It also serves the frontend
  directly, so Render alone is a functional first deployment.
- **Vercel** may serve the static `web/` frontend. `web/vercel.ts` proxies
  `/api/` to Render using `PACKSENSE_API_ORIGIN`, keeping browser requests on
  the frontend origin. Vercel never receives the database password or raw
  workbooks.

The checked food file is the earlier online-enriched 5,000-food reference:
5,000 rows import, with 84 sourced respiration values. The checked material
file imports all 81 grades. The repository's preferred USDA-Handbook-enriched
food version has 116 respiration values and a different source hash. If that
newer reviewed file is supplied, import it as a new bundle and activate it
without deleting the old one.

## 1. Provision Supabase

The separate PackSense project is
[`qmxvqbqrjpedfqvyxdpq`](https://supabase.com/dashboard/project/qmxvqbqrjpedfqvyxdpq)
in `ap-south-1` (Mumbai). The existing Codex Supabase MCP connection is scoped
to another application. Keep passwords and connection strings out of Git and
frontend environment variables.

With the Supabase CLI authenticated, link this repository to the **new**
project and apply both migrations in `supabase/migrations/`:

```sh
supabase link --project-ref YOUR_PACKSENSE_PROJECT_REF
supabase db push
```

Set `PACKSENSE_DATABASE_URL` in your shell to the new project's PostgreSQL
connection string, then run this from the repository root. The URL must stay
server-side. Importing is idempotent; `--activate` atomically switches the
active pair, and an earlier bundle can be reactivated for rollback.

```sh
python -m packsense.reference_store \
  '/home/laterabhi/Downloads/PackSense Food Inputs - Final Online Enriched - 5000 Foods.xlsx' \
  '/home/laterabhi/Downloads/PackSense_Packaging_Materials_CO2_Enriched.xlsx' \
  --activate
```

The migrations and import require the `postgres` administrator. The second
migration grants the `packsense_reader` role `SELECT` only, including its RLS
policies. A separate `packsense_web` login inherits that role. Use its pooled
connection string for Render. For a custom role on the shared Supabase pooler,
the username must be `packsense_web.qmxvqbqrjpedfqvyxdpq`.

## 2. Deploy the Python service on Render

Create a Render web service from the existing private GitHub repository
`Aspirant200715/PackSense`, branch `main`, using `render.yaml` or the equivalent
settings. The Blueprint uses Python 3.13, installs `requirements-web.txt`,
binds to Render's `PORT`, and checks `/healthz`. Set `PACKSENSE_DATABASE_URL`
to the read-only connection string after the active reference bundle exists.
Startup fails if the database is missing, no bundle is active, a file hash
changes, or a workbook has rejected rows.

On the Render URL, verify `/healthz`, `/api/status` (`mode` must be
`interactive_scenario`, `can_evaluate` true, and `model_deployed` false),
`/api/foods?q=apple`, and one actual form submission. Check that the response
identifies evidence gaps and does not claim a predicted shelf life. The
Blueprint uses Render's free plan for an initial trial; use a suitable paid
plan and operational monitoring before relying on its availability.

## 3. Connect the Vercel frontend

The Vercel project is `packsense-web`. Connect the same GitHub repository to it
with root directory `web/`, Framework Preset **Other**, build command
`npm run build`, and output directory `dist`. Set `PACKSENSE_API_ORIGIN` to
the Render service origin, such as
`https://your-service.onrender.com`, then deploy. Add the Vercel production
hostname (without `https://`) to Render's `PACKSENSE_PUBLIC_HOSTNAMES`, and
redeploy Render before submitting the form through Vercel. The browser uses
same-origin `/api/` routes, so it does not need a Supabase key or CORS setup.

If Vercel cannot link the private repo, grant its GitHub integration access
to `Aspirant200715/PackSense` or deploy the static `web/` directory with the
Vercel CLI. The CLI should run from the repository root, because the Vercel
project already specifies `web/` as its root. A fork is needed only if
repository access cannot be granted; it adds another copy to keep synchronized.

## Release boundary

The Kaggle notebook has not produced a deployable model. The catalogue's
source-rights review is still pending. This release exposes reference-backed
evidence status and supplier-listed uses, with no package approval claim.
Before offering it as a general public service, review rights, authentication,
abuse limits, operational capacity, and the missing package evidence.
