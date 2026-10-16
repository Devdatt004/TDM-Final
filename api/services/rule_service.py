"""Step 7: Rule Registry business logic.

This module manages rule metadata and immutable definition snapshots. It does
not execute the rules; execution engines are intentionally out of scope.
"""
from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from metadata_store.models import Rule, RuleVersion

SUPPORTED_RULE_TYPES = {
    "CLASSIFICATION",
    "DATA_QUALITY",
    "DATA_RELATIONSHIP_VALIDATION",
    "REFERENTIAL_INTEGRITY",      # original name - kept so existing rules stay valid
    "SYNTHETIC_DATA",
    "PRIVACY",
    "PLAUSIBILITY",               # Step 12 - declarative domain plausibility checks
}
ACTIVE = "ACTIVE"
INACTIVE = "INACTIVE"
DRAFT = "DRAFT"
VALID_STATUSES = {ACTIVE, INACTIVE, DRAFT}
_RULE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,99}$")
_FORBIDDEN_DEFINITION_KEYS = {
    "password", "passwd", "secret", "client_secret", "api_key",
    "apikey", "access_token", "refresh_token", "private_key",
}


def _validate_key(rule_key: str) -> str:
    value = (rule_key or "").strip()
    if not _RULE_KEY_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="rule_key must be 2-100 characters and contain only letters, numbers, '.', '_', ':', or '-'.",
        )
    return value


def _validate_type(rule_type: str) -> str:
    value = (rule_type or "").strip().upper()
    if value not in SUPPORTED_RULE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported rule_type. Supported types: {', '.join(sorted(SUPPORTED_RULE_TYPES))}.",
        )
    return value


def _validate_definition(definition: dict[str, Any], rule_type: str | None = None) -> dict[str, Any]:
    if not isinstance(definition, dict) or not definition:
        raise HTTPException(status_code=422, detail="definition must be a non-empty JSON object.")
    if rule_type == "PLAUSIBILITY":
        from plausibility.rules import RuleDefinitionError, parse
        try:
            parse(definition)
        except RuleDefinitionError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid plausibility rule: {exc}") from exc

    def inspect(value: Any, path: str = "definition") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in _FORBIDDEN_DEFINITION_KEYS:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Secrets are not allowed in rule definitions (field: {path}.{key}).",
                    )
                inspect(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                inspect(nested, f"{path}[{index}]")
        elif not (value is None or isinstance(value, (str, int, float, bool))):
            raise HTTPException(status_code=422, detail="definition must contain JSON-compatible values only.")

    inspect(definition)
    return definition


def _handle_integrity_error(db: Session, exc: IntegrityError, detail: str) -> None:
    db.rollback()
    raise HTTPException(status_code=409, detail=detail) from exc


def create_rule(
    db: Session,
    *,
    rule_key: str,
    name: str,
    rule_type: str,
    definition: dict[str, Any],
    description: str | None,
    created_by: str,
) -> Rule:
    key = _validate_key(rule_key)
    if not (name or "").strip():
        raise HTTPException(status_code=422, detail="name cannot be blank.")
    normalized_type = _validate_type(rule_type)
    valid_definition = _validate_definition(definition, normalized_type)

    if db.query(Rule).filter(Rule.rule_key == key).first():
        raise HTTPException(status_code=409, detail=f"Rule key '{key}' already exists.")

    now = datetime.utcnow()
    rule = Rule(
        id=str(uuid4()), rule_key=key, name=name.strip(), rule_type=normalized_type,
        description=description, status=DRAFT, current_version=1,
        created_by=created_by, updated_by=created_by, created_at=now, updated_at=now,
    )
    version = RuleVersion(
        id=str(uuid4()), rule_id=rule.id, version_number=1,
        definition=valid_definition, change_summary="Initial rule definition",
        created_by=created_by, created_at=now,
    )
    db.add_all([rule, version])
    try:
        db.commit()
        db.refresh(rule)
        return rule
    except IntegrityError as exc:
        _handle_integrity_error(db, exc, f"Rule key '{key}' already exists or violates a registry constraint.")


def get_rule(db: Session, rule_id: str) -> Rule:
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return rule


def list_rules(
    db: Session,
    *,
    rule_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[Rule]:
    query = db.query(Rule)
    if rule_type:
        query = query.filter(Rule.rule_type == _validate_type(rule_type))
    if status:
        normalized_status = status.strip().upper()
        if normalized_status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail="status must be DRAFT, ACTIVE, or INACTIVE.")
        query = query.filter(Rule.status == normalized_status)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter((Rule.rule_key.ilike(term)) | (Rule.name.ilike(term)))
    return query.order_by(Rule.created_at.desc(), Rule.rule_key.asc()).all()


def get_rule_version(db: Session, rule_id: str, version_number: int) -> RuleVersion:
    get_rule(db, rule_id)
    version = db.query(RuleVersion).filter(
        RuleVersion.rule_id == rule_id,
        RuleVersion.version_number == version_number,
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Rule version not found.")
    return version


def list_rule_versions(db: Session, rule_id: str) -> list[RuleVersion]:
    get_rule(db, rule_id)
    return db.query(RuleVersion).filter(
        RuleVersion.rule_id == rule_id
    ).order_by(RuleVersion.version_number.desc()).all()


def update_rule(
    db: Session,
    *,
    rule_id: str,
    updated_by: str,
    name: str | None = None,
    description: str | None = None,
    definition: dict[str, Any] | None = None,
    change_summary: str | None = None,
    expected_version: int | None = None,
) -> Rule:
    rule = db.query(Rule).filter(Rule.id == rule_id).with_for_update().first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    if rule.status == INACTIVE:
        raise HTTPException(status_code=409, detail="Inactive rules cannot be edited; create or activate an appropriate version first.")
    if definition is not None and expected_version is None:
        raise HTTPException(
            status_code=422,
            detail="expected_version is required when updating a rule definition.",
        )
    if expected_version is not None and expected_version != rule.current_version:
        raise HTTPException(status_code=409, detail="Rule version conflict. Refresh the rule and retry.")

    if name is not None:
        if not name.strip():
            raise HTTPException(status_code=422, detail="name cannot be blank.")
        rule.name = name.strip()
    if description is not None:
        rule.description = description

    if definition is not None:
        valid_definition = _validate_definition(definition, rule.rule_type)
        current = db.query(RuleVersion).filter(
            RuleVersion.rule_id == rule.id,
            RuleVersion.version_number == rule.current_version,
        ).first()
        if current is None:
            raise HTTPException(status_code=500, detail="Current rule version is missing.")
        if current.definition != valid_definition:
            now = datetime.utcnow()
            next_version = rule.current_version + 1
            db.add(RuleVersion(
                id=str(uuid4()), rule_id=rule.id, version_number=next_version,
                definition=valid_definition,
                change_summary=(change_summary or "Rule definition updated").strip()[:1000],
                created_by=updated_by, created_at=now,
            ))
            rule.current_version = next_version

    rule.updated_by = updated_by
    rule.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(rule)
        return rule
    except IntegrityError as exc:
        _handle_integrity_error(db, exc, "Rule update conflicted with another update. Refresh and retry.")


def set_rule_status(db: Session, *, rule_id: str, active: bool, updated_by: str) -> Rule:
    rule = db.query(Rule).filter(Rule.id == rule_id).with_for_update().first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")

    now = datetime.utcnow()
    if active:
        if rule.status == ACTIVE:
            raise HTTPException(status_code=409, detail="Rule is already active.")
        rule.status = ACTIVE
        rule.deactivated_at = None
    else:
        if rule.status != ACTIVE:
            raise HTTPException(status_code=409, detail="Only active rules can be deactivated.")
        rule.status = INACTIVE
        rule.deactivated_at = now

    rule.updated_by = updated_by
    rule.updated_at = now
    db.commit()
    db.refresh(rule)
    return rule
