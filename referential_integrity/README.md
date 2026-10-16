# Data Relationship Validation

*(formerly "Referential Integrity" - the package, API paths and `integrity_runs` table keep their original names so nothing stored or integrated breaks.)*

Generated (synthetic) tables must keep their relationships valid: every foreign key points to a parent
row that exists, so joins work and no orphan records appear. Relationships come in two kinds:

| Kind | Where it comes from | Stored as |
|---|---|---|
| **Declared** | a FOREIGN KEY constraint in the source database | `origin = "discovered"` |
| **Undeclared** | a logical link nobody declared; the platform suggests it, a steward confirms it | `origin = "manual"` |

Both kinds are treated identically when data is generated and validated. See
[`docs/DATA_RELATIONSHIP_USE_CASES.md`](../docs/DATA_RELATIONSHIP_USE_CASES.md) for the use cases.

| Step | File | What it does |
|---|---|---|
| Relationship discovery | `discovery.py` | Reads declared foreign keys from the source schema (no row values); proposes name-based candidates for undeclared ones |
| Relationship graph | `graph.py` | Child column -> parent column, parent-first order, cycle detection, sibling-FK derivations, declared/undeclared `kind` |
| Identifier registry | `registry.py` | Every generated key, so a child can only reference keys that exist |
| Relationship engine | `engine.py` | Parent-first generation, unique keys, FK assignment, cross-table consistency |
| Validation engine | `validator.py` | Orphans, required FKs, counts, multi-level joins, path/identifier consistency, score |
| Glue | `service.py` | Metadata store + connector + existing column generator; publishes CSVs only if validation passes |

API: `GET /domains`, `GET /relationships?domain=`, `POST /relationships/refresh?domain=`,
`GET /relationships/suggestions?domain=`, `POST|DELETE /relationships`, `POST /generate-related`,
`GET /integrity/runs[/{id}]`. UI: **Data Relationship Validation** tab (with a source-domain selector).

Source domains (`sample_domains/`): `healthcare` (hospital.db) and `banking` (banking.db, Banking & Financial Services).
Table names are unique across domains, which is how one metadata store holds one graph per domain.

Tests: `python tests/test_referential_integrity.py` and `python tests/test_banking_domain.py` (stdlib + PyYAML only).

Current limits: single-column foreign keys (composite keys are reported as skipped); database tables only
(uploaded CSV/XML files carry no keys); multi-table cycles are rejected with a clear message; undeclared links are
suggested only to single-column primary keys (a link to a non-key column, e.g. `cards.linked_account_no ->
accounts.account_number`, is kept consistent by the shared-identifier check but is not a graph edge).
