# TDM Platform v13 — Banking & Healthcare Data Relationships

TDM Platform is a FastAPI backend with a React/Vite frontend for data profiling, sensitive-data classification, synthetic data generation, and referential-integrity discovery and validation.

## Run locally on Windows

1. Install Python 3.10+ and Node.js 18+.
2. From this directory, install Python requirements: `python -m pip install -r requirements.txt`.
3. Start the backend in PowerShell with `./start-backend.ps1` (the script migrates the metadata database before starting the API).
4. Open a second PowerShell terminal in this directory and run `./start-frontend.ps1`.
5. Open http://127.0.0.1:5173. API docs are at http://127.0.0.1:8000/docs.

See [RUN_LOCAL.md](RUN_LOCAL.md) for the complete setup and verification steps.

## Built-in demo source domains

Both sample databases contain fictional, deterministic records and are created automatically when missing:

- **Healthcare** — `patients`, `doctors`, `appointments`, `insurance_claims`
- **Banking & Financial Services** — 11 tables spanning customers, accounts, cards, transactions, lending, and capital markets

Rebuild either explicitly from the project root with `python -m sample_domains.healthcare hospital.db 2026` or `python -m sample_domains.banking banking.db 2026`. Explicit rebuild commands replace the selected database.

## Tests

Run the suite with `python -m pytest -q`. Frontend dependencies are defined by `frontend-react/package-lock.json`; install them with `npm ci` from `frontend-react`, then run `npm run build`.

## Authentication and deployment

The local PowerShell backend launcher uses development authentication so the included React client works out of the box. Development authentication trusts `X-Dev-User` / `X-Dev-Roles` headers and must never be enabled on a public deployment. The backend defaults to production JWT authentication outside the local launcher. Read [SECURITY.md](SECURITY.md) and [DEPLOYMENT.md](DEPLOYMENT.md) before exposing the application publicly.

## Step 9 — Human classification review

Classifications marked `review_required` are persisted to the Human Review queue. Authorized reviewer, steward, and admin roles can list requests under `GET /api/v1/reviews`, inspect an item, and decide through `POST /api/v1/reviews/{id}/approve` or `/reject`. Both decisions require a reason. Approval can optionally correct `pattern_type` and `sensitivity` (`sensitive` or `unknown`); rejection remains blocking. Decisions are recorded through the existing audit subsystem. Synthetic generation and the masking-related generation path are blocked with HTTP 409 when the latest profiling run for the same source/table has a required classification that is not approved.

Apply the new migration with `python -m alembic upgrade head`. The frontend exposes the workflow through the **Human Review** tab. Review endpoints require an authenticated reviewer, steward, or admin role; development headers must never be enabled in production.


## Demo guide

New to the platform? [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) explains every page, each use case,
what happens behind every button, and a 20-minute demo script.

## Platform hardening (roadmap Steps 9-17)

| Step | Topic | Read |
|---|---|---|
| 9 | Human review proven end to end (`tests/test_human_review_e2e.py`) | `api/routers/reviews.py` |
| 10 | HMAC pseudonymization + deterministic masking (`POST /api/v1/mask/{table}`) | [docs/PSEUDONYMIZATION.md](docs/PSEUDONYMIZATION.md) |
| 11 | Bounded/stratified sampling, aggregate metrics, RI health | `Profiling/sampling.py`, `Profiling/aggregate_metrics.py` |
| 12 | Domain plausibility rules (DRAFT until a domain owner activates them) | [docs/PLAUSIBILITY.md](docs/PLAUSIBILITY.md) |
| 13 | Privacy validation and release gate | [docs/PRIVACY_VALIDATION.md](docs/PRIVACY_VALIDATION.md) |
| 14 | Least-privilege, audited Query Agent | [docs/AGENT_SECURITY.md](docs/AGENT_SECURITY.md) |
| 15 | Versioned `/api/v1` contract | [docs/API_VERSIONING.md](docs/API_VERSIONING.md) |
| 16 | Secrets, encryption at rest, retention, landing zone, backups | [docs/DATA_LIFECYCLE.md](docs/DATA_LIFECYCLE.md) |
| 17 | Locked deps, Docker, CI/CD, release checklist | [docs/RELEASE.md](docs/RELEASE.md) |

Install for development with `pip install -r requirements-dev.txt` (exact tested versions).
