# Build, CI/CD and Release (Step 17)

## Reproducible builds

| File | Purpose |
|---|---|
| `requirements.txt` | Top-level runtime dependencies (human-edited). |
| `requirements.lock` | Exact tested set for Python 3.10.5, incl. the spaCy `en_core_web_sm` wheel. CI and Docker install **this**. Regenerate deliberately: `pip install -r requirements.txt && pip freeze > requirements.lock` (drop pytest/ruff), then run the suite. |
| `requirements-dev.txt` | Lock + pytest + ruff. |
| `frontend-react/package-lock.json` | Installed with `npm ci`. |

## CI (`.github/workflows/ci.yml`) — every push and PR

1. **Backend** from a clean checkout and an empty `TDM_DATA_DIR`: lint (syntax errors / undefined
   names), `alembic upgrade head → downgrade base → upgrade head`, full pytest suite, `pip-audit`.
   The suite includes the OpenAPI contract snapshot, migration-vs-model drift, adversarial agent tests,
   privacy planted-leak tests, data-lifecycle tests, and production-auth release gates.
2. **Frontend**: `npm ci`, `npm run build`, `npm audit --audit-level=high`.
3. **Images**: both Dockerfiles are built (never pushed) after 1 and 2 pass.

Verified locally on 2026-10-13: a fresh clone with no `.db` files passes lint, the migration round
trip and **327 tests**. Docker images were deliberately **not** built locally; the first CI run is
their first build.

## Containers

* `Dockerfile` — Python 3.10.5-slim, multi-stage, locked deps, non-root uid 10001, `/data` volume,
  `/health` healthcheck, `alembic upgrade head` then uvicorn. No secrets or `.db` files in the image
  (`.dockerignore`). TLS terminates at the proxy in front.
* `frontend-react/Dockerfile` — Vite build → `nginx-unprivileged` on 8080 with security headers.
  `VITE_API_BASE` is a build argument.
* `docker-compose.yml` — api + web + named volume, reads `.env`.

## Release (`.github/workflows/release.yml`) — push a `v*.*.*` tag

images → **staging** (deploy, smoke test) → **production** (required reviewers on the GitHub
environment; backup, deploy, smoke test). The deploy commands are placeholders for your platform.

`scripts/smoke_test.py <url> --token <jwt>` is read-only and fails if: `/health` is down, anonymous
access works, **development auth headers are trusted**, the `/api/v1` contract is not served, or an
authenticated read fails.

## Environments

| | dev | staging | production |
|---|---|---|---|
| `TDM_AUTH_MODE` | `development` | `production` | `production` |
| Secrets | optional (ephemeral / plaintext fallbacks) | secret store | secret store |
| CORS | localhost | staging https origin | production https origin |
| Data | local folder | own volume | own encrypted volume + backups |

Production refuses to start without its secrets (`security/startup_checks.py`).

## Release checklist

- [ ] CI green on the release commit (tests, migration round trip, audits, image builds).
- [ ] `docs/openapi-v1.json` diff reviewed; no breaking change inside v1 (`docs/API_VERSIONING.md`).
- [ ] New Alembic revisions have a working `downgrade()`; migration plan noted in the release notes.
- [ ] **Backup** taken: `python scripts/backup_metadata.py backup` (encrypted) and restore tested on staging.
- [ ] Secrets present in the target environment; key rotations staged (`docs/DATA_LIFECYCLE.md`).
- [ ] Staging smoke test passed.
- [ ] Monitoring: `/health` probe, error rate by `error.code`, `X-Request-ID` in logs.
- [ ] **Rollback owner** named for this release.

## Rollback

1. Redeploy the previous image tag.
2. If the release ran migrations that the previous version cannot read:
   `python -m alembic downgrade <previous head>` (every revision here implements `downgrade`), or
   stop the API and `python scripts/backup_metadata.py restore <pre-release backup>`.
3. Run the smoke test against the rolled-back deployment; record the incident.
