from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from metadata_store.models import Job


QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"


ALLOWED_TRANSITIONS = {
    QUEUED: {RUNNING, FAILED},
    RUNNING: {COMPLETED, FAILED},
    COMPLETED: set(),
    FAILED: set(),
}


def create_job(
    db: Session,
    job_type: str,
    source_id: str | None,
    created_by: str | None,
) -> Job:
    job = Job(
        id=str(uuid4()),
        job_type=job_type,
        source_id=source_id,
        status=QUEUED,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


def _transition(
    db: Session,
    job: Job,
    new_status: str,
) -> Job:
    current_status = job.status

    allowed = ALLOWED_TRANSITIONS.get(
        current_status,
        set(),
    )

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

    db.commit()
    db.refresh(job)

    return job


def start_job(
    db: Session,
    job: Job,
) -> Job:
    return _transition(
        db=db,
        job=job,
        new_status=RUNNING,
    )


def complete_job(
    db: Session,
    job: Job,
    result: str | None = None,
) -> Job:
    job.result = result

    return _transition(
        db=db,
        job=job,
        new_status=COMPLETED,
    )


def fail_job(
    db: Session,
    job: Job,
    error_message: str,
) -> Job:
    job.error_message = error_message

    return _transition(
        db=db,
        job=job,
        new_status=FAILED,
    )


def get_job(
    db: Session,
    job_id: str,
) -> Job:
    job = (
        db.query(Job)
        .filter(Job.id == job_id)
        .first()
    )

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

    query = db.query(Job)

    if source_id:
        query = query.filter(
            Job.source_id == source_id
        )

    if status:
        query = query.filter(
            Job.status == status
        )

    return (
        query
        .order_by(Job.created_at.desc())
        .all()
    )