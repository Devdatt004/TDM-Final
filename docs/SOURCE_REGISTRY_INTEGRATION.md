# Source Registry integration (profiling + synthetic generation)

## Root cause
The Profiling / Synthetic Data pages were built on the legacy name-based flow:
`GET /tables` -> `source_service.list_all_sources()` (built-in demo domains, the
per-user "connected database" and uploaded files) and `POST /analyze/{table}` ->
`load_source_data()`, which resolves a **table name** to a database
(`domain_of_table`, defaulting to `hospital.db`). The Source Registry (`sources`
table, `/api/v1/sources`) was only used by `/validate`; nothing in profiling,
generation or the UI knew about a *source id*. Metadata (`analysis_runs`,
`schema_catalog`, `synthetic_datasets`) was keyed by table name only.

## What changed
| Layer | Change |
|---|---|
| Migration | `a7e1c5b2d904` adds nullable, indexed `source_id` to `analysis_runs`, `schema_catalog`, `synthetic_datasets` (existing rows = legacy, `source_id` NULL). |
| Connector bridge | `api/services/source_connector_service.py`: `build_source_connector()` turns a registry row into a connector via the existing `ConnectorFactory`; `open_source_connector()` always disposes the engine; `list_source_tables`, `assert_table_in_source`, `load_registered_source_data`. `validate_source_connection` now uses the same builder (same response shape). |
| Discovery | `GET /api/v1/sources/{source_id}/tables` (tester+). 404 unknown/deleted source, 422 unusable config (e.g. SQLite file missing - it is never auto-created), 503 DB unreachable. No credentials/paths in responses. |
| Profiling | `POST /analyze/{table}?sample_size=..&source_id=..`. With `source_id`, rows + column metadata come from that source's database and the table must exist in it (404 otherwise). Run, catalog rows and audit entry are stored against the source. Without `source_id` the legacy flow is unchanged. |
| Generation | `POST /generate/{table}?rows=..&purpose=..&source_id=..`. Uses only that source's latest profiling run + schema catalog, re-checks table membership, records `source_id` on the dataset. Source databases are never written to. |
| Metadata reads | `GET /schema-catalog/{table}?source_id=..`, `GET /results/{run_id}` and `GET /generate/history` expose / filter by `source_id`. |
| Security fix | `POST /api/v1/sources/{id}/validate` used `Depends(require_steward_or_admin)` (factory not called); now `Depends(require_steward_or_admin())`. |
| Frontend | New `RegisteredSourcePicker` (source dropdown -> that source's tables; loading / empty / error states; stale-response guard; table cleared on source change). `ConnectorPicker` has a third "Registered Source" mode. `App.jsx` keeps `selectedSourceId` separate from `selectedTable`; Profiling, Synthetic, Masking and Knowledge Base calls pass it. |

## Known limitations
* Synthetic generation is metadata-driven (profiling patterns + native types), as
  designed in v13; it does not copy real values. Column constraints beyond native
  type (CHECK, NOT NULL, FKs) are not enforced by the single-table generator.
* "Data Relationship Validation / generate-related" and the Query Agent still key
  on table names and the built-in domain graph; they are not source-scoped yet.
* Registered SQLite sources are file paths on the API server (as before). Only
  register paths you trust; relative paths resolve against the working directory,
  `TDM_DATA_DIR`, then the project root.
