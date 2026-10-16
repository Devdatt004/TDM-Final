"""Step 9: persistent human classification review workflow tests."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.models import AnalysisRun, ClassificationResult, ClassificationReview, AuditLog
from api.main import app

ADMIN = {"X-Dev-User": "review-admin", "X-Dev-Roles": "admin"}
REVIEWER = {"X-Dev-User": "reviewer1", "X-Dev-Roles": "reviewer"}
TESTER = {"X-Dev-User": "tester1", "X-Dev-Roles": "tester"}


@pytest.fixture()
def review_env():
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
    db = Session()
    run = AnalysisRun(source_table="accounts", source_id="banking-demo", sample_size=20,
                      total_fields=1, high_confidence_count=0, needs_review_count=1, status="complete")
    db.add(run)
    db.flush()
    classification = ClassificationResult(
        run_id=run.id, source_id="banking-demo", source_version="v1", table_name="accounts",
        column_name="account_number", pattern_type="ACCOUNT_NUMBER", pattern_confidence=0.82,
        sensitivity="sensitive", sensitivity_confidence=0.82, evidence=["column_name_matches_account_number"],
        detected_types=["ACCOUNT_NUMBER"], classification_status="review_required", review_required=True,
        rule_pack_version="1.0.0",
    )
    db.add(classification)
    db.flush()
    review = ClassificationReview(classification_result_id=classification.id, status="PENDING",
                                  proposed_pattern_type="ACCOUNT_NUMBER", proposed_sensitivity="sensitive")
    db.add(review)
    db.commit()
    ids = {"run_id": run.id, "classification_id": classification.id, "review_id": review.id}
    db.close()
    try:
        yield client, Session, ids
    finally:
        client.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def test_pending_review_queue_returns_classification_context(review_env):
    client, _, ids = review_env
    response = client.get("/api/v1/reviews", headers=REVIEWER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == ids["review_id"]
    assert body["items"][0]["column_name"] == "account_number"
    assert body["items"][0]["status"] == "PENDING"


def test_approval_updates_classification_and_records_audit(review_env):
    client, Session, ids = review_env
    response = client.post(f"/api/v1/reviews/{ids['review_id']}/approve", headers=REVIEWER,
                           json={"reason": "Verified against the source schema.", "pattern_type": "ACCOUNT_NUMBER", "sensitivity": "sensitive"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
    db = Session()
    try:
        c = db.get(ClassificationResult, ids["classification_id"])
        r = db.get(ClassificationReview, ids["review_id"])
        assert c.review_required is False
        assert c.classification_status == "approved"
        assert r.reviewer_username == "reviewer1"
        assert db.query(AuditLog).filter(AuditLog.event == "Classification Review Approved").count() == 1
    finally:
        db.close()


def test_rejection_requires_reason_and_remains_blocking(review_env):
    client, Session, ids = review_env
    response = client.post(f"/api/v1/reviews/{ids['review_id']}/reject", headers=REVIEWER, json={"reason": "  "})
    assert response.status_code == 422
    response = client.post(f"/api/v1/reviews/{ids['review_id']}/reject", headers=REVIEWER,
                           json={"reason": "Pattern evidence is insufficient."})
    assert response.status_code == 200, response.text
    db = Session()
    try:
        c = db.get(ClassificationResult, ids["classification_id"])
        assert c.review_required is True
        assert c.classification_status == "rejected"
        assert db.get(ClassificationReview, ids["review_id"]).status == "REJECTED"
    finally:
        db.close()


def test_already_decided_review_cannot_be_decided_twice(review_env):
    client, _, ids = review_env
    first = client.post(f"/api/v1/reviews/{ids['review_id']}/approve", headers=REVIEWER, json={"reason": "Reviewed."})
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v1/reviews/{ids['review_id']}/reject", headers=REVIEWER, json={"reason": "Changed mind."})
    assert second.status_code == 409


def test_tester_cannot_decide_review(review_env):
    client, _, ids = review_env
    response = client.post(f"/api/v1/reviews/{ids['review_id']}/approve", headers=TESTER, json={"reason": "Try."})
    assert response.status_code == 403


def test_unauthenticated_user_cannot_view_reviews(review_env):
    client, _, _ = review_env
    response = client.get("/api/v1/reviews")
    assert response.status_code == 401


def test_pending_review_blocks_synthetic_generation(review_env):
    from fastapi import HTTPException
    from api.services.generation_service import generate_synthetic_data_flow
    client, Session, ids = review_env
    db = Session()
    try:
        with pytest.raises(HTTPException) as exc:
            generate_synthetic_data_flow(db, "accounts", 5, "synthetic", "reviewer1", source_id="banking-demo")
        assert exc.value.status_code == 409
        assert "Human review is required" in exc.value.detail
    finally:
        db.close()
