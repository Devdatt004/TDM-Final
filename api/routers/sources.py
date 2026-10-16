"""
Source Registry API.

Endpoints
---------
POST   /api/v1/sources
GET    /api/v1/sources
GET    /api/v1/sources/{source_id}
PATCH  /api/v1/sources/{source_id}
DELETE /api/v1/sources/{source_id}
POST   /api/v1/sources/{source_id}/validate
GET    /api/v1/sources/{source_id}/tables
"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from credentials.resolver import validate_ref
from sqlalchemy.orm import Session

from api.auth.dependencies import (
    require_steward_or_admin,
    require_tester_or_above,
)
from api.auth.models import CurrentUser
from api.services import audit_service
from api.services.source_connector_service import (
    list_source_tables,
    validate_source_connection,
)
from api.pagination import Page, envelope, page_params, paginate
from metadata_store.db import get_db
from metadata_store.models import Source


router = APIRouter(
    prefix="/api/v1/sources",
    tags=["Source Registry"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=100)
    description: str | None = None

    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    schema_name: str | None = None

    credential_ref: str | None = None

    @field_validator("credential_ref")
    @classmethod
    def _reference_only(cls, value):
        # Only env:// or vault:// references; a pasted secret is refused, never stored.
        if value is None or not value.strip():
            return None
        return validate_ref(value)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    schema_name: str | None = None

    credential_ref: str | None = None
    status: str | None = None

    @field_validator("credential_ref")
    @classmethod
    def _reference_only(cls, value):
        # Only env:// or vault:// references; a pasted secret is refused, never stored.
        if value is None or not value.strip():
            return None
        return validate_ref(value)


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------


def _source_response(source: Source) -> dict:
    """
    Convert a Source model into a safe API response.

    IMPORTANT:
    Never return a plaintext password. The registry only exposes
    credential_ref.
    """

    return {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "description": source.description,
        "host": source.host,
        "port": source.port,
        "database_name": source.database_name,
        "schema_name": source.schema_name,
        "credential_ref": source.credential_ref,
        "status": source.status,
        "created_by": source.created_by,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "deleted_at": source.deleted_at,
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("")
def create_source(
    payload: SourceCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    existing = (
        db.query(Source)
        .filter(
            Source.name == payload.name,
            Source.status != "DELETED",
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Source '{payload.name}' already exists.",
        )

    source_id = str(uuid4())

    source = Source(
        id=source_id,
        name=payload.name.strip(),
        source_type=payload.source_type.strip().lower(),
        description=payload.description,
        host=payload.host.strip() if payload.host else None,
        port=payload.port,
        database_name=(
            payload.database_name.strip()
            if payload.database_name
            else None
        ),
        schema_name=(
            payload.schema_name.strip()
            if payload.schema_name
            else None
        ),
        credential_ref=(
            payload.credential_ref.strip()
            if payload.credential_ref
            else None
        ),
        status="ACTIVE",
        created_by=user.username,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    audit_service.record_audit(
        db,
        "Source Registry",
        user,
        "complete",
        f"Source '{source.name}' registered.",
        source=source.id,
        source_type=source.source_type,
    )

    return _source_response(source)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("")
def list_sources(
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    total, sources = paginate(
        db.query(Source)
        .filter(Source.status != "DELETED")
        .order_by(Source.created_at.desc()),
        page,
    )

    return {
        "sources": [
            _source_response(source)
            for source in sources
        ],
        "count": len(sources),
        **envelope(page, total),
    }


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------


@router.get("/{source_id}")
def get_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    source = (
        db.query(Source)
        .filter(Source.id == source_id)
        .first()
    )

    if source is None or source.status == "DELETED":
        raise HTTPException(
            status_code=404,
            detail="Source not found.",
        )

    return _source_response(source)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch("/{source_id}")
def update_source(
    source_id: str,
    payload: SourceUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    source = (
        db.query(Source)
        .filter(Source.id == source_id)
        .first()
    )

    if source is None or source.status == "DELETED":
        raise HTTPException(
            status_code=404,
            detail="Source not found.",
        )

    updates = payload.model_dump(exclude_unset=True)

    if "name" in updates and updates["name"]:
        duplicate = (
            db.query(Source)
            .filter(
                Source.name == updates["name"],
                Source.id != source.id,
                Source.status != "DELETED",
            )
            .first()
        )

        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"Source '{updates['name']}' already exists.",
            )

        updates["name"] = updates["name"].strip()

    if "source_type" in updates and updates["source_type"]:
        updates["source_type"] = updates["source_type"].strip().lower()

    for field in (
        "host",
        "database_name",
        "schema_name",
        "credential_ref",
    ):
        if field in updates and updates[field]:
            updates[field] = updates[field].strip()

    for field, value in updates.items():
        setattr(source, field, value)

    source.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(source)

    audit_service.record_audit(
        db,
        "Source Registry",
        user,
        "complete",
        f"Source '{source.name}' updated.",
        source=source.id,
        source_type=source.source_type,
    )

    return _source_response(source)


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------


@router.delete("/{source_id}")
def delete_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    source = (
        db.query(Source)
        .filter(Source.id == source_id)
        .first()
    )

    if source is None or source.status == "DELETED":
        raise HTTPException(
            status_code=404,
            detail="Source not found.",
        )

    source.status = "DELETED"
    source.deleted_at = datetime.utcnow()
    source.updated_at = datetime.utcnow()

    db.commit()

    audit_service.record_audit(
        db,
        "Source Registry",
        user,
        "complete",
        f"Source '{source.name}' soft-deleted.",
        source=source.id,
        source_type=source.source_type,
    )

    return {
        "id": source.id,
        "status": "DELETED",
    }


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

@router.post("/{source_id}/validate")
def validate_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    result = validate_source_connection(
        db=db,
        source_id=source_id,
    )

    audit_service.record_audit(
        db,
        "Source Registry",
        user,
        "complete" if result["valid"] else "failed",
        result["message"],
        source=source_id,
        source_type=result.get("connector"),
    )

    return result


# ---------------------------------------------------------------------------
# Table discovery
# ---------------------------------------------------------------------------


@router.get("/{source_id}/tables")
def list_tables_for_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    """List the tables that actually exist in the selected registered source.

    The source's own connector is used (ConnectorFactory), so the result is
    always that source's database - never a name lookup across databases.
    No credentials or connection details are returned.
    """
    source, tables = list_source_tables(db, source_id)
    return {
        "source_id": source.id,
        "source_name": source.name,
        "source_type": source.source_type,
        "tables": tables,
        "count": len(tables),
    }
