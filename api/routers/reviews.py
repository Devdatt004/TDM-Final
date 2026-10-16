"""Human review queue for classifications flagged by the classifier."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import update

from api.auth.dependencies import require_reviewer_or_above
from api.auth.models import CurrentUser
from api.services import audit_service
from metadata_store.db import get_db
from metadata_store.models import ClassificationResult, ClassificationReview, AnalysisRun

router = APIRouter(prefix="/api/v1/reviews", tags=["Human Review"])


class DecisionPayload(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)
    pattern_type: Optional[str] = Field(default=None, max_length=100)
    sensitivity: Optional[str] = Field(default=None, max_length=40)


def _serialize(review: ClassificationReview) -> dict:
    c = review.classification
    run = c.run if c else None
    return {
        "id": review.id,
        "classification_result_id": review.classification_result_id,
        "status": review.status,
        "source_id": c.source_id if c else None,
        "source_version": c.source_version if c else None,
        "run_id": c.run_id if c else None,
        "table_name": c.table_name if c else None,
        "column_name": c.column_name if c else None,
        "pattern_type": c.pattern_type if c else review.proposed_pattern_type,
        "pattern_confidence": c.pattern_confidence if c else None,
        "sensitivity": c.sensitivity if c else review.proposed_sensitivity,
        "sensitivity_confidence": c.sensitivity_confidence if c else None,
        "evidence": c.evidence if c else [],
        "detected_types": c.detected_types if c else [],
        "classification_status": c.classification_status if c else None,
        "proposed_pattern_type": review.proposed_pattern_type,
        "proposed_sensitivity": review.proposed_sensitivity,
        "final_pattern_type": review.final_pattern_type,
        "final_sensitivity": review.final_sensitivity,
        "reviewer_username": review.reviewer_username,
        "decision_reason": review.decision_reason,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "run_timestamp": run.run_timestamp.isoformat() if run and run.run_timestamp else None,
    }


def _load_review(db: Session, review_id: int) -> ClassificationReview:
    review = (
        db.query(ClassificationReview)
        .options(joinedload(ClassificationReview.classification).joinedload(ClassificationResult.run))
        .filter(ClassificationReview.id == review_id)
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail="Review request not found.")
    return review


@router.get("")
def list_reviews(
    status_filter: str = Query(default="PENDING", alias="status", pattern="^(PENDING|APPROVED|REJECTED|ALL)$"),
    source_id: Optional[str] = None,
    table_name: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    query = db.query(ClassificationReview).join(ClassificationResult).options(
        joinedload(ClassificationReview.classification).joinedload(ClassificationResult.run)
    )
    if status_filter != "ALL":
        query = query.filter(ClassificationReview.status == status_filter)
    if source_id:
        query = query.filter(ClassificationResult.source_id == source_id)
    if table_name:
        query = query.filter(ClassificationResult.table_name == table_name)
    total = query.count()
    items = query.order_by(ClassificationReview.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [_serialize(item) for item in items], "total": total, "limit": limit, "offset": offset}


@router.get("/{review_id}")
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    return _serialize(_load_review(db, review_id))


def _decide(review_id: int, payload: DecisionPayload, db: Session, user: CurrentUser, approve: bool):
    review = _load_review(db, review_id)
    if review.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Review has already been decided ({review.status}).")

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A decision reason is required.")
    classification = review.classification
    if not classification:
        raise HTTPException(status_code=409, detail="The linked classification no longer exists.")

    if approve:
        pattern_type = payload.pattern_type.strip().upper() if payload.pattern_type is not None else classification.pattern_type
        sensitivity = payload.sensitivity.strip().lower() if payload.sensitivity is not None else classification.sensitivity
        if payload.pattern_type is not None and not pattern_type:
            raise HTTPException(status_code=422, detail="Pattern type cannot be empty.")
        if sensitivity not in {"sensitive", "unknown"}:
            raise HTTPException(status_code=422, detail="Sensitivity must be 'sensitive' or 'unknown'.")
        classification.pattern_type = pattern_type
        classification.sensitivity = sensitivity
        classification.classification_status = "approved"
        classification.review_required = False
        new_status = "APPROVED"
        final_pattern_type = pattern_type
        final_sensitivity = sensitivity
        event = "Classification Review Approved"
    else:
        classification.classification_status = "rejected"
        # Keep review_required=True so downstream checks do not treat rejection as approval.
        classification.review_required = True
        new_status = "REJECTED"
        final_pattern_type = None
        final_sensitivity = None
        event = "Classification Review Rejected"

    reviewed_at = datetime.utcnow()
    # Compare-and-set protects against two reviewers deciding the same item.
    # Do not mutate the ORM review instance before this update: autoflush would
    # otherwise write its new status before the PENDING predicate is checked.
    try:
        changed = db.query(ClassificationReview).filter(
            ClassificationReview.id == review.id,
            ClassificationReview.status == "PENDING",
        ).update({
            "status": new_status,
            "final_pattern_type": final_pattern_type,
            "final_sensitivity": final_sensitivity,
            "reviewer_user_id": user.user_id,
            "reviewer_username": user.username,
            "decision_reason": reason,
            "reviewed_at": reviewed_at,
        }, synchronize_session=False)
        if changed != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Review was already decided by another request.")
        # record_audit commits the pending review/classification updates together
        # with the audit entry; its failure rolls the transaction back.
        audit_service.record_audit(
            db, event, user, "complete",
            f"Review {review.id} for classification {classification.id}: {reason[:300]}",
            source=f"classification-review:{review.id}", source_type="Classification Review",
        )
        db.refresh(review)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not persist the review decision and audit event.") from exc
    return _serialize(review)


@router.post("/{review_id}/approve")
def approve_review(
    review_id: int,
    payload: DecisionPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    return _decide(review_id, payload, db, user, True)


@router.post("/{review_id}/reject")
def reject_review(
    review_id: int,
    payload: DecisionPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    return _decide(review_id, payload, db, user, False)
