# Secrets, Encryption, Retention and Landing Zone (Step 16)

## Inventory

| Asset | Where | Protection |
|---|---|---|
| Source DB credentials | Vault KV v2 or env var, referenced by `credential_ref` | Registry stores only `env://…` / `vault://…`; anything else is rejected (422). Resolved per connection, never cached/logged. |
| Ad-hoc DB connection (Data Source Connector) | Request body → in-process memory for the session | Not persisted. Prefer registered sources for anything long-lived. |
| Uploaded files | `TDM_DATA_DIR/uploaded_files/<random>.<ext>` | Landing zone checks, encrypted at rest, 30-day retention. |
| Synthetic / masked datasets | `TDM_DATA_DIR/synthetic_output/` | Encrypted at rest, privacy gate (Step 13), 30-day retention, row kept for lineage. |
| Metadata store | `TDM_DATA_DIR/metadata_store.db` (SQLite) | **Not encrypted by SQLite.** Use an encrypted volume; encrypted backups. |
| Keys | `TDM_ARTIFACT_KEYS`, `TDM_PSEUDONYM_KEYS`, `TDM_JWT_SECRET`, Vault token | Environment / secret injection only. Never in code, DB, logs, API or browser bundle. |

## Encryption at rest

`security/artifact_store.py` — Fernet (AES-128-CBC + HMAC-SHA256), header `TDMENC1 <kid>`.
Writes are atomic (temp file + rename). Legacy plaintext files stay readable.

**Rotation:** add the new key first (`TDM_ARTIFACT_KEYS=a2:<new>,a1:<old>`, `TDM_ARTIFACT_ACTIVE_KEY_ID=a2`),
re-encrypt existing files with `artifact_store.rotate_file()` (also encrypts legacy plaintext),
then remove `a1`. Every file names its key id, so you can check none still uses the old one.
**Key loss = data loss** for unexpired artifacts; keep keys in the secret manager with backup.

## Landing zone (uploads)

1. Extension allowlist (`.csv`, `.xml`, `.txt`) and ~5 MB size cap.
2. Content must be plain text — NUL/control bytes are rejected before anything is stored.
3. Parsed and validated in memory; failures store nothing.
4. Stored under a random name (the user's filename never touches the filesystem) and encrypted.
5. Replacing an upload deletes the previous file after the DB commit.
6. Responses never include server paths.

## Retention

| Class | Default | Setting |
|---|---|---|
| Generated / masked datasets | 30 days (file deleted, row marked `purged_at`; download → 410) | `TDM_DATASET_RETENTION_DAYS` |
| Uploaded source files | 30 days (file + row deleted) | `TDM_UPLOAD_RETENTION_DAYS` |
| Activity log | 5 days | `TDM_LOG_RETENTION_DAYS` |
| Idempotency records | 24 hours | — |
| Audit log, metadata | permanent | — |

The purge runs at startup and on the log-cleanup schedule. It is idempotent, tolerates missing files,
continues past individual failures and writes one `Artifact Retention Purge` audit event per run.

## Transport security

The API does not terminate TLS itself. Run it behind a reverse proxy / load balancer that terminates
HTTPS (or `uvicorn --ssl-keyfile … --ssl-certfile …`). Production requires `https://` CORS origins
(startup check). Vault must be reached over `https://` (`TDM_VAULT_CA_CERT` for a private CA).

## Startup guardrails

Outside development mode the API **refuses to start** unless: a real ≥ 32-char `TDM_JWT_SECRET` is set,
`TDM_ARTIFACT_KEYS` and `TDM_PSEUDONYM_KEYS` are valid, and `TDM_ALLOWED_ORIGINS` lists only
`https://` non-local origins. SQLite use is logged as a warning.

## Backup and restore

```
python scripts/backup_metadata.py backup [--dest DIR]
python scripts/backup_metadata.py restore <file>
```

Backups use SQLite's online backup API and are encrypted with the artifact keys. Restore decrypts,
runs `PRAGMA integrity_check`, reads the Alembic revision, keeps the replaced DB as `.pre-restore`,
then swaps the file. Stop the API first; run `alembic upgrade head` afterwards if the backup is older.

## SQLite in production — assessment

Fine for a single API worker and modest volume. Limits: one writer at a time, no built-in encryption,
audit-log tamper guards are SQLite triggers (a PostgreSQL move must port `metadata_store/audit.py`
triggers and re-validate the Alembic chain). Recommended before multi-user production: PostgreSQL on
encrypted storage with managed backups.
