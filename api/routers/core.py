"""
api/routers/core.py

Core public and protected endpoints.

RBAC mapping
------------
GET  /health         – public (infrastructure health check)
GET  /tables         – tester+   (need to know what sources exist)
GET  /runs           – reviewer+ (see activity history)
GET  /summary        – reviewer+ (dashboard summary stats)
POST /agent/ask      – reviewer+ (query agent on existing data)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import os

from metadata_store.db import get_db
from metadata_store.models import AnalysisRun, ActivityLog
from metadata_store import activity as act
from api.services import source_service
from api.auth.dependencies import get_current_user, require_tester_or_above, require_reviewer_or_above
from api.auth.models import CurrentUser
from pydantic import BaseModel
from agents import query_agent

router = APIRouter()


@router.get("/health")
def health():
    """Public health-check — no auth required."""
    return {"status": "ok", "service": "tdm-platform-api"}


@router.get("/tables")
def list_tables(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    sources = source_service.list_all_sources(db, user.username)
    return {"tables": [x["name"] for x in sources], "sources": sources}


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    entries = (
        db.query(ActivityLog)
        .filter(ActivityLog.activity.notin_(act.AUDIT_ACTIVITIES))
        .order_by(ActivityLog.created_at.desc()).limit(100).all()
    )
    return [
        {
            "log_id": e.id,
            "activity": e.activity,
            "user": e.username or "-",
            "source": e.source or "-",
            "type": e.source_type or "-",
            "fields": e.fields,
            "status": act.status_of(e),
            "message": e.message,
            "run_timestamp": act.iso_utc(e.created_at),
        }
        for e in entries
    ]


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    distinct_tables_scanned = db.query(func.count(func.distinct(AnalysisRun.source_table))).scalar() or 0
    total_fields = db.query(func.sum(AnalysisRun.total_fields)).scalar() or 0
    total_high_confidence = db.query(func.sum(AnalysisRun.high_confidence_count)).scalar() or 0
    total_needs_review = db.query(func.sum(AnalysisRun.needs_review_count)).scalar() or 0

    latest = (
        db.query(ActivityLog)
        .filter(ActivityLog.activity.notin_(act.AUDIT_ACTIVITIES))
        .order_by(ActivityLog.created_at.desc()).first()
    )
    latest_activity = None
    if latest:
        latest_activity = {
            "activity": latest.activity,
            "user": latest.username or "-",
            "source": latest.source,
            "status": act.status_of(latest),
            "message": latest.message,
            "at": act.iso_utc(latest.updated_at or latest.created_at),
        }

    return {
        "tables_scanned": distinct_tables_scanned,
        "fields_classified": total_fields,
        "high_confidence": total_high_confidence,
        "needs_review": total_needs_review,
        "latest_activity": latest_activity,
    }


class AgentQuestion(BaseModel):
    question: str
    table_name: str | None = None


@router.post("/agent/ask")
def agent_ask(
    payload: AgentQuestion,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    return query_agent.ask(db, payload.question, payload.table_name)
