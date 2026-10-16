# Deploying TDM Platform to a public URL - $0/month

Two pieces get deployed separately: the FastAPI backend (`api/`) and the
built React frontend (`frontend-react/`). This guide uses Render's free
plan for the backend and Vercel's free plan for the frontend - both are
free indefinitely (not a trial), both deploy straight from a GitHub repo,
and this repo is already set up for both (`render.yaml`, `.gitignore`).

## What "free" actually means here

- **Vercel (frontend):** genuinely free, no caveats that matter for this
  app - static sites don't sleep, don't cold-start, and don't cost
  anything at this scale.
- **Render (backend), free plan:**
  - The service spins down after 15 minutes with no requests, and the
    next request wakes it back up - expect a 30-60 second delay on that
    first request after it's been idle. Every request after that is
    normal speed until it goes idle again.
  - The filesystem is ephemeral: `metadata_store.db`, uploaded files, and
    generated synthetic-data files reset whenever the service redeploys
    or Render recycles the container. The built-in `hospital.db` and
    `banking.db` demo sources are recreated at startup if missing.
  - In practice: you may need to re-upload files and re-run Profiling
    after a service reset because local generated data is ephemeral.

If that filesystem reset is annoying later, there's a genuinely free fix
too (a free hosted Postgres database instead of local SQLite) - see
**Optional: free persistent storage** at the bottom. It's a separate step
you can do anytime, not a blocker to deploying now.

## Step 1 - Push the code to GitHub

Render and Vercel both deploy from a git repo.

```bash
cd "TDM Platform"
git init
git add .
git commit -m "Initial commit"
```

Create an empty repo on GitHub (github.com -> New repository, no README/
.gitignore - you already have one), then:

```bash
git remote add origin https://github.com/<you>/tdm-platform.git
git branch -M main
git push -u origin main
```

> Pushing from this exact folder (not a parent folder containing it) keeps
> `render.yaml` at the repo root, which is where Render expects to find it.

## Step 2 - Deploy the backend (Render, free)

1. Go to [render.com](https://render.com), sign up/log in, connect your
   GitHub account. No credit card is required for the free plan.
2. **New +** -> **Blueprint** -> pick the `tdm-platform` repo. Render reads
   `render.yaml` and proposes the `tdm-platform-api` service on the free
   plan - no changes needed.
3. Optional: set the `ANTHROPIC_API_KEY` environment variable to your real
   key if you want the Query Agent to call Claude for real; it falls back
   to a canned response without one. Set this in the Render dashboard,
   never committed to git.
4. Deploy. When it is live, Render gives you a URL like `https://tdm-platform-api.onrender.com` - copy it, you need it next.
5. Sanity-check it: open `https://<your-backend-url>/tables` in a browser.
   Give it up to a minute on the very first request - that's the cold start.

CORS is restricted to your own frontend. Once you have the frontend URL (Step 3),
set `TDM_ALLOWED_ORIGINS` on the backend to it, e.g.
`https://your-app.vercel.app` (comma-separate several). Left unset, only the
local dev servers (`localhost:5173` / `4173`) are allowed.

## Step 3 - Deploy the frontend (Vercel, free)

1. Go to [vercel.com](https://vercel.com), sign up/log in, connect GitHub.
2. **Add New** -> **Project** -> pick the same repo.
3. Set the **Root Directory** to `frontend-react` (Vercel asks for this
   during import - the repo root isn't the frontend).
4. Framework preset: Vite (Vercel usually detects this automatically from
   `package.json`).
5. Add an environment variable:
   - `VITE_API_BASE` = the backend URL from Step 2
     (e.g. `https://tdm-platform-api.onrender.com`)
6. Deploy. Vercel gives you a URL like `https://tdm-platform.vercel.app` -
   **that's the link you share.** No credit card required.

Vite bakes `VITE_API_BASE` into the build at build time, not at runtime -
if you ever change the backend URL, update the env var in Vercel's project
settings and trigger a redeploy (it won't pick up the new value otherwise).

## Step 4 - Verify end to end

**Authentication limitation:** the current React client sends development identity headers and is intended for local development. Do not expose development authentication publicly. Before deploying this frontend to a public URL, integrate a real sign-in/token flow and configure the backend with production JWT settings. The backend defaults to production authentication; without a real bearer token, protected frontend routes receive HTTP 401. After that integration, go to **Profiling**, run profiling on a table, confirm results show up, then check **Logs** to confirm the activity was recorded.
If the Dashboard shows "Could not reach API," give it a minute in case the
backend was asleep, then double check `VITE_API_BASE` matches the
backend's actual URL exactly (including `https://`, no trailing slash).

## Optional: connecting Oracle / MSSQL / PostgreSQL / MySQL

The **Data Source Connector -> Database** picker lists SQLite (Demo), Oracle,
MSSQL, PostgreSQL and MySQL. SQLite needs nothing. For the others:

1. Install the driver you need: `pip install -r requirements-connectors.txt`
   locally. On Render the build installs them automatically; any that fail
   to build are skipped and the UI says "driver not installed".
2. The database must be **reachable from where the API runs** - a Render
   service can't reach a database that is only open on a private/office
   network (use a publicly reachable host, or run the API inside the network).
3. Users enter host, port, database (Oracle: service name), username and
   password in the portal. The password is kept **in server memory only**
   (dropped on sign-out, after 60 idle minutes, or on restart) - never saved.
4. Optional: set `TDM_ALLOWED_DB_HOSTS` (comma-separated) so users can only
   point the portal at hosts you approve.

## Optional: free persistent storage (keep data across resets)

If re-running Profiling after every cold reset gets old, swap local SQLite
for a free hosted Postgres database - still $0, but the data lives outside
the web service's ephemeral filesystem so it survives redeploys and
restarts. [Neon](https://neon.tech) and [Supabase](https://supabase.com)
both offer a free Postgres tier that doesn't expire (unlike Render's own
free Postgres, which is deleted after 30 days).

This is a slightly bigger change than anything above - `metadata_store/db.py`
would point at the Postgres connection string instead of a local file, and
`requirements.txt` would need `psycopg2-binary`. It's a reasonable next
step once you know you want this running long-term, but it's not required
to get a free, working, shareable link today. Ask me when you're ready and
I'll make that change.

## Notes

- **Custom domain:** both Render and Vercel support adding your own domain
  under the service/project's Settings, once you have one, at no extra
  cost on either platform.
- **Staying within free limits:** Render's free plan includes 750 instance
  hours per month shared across your account - one service running
  on-and-off (per Render's normal spin-down behavior) comfortably stays
  within that for a single demo app like this one.
