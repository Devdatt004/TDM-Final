"""Step 13: privacy validation and release gate - planted leakage must be caught."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.models import AuditLog
from privacy.validation import BUILTIN_POLICY, Roles, assess
from api.services.privacy_service import PolicyError, parse_policy
from sample_domains import registry as domains
from synthetic_generation import generator
from api.main import app

ADMIN = {"X-Dev-User": "admin1", "X-Dev-Roles": "admin"}
STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
TESTER = {"X-Dev-User": "tester1", "X-Dev-Roles": "tester"}

SOURCE = [
    {"ssn": f"123-45-{i:04d}", "dob": f"19{50 + i % 40}-0{1 + i % 9}-1{i % 10}", "gender": "MF"[i % 2],
     "zip": f"4000{i % 7}", "plan": "gold" if i % 3 else "silver"}
    for i in range(300)
]
ROLES = Roles(identifiers=["ssn"], quasi_identifiers=["dob", "gender", "zip"],
              compare=["ssn", "dob", "gender", "zip", "plan"])


def synthetic(n=100):
    return [{"ssn": f"999-00-{i:04d}", "dob": "2001-01-01", "gender": "MF"[i % 2], "zip": "50000",
             "plan": "gold"} for i in range(n)]


def check(report, name):
    return next(c for c in report["checks"] if c["check"] == name)


def test_clean_synthetic_data_passes():
    r = assess(synthetic(), SOURCE, ROLES, "synthetic")
    assert r["passed"], r["checks"]


def test_planted_identifier_leak_is_detected():
    out = synthetic()
    out[5]["ssn"] = SOURCE[42]["ssn"]
    r = assess(out, SOURCE, ROLES, "synthetic")
    assert not r["passed"] and check(r, "identifier_leakage")["status"] == "fail"
    assert r["identifier_leakage"]["found_in_source"] == 1


def test_planted_exact_and_near_copies_are_detected():
    out = synthetic()
    out[0] = dict(SOURCE[7])                                  # memorised row
    out[1] = dict(SOURCE[8], plan="platinum")                 # differs in one column only
    out[1]["ssn"] = "000-00-0000"                             # ...two columns -> not near
    out[2] = dict(SOURCE[9], plan="platinum")                 # differs in exactly one column
    r = assess(out, SOURCE, Roles(compare=ROLES.compare), "synthetic")
    assert r["row_matches"]["exact"] == 1 and r["row_matches"]["near"] == 1
    assert check(r, "exact_row_matches")["status"] == "fail"


def test_planted_rare_quasi_identifier_combination_is_detected():
    out = synthetic(20)
    for i in range(3):                                        # 15 % of rows carry a source-unique QI combo
        out[i].update({k: SOURCE[i][k] for k in ("dob", "gender", "zip")})
    r = assess(out, SOURCE, Roles(quasi_identifiers=ROLES.quasi_identifiers), "synthetic")
    assert r["quasi_identifier_risk"]["unique_in_source_matches"] == 3
    assert check(r, "unique_qi_matches")["status"] == "fail"


def test_masked_tokens_must_differ_from_the_rows_original_value():
    source = [{"mrn": f"MRN{i}", "name": f"N{i}"} for i in range(100)]
    masked = [{"mrn": f"pz_x_{i}", "name": f"Z{i}"} for i in range(100)]
    roles = Roles(identifiers=["mrn"], substituted=["name"], compare=["mrn", "name"])
    assert assess(masked, source, roles, "masked")["passed"]
    masked[3]["mrn"] = "MRN3"                                  # token left as the raw value
    r = assess(masked, source, roles, "masked")
    assert check(r, "identifier_leakage")["status"] == "fail"
    masked[3]["mrn"] = "pz_x_3"
    masked[4]["name"] = "N4"                                    # 1 % coincidence: within allowance
    assert assess(masked, source, roles, "masked")["passed"]
    for i in range(5, 10):
        masked[i]["name"] = f"N{i}"                             # 6 %: too many
    assert check(assess(masked, source, roles, "masked"), "substitute_coincidence")["status"] == "fail"


def test_utility_is_measured_alongside_privacy():
    same = assess([dict(r) for r in SOURCE], SOURCE, Roles(compare=["gender", "plan"]), "masked")
    assert same["utility"]["mean_distance"] == 0.0
    skew = [dict(r, gender="M", plan="silver") for r in SOURCE]
    assert assess(skew, SOURCE, Roles(compare=["gender", "plan"]), "masked")["utility"]["mean_distance"] > 0.4


def test_reports_contain_no_values():
    out = synthetic()
    out[5]["ssn"] = SOURCE[42]["ssn"]
    out[0] = dict(SOURCE[7])
    text = str(assess(out, SOURCE, ROLES, "synthetic"))
    assert SOURCE[42]["ssn"] not in text and SOURCE[7]["ssn"] not in text


def test_policy_overrides_validate_and_merge():
    merged = parse_policy({"synthetic": {"max_near_row_match_rate": 0.0, "k": 10}})
    assert merged["synthetic"]["k"] == 10 and merged["masked"] == BUILTIN_POLICY["masked"]
    for bad in ({}, {"synthetic": {"k": 1}}, {"synthetic": {"max_exact_row_match_rate": 2}},
                {"synthetic": {"surprise": 1}}):
        with pytest.raises(PolicyError):
            parse_policy(bad)


# ── release gate through the API ─────────────────────────────────────────────

@pytest.fixture()
def client():
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
        yield c, Session
    finally:
        c.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def _profile(client, table):
    assert client.post(f"/analyze/{table}?sample_size=200", headers=STEWARD).status_code == 200
    for item in client.get(f"/api/v1/reviews?table_name={table}", headers=ADMIN).json()["items"]:
        client.post(f"/api/v1/reviews/{item['id']}/approve", headers=ADMIN, json={"reason": "test"})


def test_planted_leak_blocks_download_until_audited_admin_override(client, monkeypatch):
    c, Session = client
    _profile(c, "patients")
    con = sqlite3.connect(domains.db_path("healthcare"))
    real_emails = [r[0] for r in con.execute("SELECT email FROM patients LIMIT 50")]
    con.close()

    original = generator._generate_value
    leaked = iter(real_emails * 10)
    monkeypatch.setattr(generator, "_generate_value",
                        lambda col, pt, dt: next(leaked) if col == "email" else original(col, pt, dt))

    g = c.post("/generate/patients?rows=20", headers=STEWARD)
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["release_status"] == "BLOCKED" and body["preview"] == []
    leak = body["validation"]["privacy"]["tables"]["patients"]["identifier_leakage"]
    assert leak["columns"]["email"]["found_in_source"] == 20

    dataset_id = body["dataset_id"]
    assert c.get(f"/generate/download/{dataset_id}", headers=TESTER).status_code == 409
    assert c.post(f"/api/v1/datasets/{dataset_id}/release-override", headers=STEWARD,
                  json={"reason": "Reviewed with the privacy officer."}).status_code == 403
    assert c.post(f"/api/v1/datasets/{dataset_id}/release-override", headers=ADMIN,
                  json={"reason": "short"}).status_code == 422

    o = c.post(f"/api/v1/datasets/{dataset_id}/release-override", headers=ADMIN,
               json={"reason": "Approved by privacy officer for an isolated test environment."})
    assert o.status_code == 200 and o.json()["release_status"] == "OVERRIDDEN"
    assert c.get(f"/generate/download/{dataset_id}", headers=TESTER).status_code == 200
    v = c.get(f"/api/v1/datasets/{dataset_id}/validation", headers=ADMIN).json()
    assert v["override_by"] == "admin1" and "privacy officer" in v["override_reason"]

    db = Session()
    try:
        events = {a.event for a in db.query(AuditLog).all()}
        assert {"File Download Blocked", "Privacy Gate Override", "File Download"} <= events
    finally:
        db.close()


def test_clean_generation_is_released_and_policy_is_recorded(client):
    c, _ = client
    _profile(c, "customers")
    g = c.post("/generate/customers?rows=50", headers=STEWARD).json()
    assert g["release_status"] == "RELEASED" and g["preview"]
    assert g["validation"]["privacy"]["policy"] == "builtin-1"


def test_active_registry_policy_is_applied_and_versioned(client):
    c, _ = client
    r = c.post("/api/v1/rules", headers=ADMIN, json={
        "rule_key": "privacy.release_policy.banking", "name": "Banking release policy",
        "rule_type": "PRIVACY", "definition": {"synthetic": {"k": 10}}})
    assert r.status_code in (200, 201), r.text
    assert c.post(f"/api/v1/rules/{r.json()['id']}/activate", headers=ADMIN).status_code == 200
    _profile(c, "customers")
    g = c.post("/generate/customers?rows=20", headers=STEWARD).json()
    report = g["validation"]["privacy"]
    assert report["policy"] == "privacy.release_policy.banking@v1"
    assert report["tables"]["customers"]["thresholds"]["k"] == 10

    bad = c.post("/api/v1/rules", headers=ADMIN, json={
        "rule_key": "privacy.release_policy.default", "name": "bad", "rule_type": "PRIVACY",
        "definition": {"synthetic": {"max_exact_row_match_rate": 5}}})
    assert bad.status_code == 422
