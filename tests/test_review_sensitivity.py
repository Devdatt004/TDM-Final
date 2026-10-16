"""Reviewer sensitivity choices and what masking does with each.

  sensitive      -> masked
  unknown        -> masked anyway ("requires caution": not proven safe)
  not_sensitive  -> copied unchanged (the only reviewer choice that passes through)
"""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from api.services.masking_service import plan_columns
from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from referential_integrity.graph import RelationshipGraph
from api.main import app

STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
REVIEWER = {"X-Dev-User": "reviewer1", "X-Dev-Roles": "reviewer"}


def _c(sensitivity, status="approved", detected=(), pattern="TEXT"):
    return SimpleNamespace(sensitivity=sensitivity, classification_status=status,
                           detected_types=list(detected), pattern_type=pattern)


@pytest.mark.parametrize("classification,action,reason", [
    (_c("not_sensitive"), "passthrough", "reviewer approved as not sensitive"),
    (_c("unknown"), "substitute", "reviewer marked unknown - masked to be safe"),
    (_c("unknown", detected=["EMAIL"]), "tokenize", "identifier (EMAIL)"),
    (_c("sensitive", detected=["PERSON"]), "substitute", "sensitive: PERSON"),
    (_c("unknown", status="unknown"), "passthrough", "no sensitivity evidence"),
])
def test_plan_follows_the_reviewers_choice(classification, action, reason):
    plan = plan_columns(RelationshipGraph([]), "t", ["notes"], {"notes": classification})
    assert plan["notes"]["action"] == action and plan["notes"]["reason"] == reason


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
        yield c
    finally:
        c.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def _profile_and_decide_state(client, sensitivity):
    """Profile patients (state is flagged by NER), decide every pending item."""
    assert client.post("/api/v1/analyze/patients?sample_size=200&method=head", headers=STEWARD).status_code == 200
    items = client.get("/api/v1/reviews?table_name=patients", headers=REVIEWER).json()["items"]
    assert any(i["column_name"] == "state" for i in items)
    for item in items:
        r = client.post(f"/api/v1/reviews/{item['id']}/approve", headers=REVIEWER,
                        json={"reason": "Reviewed.", "sensitivity": sensitivity})
        assert r.status_code == 200, r.text
        assert r.json()["final_sensitivity"] == sensitivity


@pytest.mark.parametrize("sensitivity,action", [
    ("not_sensitive", "passthrough"),
    ("unknown", "substitute"),
    ("sensitive", "substitute"),
])
def test_masking_end_to_end_for_each_choice(client, sensitivity, action):
    _profile_and_decide_state(client, sensitivity)
    r = client.post("/api/v1/mask/patients?rows=20", headers=STEWARD)
    assert r.status_code == 200, r.text
    state = next(c for c in r.json()["columns"] if c["column"] == "state")
    assert state["action"] == action


def test_invalid_sensitivity_is_rejected(client):
    client.post("/api/v1/analyze/patients?sample_size=200&method=head", headers=STEWARD)
    item = client.get("/api/v1/reviews?table_name=patients", headers=REVIEWER).json()["items"][0]
    r = client.post(f"/api/v1/reviews/{item['id']}/approve", headers=REVIEWER,
                    json={"reason": "x", "sensitivity": "harmless"})
    assert r.status_code == 422 and "not_sensitive" in r.json()["error"]["message"]
