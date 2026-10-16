"""Step-6 API tests for Workflow Management."""

import os

os.environ["TDM_AUTH_MODE"] = "development"

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routers.workflows import router as workflows_router
from metadata_store.db import Base, get_db
from metadata_store.models import (
    AuditLog,
    Job,
    Workflow,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepRun,
)


# ---------------------------------------------------------------------------
# Test database and application
# ---------------------------------------------------------------------------

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

app = FastAPI()
app.include_router(workflows_router)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client

    # Remove test data in dependency order.
    db = _TestingSessionLocal()
    try:
        db.query(WorkflowStepRun).delete()
        db.query(WorkflowRun).delete()
        db.query(WorkflowStep).delete()
        db.query(Workflow).delete()
        db.query(Job).delete()
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()


def headers(user="workflow-tester", roles="tester"):
    return {
        "X-Dev-User": user,
        "X-Dev-Roles": roles,
    }


def create_workflow(client, steps=None, roles="tester"):
    """Create a workflow for a test and return its ID."""
    if steps is None:
        steps = ["SCAN", "PROFILE"]

    response = client.post(
        "/api/v1/workflows",
        headers=headers(roles=roles),
        json={
            "name": "Test Workflow",
            "description": "Workflow execution test",
            "steps": steps,
        },
    )

    assert response.status_code == 200, response.text
    return response.json()["id"]


def create_run(client, workflow_id, roles="tester"):
    """Create a queued workflow run and return its response body."""
    response = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        headers=headers(roles=roles),
        json={"source_id": None},
    )

    assert response.status_code == 200, response.text
    return response.json()


def start_run(client, run_id, roles="steward"):
    return client.post(
        f"/api/v1/workflows/runs/{run_id}/start",
        headers=headers(roles=roles),
    )


def start_step(client, run_id, roles="steward"):
    return client.post(
        f"/api/v1/workflows/runs/{run_id}/steps/start",
        headers=headers(roles=roles),
    )


def complete_step(client, run_id, result=None, roles="steward"):
    return client.post(
        f"/api/v1/workflows/runs/{run_id}/steps/complete",
        headers=headers(roles=roles),
        json={"result": result},
    )


def fail_step(client, run_id, error_message="Test step failure", roles="steward"):
    return client.post(
        f"/api/v1/workflows/runs/{run_id}/steps/fail",
        headers=headers(roles=roles),
        json={"error_message": error_message},
    )


# ---------------------------------------------------------------------------
# Workflow definition tests
# ---------------------------------------------------------------------------

def test_create_workflow_with_ordered_steps(client):
    response = client.post(
        "/api/v1/workflows",
        headers=headers(),
        json={
            "name": "API Test Workflow",
            "description": "Workflow API test",
            "steps": ["SCAN", "PROFILE", "VALIDATION"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "API Test Workflow"
    assert [step["step_order"] for step in body["steps"]] == [1, 2, 3]
    assert [step["job_type"] for step in body["steps"]] == [
        "SCAN",
        "PROFILE",
        "VALIDATION",
    ]


def test_list_and_get_workflow(client):
    workflow_id = create_workflow(client, ["SCAN", "PROFILE"])

    list_response = client.get(
        "/api/v1/workflows",
        headers=headers(),
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    get_response = client.get(
        f"/api/v1/workflows/{workflow_id}",
        headers=headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == workflow_id


def test_unsupported_job_type_is_rejected(client):
    response = client.post(
        "/api/v1/workflows",
        headers=headers(),
        json={
            "name": "Invalid Workflow",
            "steps": ["NOT_A_JOB_TYPE"],
        },
    )

    assert response.status_code == 400


def test_missing_workflow_returns_404(client):
    response = client.get(
        "/api/v1/workflows/does-not-exist",
        headers=headers(),
    )

    assert response.status_code == 404


def test_workflow_creation_requires_authentication(client):
    response = client.post(
        "/api/v1/workflows",
        json={
            "name": "Unauthenticated Workflow",
            "steps": ["SCAN"],
        },
    )

    assert response.status_code == 401


def test_workflow_creation_requires_tester_role(client):
    response = client.post(
        "/api/v1/workflows",
        headers=headers(roles=""),
        json={
            "name": "Unauthorized Workflow",
            "steps": ["SCAN"],
        },
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Workflow run creation and read tests
# ---------------------------------------------------------------------------

def test_create_queued_workflow_run(client):
    workflow_id = create_workflow(client, ["SCAN", "PROFILE"])
    body = create_run(client, workflow_id)

    assert body["workflow_id"] == workflow_id
    assert body["status"] == "QUEUED"
    assert body["current_step_order"] == 1
    assert [step["step_order"] for step in body["steps"]] == [1, 2]
    assert [step["status"] for step in body["steps"]] == [
        "QUEUED",
        "QUEUED",
    ]


def test_list_and_get_workflow_run(client):
    workflow_id = create_workflow(client, ["SCAN"])
    run = create_run(client, workflow_id)

    list_response = client.get(
        "/api/v1/workflows/runs/list",
        headers=headers(),
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    get_response = client.get(
        f"/api/v1/workflows/runs/{run['id']}",
        headers=headers(),
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == run["id"]


# ---------------------------------------------------------------------------
# Workflow execution tests
# ---------------------------------------------------------------------------

def test_start_workflow_run(client):
    workflow_id = create_workflow(client, ["SCAN"])
    run = create_run(client, workflow_id)

    response = start_run(client, run["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == run["id"]
    assert body["status"] == "RUNNING"
    assert body["started_at"] is not None


def test_start_step_creates_and_starts_job(client):
    workflow_id = create_workflow(client, ["SCAN"])
    run = create_run(client, workflow_id)

    start_response = start_run(client, run["id"])
    assert start_response.status_code == 200, start_response.text

    response = start_step(client, run["id"])

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "RUNNING"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["status"] == "RUNNING"
    assert body["steps"][0]["job_id"] is not None
    assert body["steps"][0]["started_at"] is not None


def test_complete_step_advances_to_next_step(client):
    workflow_id = create_workflow(client, ["SCAN", "PROFILE"])
    run = create_run(client, workflow_id)

    response = start_run(client, run["id"])
    assert response.status_code == 200, response.text

    response = start_step(client, run["id"])
    assert response.status_code == 200, response.text

    first_job_id = response.json()["steps"][0]["job_id"]
    assert first_job_id is not None

    response = complete_step(
        client,
        run["id"],
        result={"records_processed": 10},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "RUNNING"
    assert body["current_step_order"] == 2
    assert body["steps"][0]["status"] == "COMPLETED"
    assert body["steps"][0]["completed_at"] is not None
    assert body["steps"][1]["status"] == "QUEUED"

    # The next step can now be started.
    response = start_step(client, run["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["steps"][1]["status"] == "RUNNING"
    assert body["steps"][1]["job_id"] is not None


def test_completing_last_step_completes_workflow_run(client):
    workflow_id = create_workflow(client, ["SCAN"])
    run = create_run(client, workflow_id)

    response = start_run(client, run["id"])
    assert response.status_code == 200, response.text

    response = start_step(client, run["id"])
    assert response.status_code == 200, response.text

    response = complete_step(
        client,
        run["id"],
        result={"success": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "COMPLETED"
    assert body["completed_at"] is not None
    assert body["steps"][0]["status"] == "COMPLETED"


def test_failing_step_marks_workflow_failed(client):
    workflow_id = create_workflow(client, ["SCAN", "PROFILE"])
    run = create_run(client, workflow_id)

    response = start_run(client, run["id"])
    assert response.status_code == 200, response.text

    response = start_step(client, run["id"])
    assert response.status_code == 200, response.text

    response = fail_step(
        client,
        run["id"],
        error_message="Simulated scan failure",
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "FAILED"
    assert body["completed_at"] is not None
    assert body["error_message"] is not None
    assert "Simulated scan failure" in body["error_message"]
    assert body["steps"][0]["status"] == "FAILED"
    assert body["steps"][0]["error_message"] == "Simulated scan failure"
    assert body["steps"][1]["status"] == "QUEUED"


def test_tester_cannot_start_workflow_run(client):
    workflow_id = create_workflow(client, ["SCAN"])
    run = create_run(client, workflow_id)

    response = start_run(
        client,
        run["id"],
        roles="tester",
    )

    assert response.status_code == 403


def test_tester_cannot_start_workflow_step(client):
    workflow_id = create_workflow(client, ["SCAN"])
    run = create_run(client, workflow_id)

    response = start_run(client, run["id"])
    assert response.status_code == 200, response.text

    response = start_step(
        client,
        run["id"],
        roles="tester",
    )

    assert response.status_code == 403


def test_missing_workflow_run_returns_404(client):
    response = client.get(
        "/api/v1/workflows/runs/does-not-exist",
        headers=headers(),
    )

    assert response.status_code == 404
