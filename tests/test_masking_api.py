"""Step 10: deterministic masking of real source rows through the API."""
import base64
import csv
import os
import sqlite3

os.environ.setdefault("TDM_AUTH_MODE", "development")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from privacy import pseudonymization
from privacy.pseudonymization import is_token
from sample_domains import registry as domains
from api.main import app
from synthetic_generation import generator

STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
REVIEWER = {"X-Dev-User": "reviewer1", "X-Dev-Roles": "reviewer"}
TESTER = {"X-Dev-User": "tester1", "X-Dev-Roles": "tester"}
KEY = base64.b64encode(b"K" * 32).decode()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("TDM_PSEUDONYM_KEYS", f"t1:{KEY}")
    pseudonymization.reset_pseudonymizer()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    audit_mod.install_guards(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()
        pseudonymization.reset_pseudonymizer()


def _profile_and_clear_reviews(client, table):
    assert client.post(f"/analyze/{table}?sample_size=200", headers=STEWARD).status_code == 200
    for item in client.get(f"/api/v1/reviews?table_name={table}", headers=REVIEWER).json()["items"]:
        r = client.post(f"/api/v1/reviews/{item['id']}/approve", headers=REVIEWER, json={"reason": "ok"})
        assert r.status_code == 200, r.text


def _raw(table, column):
    con = sqlite3.connect(domains.db_path(domains.domain_of_table(table)))
    try:
        return {str(v[0]) for v in con.execute(f'SELECT "{column}" FROM "{table}"') if v[0] is not None}
    finally:
        con.close()


def test_masking_preserves_joins_and_removes_raw_identifiers(client):
    _profile_and_clear_reviews(client, "patients")
    _profile_and_clear_reviews(client, "appointments")

    patients = client.post("/mask/patients?rows=200", headers=STEWARD)
    assert patients.status_code == 200, patients.text
    appts = client.post("/mask/appointments?rows=200", headers=STEWARD)
    assert appts.status_code == 200, appts.text
    patients, appts = patients.json(), appts.json()

    plan = {c["column"]: c for c in patients["columns"]}
    assert plan["patient_id"]["action"] == "tokenize"
    assert plan["mrn"]["action"] == "tokenize"
    assert plan["email"]["action"] == "tokenize"
    assert plan["first_name"]["action"] == "substitute"

    # Join survives: every masked FK in appointments is a masked patient key.
    with open(os.path.join(generator.OUTPUT_DIR, patients["file_name"]), encoding="utf-8") as f:
        masked_patients = list(csv.DictReader(f))
    with open(os.path.join(generator.OUTPUT_DIR, appts["file_name"]), encoding="utf-8") as f:
        masked_appts = list(csv.DictReader(f))
    patient_tokens = {r["patient_id"] for r in masked_patients}
    assert all(is_token(t) for t in patient_tokens)
    appt_fks = {r["patient_id"] for r in masked_appts if r["patient_id"]}
    assert appt_fks and appt_fks <= patient_tokens

    # Raw identifiers are absent from the protected output and the response.
    body = str(patients)
    file_text = open(os.path.join(generator.OUTPUT_DIR, patients["file_name"]), encoding="utf-8").read()
    for column in ("patient_id", "mrn", "email", "phone"):
        raw_values = _raw("patients", column)
        assert not raw_values & {r[column] for r in masked_patients}, f"raw {column} in masked file"
        for raw in raw_values:
            if len(raw) >= 6:                      # short ids like "12" occur by chance in any text
                assert raw not in body, f"raw {column} leaked to API response"
    # Substituted names: Faker may coincide with a common name, but not systematically.
    source_rows = sqlite3.connect(domains.db_path("healthcare")).execute(
        "SELECT first_name FROM patients LIMIT 200").fetchall()
    same = sum(1 for (src,), out in zip(source_rows, masked_patients) if src == out["first_name"])
    assert same <= len(masked_patients) * 0.05
    assert KEY not in body and KEY not in file_text
    assert patients["key_id"] == "t1" and patients["ephemeral_key"] is False


def test_masking_is_blocked_by_pending_review(client):
    assert client.post("/analyze/patients?sample_size=200", headers=STEWARD).status_code == 200
    pending = client.get("/api/v1/reviews?table_name=patients", headers=REVIEWER).json()["total"]
    assert pending > 0
    r = client.post("/mask/patients?rows=5", headers=STEWARD)
    assert r.status_code == 409 and "Human review is required before masking" in r.json()["detail"]


def test_masking_requires_profiling_and_steward_role(client):
    assert client.post("/mask/doctors?rows=5", headers=STEWARD).status_code == 409
    assert client.post("/mask/doctors?rows=5", headers=TESTER).status_code == 403


def test_masking_without_key_in_production_mode_is_refused(client, monkeypatch):
    _profile_and_clear_reviews(client, "doctors")
    monkeypatch.delenv("TDM_PSEUDONYM_KEYS")
    monkeypatch.setenv("TDM_AUTH_MODE", "production")      # keyring reads this; auth mode is already fixed at import
    pseudonymization.reset_pseudonymizer()
    r = client.post("/mask/doctors?rows=5", headers=STEWARD)
    assert r.status_code == 503
