"""Step 9 end-to-end: a real profiling run must populate the review queue.

Unlike test_human_review.py, nothing here inserts review rows by hand. The
queue item is produced by profiling the built-in banking `transactions`
table, whose free-text `description` column only carries NER evidence
(confidence 0.65 < sensitive_threshold), so it must be routed to review.
"""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.models import AuditLog, ClassificationResult
from api.main import app

STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
REVIEWER = {"X-Dev-User": "reviewer1", "X-Dev-Roles": "reviewer"}
TABLE = "transactions"
COLUMN = "description"


@pytest.fixture()
def client_env():
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
    client = TestClient(app)
    try:
        yield client, Session
    finally:
        client.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def _profile(client):
    response = client.post(f"/analyze/{TABLE}?sample_size=200", headers=STEWARD)
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def _pending_item(client, run_id):
    response = client.get(f"/api/v1/reviews?table_name={TABLE}", headers=REVIEWER)
    assert response.status_code == 200, response.text
    items = [i for i in response.json()["items"] if i["run_id"] == run_id and i["column_name"] == COLUMN]
    assert len(items) == 1, response.json()
    return items[0]


def _generate(client):
    return client.post(f"/generate/{TABLE}?rows=5", headers=STEWARD)


def test_real_profiling_run_enqueues_review_and_approval_unblocks_generation(client_env):
    client, Session = client_env
    run_id = _profile(client)

    item = _pending_item(client, run_id)
    assert item["status"] == "PENDING"
    assert item["classification_status"] == "review_required"
    assert item["evidence"], "review context must explain why the item was flagged"

    blocked = _generate(client)
    assert blocked.status_code == 409, blocked.text
    assert "Human review is required" in blocked.json()["detail"]

    # Every review-required column in the run must be approved before generation.
    pending = client.get(f"/api/v1/reviews?table_name={TABLE}", headers=REVIEWER).json()["items"]
    for review in pending:
        decision = client.post(f"/api/v1/reviews/{review['id']}/approve", headers=REVIEWER,
                               json={"reason": "Free-text memo, no direct identifiers.", "sensitivity": "unknown"})
        assert decision.status_code == 200, decision.text

    # Decision persists across requests (what a UI refresh would see).
    refreshed = client.get(f"/api/v1/reviews/{item['id']}", headers=REVIEWER).json()
    assert refreshed["status"] == "APPROVED"
    assert refreshed["reviewer_username"] == "reviewer1"
    assert refreshed["final_sensitivity"] == "unknown"

    db = Session()
    try:
        classification = db.get(ClassificationResult, item["classification_result_id"])
        assert classification.review_required is False
        assert db.query(AuditLog).filter(AuditLog.event == "Classification Review Approved").count() == len(pending)
    finally:
        db.close()

    allowed = _generate(client)
    assert allowed.status_code == 200, allowed.text


def test_rejection_keeps_generation_blocked_until_reprofiled_and_approved(client_env):
    client, _ = client_env
    run_id = _profile(client)
    item = _pending_item(client, run_id)

    rejected = client.post(f"/api/v1/reviews/{item['id']}/reject", headers=REVIEWER,
                           json={"reason": "Evidence too weak to trust."})
    assert rejected.status_code == 200, rejected.text
    assert _generate(client).status_code == 409

    # Re-profiling produces a fresh pending item against the new run.
    new_run_id = _profile(client)
    assert new_run_id != run_id
    assert _pending_item(client, new_run_id)["status"] == "PENDING"
