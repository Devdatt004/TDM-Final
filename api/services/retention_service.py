"""
api/services/retention_service.py

Step 16 - artifact retention classes and the scheduled purge.

| Class                  | Default   | Setting                        | What is deleted                         |
|------------------------|-----------|--------------------------------|-----------------------------------------|
| Generated/masked data  | 30 days   | TDM_DATASET_RETENTION_DAYS     | the file; the dataset row is kept,      |
|                        |           |                                | marked purged, for audit/lineage        |
| Uploaded source files  | 30 days   | TDM_UPLOAD_RETENTION_DAYS      | the file and its upload row             |
| Activity log           | 5 days    | TDM_LOG_RETENTION_DAYS         | (metadata_store/activity.py)            |
| Idempotency records    | 24 hours  | -                              | (api/http_layer.py)                     |
| Audit log, metadata    | permanent | -                              | never (append-only, hash-chained)       |

The purge is safe to retry: a file already gone counts as purged, one item
failing does not stop the rest, and each run writes one audit event with
counts. Runs at startup and on the existing log-cleanup schedule.
"""

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from metadata_store.models import SyntheticDataset, UploadedSource

logger = logging.getLogger(__name__)


def dataset_retention_days() -> int:
    return int(os.getenv("TDM_DATASET_RETENTION_DAYS", "30"))


def upload_retention_days() -> int:
    return int(os.getenv("TDM_UPLOAD_RETENTION_DAYS", "30"))


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass                                  # already gone: idempotent


def purge_expired(db: Session, now: datetime = None) -> dict:
    now = now or datetime.utcnow()
    result = {"datasets_purged": 0, "uploads_purged": 0, "errors": 0}

    dataset_cutoff = now - timedelta(days=dataset_retention_days())
    for d in (db.query(SyntheticDataset)
              .filter(SyntheticDataset.purged_at.is_(None), SyntheticDataset.created_at < dataset_cutoff).all()):
        try:
            _remove(d.file_path)
            d.purged_at = now
            db.commit()
            result["datasets_purged"] += 1
        except OSError:
            db.rollback()
            result["errors"] += 1
            logger.exception("Could not purge dataset %s", d.public_id)

    upload_cutoff = now - timedelta(days=upload_retention_days())
    for u in db.query(UploadedSource).filter(UploadedSource.uploaded_at < upload_cutoff).all():
        try:
            _remove(u.file_path)
            db.delete(u)
            db.commit()
            result["uploads_purged"] += 1
        except OSError:
            db.rollback()
            result["errors"] += 1
            logger.exception("Could not purge upload %s", u.id)

    if any(result.values()):
        from api.services import audit_service
        audit_service.record_audit(
            db, "Artifact Retention Purge", "system", "complete" if not result["errors"] else "failed",
            f"{result['datasets_purged']} dataset file(s), {result['uploads_purged']} upload(s) purged; "
            f"{result['errors']} error(s). Retention: datasets {dataset_retention_days()}d, "
            f"uploads {upload_retention_days()}d.",
            source="retention", source_type="Data lifecycle")
    return result
