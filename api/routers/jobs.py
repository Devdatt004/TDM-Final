"""
Job Management API.

Endpoints
---------
POST   /api/v1/jobs
GET    /api/v1/jobs
GET    /api/v1/jobs/{job_id}
POST   /api/v1/jobs/{job_id}/start
POST   /api/v1/jobs/{job_id}/complete
POST   /api/v1/jobs/{job_id}/fail

Job creation is available to tester+ users. Lifecycle mutation endpoints
are restricted to steward/admin because they change execution state.
The service layer remains the authoritative state-machine implementation.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth.dependencies import (
    require_steward_or_admin,
    require_tester_or_above,
)
from api.auth.models import CurrentUser
from api.services import audit_service
from api.services.job_service import (
    complete_job,
    create_job,
    fail_job,
    get_job,
    jobs_query,
    start_job,
)
from api.pagination import Page, envelope, page_params, paginate
from metadata_store.db import get_db


router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["Job Management"],
)


class JobCreate(BaseModel):
    job_type: str = Field(min_length=1, max_length=50)
    source_id: str | None = None


class JobComplete(BaseModel):
    result: object | None = None


class JobFail(BaseModel):
    error_message: str = Field(min_length=1, max_length=4000)


def _job_response(job) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "source_id": job.source_id,
        "status": job.status,
        "created_by": job.created_by,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message,
        "result": job.result,
    }


@router.post("")
def create_job_endpoint(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    job = create_job(
        db=db,
        job_type=payload.job_type,
        source_id=payload.source_id,
        created_by=user.username,
    )

    audit_service.record_audit(
        db,
        "Job Management",
        user,
        "complete",
        f"Job '{job.id}' created.",
        source=job.source_id or job.id,
        source_type=f"Job/{job.job_type}",
    )

    return _job_response(job)


@router.get("")
def list_jobs_endpoint(
    source_id: str | None = None,
    status: str | None = None,
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    total, jobs = paginate(jobs_query(db=db, source_id=source_id, status=status), page)

    return {
        "jobs": [_job_response(job) for job in jobs],
        "count": len(jobs),
        **envelope(page, total),
    }


@router.get("/{job_id}")
def get_job_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    return _job_response(
        get_job(
            db=db,
            job_id=job_id,
        )
    )


@router.post("/{job_id}/start")
def start_job_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    job = start_job(
        db=db,
        job=get_job(db, job_id),
    )

    audit_service.record_audit(
        db,
        "Job Management",
        user,
        "complete",
        f"Job '{job.id}' transitioned to RUNNING.",
        source=job.source_id or job.id,
        source_type=f"Job/{job.job_type}",
    )

    return _job_response(job)


@router.post("/{job_id}/complete")
def complete_job_endpoint(
    job_id: str,
    payload: JobComplete | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    job = complete_job(
        db=db,
        job=get_job(db, job_id),
        result=payload.result if payload is not None else None,
    )

    audit_service.record_audit(
        db,
        "Job Management",
        user,
        "complete",
        f"Job '{job.id}' transitioned to COMPLETED.",
        source=job.source_id or job.id,
        source_type=f"Job/{job.job_type}",
    )

    return _job_response(job)


@router.post("/{job_id}/fail")
def fail_job_endpoint(
    job_id: str,
    payload: JobFail,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    job = fail_job(
        db=db,
        job=get_job(db, job_id),
        error_message=payload.error_message,
    )

    audit_service.record_audit(
        db,
        "Job Management",
        user,
        "failed",
        f"Job '{job.id}' transitioned to FAILED.",
        source=job.source_id or job.id,
        source_type=f"Job/{job.job_type}",
    )

    return _job_response(job)
