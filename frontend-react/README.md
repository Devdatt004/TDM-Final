# TDM Platform — React Frontend

React (Vite) frontend for the TDM Platform. It talks to the FastAPI backend in
`../api/main.py` over HTTP (default http://localhost:8000).

## Tabs

- **Dashboard** — minimal overview: *Recent activity* card (what the platform is doing / did last),
  classification totals and last 3 activities.
- **Profiling** — upload a CSV / XML / text file *or* pick a database table, then: Data Source
  Connector → sample → Pattern Analyzer + Profiler → Classification. Includes the Recent runs table
  (with an Activity column).
- **Synthetic Data Generation** — detailed preview/download tables live only in this tab.
- **Masking** — recommended masking technique per column (from Data Dictionary sensitivity level)
  plus a masked-sample preview (reuses the synthetic-substitution engine; swap in a dedicated
  masking engine here once the backend has one).
- **Knowledge Base** — Schema Catalog + full Data Dictionary business glossary.
- **Query Agent** — the read-only conversational agent, on its own tab.
- **Logs** — activity log, file locations, generated output files, uploaded input files, and the
  log-retention status. Log entries older than 5 days are deleted automatically.

## Log retention

Retention is enforced by the backend (`metadata_store/activity.py`): at startup and then hourly it
deletes `activity_log` rows older than 5 days. Change the window without editing code by setting
`TDM_LOG_RETENTION_DAYS` before starting uvicorn (e.g. `set TDM_LOG_RETENTION_DAYS=10` on Windows).
Only log entries are deleted - uploaded files, generated files and profiling results are kept.

## Run it

```bash
npm install
npm run dev
```

This starts a dev server at **http://localhost:5500**. Make sure the FastAPI
backend is running at http://localhost:8000 (or set `VITE_API_BASE`, see
below) — the app fetches tables, runs, and summary data on load.

## Pointing at a different backend URL

Copy `.env.example` to `.env` and set `VITE_API_BASE` to your backend's URL:

```
VITE_API_BASE=http://localhost:8000
```

## Build for production

```bash
npm run build
```

Outputs static files to `dist/`, which you can serve from any static host
(same deployment model as the original HTML file — it's still just static
assets that call the API over HTTP).

## Structure

```
src/
  api.js                          - fetch wrapper for all backend calls
  App.jsx                         - top-level state, polling, routing between tabs
  pages/                          - one file per tab (Dashboard, Profiling, ..., Logs)
  components/
    AnalysisControls.jsx          - source select, sample size, Run Profiling
    SourceSelect.jsx              - grouped dropdown (database tables / uploaded files)
    UploadPanel.jsx               - CSV / XML / text upload (drag & drop)
    SummaryCards.jsx              - Recent activity card + classification totals
    ColumnDetailsTable.jsx        - per-run column analysis table
    SchemaCatalogTable.jsx        - schema catalog / data dictionary join
    SyntheticGenerationPanel.jsx  - synthetic data generation + CSV download
    QueryAgentChat.jsx            - conversational query agent chat panel
    RecentRunsTable.jsx           - recent runs table
    VerdictBadge.jsx              - shared "high confidence" / "needs review" badge
  styles.css                      - global styles, ported 1:1 from the
                                     original inline <style> block
```
