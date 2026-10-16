"""
Step-5 tests: Job Management / Job Service.

Tests:
- Job creation
- QUEUED -> RUNNING
- RUNNING -> COMPLETED
- RUNNING -> FAILED
- Invalid state transitions
- Job retrieval
- Job listing

Uses the same in-memory SQLite + StaticPool approach
used by the existing Step-3 tests.
"""

import os

import pytest

# Force development auth mode for consistency with existing tests.
os.environ["TDM_AUTH_MODE"] = "development"

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from metadata_store.db import Base
from metadata_store.models import Job, Source
from api.services.job_service import (
    QUEUED,
    RUNNING,
    COMPLETED,
    FAILED,
    create_job,
    start_job,
    complete_job,
    fail_job,
    get_job,
    list_jobs,
)


# ============================================================
# Test database
# ============================================================

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


@pytest.fixture()
def db():
    """
    Provide a clean database session for each test.
    """

    session = _TestingSessionLocal()

    try:
        session.add_all(
            [
                Source(
                    id="source-123",
                    name="Test Source 123",
                    source_type="sqlite",
                    database_name="hospital.db",
                    status="ACTIVE",
                ),
                Source(
                    id="source-456",
                    name="Test Source 456",
                    source_type="sqlite",
                    database_name="hospital.db",
                    status="ACTIVE",
                ),
            ]
        )
        session.commit()

        yield session
    finally:
        session.query(Job).delete()
        session.query(Source).delete()
        session.commit()
        session.close()


# ============================================================
# 1. Job creation
# ============================================================

def test_create_job_starts_as_queued(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    assert job.id is not None
    assert job.job_type == "SCAN"
    assert job.source_id == "source-123"
    assert job.created_by == "devdatt"
    assert job.status == QUEUED
    assert job.created_at is not None
    assert job.started_at is None
    assert job.completed_at is None


# ============================================================
# 2. QUEUED -> RUNNING
# ============================================================

def test_start_job_moves_queued_to_running(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    updated = start_job(
        db=db,
        job=job,
    )

    assert updated.status == RUNNING
    assert updated.started_at is not None
    assert updated.completed_at is None


# ============================================================
# 3. RUNNING -> COMPLETED
# ============================================================

def test_complete_job_moves_running_to_completed(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    start_job(
        db=db,
        job=job,
    )

    updated = complete_job(
        db=db,
        job=job,
        result='{"tables": 4}',
    )

    assert updated.status == COMPLETED
    assert updated.completed_at is not None
    assert updated.result == '{"tables": 4}'
    assert updated.error_message is None


# ============================================================
# 4. RUNNING -> FAILED
# ============================================================

def test_fail_job_moves_running_to_failed(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    start_job(
        db=db,
        job=job,
    )

    updated = fail_job(
        db=db,
        job=job,
        error_message="Database connection failed.",
    )

    assert updated.status == FAILED
    assert updated.completed_at is not None
    assert updated.error_message == "Database connection failed."


# ============================================================
# 5. QUEUED -> FAILED
# ============================================================

def test_queued_job_can_fail(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    updated = fail_job(
        db=db,
        job=job,
        error_message="Job could not be started.",
    )

    assert updated.status == FAILED
    assert updated.error_message == "Job could not be started."
    assert updated.completed_at is not None


# ============================================================
# 6. Invalid transition: QUEUED -> COMPLETED
# ============================================================

def test_queued_cannot_be_completed_directly(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    with pytest.raises(HTTPException) as exc:
        complete_job(
            db=db,
            job=job,
            result="completed",
        )

    assert exc.value.status_code == 409
    assert "QUEUED -> COMPLETED" in exc.value.detail

    db.refresh(job)

    assert job.status == QUEUED


# ============================================================
# 7. Invalid transition: COMPLETED -> RUNNING
# ============================================================

def test_completed_cannot_be_started_again(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    start_job(
        db=db,
        job=job,
    )

    complete_job(
        db=db,
        job=job,
        result="completed",
    )

    with pytest.raises(HTTPException) as exc:
        start_job(
            db=db,
            job=job,
        )

    assert exc.value.status_code == 409
    assert "COMPLETED -> RUNNING" in exc.value.detail


# ============================================================
# 8. Invalid transition: FAILED -> RUNNING
# ============================================================

def test_failed_cannot_be_started_again(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    fail_job(
        db=db,
        job=job,
        error_message="Initial failure.",
    )

    with pytest.raises(HTTPException) as exc:
        start_job(
            db=db,
            job=job,
        )

    assert exc.value.status_code == 409
    assert "FAILED -> RUNNING" in exc.value.detail


# ============================================================
# 9. Get job
# ============================================================

def test_get_job_returns_existing_job(db):
    created = create_job(
        db=db,
        job_type="PROFILE",
        source_id="source-456",
        created_by="devdatt",
    )

    result = get_job(
        db=db,
        job_id=created.id,
    )

    assert result.id == created.id
    assert result.job_type == "PROFILE"
    assert result.source_id == "source-456"
    assert result.status == QUEUED


# ============================================================
# 10. Get missing job
# ============================================================

def test_get_missing_job_returns_404(db):
    with pytest.raises(HTTPException) as exc:
        get_job(
            db=db,
            job_id="does-not-exist",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Job not found."


# ============================================================
# 11. List jobs
# ============================================================

def test_list_jobs_returns_jobs(db):
    create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    create_job(
        db=db,
        job_type="PROFILE",
        source_id="source-456",
        created_by="devdatt",
    )

    jobs = list_jobs(db=db)

    assert len(jobs) == 2


# ============================================================
# 12. List jobs by source
# ============================================================

def test_list_jobs_can_filter_by_source(db):
    create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    create_job(
        db=db,
        job_type="PROFILE",
        source_id="source-456",
        created_by="devdatt",
    )

    jobs = list_jobs(
        db=db,
        source_id="source-123",
    )

    assert len(jobs) == 1
    assert jobs[0].source_id == "source-123"


# ============================================================
# 13. List jobs by status
# ============================================================

def test_list_jobs_can_filter_by_status(db):
    job = create_job(
        db=db,
        job_type="SCAN",
        source_id="source-123",
        created_by="devdatt",
    )

    start_job(
        db=db,
        job=job,
    )

    jobs = list_jobs(
        db=db,
        status=RUNNING,
    )

    assert len(jobs) == 1
    assert jobs[0].id == job.id
    assert jobs[0].status == RUNNING

# ============================================================
# 14. Unsupported job type
# ============================================================

def test_create_job_rejects_unsupported_job_type(db):
    with pytest.raises(HTTPException) as exc:
        create_job(
            db=db,
            job_type="UNKNOWN",
            source_id="source-123",
            created_by="devdatt",
        )

    assert exc.value.status_code == 400
    assert "Unsupported job type" in exc.value.detail


# ============================================================
# 15. Unknown source
# ============================================================

def test_create_job_rejects_unknown_source(db):
    with pytest.raises(HTTPException) as exc:
        create_job(
            db=db,
            job_type="SCAN",
            source_id="does-not-exist",
            created_by="devdatt",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Source not found."


# ============================================================
# 16. Invalid status filter
# ============================================================

def test_list_jobs_rejects_invalid_status(db):
    with pytest.raises(HTTPException) as exc:
        list_jobs(
            db=db,
            status="NOT_A_STATUS",
        )

    assert exc.value.status_code == 400
    assert "Unsupported job status" in exc.value.detail
