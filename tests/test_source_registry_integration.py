
"""
End-to-end Source Registry integration tests.

Covers: source listing, source-aware table discovery, profiling and synthetic
generation for banking AND healthcare registered sources, rejection of invalid
sources / foreign tables, "source database is never modified", legacy/demo
behaviour, RBAC, audit and metadata persistence.

Everything is hermetic: the banking / healthcare / extra SQLite databases are
built into pytest temp directories, the metadata store is a fresh in-memory
SQLite per test, and no test relies on a pre-existing source id or on
machine-specific paths.

Run from the project root:   python -m pytest tests/test_source_registry_integration.py -v
"""
import csv
import hashlib
import os
import sqlite3

os.environ["TDM_AUTH_MODE"] = "development"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store import audit as audit_mod
from metadata_store.db import Base, get_db
from metadata_store.models import (
    ActivityLog,
    AnalysisRun,
    ClassificationResult,
    SchemaCatalogEntry,
    SyntheticDataset,
)
from sample_domains import banking, healthcare, registry as domains
from synthetic_generation import generator as synthetic_generator

from api.main import app  # noqa: E402  (after TDM_AUTH_MODE)

ADMIN = {"X-Dev-User": "alice", "X-Dev-Roles": "admin"}
STEWARD = {"X-Dev-User": "bob", "X-Dev-Roles": "steward"}
TESTER = {"X-Dev-User": "dave", "X-Dev-Roles": "tester"}
NOBODY = {"X-Dev-User": "eve", "X-Dev-Roles": ""}

BANKING_TABLES = sorted([
    "accounts", "branches", "cards", "customers", "loan_repayments", "loans",
    "portfolios", "products", "securities", "trades", "transactions",
])
HEALTHCARE_TABLES = sorted(["appointments", "doctors", "insurance_claims", "patients"])


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _columns(path, table):
    con = sqlite3.connect(path)
    try:
        return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    finally:
        con.close()


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dbfiles(tmp_path_factory):
    root = tmp_path_factory.mktemp("sources")
    bank = str(root / "banking_fixture.db")
    hosp = str(root / "hospital_fixture.db")
    other = str(root / "other_fixture.db")
    banking.build_banking_db(bank, seed=11, sizes={"customers": 20, "trades": 40})
    healthcare.build_healthcare_db(hosp, seed=11)
    # A third database that deliberately reuses the table name "patients"
    # with a different shape, to prove tables are resolved PER SOURCE.
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE patients (vet_id INTEGER PRIMARY KEY, pet_name TEXT, species TEXT)")
    con.executemany("INSERT INTO patients VALUES (?,?,?)",
                    [(i, f"Rex{i}", "dog") for i in range(1, 15)])
    con.commit()
    con.close()
    return {"banking": bank, "healthcare": hosp, "other": other}


@pytest.fixture()
def env(dbfiles, tmp_path, monkeypatch):
    """Fresh in-memory metadata store + app override + isolated output dir."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    audit_mod.install_guards(engine)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override

    out_dir = tmp_path / "synthetic_output"
    out_dir.mkdir()
    monkeypatch.setattr(synthetic_generator, "OUTPUT_DIR", str(out_dir))

    # Point the built-in (legacy) domains at the temp fixtures too.
    monkeypatch.setitem(domains.DOMAINS["healthcare"], "db_file", dbfiles["healthcare"])
    monkeypatch.setitem(domains.DOMAINS["banking"], "db_file", dbfiles["banking"])

    client = TestClient(app)
    try:
        yield {"client": client, "Session": Session, "files": dbfiles, "out": out_dir}
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def _register(env, name, kind):
    r = env["client"].post("/api/v1/sources", headers=ADMIN, json={
        "name": name, "source_type": "sqlite", "database_name": env["files"][kind]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture()
def banking_id(env):
    return _register(env, "Banking SQLite Source", "banking")


@pytest.fixture()
def healthcare_id(env):
    return _register(env, "Healthcare SQLite Source", "healthcare")


# --------------------------------------------------------------------------
# 1. Listing registered sources
# --------------------------------------------------------------------------

def test_list_registered_sources(env, banking_id, healthcare_id):
    r = env["client"].get("/api/v1/sources", headers=TESTER)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id[banking_id]["name"] == "Banking SQLite Source"
    assert by_id[healthcare_id]["name"] == "Healthcare SQLite Source"
    for s in body["sources"]:
        assert "password" not in s and "connection_url" not in s


# --------------------------------------------------------------------------
# 2 / 3. Source-aware table discovery
# --------------------------------------------------------------------------

def test_discover_banking_tables(env, banking_id):
    r = env["client"].get(f"/api/v1/sources/{banking_id}/tables", headers=TESTER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_id"] == banking_id
    assert sorted(body["tables"]) == BANKING_TABLES
    assert body["count"] == 11
    assert env["files"]["banking"] not in r.text          # no connection details leaked


def test_discover_healthcare_tables(env, healthcare_id):
    r = env["client"].get(f"/api/v1/sources/{healthcare_id}/tables", headers=TESTER)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["tables"]) == HEALTHCARE_TABLES


# --------------------------------------------------------------------------
# 4 / 5. Source-aware profiling
# --------------------------------------------------------------------------

def test_profile_banking_table_uses_banking_source(env, banking_id):
    c = env["client"]
    r = c.post(f"/analyze/customers?sample_size=20&source_id={banking_id}", headers=STEWARD)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["source_id"] == banking_id and result["source_table"] == "customers"
    assert result["rows_sampled"] == 20

    run = c.get(f"/results/{result['run_id']}", headers=ADMIN).json()
    assert run["source_id"] == banking_id
    assert [x["column_name"] for x in run["columns"]] == _columns(env["files"]["banking"], "customers")

    catalog = c.get(f"/schema-catalog/customers?source_id={banking_id}", headers=ADMIN)
    assert catalog.status_code == 200
    assert [x["column_name"] for x in catalog.json()["columns"]] == \
        _columns(env["files"]["banking"], "customers")

def test_profile_persists_classification_results(env, banking_id):
    c = env["client"]

    response = c.post(
        f"/analyze/customers?sample_size=20&source_id={banking_id}",
        headers=STEWARD,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    run_id = result["run_id"]

    db = env["Session"]()
    try:
        run = db.query(AnalysisRun).filter_by(id=run_id).one()
        classifications = (
            db.query(ClassificationResult)
            .filter_by(run_id=run_id)
            .order_by(ClassificationResult.column_name)
            .all()
        )

        assert classifications, "No classification results were persisted"
        assert all(item.source_id == banking_id for item in classifications)
        assert all(item.table_name == "customers" for item in classifications)

        # Every profiled column should have a corresponding classification.
        column_names = {
            item.column_name
            for item in classifications
        }
        profiled_columns = {
            item.column_name
            for item in run.columns
        }
        assert column_names == profiled_columns

        # Check the persisted classification payload is populated and valid.
        for item in classifications:
            assert item.sensitivity in {
                "sensitive", "non_sensitive", "unknown"
            }
            assert 0.0 <= item.sensitivity_confidence <= 1.0
            assert isinstance(item.evidence, list)
            assert isinstance(item.detected_types, list)
            assert item.rule_pack_version
    finally:
        db.close()


def test_profile_healthcare_table_uses_healthcare_source(env, healthcare_id):
    c = env["client"]
    r = c.post(f"/analyze/patients?sample_size=20&source_id={healthcare_id}", headers=STEWARD)
    assert r.status_code == 200, r.text
    run = c.get(f"/results/{r.json()['run_id']}", headers=ADMIN).json()
    assert run["source_id"] == healthcare_id
    assert [x["column_name"] for x in run["columns"]] == _columns(env["files"]["healthcare"], "patients")


def test_same_table_name_in_two_sources_is_never_mixed_up(env, healthcare_id):
    other_id = _register(env, "Other SQLite Source", "other")
    c = env["client"]
    a = c.post(f"/analyze/patients?sample_size=10&source_id={healthcare_id}", headers=STEWARD).json()
    b = c.post(f"/analyze/patients?sample_size=10&source_id={other_id}", headers=STEWARD).json()
    cols_a = [x["column_name"] for x in c.get(f"/results/{a['run_id']}", headers=ADMIN).json()["columns"]]
    cols_b = [x["column_name"] for x in c.get(f"/results/{b['run_id']}", headers=ADMIN).json()["columns"]]
    assert cols_a == _columns(env["files"]["healthcare"], "patients")
    assert cols_b == ["vet_id", "pet_name", "species"]

    # Catalog entries are kept per source as well.
    cat_b = c.get(f"/schema-catalog/patients?source_id={other_id}", headers=ADMIN).json()
    assert [x["column_name"] for x in cat_b["columns"]] == ["vet_id", "pet_name", "species"]

    # Generation follows the selected source's profile.
    g = c.post(f"/generate/patients?rows=5&source_id={other_id}", headers=TESTER)
    assert g.status_code == 200, g.text
    assert list(g.json()["preview"][0].keys()) == ["vet_id", "pet_name", "species"]


# --------------------------------------------------------------------------
# 6. Invalid sources / tables / unavailable databases
# --------------------------------------------------------------------------

def test_unknown_source_is_rejected_everywhere(env):
    c = env["client"]
    bogus = "00000000-0000-0000-0000-000000000000"
    assert c.get(f"/api/v1/sources/{bogus}/tables", headers=TESTER).status_code == 404
    assert c.post(f"/analyze/customers?source_id={bogus}", headers=STEWARD).status_code == 404
    assert c.post(f"/generate/customers?source_id={bogus}", headers=TESTER).status_code == 404


def test_soft_deleted_source_is_rejected(env, banking_id):
    c = env["client"]
    assert c.delete(f"/api/v1/sources/{banking_id}", headers=ADMIN).status_code == 200
    assert c.get(f"/api/v1/sources/{banking_id}/tables", headers=TESTER).status_code == 404
    assert c.post(f"/analyze/customers?source_id={banking_id}", headers=STEWARD).status_code == 404


def test_table_from_another_source_is_rejected(env, banking_id, healthcare_id):
    c = env["client"]
    # healthcare table through the banking source, and vice versa
    r = c.post(f"/analyze/patients?source_id={banking_id}", headers=STEWARD)
    assert r.status_code == 404 and "patients" in r.json()["detail"]
    assert c.post(f"/analyze/customers?source_id={healthcare_id}", headers=STEWARD).status_code == 404
    assert c.post(f"/generate/patients?source_id={banking_id}", headers=TESTER).status_code == 404
    assert c.post(f"/analyze/no_such_table?source_id={banking_id}", headers=STEWARD).status_code == 404
    # SQL-injection style table names are just "not in this source"
    assert c.post("/analyze/customers%3B%20DROP%20TABLE%20customers?source_id=" + banking_id,
                  headers=STEWARD).status_code == 404
    with sqlite3.connect(env["files"]["banking"]) as con:
        assert con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0


def test_unavailable_database_gives_safe_error(env):
    c = env["client"]
    missing = os.path.join(os.path.dirname(env["files"]["banking"]), "gone", "missing.db")
    r = c.post("/api/v1/sources", headers=ADMIN, json={
        "name": "Missing", "source_type": "sqlite", "database_name": missing})
    sid = r.json()["id"]
    t = c.get(f"/api/v1/sources/{sid}/tables", headers=TESTER)
    assert t.status_code == 422
    assert missing not in t.text
    assert not os.path.exists(missing)                      # SQLite must not create it
    v = c.post(f"/api/v1/sources/{sid}/validate", headers=ADMIN).json()
    assert v["valid"] is False


def test_validate_endpoint_still_works_and_requires_steward(env, banking_id):
    c = env["client"]
    ok = c.post(f"/api/v1/sources/{banking_id}/validate", headers=STEWARD)
    assert ok.status_code == 200 and ok.json()["valid"] is True
    assert sorted(ok.json()["tables"]) == BANKING_TABLES
    assert c.post(f"/api/v1/sources/{banking_id}/validate", headers=TESTER).status_code == 403


# --------------------------------------------------------------------------
# 7 / 8. Synthetic generation from the selected source; source unchanged
# --------------------------------------------------------------------------

def test_generation_requires_profiling_of_that_source(env, banking_id):
    r = env["client"].post(f"/generate/accounts?rows=5&source_id={banking_id}", headers=TESTER)
    assert r.status_code == 400 and "profiled" in r.json()["detail"]


def test_generate_synthetic_for_banking_source_and_source_not_modified(env, banking_id):
    c = env["client"]
    before = _sha256(env["files"]["banking"])

    p = c.post(f"/analyze/accounts?sample_size=30&source_id={banking_id}", headers=STEWARD)
    assert p.status_code == 200, p.text
    g = c.post(f"/generate/accounts?rows=12&source_id={banking_id}", headers=TESTER)
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["source_id"] == banking_id and body["source_table"] == "accounts"
    assert body["row_count"] == 12 and len(body["preview"]) == 10
    expected_cols = _columns(env["files"]["banking"], "accounts")
    assert list(body["preview"][0].keys()) == expected_cols

    # CSV on disk has exactly the source table's columns and 12 rows.
    path = os.path.join(synthetic_generator.OUTPUT_DIR, body["file_name"])
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 12 and list(rows[0].keys()) == expected_cols

    # Metadata: dataset is tied to the source + table + the profiling run used.
    db = env["Session"]()
    try:
        ds = db.query(SyntheticDataset).filter_by(public_id=body["dataset_id"]).one()
        assert (ds.source_id, ds.source_table) == (banking_id, "accounts")
        assert ds.run_id == p.json()["run_id"]
    finally:
        db.close()

    hist = c.get("/generate/history", headers=ADMIN).json()
    assert any(h["dataset_id"] == body["dataset_id"] and h["source_id"] == banking_id for h in hist)
    dl = c.get(f"/generate/download/{body['dataset_id']}", headers=TESTER)
    assert dl.status_code == 200

    # The source database file is byte-for-byte unchanged.
    assert _sha256(env["files"]["banking"]) == before


def test_generate_synthetic_for_healthcare_source(env, healthcare_id):
    c = env["client"]
    before = _sha256(env["files"]["healthcare"])
    assert c.post(f"/analyze/patients?sample_size=20&source_id={healthcare_id}", headers=STEWARD).status_code == 200
    g = c.post(f"/generate/patients?rows=6&source_id={healthcare_id}", headers=TESTER)
    assert g.status_code == 200, g.text
    assert list(g.json()["preview"][0].keys()) == _columns(env["files"]["healthcare"], "patients")
    assert _sha256(env["files"]["healthcare"]) == before


def test_masking_purpose_is_source_aware(env, banking_id):
    c = env["client"]
    c.post(f"/analyze/customers?sample_size=20&source_id={banking_id}", headers=STEWARD)
    r = c.post(f"/generate/customers?rows=4&purpose=masking&source_id={banking_id}", headers=TESTER)
    assert r.status_code == 200, r.text
    db = env["Session"]()
    try:
        entry = db.query(ActivityLog).filter_by(activity="Masking Preview").one()
        assert "Registered sqlite source" in entry.source_type
    finally:
        db.close()


# --------------------------------------------------------------------------
# 9. Legacy / demo behaviour is preserved
# --------------------------------------------------------------------------

def test_legacy_tables_endpoint_still_lists_demo_sources(env):
    r = env["client"].get("/tables", headers=TESTER)
    assert r.status_code == 200
    names = r.json()["tables"]
    assert "patients" in names and "customers" in names


def test_legacy_profile_and_generate_without_source_id(env, banking_id):
    c = env["client"]
    a = c.post("/analyze/patients?sample_size=15", headers=STEWARD)
    assert a.status_code == 200, a.text
    assert a.json()["source_id"] is None
    g = c.post("/generate/patients?rows=5", headers=TESTER)
    assert g.status_code == 200, g.text
    assert g.json()["source_id"] is None

    # A legacy run is NOT silently reused for a registered source ...
    r = c.post(f"/generate/patients?rows=5&source_id={banking_id}", headers=TESTER)
    assert r.status_code == 404                           # table not in banking source
    # ... and a registered-source profile is not picked up by the legacy flow.
    c.post(f"/analyze/customers?sample_size=10&source_id={banking_id}", headers=STEWARD)
    legacy = c.post("/generate/customers?rows=3", headers=TESTER)
    assert legacy.status_code == 400 and "profiled" in legacy.json()["detail"]


def test_legacy_unknown_table_still_400(env):
    r = env["client"].post("/analyze/definitely_missing", headers=STEWARD)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# 10. Authorization, audit and metadata persistence
# --------------------------------------------------------------------------

def test_authorization_rules(env, banking_id):
    c = env["client"]
    url = f"/api/v1/sources/{banking_id}/tables"
    assert c.get(url).status_code == 401                              # no identity
    assert c.get(url, headers=NOBODY).status_code == 403              # identity, no role
    assert c.get(url, headers=TESTER).status_code == 200              # tester may discover
    assert c.post(f"/analyze/customers?source_id={banking_id}", headers=TESTER).status_code == 403
    assert c.post(f"/generate/customers?source_id={banking_id}", headers=NOBODY).status_code == 403
    assert c.post(f"/generate/customers?source_id={banking_id}").status_code == 401


def test_audit_activity_and_metadata_persistence(env, banking_id):
    c = env["client"]
    run_id = c.post(f"/analyze/loans?sample_size=25&source_id={banking_id}", headers=STEWARD).json()["run_id"]
    c.post(f"/generate/loans?rows=5&source_id={banking_id}", headers=TESTER)

    db = env["Session"]()
    try:
        run = db.query(AnalysisRun).filter_by(id=run_id).one()
        assert (run.source_id, run.source_table, run.status) == (banking_id, "loans", "complete")
        assert run.total_fields == len(_columns(env["files"]["banking"], "loans"))
        assert db.query(SchemaCatalogEntry).filter_by(source_id=banking_id, table_name="loans").count() \
            == run.total_fields

        profiling = db.query(ActivityLog).filter_by(activity="Profiling").one()
        assert profiling.status == "complete" and profiling.username == "bob"
        assert profiling.source == "loans" and "Banking SQLite Source" in profiling.source_type
        assert db.query(ActivityLog).filter_by(activity="Synthetic Data Generation").one().username == "dave"

        # Re-profiling replaces (not duplicates) this source's catalog rows.
        c.post(f"/analyze/loans?sample_size=25&source_id={banking_id}", headers=STEWARD)
        assert db.query(SchemaCatalogEntry).filter_by(source_id=banking_id, table_name="loans").count() \
            == run.total_fields

        # Tamper-evident audit chain (source registration + validation events) stays intact.
        c.post(f"/api/v1/sources/{banking_id}/validate", headers=STEWARD)
        from api.services import audit_service
        assert audit_service.verify_chain(db)["intact"] is True
    finally:
        db.close()


def test_failed_profile_is_audited_as_failed(env, banking_id):
    env["client"].post(f"/analyze/patients?source_id={banking_id}", headers=STEWARD)
    db = env["Session"]()
    try:
        entry = db.query(ActivityLog).filter_by(activity="Profiling").one()
        assert entry.status == "failed"
    finally:
        db.close()
