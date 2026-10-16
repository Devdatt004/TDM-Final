"""Step 12: domain plausibility rules - engine, catalogue and generation gate."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.models import SyntheticDataset
from plausibility import engine
from plausibility.rules import RuleDefinitionError, parse
from api.services import plausibility_service
from api.main import app

TODAY = date(2026, 10, 13)
STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
ADMIN = {"X-Dev-User": "admin1", "X-Dev-Roles": "admin"}
TESTER = {"X-Dev-User": "tester1", "X-Dev-Roles": "tester"}


def rule(**over):
    base = {"domain": "healthcare", "severity": "hard", "table": "t",
            "explanation": "e", "rationale": "r"}
    base.update(over)
    return parse(base, key=over.pop("key", "k"))


def outcomes(r, rows, tables=None):
    tables = dict(tables or {})
    tables[r.table] = rows
    rep = engine.evaluate(tables, [r], "healthcare", today=TODAY)["rules"][0]
    return rep["violations"], rep["unknown"], rep.get("not_applicable", 0)


# ── each check kind: positive / negative / unknown ───────────────────────────

def test_allowed_values():
    r = rule(check="allowed_values", field="g", values=["M", "F"])
    assert outcomes(r, [{"g": "M"}, {"g": "Q"}, {"g": None}]) == (1, 1, 0)


def test_range():
    r = rule(check="range", field="x", min=1, max=10)
    assert outcomes(r, [{"x": 5}, {"x": 0}, {"x": 11}, {"x": "abc"}]) == (2, 1, 0)


def test_pattern():
    r = rule(check="pattern", field="c", regex="[A-Z][0-9]{2}")
    assert outcomes(r, [{"c": "E11"}, {"c": "e11"}, {"c": ""}]) == (1, 1, 0)


def test_age_range_rejects_future_and_impossible_ages():
    r = rule(check="age_range", field="dob", min_years=0, max_years=120)
    rows = [{"dob": "1980-01-01"}, {"dob": "2030-01-01"}, {"dob": "1850-01-01"}, {"dob": "not a date"}]
    assert outcomes(r, rows) == (2, 1, 0)


def test_same_row_and_joined_date_order():
    same = rule(check="date_order", earlier="admit", later="discharge", max_gap_days=30)
    rows = [{"admit": "2026-01-01", "discharge": "2026-01-05"},
            {"admit": "2026-01-10", "discharge": "2026-01-01"},      # discharge before admission
            {"admit": "2026-01-01", "discharge": "2026-06-01"},      # gap too long
            {"admit": None, "discharge": "2026-01-01"}]
    assert outcomes(same, rows) == (2, 1, 0)

    joined = rule(check="date_order", table="appt", earlier="dob", later="when",
                  join={"fk": "pid", "parent_table": "pat", "parent_key": "id"})
    pats = [{"id": 1, "dob": "2000-01-01"}]
    appts = [{"pid": 1, "when": "2020-01-01"}, {"pid": 1, "when": "1999-01-01"}, {"pid": 99, "when": "2020-01-01"}]
    assert outcomes(joined, appts, {"pat": pats}) == (1, 1, 0)


def test_conditional():
    r = rule(check="conditional", severity="soft", when={"field": "dx", "prefixes": ["O"]},
             then={"field": "sex", "values": ["F"]})
    rows = [{"dx": "O80", "sex": "F"}, {"dx": "O80", "sex": "M"}, {"dx": "I10", "sex": "M"}, {"dx": None, "sex": "F"}]
    assert outcomes(r, rows) == (1, 1, 1)


@pytest.mark.parametrize("bad", [
    {"check": "eval", "field": "x"},                                         # unknown check kind
    {"check": "range", "field": "x", "min": 1, "rationale": ""},             # rationale required
    {"check": "range", "field": "x", "min": 1, "tolerance": 0.1},            # tolerance on hard rule
    {"check": "range", "field": "x", "min": 1, "severity": "soft", "repair": True},
    {"check": "range", "field": "x", "min": 1, "repair": True},              # repair needs both bounds
    {"check": "pattern", "field": "x", "regex": "("},
    {"check": "pattern", "field": "x", "regex": "a", "repair": True},
    {"check": "range", "field": "x; DROP TABLE", "min": 1},
])
def test_invalid_definitions_rejected(bad):
    with pytest.raises(RuleDefinitionError):
        rule(**bad)


# ── severity, scoping, repair ────────────────────────────────────────────────

def test_soft_rule_warns_within_tolerance_and_never_fails():
    r = rule(check="range", field="x", min=0, severity="soft", tolerance=0.25)
    rows = [{"x": 1}] * 3 + [{"x": -1}]
    rep = engine.evaluate({"t": rows}, [r], "healthcare", today=TODAY)
    assert rep["passed"] and rep["rules"][0]["status"] == "pass"
    rep = engine.evaluate({"t": rows + [{"x": -1}]}, [r], "healthcare", today=TODAY)
    assert rep["passed"] and rep["soft_warnings"] == 1


def test_healthcare_rules_never_run_on_banking_data():
    r = rule(check="allowed_values", table="customers", field="gender", values=["M"])
    rep = engine.evaluate({"customers": [{"gender": "Q"}]}, [r], "banking", today=TODAY)
    assert rep["rules_evaluated"] == 0 and rep["passed"]


def test_repair_is_bounded_and_recorded():
    fixable = rule(key="a", check="allowed_values", field="g", values=["M", "F"], repair=True)
    unfixable = rule(key="b", check="pattern", field="c", regex="[A-Z][0-9]{2}")
    rows = [{"g": "?", "c": "E11"}, {"g": "M", "c": "bad"}]
    rep = engine.repair_and_evaluate({"t": rows}, [fixable, unfixable], "healthcare", seed=1, today=TODAY)
    assert rep["repairs"] == {"a@v1": 1}
    assert rows[0]["g"] in ("M", "F")
    assert rep["hard_failures"] == 1 and not rep["passed"]
    assert rep["repair_passes"] <= engine.MAX_PASSES
    assert "bad" not in str(rep)                     # reports never contain values


def test_starter_catalogue_rules_are_valid_and_justified():
    cat = plausibility_service.load_catalogue("healthcare")
    assert cat["rules"]
    for entry in cat["rules"]:
        parsed = parse(entry["definition"], key=entry["rule_key"])
        assert parsed.domain == "healthcare" and parsed.rationale


# ── API lifecycle ────────────────────────────────────────────────────────────

@pytest.fixture()
def env():
    engine_ = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine_)
    audit_mod.install_guards(engine_)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine_)

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
        engine_.dispose()


def _activate(client, *keys):
    rules = client.get("/api/v1/rules?rule_type=PLAUSIBILITY", headers=ADMIN).json()
    by_key = {r["rule_key"]: r for r in rules["rules"]}
    for key in keys:
        r = client.post(f"/api/v1/rules/{by_key[f'plausibility.healthcare.{key}']['id']}/activate", headers=ADMIN)
        assert r.status_code == 200, r.text


def _profile(client, table):
    """Profile and approve any review items so the Step 9 gate is clear."""
    assert client.post(f"/analyze/{table}?sample_size=50&method=head", headers=STEWARD).status_code == 200
    for item in client.get(f"/api/v1/reviews?table_name={table}", headers=ADMIN).json()["items"]:
        client.post(f"/api/v1/reviews/{item['id']}/approve", headers=ADMIN, json={"reason": "test"})


def test_catalogue_imports_as_draft_and_is_not_enforced(env):
    client, _ = env
    r = client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=STEWARD)
    assert r.status_code == 200 and r.json()["created_as_draft"]
    again = client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=STEWARD).json()
    assert again["created_as_draft"] == [] and again["already_present"]
    assert client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=TESTER).status_code == 403

    _profile(client, "patients")
    g = client.post("/generate/patients?rows=20", headers=STEWARD).json()
    assert g["validation"]["plausibility"]["rules_evaluated"] == 0      # drafts are not enforced


def test_active_rules_repair_generated_rows_and_record_versions(env):
    client, Session = env
    client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=STEWARD)
    _activate(client, "patient_gender_values", "patient_blood_group_values", "patient_age_range")
    _profile(client, "patients")

    g = client.post("/generate/patients?rows=50", headers=STEWARD)
    assert g.status_code == 200, g.text
    report = g.json()["validation"]["plausibility"]
    assert report["passed"] and report["rules_evaluated"] == 3
    assert {r["rule"] for r in report["rules"]} == {
        "plausibility.healthcare.patient_gender_values@v1",
        "plausibility.healthcare.patient_blood_group_values@v1",
        "plausibility.healthcare.patient_age_range@v1"}
    assert all(row["gender"] in ("M", "F", "X") for row in g.json()["preview"])
    db = Session()
    try:
        stored = db.query(SyntheticDataset).one().validation_report
        assert stored["plausibility"]["rules_evaluated"] == 3
    finally:
        db.close()


def test_unrepairable_hard_failure_blocks_release(env):
    client, Session = env
    client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=STEWARD)
    _activate(client, "diagnosis_code_icd10_format")
    _profile(client, "appointments")
    g = client.post("/generate/appointments?rows=20", headers=STEWARD)
    if g.status_code == 200:
        # Generator happened to emit valid codes for every row; the gate still ran.
        assert g.json()["validation"]["plausibility"]["passed"]
        return
    assert g.status_code == 422
    assert g.json()["detail"]["validation"]["plausibility"]["hard_failures"] == 1
    db = Session()
    try:
        assert db.query(SyntheticDataset).count() == 0                 # nothing written
    finally:
        db.close()


def test_rules_do_not_touch_banking_generation(env):
    client, _ = env
    client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=STEWARD)
    _activate(client, "patient_gender_values")
    _profile(client, "customers")
    g = client.post("/generate/customers?rows=10", headers=STEWARD)
    assert g.status_code == 200, g.text
    report = g.json()["validation"]["plausibility"]
    assert report["domain"] == "banking" and report["rules_evaluated"] == 0


def test_source_check_reports_aggregates_only(env):
    client, _ = env
    client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=STEWARD)
    r = client.get("/api/v1/plausibility/source-check/healthcare", headers=STEWARD)
    assert r.status_code == 200, r.text
    rules = {x["rule"]: x for x in r.json()["rules"]}
    claim = rules["plausibility.healthcare.claim_after_appointment@v1"]
    assert claim["violations"] > 0 and claim["status"] == "warn"     # the source itself breaks this
    assert rules["plausibility.healthcare.patient_blood_group_values@v1"]["violations"] == 0
    assert all("violating_row_indexes" not in x for x in r.json()["rules"])


def test_registry_rejects_invalid_plausibility_definition(env):
    client, _ = env
    r = client.post("/api/v1/rules", headers=ADMIN, json={
        "rule_key": "plausibility.bad", "name": "bad", "rule_type": "PLAUSIBILITY",
        "definition": {"check": "range", "domain": "healthcare", "severity": "hard", "table": "t"}})
    assert r.status_code == 422 and "Invalid plausibility rule" in r.text
