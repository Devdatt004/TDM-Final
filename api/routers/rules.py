"""Step 7 - Rule Registry API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth.dependencies import require_steward_or_admin, require_tester_or_above
from api.auth.models import CurrentUser
from api.services import audit_service
from api.services.rule_service import (
    create_rule, get_rule, get_rule_version, list_rule_versions,
    list_rules, set_rule_status, update_rule,
)
from metadata_store.db import get_db
from metadata_store.models import Rule, RuleVersion

router = APIRouter(prefix="/api/v1/rules", tags=["Rule Registry"])


class RuleCreate(BaseModel):
    class Config:
        extra = "forbid"
    rule_key: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    rule_type: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=4000)
    definition: dict[str, Any]


class RuleUpdate(BaseModel):
    class Config:
        extra = "forbid"
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    definition: dict[str, Any] | None = None
    change_summary: str | None = Field(default=None, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)


class RuleVersionResponse(BaseModel):
    id: str
    rule_id: str
    version_number: int
    definition: dict[str, Any]
    change_summary: str | None
    created_by: str | None
    created_at: Any


def _version_response(version: RuleVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "rule_id": version.rule_id,
        "version_number": version.version_number,
        "definition": version.definition,
        "change_summary": version.change_summary,
        "created_by": version.created_by,
        "created_at": version.created_at,
    }


def _rule_response(db: Session, rule: Rule, include_definition: bool = True) -> dict[str, Any]:
    body = {
        "id": rule.id,
        "rule_key": rule.rule_key,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "description": rule.description,
        "status": rule.status,
        "current_version": rule.current_version,
        "created_by": rule.created_by,
        "updated_by": rule.updated_by,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
        "deactivated_at": rule.deactivated_at,
    }
    if include_definition:
        version = db.query(RuleVersion).filter(
            RuleVersion.rule_id == rule.id,
            RuleVersion.version_number == rule.current_version,
        ).first()
        body["definition"] = version.definition if version else None
    return body


@router.post("")
def create_rule_endpoint(
    payload: RuleCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    rule = create_rule(
        db, rule_key=payload.rule_key, name=payload.name, rule_type=payload.rule_type,
        definition=payload.definition, description=payload.description, created_by=user.username,
    )
    audit_service.record_audit(
        db, "Rule Created", user, "complete", f"Rule '{rule.rule_key}' created at version 1.",
        source=rule.id, source_type="Rule Registry",
    )
    return _rule_response(db, rule)


@router.get("")
def list_rules_endpoint(
    rule_type: str | None = None,
    status: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    rows = list_rules(db, rule_type=rule_type, status=status, search=search)
    return {"rules": [_rule_response(db, row) for row in rows], "count": len(rows)}


@router.get("/{rule_id}")
def get_rule_endpoint(
    rule_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    return _rule_response(db, get_rule(db, rule_id))


@router.patch("/{rule_id}")
def update_rule_endpoint(
    rule_id: str,
    payload: RuleUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    changes = (
        payload.model_dump(exclude_unset=True)
        if hasattr(payload, "model_dump")
        else payload.dict(exclude_unset=True)
    )
    if "definition" in changes and changes["definition"] is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="definition cannot be null.")
    if not any(key in changes for key in ("name", "description", "definition")):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Provide at least one field to update.")
    old_rule = get_rule(db, rule_id)
    old_version = old_rule.current_version
    rule = update_rule(db, rule_id=rule_id, updated_by=user.username, **changes)
    event = "Rule Definition Version Created" if rule.current_version > old_version else "Rule Metadata Updated"
    audit_service.record_audit(
        db, event, user, "complete",
        f"Rule '{rule.rule_key}' updated; current version is {rule.current_version}.",
        source=rule.id, source_type="Rule Registry",
    )
    return _rule_response(db, rule)


@router.get("/{rule_id}/versions")
def list_rule_versions_endpoint(
    rule_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    versions = list_rule_versions(db, rule_id)
    return {"versions": [_version_response(v) for v in versions], "count": len(versions)}


@router.get("/{rule_id}/versions/{version}")
def get_rule_version_endpoint(
    rule_id: str,
    version: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_tester_or_above()),
):
    return _version_response(get_rule_version(db, rule_id, version))


@router.post("/{rule_id}/activate")
def activate_rule_endpoint(
    rule_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    rule = set_rule_status(db, rule_id=rule_id, active=True, updated_by=user.username)
    audit_service.record_audit(
        db, "Rule Activated", user, "complete", f"Rule '{rule.rule_key}' activated.",
        source=rule.id, source_type="Rule Registry",
    )
    return _rule_response(db, rule)


@router.post("/{rule_id}/deactivate")
def deactivate_rule_endpoint(
    rule_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    rule = set_rule_status(db, rule_id=rule_id, active=False, updated_by=user.username)
    audit_service.record_audit(
        db, "Rule Deactivated", user, "complete", f"Rule '{rule.rule_key}' deactivated.",
        source=rule.id, source_type="Rule Registry",
    )
    return _rule_response(db, rule)
