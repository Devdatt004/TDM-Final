"""Step 6 - Workflow Management API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth.dependencies import (
    require_steward_or_admin,
    require_tester_or_above,
)
from api.auth.models import CurrentUser
from api.services import audit_service
from api.services.workflow_service import (
    complete_current_step,
    create_workflow,
    create_workflow_run,
    fail_current_step,
    get_workflow,
    get_workflow_run,
    get_workflow_steps,
    list_workflow_runs,
    workflows_query,
    start_current_step,
    start_workflow_run,
)
from api.pagination import Page, envelope, page_params, paginate
from metadata_store.db import get_db


router = APIRouter(
    prefix="/api/v1/workflows",
    tags=["Workflow Management"],
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    steps: list[str] = Field(min_length=1, max_length=100)


class WorkflowRunCreate(BaseModel):
    source_id: str | None = None


class WorkflowStepComplete(BaseModel):
    result: dict[str, Any] | None = None


class WorkflowStepFail(BaseModel):
    error_message: str = Field(min_length=1, max_length=4000)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _workflow_response(db: Session, workflow) -> dict:
    steps = get_workflow_steps(db, workflow.id)

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "created_by": workflow.created_by,
        "created_at": workflow.created_at,
        "steps": [
            {
                "id": step.id,
                "step_order": step.step_order,
                "job_type": step.job_type,
            }
            for step in steps
        ],
    }


def _run_response(db: Session, run) -> dict:
    from metadata_store.models import WorkflowStep, WorkflowStepRun

    step_runs = (
        db.query(WorkflowStepRun, WorkflowStep)
        .join(
            WorkflowStep,
            WorkflowStep.id == WorkflowStepRun.workflow_step_id,
        )
        .filter(
            WorkflowStepRun.workflow_run_id == run.id,
        )
        .order_by(
            WorkflowStep.step_order.asc(),
        )
        .all()
    )

    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "source_id": run.source_id,
        "status": run.status,
        "current_step_order": run.current_step_order,
        "created_by": run.created_by,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "error_message": run.error_message,
        "steps": [
            {
                "workflow_step_id": step.id,
                "step_order": step.step_order,
                "job_type": step.job_type,
                "workflow_step_run_id": step_run.id,
                "job_id": step_run.job_id,
                "status": step_run.status,
                "started_at": step_run.started_at,
                "completed_at": step_run.completed_at,
                "error_message": step_run.error_message,
            }
            for step_run, step in step_runs
        ],
    }


def _audit_workflow_action(
    db: Session,
    user: CurrentUser,
    action: str,
    run_id: str,
    status: str,
    message: str,
) -> None:
    audit_service.record_audit(
        db,
        "Workflow Management",
        user,
        status,
        f"{action}: {message}",
        source=run_id,
        source_type="WorkflowRun",
    )


# ---------------------------------------------------------------------------
# Workflow definitions
# ---------------------------------------------------------------------------

@router.post("")
def create_workflow_endpoint(
    payload: WorkflowCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    workflow = create_workflow(
        db=db,
        name=payload.name,
        description=payload.description,
        steps=payload.steps,
        created_by=user.username,
    )

    audit_service.record_audit(
        db,
        "Workflow Management",
        user,
        "complete",
        (
            f"Workflow '{workflow.id}' created with "
            f"{len(payload.steps)} steps."
        ),
        source=workflow.id,
        source_type="Workflow",
    )

    return _workflow_response(db, workflow)


@router.get("")
def list_workflows_endpoint(
    include_inactive: bool = False,
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    total, workflows = paginate(workflows_query(db, include_inactive), page)

    return {
        "workflows": [
            _workflow_response(db, workflow)
            for workflow in workflows
        ],
        "count": len(workflows),
        **envelope(page, total),
    }


@router.get("/{workflow_id}")
def get_workflow_endpoint(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    workflow = get_workflow(db, workflow_id)
    return _workflow_response(db, workflow)


# ---------------------------------------------------------------------------
# Workflow runs - creation and read operations
# ---------------------------------------------------------------------------

@router.post("/{workflow_id}/runs")
def create_workflow_run_endpoint(
    workflow_id: str,
    payload: WorkflowRunCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    run = create_workflow_run(
        db=db,
        workflow_id=workflow_id,
        source_id=payload.source_id,
        created_by=user.username,
    )

    audit_service.record_audit(
        db,
        "Workflow Management",
        user,
        "complete",
        f"Workflow run '{run.id}' queued.",
        source=run.id,
        source_type="WorkflowRun",
    )

    return _run_response(db, run)


@router.get("/runs/list")
def list_workflow_runs_endpoint(
    workflow_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    runs = list_workflow_runs(
        db=db,
        workflow_id=workflow_id,
        status=status,
    )

    return {
        "runs": [
            _run_response(db, run)
            for run in runs
        ],
        "count": len(runs),
    }


@router.get("/runs/{run_id}")
def get_workflow_run_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    run = get_workflow_run(db, run_id)
    return _run_response(db, run)


# ---------------------------------------------------------------------------
# Workflow execution - steward/admin only
# ---------------------------------------------------------------------------

@router.post("/runs/{run_id}/start")
def start_workflow_run_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    run = start_workflow_run(
        db=db,
        run_id=run_id,
    )

    _audit_workflow_action(
        db,
        user,
        "Workflow run started",
        run.id,
        "complete",
        f"Run status is {run.status}.",
    )

    return _run_response(db, run)


@router.post("/runs/{run_id}/steps/start")
def start_workflow_step_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    run, step_run, job = start_current_step(
        db=db,
        run_id=run_id,
        created_by=user.username,
    )

    _audit_workflow_action(
        db,
        user,
        "Workflow step started",
        run.id,
        "complete",
        (
            f"Step run '{step_run.id}' started "
            f"with job '{job.id}'."
        ),
    )

    return _run_response(db, run)


@router.post("/runs/{run_id}/steps/complete")
def complete_workflow_step_endpoint(
    run_id: str,
    payload: WorkflowStepComplete,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    # The service returns (WorkflowRun, WorkflowStepRun, Job).
    run, step_run, job = complete_current_step(
        db=db,
        run_id=run_id,
        result=payload.result,
    )

    _audit_workflow_action(
        db,
        user,
        "Workflow step completed",
        run.id,
        "complete",
        (
            f"Step run '{step_run.id}' completed "
            f"with job '{job.id}'. "
            f"Workflow run status is {run.status}; "
            f"current step is {run.current_step_order}."
        ),
    )

    return _run_response(db, run)


@router.post("/runs/{run_id}/steps/fail")
def fail_workflow_step_endpoint(
    run_id: str,
    payload: WorkflowStepFail,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    # The service returns (WorkflowRun, WorkflowStepRun, Job).
    run, step_run, job = fail_current_step(
        db=db,
        run_id=run_id,
        error_message=payload.error_message,
    )

    _audit_workflow_action(
        db,
        user,
        "Workflow step failed",
        run.id,
        "failed",
        (
            f"Step run '{step_run.id}' failed "
            f"with job '{job.id}'. "
            f"Error: {payload.error_message}"
        ),
    )

    return _run_response(db, run)
