"""
api/services/audit_service.py

Thin facade over metadata_store.audit and metadata_store.activity.

Step-3 changes
--------------
- record_audit() now accepts a CurrentUser (or a plain username string for
  backward compat with background/system callers) and writes user_id + role
  into the audit record so the full actor identity is captured.
- Audit failures propagate (AuditError) — callers for sensitive operations
  should let them surface rather than claiming success with no audit trail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union
from sqlalchemy.orm import Session

from metadata_store import activity as act
from metadata_store import audit
from metadata_store.audit import AuditError  # re-export for callers

if TYPE_CHECKING:
    from api.auth.models import CurrentUser


def log_activity_start(
    db: Session,
    activity_name: str,
    source: str,
    source_type: str,
    user: str,
):
    return act.log_start(
        db, activity_name, source=source, source_type=source_type, user=user
    )


def log_activity_finish(
    db: Session,
    entry,
    status: str,
    message: str,
    fields: Optional[int] = None,
    file_path: Optional[str] = None,
):
    act.log_finish(db, entry, status, message, fields=fields, file_path=file_path)


def record_audit(
    db: Session,
    activity: str,
    actor: Union[str, "CurrentUser"],
    status: str,
    message: str,
    source: str = "portal",
    source_type: str = "Operational",
) -> None:
    """Write one audit record.

    ``actor`` may be:
    - a ``CurrentUser`` instance (from an authenticated HTTP request)
    - a plain string (legacy / background callers, e.g. "system")

    Raises AuditError if the record cannot be persisted.
    """
    # Import here to avoid circular imports at module load time
    try:
        from api.auth.models import CurrentUser as _CU
        if isinstance(actor, _CU):
            username = actor.username
            user_id = actor.user_id
            role = ",".join(actor.roles) if actor.roles else None
        else:
            username = str(actor)
            user_id = None
            role = None
    except ImportError:
        username = str(actor)
        user_id = None
        role = None

    audit.record(
        db,
        event=activity,
        username=username,
        status=status,
        detail=message,
        target=source,
        target_type=source_type,
        user_id=user_id,
        role=role,
    )


def verify_audit_chain(db: Session) -> dict:
    return audit.verify_chain(db)

def verify_chain(db: Session) -> dict:
    return audit.verify_chain(db)


def purge_old_logs(db: Session) -> int:
    return act.purge_old_logs(db)
