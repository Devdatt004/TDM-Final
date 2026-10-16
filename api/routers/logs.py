"""
api/routers/logs.py

Activity log, files, retention, and audit log endpoints.

RBAC mapping
------------
GET  /logs              – reviewer+  (read activity log)
GET  /files             – reviewer+  (file inventory)
GET  /logs/retention    – admin      (retention policy config)
POST /logs/purge        – admin      (manually trigger purge)
GET  /audit             – admin      (security audit log)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
import os

from metadata_store.db import get_db
from metadata_store.models import ActivityLog, SyntheticDataset, UploadedSource, AuditLog
from metadata_store import activity as act
from api.services import audit_service
from synthetic_generation import generator as synthetic_generator
from api.routers.connectors import UPLOAD_DIR
from api.auth.dependencies import (
    require_admin,
    require_reviewer_or_above,
)
from api.auth.models import CurrentUser

router = APIRouter()


@router.get("/logs")
def get_logs(
    activity: str | None = None,
    user_filter: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    query = db.query(ActivityLog)
    if activity:
        query = query.filter(ActivityLog.activity == activity)
    if user_filter:
        query = query.filter(ActivityLog.username == user_filter)
    entries = query.order_by(ActivityLog.created_at.desc()).limit(max(1, min(limit, 500))).all()
    activities = sorted(r[0] for r in db.query(ActivityLog.activity).distinct().all())
    users = sorted(r[0] for r in db.query(ActivityLog.username).distinct().all() if r[0])
    return {
        "total": db.query(ActivityLog).count(),
        "activities": activities,
        "users": users,
        "entries": [
            {
                "id": e.id,
                "activity": e.activity,
                "user": e.username or "-",
                "source": e.source,
                "source_type": e.source_type,
                "fields": e.fields,
                "status": act.status_of(e),
                "message": e.message,
                "file_path": e.file_path,
                "created_at": act.iso_utc(e.created_at),
            }
            for e in entries
        ],
    }


def _location_info(label, description, path):
    file_count, total_bytes = 0, 0
    if os.path.isdir(path):
        for n in os.listdir(path):
            fp = os.path.join(path, n)
            if n != ".gitkeep" and os.path.isfile(fp):
                file_count += 1
                total_bytes += os.path.getsize(fp)
    return {
        "label": label,
        "description": description,
        "path": os.path.abspath(path),
        "exists": os.path.isdir(path),
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


@router.get("/files")
def get_files(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    db_path = os.path.abspath("metadata_store.db")
    locations = [
        _location_info(
            "Uploaded input files",
            "CSV / XML / text files uploaded as data sources",
            UPLOAD_DIR,
        ),
        _location_info(
            "Generated output files",
            "Synthetic and masked-preview CSVs",
            synthetic_generator.OUTPUT_DIR,
        ),
        {
            "label": "Metadata store",
            "description": "Database holding logs, profiling results, catalog and dictionary",
            "path": db_path,
            "exists": os.path.isfile(db_path),
            "file_count": 1 if os.path.isfile(db_path) else 0,
            "total_bytes": os.path.getsize(db_path) if os.path.isfile(db_path) else 0,
        },
    ]

    datasets = db.query(SyntheticDataset).order_by(SyntheticDataset.created_at.desc()).limit(100).all()
    generated_by = {
        row.file_path: (row.activity, row.username)
        for row in db.query(ActivityLog).filter(
            ActivityLog.file_path.in_([d.file_path for d in datasets] or [""])
        ).all()
    }
    outputs = []
    for d in datasets:
        exists = os.path.isfile(d.file_path)
        outputs.append({
            "dataset_id": d.public_id,
            "file_name": os.path.basename(d.file_path),
            "source_table": d.source_table,
            "row_count": d.row_count,
            "generated_by": generated_by.get(d.file_path, ("-", None))[0],
            "generated_by_user": generated_by.get(d.file_path, ("-", None))[1] or "-",
            "size_bytes": os.path.getsize(d.file_path) if exists else None,
            "exists": exists,
            "file_path": d.file_path,
            "created_at": act.iso_utc(d.created_at),
        })

    uploaded_by = {
        row.file_path: row.username
        for row in db.query(ActivityLog)
        .filter(ActivityLog.activity == "File Upload", ActivityLog.file_path.isnot(None))
        .order_by(ActivityLog.created_at.asc())
        .all()
    }
    uploads = [
        {
            "uploaded_by": uploaded_by.get(u.file_path) or "-",
            "name": u.name,
            "file_type": u.file_type,
            "row_count": u.row_count,
            "column_count": u.column_count,
            "size_bytes": u.size_bytes,
            "exists": os.path.isfile(u.file_path),
            "file_path": u.file_path,
            "uploaded_at": act.iso_utc(u.uploaded_at),
        }
        for u in db.query(UploadedSource).order_by(UploadedSource.uploaded_at.desc()).all()
    ]
    return {"locations": locations, "outputs": outputs, "uploads": uploads}


@router.get("/logs/retention")
def get_log_retention(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin()),
):
    oldest = db.query(func.min(ActivityLog.created_at)).scalar()
    return {
        "retention_days": act.LOG_RETENTION_DAYS,
        "check_interval_seconds": act.LOG_PURGE_INTERVAL_SECONDS,
        "last_purge_at": act.iso_utc(act.purge_state["last_purge_at"]),
        "last_purge_deleted": act.purge_state["last_purge_deleted"],
        "oldest_log_at": act.iso_utc(oldest),
        "total_logs": db.query(ActivityLog).count(),
    }


@router.post("/logs/purge")
def purge_logs_now(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin()),
):
    deleted = audit_service.purge_old_logs(db)
    return {"deleted": deleted, "retention_days": act.LOG_RETENTION_DAYS}


@router.get("/audit")
def get_audit_log(
    limit: int = 200,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin()),
):
    entries = (
        db.query(AuditLog)
        .order_by(AuditLog.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return {
        "total": db.query(AuditLog).count(),
        "chain": audit_service.verify_audit_chain(db),
        "entries": [
            {
                "id": e.id,
                "event": e.event,
                "user": e.username or "-",
                "user_id": e.user_id or "-",
                "role": e.role or "-",
                "target": e.target,
                "target_type": e.target_type,
                "status": act.status_of(e),
                "detail": e.detail,
                "created_at": act.iso_utc(e.created_at),
            }
            for e in entries
        ],
    }
