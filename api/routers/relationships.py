"""
api/routers/relationships.py

Data Relationship Validation (formerly "Referential Integrity"): relationship
discovery and related-dataset generation.

A relationship is either DECLARED (a foreign-key constraint in the source database)
or UNDECLARED (a logical link nobody declared; suggested, then confirmed by a steward).
Relationship endpoints work on one source domain at a time (?domain=healthcare|banking).

RBAC mapping
------------
GET  /domains                    – reviewer+ (list built-in source domains)
GET  /relationships              – reviewer+ (read relationships)
POST /relationships/refresh      – steward+  (run discovery)
GET  /relationships/suggestions  – steward+  (find undeclared relationships)
POST /relationships              – steward+  (confirm an undeclared relationship)
DELETE /relationships/{id}       – admin     (delete — admin only, data-governance risk)
POST /generate-related           – tester+   (generate datasets whose relationships validate)
GET  /integrity/runs             – reviewer+ (read integrity run history)
GET  /integrity/runs/{run_id}    – reviewer+
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from metadata_store.db import get_db
from api.services import relationship_service
from api.auth.dependencies import (
    require_admin,
    require_steward_or_admin,
    require_reviewer_or_above,
    require_tester_or_above,
)
from api.auth.models import CurrentUser

router = APIRouter()


class RelationshipCreate(BaseModel):
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str


class RelatedGenerateRequest(BaseModel):
    tables: list[str]
    row_counts: dict[str, int] = {}
    ensure_parent_coverage: bool = True
    seed: int | None = None


@router.get("/domains")
def list_domains(user: CurrentUser = Depends(require_reviewer_or_above())):
    return relationship_service.list_domains()


@router.get("/relationships")
def get_relationships(
    refresh: bool = False,
    domain: str = "healthcare",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    try:
        return relationship_service.get_relationships(db, refresh, domain)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Relationship discovery failed: {e}")


@router.post("/relationships/refresh")
def refresh_relationships(
    domain: str = "healthcare",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    try:
        return relationship_service.refresh_relationships(db, user.username, domain)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Relationship discovery failed: {e}")


@router.get("/relationships/suggestions")
def relationship_suggestions(
    domain: str = "healthcare",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    try:
        return relationship_service.get_relationship_suggestions(db, user.username, domain)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not look for undeclared relationships: {e}",
        )


@router.post("/relationships")
def add_relationship(
    payload: RelationshipCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    try:
        return relationship_service.add_relationship(
            db, payload.child_table, payload.child_column,
            payload.parent_table, payload.parent_column,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/relationships/{relationship_id}")
def delete_relationship(
    relationship_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin()),
):
    try:
        relationship_service.delete_relationship(db, relationship_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": relationship_id}


@router.post("/generate-related")
def generate_related_tables(
    payload: RelatedGenerateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    try:
        return relationship_service.generate_related_tables_flow(
            db, payload.tables, payload.row_counts,
            payload.ensure_parent_coverage, payload.seed, user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Related generation failed: {e}")


@router.get("/integrity/runs")
def integrity_runs(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    return relationship_service.get_integrity_runs(db)


@router.get("/integrity/runs/{run_id}")
def integrity_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    try:
        return relationship_service.get_integrity_run(db, run_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
