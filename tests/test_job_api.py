"""
Step-5 API tests for Job Management.

Uses a small FastAPI test application containing only the job router,
so the tests do not depend on the full application startup.
"""

import os

os.environ["TDM_AUTH_MODE"] = "development"

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth.models import CurrentUser
from api.routers.jobs import router as jobs_router
from metadata_store.db import Base, get_db
from metadata_store.models import Source


_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_engine,
)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI()
app.include_router(jobs_router)
app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture()
def client():
    db = _TestingSessionLocal()
    db.add(
        Source(
            id="api-source-1",
            name="API Test Source",
            source_type="sqlite",
            database_name="hospital.db",
            status="ACTIVE",
        )
    )
    db.commit()
    db.close()

    with TestClient(app) as c:
        yield c

    db = _TestingSessionLocal()
    from metadata_store.models import Job, AuditLog
    db.query(Job).delete()
    db.query(AuditLog).delete()
    db.query(Source).delete()
    db.commit()
    db.close()


def headers(user="devdatt", roles="tester"):
    return {
        "X-Dev-User": user,
        "X-Dev-Roles": roles,
    }


def test_create_job_api(client):
    response = client.post(
        "/api/v1/jobs",
        headers=headers(),
        json={
            "job_type": "SCAN",
            "source_id": "api-source-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_type"] == "SCAN"
    assert body["source_id"] == "api-source-1"
    assert body["status"] == "QUEUED"
    assert body["created_by"] == "devdatt"


def test_list_and_get_job_api(client):
    create_response = client.post(
        "/api/v1/jobs",
        headers=headers(),
        json={"job_type": "PROFILE", "source_id": "api-source-1"},
    )
    job_id = create_response.json()["id"]

    list_response = client.get(
        "/api/v1/jobs",
        headers=headers(),
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    get_response = client.get(
        f"/api/v1/jobs/{job_id}",
        headers=headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == job_id


def test_job_lifecycle_api(client):
    create_response = client.post(
        "/api/v1/jobs",
        headers=headers(),
        json={"job_type": "SCAN", "source_id": "api-source-1"},
    )
    job_id = create_response.json()["id"]

    start_response = client.post(
        f"/api/v1/jobs/{job_id}/start",
        headers=headers(roles="admin"),
    )
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "RUNNING"

    complete_response = client.post(
        f"/api/v1/jobs/{job_id}/complete",
        headers=headers(roles="admin"),
        json={"result": {"tables": 4}},
    )
    assert complete_response.status_code == 200
    body = complete_response.json()
    assert body["status"] == "COMPLETED"
    assert body["result"] == '{"tables": 4}'


def test_job_failure_api(client):
    create_response = client.post(
        "/api/v1/jobs",
        headers=headers(),
        json={"job_type": "SCAN", "source_id": "api-source-1"},
    )
    job_id = create_response.json()["id"]

    response = client.post(
        f"/api/v1/jobs/{job_id}/fail",
        headers=headers(roles="admin"),
        json={"error_message": "Connection failed."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert response.json()["error_message"] == "Connection failed."


def test_lifecycle_mutation_requires_steward_or_admin(client):
    create_response = client.post(
        "/api/v1/jobs",
        headers=headers(),
        json={"job_type": "SCAN", "source_id": "api-source-1"},
    )
    job_id = create_response.json()["id"]

    response = client.post(
        f"/api/v1/jobs/{job_id}/start",
        headers=headers(roles="tester"),
    )

    assert response.status_code == 403


def test_unauthenticated_job_api_is_rejected(client):
    response = client.get("/api/v1/jobs")
    assert response.status_code == 401
