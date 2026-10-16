"""Step 6 - Workflow Management service."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.services.job_service import (
    JOB_TYPES,
    create_job,
    start_job,
    complete_job,
    fail_job,
    get_job,
)
from metadata_store.models import (
    Workflow,
    WorkflowStep,
    WorkflowRun,
    WorkflowStepRun,
    Job,
)


QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"


def create_workflow(
    db: Session,
    name: str,
    steps: list[str],
    created_by: str | None = None,
    description: str | None = None,
) -> Workflow:
    """Create a workflow definition with ordered job types."""

    normalized_name = (name or "").strip()
    if not normalized_name:
        raise HTTPException(400, "Workflow name is required.")

    if not steps:
        raise HTTPException(400, "A workflow must contain at least one step.")

    normalized_steps = []
    for job_type in steps:
        normalized_type = (job_type or "").strip().upper()
        if normalized_type not in JOB_TYPES:
            raise HTTPException(
                400,
                f"Unsupported job type '{job_type}'. "
                f"Supported types: {', '.join(sorted(JOB_TYPES))}.",
            )
        normalized_steps.append(normalized_type)

    existing = (
        db.query(Workflow)
        .filter(Workflow.name == normalized_name)
        .first()
    )
    if existing:
        raise HTTPException(409, "A workflow with this name already exists.")

    try:
        workflow = Workflow(
            id=str(uuid4()),
            name=normalized_name,
            description=description,
            is_active=True,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        db.add(workflow)
        db.flush()

        for order, job_type in enumerate(normalized_steps, start=1):
            db.add(
                WorkflowStep(
                    id=str(uuid4()),
                    workflow_id=workflow.id,
                    step_order=order,
                    job_type=job_type,
                )
            )

        db.commit()
        db.refresh(workflow)
        return workflow
    except Exception:
        db.rollback()
        raise


def list_workflows(
    db: Session,
    include_inactive: bool = False,
) -> list[Workflow]:
    """List workflow definitions."""

    query = db.query(Workflow)
    if not include_inactive:
        query = query.filter(Workflow.is_active.is_(True))

    return query.order_by(Workflow.name.asc()).all()


def get_workflow(db: Session, workflow_id: str) -> Workflow:
    """Get a workflow definition or return 404."""

    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id)
        .first()
    )
    if workflow is None:
        raise HTTPException(404, "Workflow not found.")

    return workflow


def get_workflow_steps(
    db: Session,
    workflow_id: str,
) -> list[WorkflowStep]:
    """Return steps in execution order."""

    get_workflow(db, workflow_id)

    return (
        db.query(WorkflowStep)
        .filter(WorkflowStep.workflow_id == workflow_id)
        .order_by(WorkflowStep.step_order.asc())
        .all()
    )


def create_workflow_run(
    db: Session,
    workflow_id: str,
    source_id: str | None,
    created_by: str | None,
) -> WorkflowRun:
    """Create a queued run and its queued step-run records."""

    workflow = get_workflow(db, workflow_id)

    if not workflow.is_active:
        raise HTTPException(409, "This workflow is inactive.")

    steps = get_workflow_steps(db, workflow_id)
    if not steps:
        raise HTTPException(409, "Workflow has no steps.")

    try:
        run = WorkflowRun(
            id=str(uuid4()),
            workflow_id=workflow.id,
            source_id=source_id,
            status=QUEUED,
            current_step_order=1,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        db.add(run)
        db.flush()

        for step in steps:
            db.add(
                WorkflowStepRun(
                    id=str(uuid4()),
                    workflow_run_id=run.id,
                    workflow_step_id=step.id,
                    status=QUEUED,
                )
            )

        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise


def get_workflow_run(db: Session, run_id: str) -> WorkflowRun:
    """Get a workflow run or return 404."""

    run = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(404, "Workflow run not found.")

    return run


def list_workflow_runs(
    db: Session,
    workflow_id: str | None = None,
    status: str | None = None,
) -> list[WorkflowRun]:
    """List runs, optionally filtered by workflow and status."""

    query = db.query(WorkflowRun)

    if workflow_id:
        query = query.filter(WorkflowRun.workflow_id == workflow_id)

    if status:
        normalized_status = status.strip().upper()
        if normalized_status not in {QUEUED, RUNNING, COMPLETED, FAILED}:
            raise HTTPException(
                400,
                "Unsupported workflow run status. "
                "Supported statuses: QUEUED, RUNNING, COMPLETED, FAILED.",
            )
        query = query.filter(WorkflowRun.status == normalized_status)

    return query.order_by(WorkflowRun.created_at.desc()).all()


def start_workflow_run(db: Session, run_id: str) -> WorkflowRun:
    """Transition a queued workflow run to RUNNING."""

    run = get_workflow_run(db, run_id)
    if run.status != QUEUED:
        raise HTTPException(
            409,
            f"Cannot start workflow run in state {run.status}.",
        )

    try:
        run.status = RUNNING
        run.started_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise


def start_current_step(
    db: Session,
    run_id: str,
    created_by: str,
) -> tuple[WorkflowRun, WorkflowStepRun, Job]:
    """Create and start a job for the workflow run's current step."""

    run = get_workflow_run(db, run_id)
    if run.status != RUNNING:
        raise HTTPException(409, "Workflow run must be RUNNING.")

    step = (
        db.query(WorkflowStep)
        .filter(
            WorkflowStep.workflow_id == run.workflow_id,
            WorkflowStep.step_order == run.current_step_order,
        )
        .first()
    )
    if step is None:
        raise HTTPException(409, "Current workflow step was not found.")

    step_run = (
        db.query(WorkflowStepRun)
        .filter(
            WorkflowStepRun.workflow_run_id == run.id,
            WorkflowStepRun.workflow_step_id == step.id,
        )
        .first()
    )
    if step_run is None or step_run.status != QUEUED:
        raise HTTPException(409, "Current workflow step is not queued.")

    if step_run.job_id:
        raise HTTPException(409, "Current step already has a linked job.")

    try:
        # Defer commits until the job and workflow-step changes are ready.
        job = create_job(
            db=db,
            job_type=step.job_type,
            source_id=run.source_id,
            created_by=created_by,
            commit=False,
        )
        job = start_job(
            db=db,
            job=job,
            commit=False,
        )

        step_run.job_id = job.id
        step_run.status = RUNNING
        step_run.started_at = datetime.utcnow()

        db.commit()
        db.refresh(run)
        db.refresh(step_run)
        db.refresh(job)

        return run, step_run, job
    except Exception:
        db.rollback()
        raise


def complete_current_step(
    db: Session,
    run_id: str,
    result: object | None = None,
) -> tuple[WorkflowRun, WorkflowStepRun, Job]:
    """Complete the current job and advance or finish the workflow."""

    run = get_workflow_run(db, run_id)
    if run.status != RUNNING:
        raise HTTPException(409, "Workflow run must be RUNNING.")

    step = (
        db.query(WorkflowStep)
        .filter(
            WorkflowStep.workflow_id == run.workflow_id,
            WorkflowStep.step_order == run.current_step_order,
        )
        .first()
    )
    if step is None:
        raise HTTPException(409, "Current workflow step was not found.")

    step_run = (
        db.query(WorkflowStepRun)
        .filter(
            WorkflowStepRun.workflow_run_id == run.id,
            WorkflowStepRun.workflow_step_id == step.id,
        )
        .first()
    )
    if step_run is None or step_run.status != RUNNING or not step_run.job_id:
        raise HTTPException(409, "Current workflow step has no running job.")

    job = get_job(db, step_run.job_id)
    if job.status != RUNNING:
        raise HTTPException(409, "Linked job must be RUNNING to complete the step.")

    try:
        # Keep job completion and workflow progression in one transaction.
        complete_job(
            db=db,
            job=job,
            result=result,
            commit=False,
        )

        step_run.status = COMPLETED
        step_run.completed_at = datetime.utcnow()

        next_step = (
            db.query(WorkflowStep)
            .filter(
                WorkflowStep.workflow_id == run.workflow_id,
                WorkflowStep.step_order > run.current_step_order,
            )
            .order_by(WorkflowStep.step_order.asc())
            .first()
        )

        if next_step is None:
            run.status = COMPLETED
            run.completed_at = datetime.utcnow()
        else:
            run.current_step_order = next_step.step_order

        db.commit()
        db.refresh(run)
        db.refresh(step_run)
        db.refresh(job)

        return run, step_run, job
    except Exception:
        db.rollback()
        raise


def fail_current_step(
    db: Session,
    run_id: str,
    error_message: str,
) -> tuple[WorkflowRun, WorkflowStepRun, Job]:
    """Fail the current job and stop the workflow run."""

    message = (error_message or "").strip()
    if not message:
        raise HTTPException(400, "error_message is required.")

    run = get_workflow_run(db, run_id)
    if run.status != RUNNING:
        raise HTTPException(409, "Workflow run must be RUNNING.")

    step = (
        db.query(WorkflowStep)
        .filter(
            WorkflowStep.workflow_id == run.workflow_id,
            WorkflowStep.step_order == run.current_step_order,
        )
        .first()
    )
    if step is None:
        raise HTTPException(409, "Current workflow step was not found.")

    step_run = (
        db.query(WorkflowStepRun)
        .filter(
            WorkflowStepRun.workflow_run_id == run.id,
            WorkflowStepRun.workflow_step_id == step.id,
        )
        .first()
    )
    if step_run is None or step_run.status != RUNNING or not step_run.job_id:
        raise HTTPException(409, "Current workflow step has no running job.")

    job = get_job(db, step_run.job_id)
    if job.status != RUNNING:
        raise HTTPException(409, "Linked job must be RUNNING to fail the step.")

    try:
        # Keep job failure and workflow failure in one transaction.
        fail_job(
            db=db,
            job=job,
            error_message=message,
            commit=False,
        )

        step_run.status = FAILED
        step_run.completed_at = datetime.utcnow()
        step_run.error_message = message[:4000]

        run.status = FAILED
        run.completed_at = datetime.utcnow()
        run.error_message = message[:4000]

        db.commit()
        db.refresh(run)
        db.refresh(step_run)
        db.refresh(job)

        return run, step_run, job
    except Exception:
        db.rollback()
        raise
