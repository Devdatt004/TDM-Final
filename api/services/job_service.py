"""
Job management service.

Step-5 responsibilities:
- Create persistent jobs.
- Enforce the job lifecycle state machine.
- Record start/completion/failure timestamps.
- Store execution results/errors.
- Retrieve and filter jobs.

Lifecycle:
    QUEUED -> RUNNING -> COMPLETED
                   \\-> FAILED
    QUEUED -> FAILED

Terminal states cannot be transitioned again.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from metadata_store.models import Job, Source


QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

JOB_TYPES = {
    "SCAN",
    "PROFILE",
    "CLASSIFICATION",
    "GENERATION",
    "VALIDATION",
}

ALLOWED_TRANSITIONS = {
    QUEUED: {RUNNING, FAILED},
    RUNNING: {COMPLETED, FAILED},
    COMPLETED: set(),
    FAILED: set(),
}


def _validate_job_type(job_type: str) -> str:
    normalized = (job_type or "").strip().upper()

    if normalized not in JOB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported job type '{job_type}'. "
                f"Supported types: {', '.join(sorted(JOB_TYPES))}."
            ),
        )

    return normalized


def _validate_source(db: Session, source_id: str | None) -> None:
    if not source_id:
        return

    source = (
        db.query(Source)
        .filter(
            Source.id == source_id,
            Source.status != "DELETED",
        )
        .first()
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found.",
        )


def _finish_write(db: Session, commit: bool) -> None:
    """Commit for normal callers, or flush for a larger transaction."""
    if commit:
        db.commit()
    else:
        db.flush()


def create_job(
    db: Session,
    job_type: str,
    source_id: str | None,
    created_by: str | None,
    *,
    commit: bool = True,
) -> Job:
    """Create a QUEUED job.

    Set commit=False when the caller owns a larger transaction.
    """
    normalized_type = _validate_job_type(job_type)
    _validate_source(db, source_id)

    job = Job(
        id=str(uuid4()),
        job_type=normalized_type,
        source_id=source_id,
        status=QUEUED,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )

    db.add(job)

    try:
        _finish_write(db, commit)
        db.refresh(job) if commit else None
    except Exception:
        db.rollback()
        raise

    return job


def _transition(
    db: Session,
    job: Job,
    new_status: str,
    *,
    commit: bool = True,
) -> Job:
    """Apply one valid lifecycle transition."""
    current_status = job.status
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())

    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invalid job state transition: "
                f"{current_status} -> {new_status}"
            ),
        )

    job.status = new_status

    if new_status == RUNNING:
        job.started_at = datetime.utcnow()
    elif new_status in {COMPLETED, FAILED}:
        job.completed_at = datetime.utcnow()

    try:
        _finish_write(db, commit)
        db.refresh(job) if commit else None
    except Exception:
        db.rollback()
        raise

    return job


def start_job(
    db: Session,
    job: Job,
    *,
    commit: bool = True,
) -> Job:
    """Transition QUEUED -> RUNNING."""
    return _transition(
        db=db,
        job=job,
        new_status=RUNNING,
        commit=commit,
    )


def complete_job(
    db: Session,
    job: Job,
    result: object | None = None,
    *,
    commit: bool = True,
) -> Job:
    """Transition RUNNING -> COMPLETED and store a JSON-safe result."""
    if result is not None:
        if isinstance(result, str):
            job.result = result
        else:
            try:
                job.result = json.dumps(result, default=str)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Job result could not be serialized: {exc}",
                ) from exc
    else:
        job.result = None

    return _transition(
        db=db,
        job=job,
        new_status=COMPLETED,
        commit=commit,
    )


def fail_job(
    db: Session,
    job: Job,
    error_message: str,
    *,
    commit: bool = True,
) -> Job:
    """Transition QUEUED/RUNNING -> FAILED."""
    message = (error_message or "").strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="error_message is required when failing a job.",
        )

    job.error_message = message[:4000]

    return _transition(
        db=db,
        job=job,
        new_status=FAILED,
        commit=commit,
    )


def get_job(db: Session, job_id: str) -> Job:
    """Retrieve a job by ID."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    return job


def list_jobs(
    db: Session,
    source_id: str | None = None,
    status: str | None = None,
) -> list[Job]:
    """Retrieve jobs, optionally filtered by source and/or status."""
    query = db.query(Job)

    if source_id:
        query = query.filter(Job.source_id == source_id)

    if status:
        normalized_status = status.strip().upper()

        if normalized_status not in {
            QUEUED,
            RUNNING,
            COMPLETED,
            FAILED,
        }:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported job status '{status}'. "
                    "Supported statuses: QUEUED, RUNNING, COMPLETED, FAILED."
                ),
            )

        query = query.filter(Job.status == normalized_status)

    return query.order_by(Job.created_at.desc()).all()
