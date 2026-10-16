"""
api/routers/datasets.py

Generated / masked dataset metadata and the Step 13 release gate.

RBAC mapping
------------
GET  /api/v1/datasets                          – reviewer+ (paginated list)
GET  /api/v1/datasets/{id}/validation          – reviewer+ (plausibility + privacy evidence)
POST /api/v1/datasets/{id}/release-override    – admin     (release a privacy-BLOCKED dataset, audited)
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth.dependencies import require_admin, require_reviewer_or_above
from api.auth.models import CurrentUser
from api.pagination import Page, envelope, page_params, paginate
from api.services import audit_service
from metadata_store.db import get_db
from metadata_store.models import SyntheticDataset

router = APIRouter(prefix="/api/v1/datasets", tags=["Datasets"])


@router.get("")
def list_datasets(
    release_status: str | None = None,
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    q = db.query(SyntheticDataset)
    if release_status:
        q = q.filter(SyntheticDataset.release_status == release_status.upper())
    total, rows = paginate(q.order_by(SyntheticDataset.created_at.desc()), page)
    return {"items": [{
        "dataset_id": d.public_id, "source_id": d.source_id, "source_table": d.source_table,
        "row_count": d.row_count, "release_status": d.release_status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in rows], **envelope(page, total)}


class ReleaseOverride(BaseModel):
    reason: str = Field(..., min_length=10, max_length=1000)


@router.get("/{dataset_id}/validation")
def dataset_validation(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    dataset = db.query(SyntheticDataset).filter(SyntheticDataset.public_id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Synthetic dataset not found")
    return {
        "dataset_id": dataset.public_id,
        "source_table": dataset.source_table,
        "release_status": dataset.release_status,
        "override_by": dataset.override_by,
        "override_reason": dataset.override_reason,
        "override_at": dataset.override_at.isoformat() if dataset.override_at else None,
        "validation": dataset.validation_report,
    }


@router.post("/{dataset_id}/release-override")
def override_release(
    dataset_id: str,
    payload: ReleaseOverride,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin()),
):
    """Release a dataset the privacy gate BLOCKED. Admin only; the reason and
    actor are stored on the dataset and in the append-only audit log."""
    dataset = db.query(SyntheticDataset).filter(SyntheticDataset.public_id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Synthetic dataset not found")
    if dataset.release_status != "BLOCKED":
        raise HTTPException(status_code=409, detail=f"Dataset is not blocked (status: {dataset.release_status}).")
    reason = payload.reason.strip()
    dataset.release_status = "OVERRIDDEN"
    dataset.override_by = user.username
    dataset.override_reason = reason
    dataset.override_at = datetime.utcnow()
    # record_audit commits the dataset change together with the audit entry.
    audit_service.record_audit(
        db, "Privacy Gate Override", user, "complete",
        f"Dataset {dataset.public_id} ({dataset.source_table}) released despite failed privacy checks: {reason[:300]}",
        source=dataset.source_table, source_type="Synthetic dataset")
    return {"dataset_id": dataset.public_id, "release_status": dataset.release_status,
            "override_by": dataset.override_by}
