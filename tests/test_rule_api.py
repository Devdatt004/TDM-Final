"""Step 7 Rule Registry API tests using an isolated in-memory database."""
import os
os.environ["TDM_AUTH_MODE"] = "development"

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routers.rules import router as rules_router
from metadata_store.db import Base, get_db
from metadata_store.models import AuditLog, Rule, RuleVersion

_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI()
app.include_router(rules_router)
app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    db = _TestingSessionLocal()
    try:
        db.query(RuleVersion).delete()
        db.query(Rule).delete()
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()


def headers(user="rule-admin", roles="admin"):
    return {"X-Dev-User": user, "X-Dev-Roles": roles}


def payload(rule_key="PII_EMAIL_CHECK", definition=None):
    return {
        "rule_key": rule_key,
        "name": "Email PII check",
        "rule_type": "CLASSIFICATION",
        "description": "Identify email addresses",
        "definition": definition or {"pattern": "email", "sensitivity": "PII"},
    }


def create_rule(client, rule_key="PII_EMAIL_CHECK"):
    response = client.post("/api/v1/rules", headers=headers(), json=payload(rule_key))
    assert response.status_code == 200, response.text
    return response.json()


def test_create_rule_starts_draft_at_version_one(client):
    body = create_rule(client)
    assert body["status"] == "DRAFT"
    assert body["current_version"] == 1
    assert body["definition"]["pattern"] == "email"
    assert len(client.get(f"/api/v1/rules/{body['id']}/versions", headers=headers()).json()["versions"]) == 1


def test_duplicate_rule_key_is_rejected(client):
    create_rule(client)
    response = client.post("/api/v1/rules", headers=headers(), json=payload())
    assert response.status_code == 409


def test_rule_types_are_validated(client):
    data = payload()
    data["rule_type"] = "UNKNOWN"
    response = client.post("/api/v1/rules", headers=headers(), json=data)
    assert response.status_code == 422


def test_secrets_are_rejected_from_definition(client):
    response = client.post(
        "/api/v1/rules", headers=headers(),
        json=payload(definition={"condition": {"api_key": "do-not-store"}}),
    )
    assert response.status_code == 422


def test_definition_change_creates_immutable_history(client):
    rule = create_rule(client)
    response = client.patch(
        f"/api/v1/rules/{rule['id']}", headers=headers(),
        json={"definition": {"pattern": "phone", "sensitivity": "PII"},
              "change_summary": "Add phone pattern", "expected_version": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["current_version"] == 2
    old = client.get(f"/api/v1/rules/{rule['id']}/versions/1", headers=headers()).json()
    new = client.get(f"/api/v1/rules/{rule['id']}/versions/2", headers=headers()).json()
    assert old["definition"]["pattern"] == "email"
    assert new["definition"]["pattern"] == "phone"


def test_metadata_only_change_does_not_increment_version(client):
    rule = create_rule(client)
    response = client.patch(
        f"/api/v1/rules/{rule['id']}", headers=headers(),
        json={"description": "Updated description", "expected_version": 1},
    )
    assert response.status_code == 200
    assert response.json()["current_version"] == 1
    versions = client.get(f"/api/v1/rules/{rule['id']}/versions", headers=headers()).json()
    assert versions["count"] == 1


def test_stale_expected_version_is_conflict(client):
    rule = create_rule(client)
    client.patch(f"/api/v1/rules/{rule['id']}", headers=headers(),
                 json={"definition": {"x": 1}, "expected_version": 1})
    response = client.patch(f"/api/v1/rules/{rule['id']}", headers=headers(),
                            json={"definition": {"x": 2}, "expected_version": 1})
    assert response.status_code == 409


def test_activate_and_deactivate_rule(client):
    rule = create_rule(client)
    activated = client.post(f"/api/v1/rules/{rule['id']}/activate", headers=headers())
    assert activated.status_code == 200
    assert activated.json()["status"] == "ACTIVE"
    deactivated = client.post(f"/api/v1/rules/{rule['id']}/deactivate", headers=headers())
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "INACTIVE"


def test_tester_can_read_but_cannot_create_rule(client):
    response = client.post("/api/v1/rules", headers=headers(roles="tester"), json=payload())
    assert response.status_code == 403


def test_unauthenticated_rule_access_is_rejected(client):
    response = client.get("/api/v1/rules")
    assert response.status_code == 401


def test_list_filters_rules(client):
    create_rule(client, "CLASSIFY_EMAIL")
    data = payload("QUALITY_NULL_CHECK")
    data["rule_type"] = "DATA_QUALITY"
    client.post("/api/v1/rules", headers=headers(), json=data)
    response = client.get("/api/v1/rules?rule_type=DATA_QUALITY", headers=headers(roles="tester"))
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["rules"][0]["rule_key"] == "QUALITY_NULL_CHECK"


def test_missing_rule_returns_404(client):
    response = client.get("/api/v1/rules/not-a-rule", headers=headers(roles="tester"))
    assert response.status_code == 404


def test_activation_is_audited(client):
    rule = create_rule(client)
    response = client.post(f"/api/v1/rules/{rule['id']}/activate", headers=headers())
    assert response.status_code == 200
    db = _TestingSessionLocal()
    try:
        entries = db.query(AuditLog).filter(AuditLog.target == rule["id"]).all()
        assert len(entries) >= 2
        assert any("activated" in (entry.detail or "") for entry in entries)
    finally:
        db.close()
