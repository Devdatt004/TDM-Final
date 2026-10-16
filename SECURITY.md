# TDM Platform — Security Architecture (Step 3)

## Authentication Flow

```
OIDC / SSO Identity Provider
         ↓  (issues JWT on behalf of user)
   Bearer JWT in Authorization header
         ↓
   get_current_user()  [api/auth/dependencies.py]
         ↓  decodes + validates JWT claims
   CurrentUser(user_id, username, roles, tenant_id=None)
         ↓
   require_role(...)   [api/auth/dependencies.py]
         ↓  raises HTTP 403 if role not held
   API endpoint
         ↓
   audit_service.record_audit(...)  [api/services/audit_service.py]
         ↓  username + user_id + role written to audit_log
   AuditLog row (append-only, hash-chained)
```

---

## Auth Modes

| Mode | How to enable | How it works |
|------|--------------|-------------|
| **production** | `TDM_AUTH_MODE=production` (default) | Requires a signed JWT in `Authorization: Bearer <token>` |
| **development** | `TDM_AUTH_MODE=development` | Accepts `X-Dev-User: alice` and `X-Dev-Roles: admin,steward` headers instead of a JWT |

> CAUTION: `TDM_AUTH_MODE=development` must **never** be used in a production environment.
> It bypasses all cryptographic verification.

### Production JWT Requirements

- Algorithm: `HS256` (default) — set `TDM_JWT_ALGORITHM` to change
- Secret key: `TDM_JWT_SECRET` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- Issuer (optional): `TDM_JWT_ISSUER`
- Audience (optional): `TDM_JWT_AUDIENCE`
- For RS256 / OIDC: the issuer's JWKS endpoint can be integrated as a future extension

### JWT Claims Used

| Claim | Purpose |
|-------|---------|
| `sub` or `uid` | Mapped to `CurrentUser.user_id` |
| `preferred_username`, `email`, or `name` | Mapped to `CurrentUser.username` |
| `roles` or `tdm_roles` | List of role strings mapped to `CurrentUser.roles` |

---

## RBAC — Roles and Permissions

### Roles

| Role | Description |
|------|-------------|
| `admin` | Full administrative access; can view audit log, manage retention, delete relationships |
| `steward` | Source/data management; profiling, classification, upload, DB connections |
| `reviewer` | Read-only access to profiling results, catalog, relationships, logs |
| `tester` | Can generate synthetic data and download results; read sources list |

### Endpoint Permission Map

| Endpoint | Required Role(s) |
|----------|----------------|
| `GET /health` | **public** |
| `GET /tables` | tester, reviewer, steward, admin |
| `GET /summary` | reviewer, steward, admin |
| `GET /runs` | reviewer, steward, admin |
| `POST /agent/ask` | reviewer, steward, admin |
| `POST /analyze/{table}` | steward, admin |
| `GET /results/{run_id}` | reviewer, steward, admin |
| `GET /schema-catalog/{table}` | reviewer, steward, admin |
| `GET /data-dictionary` | reviewer, steward, admin |
| `POST /generate/{table}` | tester, reviewer, steward, admin |
| `GET /generate/download/{id}` | tester, reviewer, steward, admin |
| `GET /generate/history` | reviewer, steward, admin |
| `POST /upload` | steward, admin |
| `GET /connectors/db-types` | tester, reviewer, steward, admin |
| `POST /connectors/db/connect` | steward, admin |
| `POST /connectors/db/disconnect` | steward, admin |
| `GET /domains` | reviewer, steward, admin |
| `GET /relationships` | reviewer, steward, admin | (`?domain=healthcare\|banking`)
| `POST /relationships/refresh` | steward, admin |
| `GET /relationships/suggestions` | steward, admin |
| `POST /relationships` | steward, admin |
| `DELETE /relationships/{id}` | **admin only** |
| `POST /generate-related` | tester, reviewer, steward, admin |
| `GET /integrity/runs` | reviewer, steward, admin |
| `GET /logs` | reviewer, steward, admin |
| `GET /files` | reviewer, steward, admin |
| `GET /logs/retention` | **admin only** |
| `POST /logs/purge` | **admin only** |
| `GET /audit` | **admin only** |

---

## Audit Hardening

### What is logged

Every audit record contains:
- `event` — what happened (e.g. "DB Connection", "File Download")
- `username` — human-readable actor name
- `user_id` — stable opaque actor id (JWT `sub` or `dev:<name>`)
- `role` — comma-separated roles held at the time
- `target` — resource identifier (table name, file name, etc.)
- `target_type` — resource category
- `status` — "complete" | "failed" | "denied"
- `created_at` — UTC timestamp
- `prev_hash` / `entry_hash` — SHA-256 hash chain

### What is NEVER logged

- Passwords
- JWT tokens
- API keys or signing secrets
- Database connection URLs with credentials
- Raw PHI or patient data
- Raw source records

### Failure behaviour

`audit.record()` raises `AuditError` if the record cannot be persisted.
Sensitive operations (generate, upload, connect) propagate this error rather
than silently claiming success with no audit trail.

Background / system tasks (e.g. log purge) may catch `AuditError` and log
a warning, because their failure mode is less critical than an HTTP request.

### Hash-chain integrity

Each row stores:
- `prev_hash` — the `entry_hash` of the immediately preceding row (or `""` for the first row)
- `entry_hash` — SHA-256 of all meaningful columns concatenated with a unit separator

Tampering with any field in any row is detectable by `GET /audit` which calls
`verify_chain()` and reports the first broken row.

SQLite append-only enforcement is done with database triggers installed by
`audit.install_guards()`. On Postgres, `REVOKE UPDATE, DELETE` from the app role.

### Concurrency safety

A module-level `threading.Lock` in `metadata_store/audit.py` serialises chain
writes within a single process.

**SQLite limitation**: the lock is in-process only. Running uvicorn with
`--workers > 1` (multiple processes sharing the same SQLite file) can still
race. This is acceptable for the single-worker SQLite MVP.
Migrating to Postgres with `SELECT ... FOR UPDATE` or a serialisable
transaction fully resolves this.

---

## SYSTEM_USER vs Authenticated User

| Actor | When | Identity |
|-------|------|---------|
| `CurrentUser` from `get_current_user()` | All HTTP requests | Real user from JWT / dev header |
| `SYSTEM_ACTOR` (`api/auth/models.py`) | Background tasks only (log purge, seed, backfill) | `user_id="system"`, `is_system=True` |

User-triggered actions are **never** recorded as "system".

---

## Tenant Decision — Single-Tenant MVP

**Decision: SINGLE-TENANT**

The TDM Platform v12 MVP is explicitly single-tenant. There is no
`tenant_id` column in the database and no tenant routing logic.

`CurrentUser` carries a reserved `tenant_id: Optional[str] = None` field as
a future extension point. When multi-tenancy is introduced (a later roadmap
step), this field can be populated from a JWT claim and used for
data-scoped queries without breaking the current interface.

To add multi-tenancy later:
1. Add `tenant_id` to all relevant tables (Alembic migration)
2. Populate `CurrentUser.tenant_id` from the JWT claim
3. Add tenant-scoping to all queries

---

## Environment Variables Reference

| Variable | Required in prod | Purpose |
|----------|-----------------|---------|
| `TDM_AUTH_MODE` | Yes (`production`) | Auth mode: `production` or `development` |
| `TDM_JWT_SECRET` | Yes | HMAC-SHA256 signing key |
| `TDM_JWT_ALGORITHM` | No (`HS256`) | JWT algorithm |
| `TDM_JWT_ISSUER` | No | Expected JWT issuer |
| `TDM_JWT_AUDIENCE` | No | Expected JWT audience |
| `TDM_DATA_DIR` | No | Persistent storage directory |
| `TDM_ALLOWED_ORIGINS` | No | CORS allowed origins |
| `TDM_LOG_RETENTION_DAYS` | No (`5`) | Activity log retention |
| `TDM_ALLOWED_DB_HOSTS` | No | Allowlist for DB connector hosts |
