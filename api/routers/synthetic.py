"""
api/routers/synthetic.py

Synthetic data generation and download endpoints.

RBAC mapping
------------
POST /generate/{table_name}          – steward+ / tester+  (generate synthetic data)
                                       optional ?source_id=<registered source id>
GET  /generate/download/{dataset_id} – tester+             (download generated file)
GET  /generate/history               – reviewer+           (list datasets)
POST /mask/{table_name}              – steward+            (deterministic masking of real rows, Step 10)
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os

from metadata_store.db import get_db
from metadata_store.models import SyntheticDataset
from api.services import generation_service, audit_service, masking_service
from api.auth.dependencies import (
    require_tester_or_above,
    require_reviewer_or_above,
    require_steward_or_admin,
)
from api.auth.models import CurrentUser
from api.pagination import Page, page_params, paginate

router = APIRouter()


@router.post("/generate/{table_name}")
def generate_synthetic_data(
    table_name: str,
    rows: int = 50,
    purpose: str = "synthetic",
    source_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    try:
        return generation_service.generate_synthetic_data_flow(
            db, table_name, rows, purpose, user.username, source_id=source_id
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/mask/{table_name}")
def mask_table(
    table_name: str,
    rows: int = 50,
    source_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    # Reads real source rows, so steward+ (same as profiling) rather than tester+.
    try:
        return masking_service.mask_table(db, table_name, rows, user.username, source_id=source_id)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/generate/download/{dataset_id}")
def download_synthetic_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    dataset = db.query(SyntheticDataset).filter(
        SyntheticDataset.public_id == dataset_id
    ).first()
    if not dataset or not os.path.exists(dataset.file_path):
        raise HTTPException(status_code=404, detail="Synthetic dataset not found")
    if dataset.release_status == "BLOCKED":
        audit_service.record_audit(
            db, "File Download Blocked", user, "failed",
            f"{os.path.basename(dataset.file_path)} is blocked by the privacy release gate",
            source=dataset.source_table, source_type="Synthetic dataset")
        raise HTTPException(status_code=409, detail=(
            "This dataset failed the privacy release gate and cannot be downloaded. "
            "An admin can review the privacy report and record an override."))

    audit_service.record_audit(
        db,
        "File Download",
        user,
        "complete",
        os.path.basename(dataset.file_path),
        source=dataset.source_table,
        source_type="Synthetic dataset",
    )
    return FileResponse(
        dataset.file_path,
        media_type="text/csv",
        filename=os.path.basename(dataset.file_path),
    )


@router.get("/generate/history")
def synthetic_dataset_history(
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    _, datasets = paginate(db.query(SyntheticDataset).order_by(SyntheticDataset.created_at.desc()), page)
    return [
        {
            "dataset_id": d.public_id,
            "source_id": d.source_id,
            "source_table": d.source_table,
            "row_count": d.row_count,
            "created_at": d.created_at.isoformat(),
            "release_status": d.release_status,
        }
        for d in datasets
    ]

