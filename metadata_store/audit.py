"""
metadata_store/audit.py

Immutable, append-only audit log with hash-chain integrity.

Public API
----------
record(db, event, username, ...)   – append one entry (raises on failure)
install_guards(engine)             – install SQLite triggers blocking UPDATE/DELETE
verify_chain(db)                   – recompute chain and report first broken row

Step-3 changes
--------------
1. **Concurrency-safe chaining**: a module-level threading.Lock serialises
   all writes to the chain head.  Under the SQLite WAL model (single-writer)
   this prevents two concurrent requests from reading the same prev_hash and
   producing a broken chain.

   SQLite limitation note: this lock is in-process only.  If multiple
   uvicorn worker processes share the same SQLite file (e.g. --workers > 1),
   each process has its own lock instance and concurrent writes from different
   processes could still race.  For single-worker deployments (the typical
   SQLite MVP) this is fully safe.  Moving to Postgres + a serialisable
   transaction or SELECT FOR UPDATE removes the limitation.

2. **Raises on audit failure**: previously exceptions were silently swallowed.
   Now record() raises AuditError so callers know when an audit write failed.
   Sensitive operations (generate, upload, connect) must let this propagate
   rather than claiming success while missing an audit record.

3. **Actor fields**: record() now accepts user_id and role so the full
   authenticated identity is captured.

Security: this module never logs passwords, tokens, keys, or raw PHI.
Log identifiers and metadata only.
"""

import hashlib
import logging
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from metadata_store.models import AuditLog

log = logging.getLogger(__name__)

# ── Concurrency guard ─────────────────────────────────────────────────────
# Serialises access to the chain head within a single process.
# See module docstring for the multi-process limitation note.
_chain_lock = threading.Lock()


# ── Custom exception ───────────────────────────────────────────────────────

class AuditError(RuntimeError):
    """Raised when an audit record cannot be persisted.

    Callers that treat audit as mandatory must let this propagate.
    Callers that truly want best-effort auditing (background tasks)
    may catch it explicitly and log a warning.
    """


# ── Hashing ───────────────────────────────────────────────────────────────

def _hash(prev_hash: str, entry: AuditLog) -> str:
    """Derive the entry_hash from the previous hash + this row's fields.

    The hash covers all audit-meaningful columns so that any out-of-band
    edit to any field is detectable by verify_chain().
    """
    parts = [
        prev_hash,
        entry.created_at.isoformat() if entry.created_at else "",
        entry.username or "",
        entry.user_id or "",
        entry.role or "",
        entry.event or "",
        entry.target or "",
        entry.target_type or "",
        entry.status or "",
        entry.detail or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# ── Core write ────────────────────────────────────────────────────────────

def record(
    db,
    event: str,
    username: str,
    status: str = "complete",
    detail: Optional[str] = None,
    target: Optional[str] = None,
    target_type: Optional[str] = None,
    user_id: Optional[str] = None,
    role: Optional[str] = None,
) -> AuditLog:
    """Append one audit entry to the hash chain.

    This function is intentionally NOT silent on failure (Step-3 hardening).
    Raises AuditError if the record cannot be persisted.

    Parameters
    ----------
    db          : SQLAlchemy session
    event       : what happened, e.g. "DB Connection", "File Download"
    username    : human-readable actor name
    status      : "complete" | "failed" | "denied"
    detail      : free-text detail — never include secrets/PHI here
    target      : resource identifier (table name, file name, etc.)
    target_type : resource category ("Database", "Synthetic dataset", …)
    user_id     : stable actor id (JWT sub or "dev:<username>")
    role        : comma-separated roles held by the actor at the time
    """
    with _chain_lock:
        try:
            now = datetime.utcnow()
            last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
            prev_hash = last.entry_hash if last else ""

            entry = AuditLog(
                created_at=now,
                username=username,
                user_id=user_id,
                role=role,
                event=event,
                target=target,
                target_type=target_type,
                status=status,
                detail=(detail or "")[:500],
                prev_hash=prev_hash,
            )
            entry.entry_hash = _hash(prev_hash, entry)
            db.add(entry)
            db.commit()
            log.debug(
                "[Audit] event=%s user=%s user_id=%s status=%s target=%s",
                event, username, user_id, status, target,
            )
            return entry
        except Exception as exc:
            db.rollback()
            log.error(
                "[Audit] FAILED to write audit record: event=%s user=%s error=%s",
                event, username, exc,
            )
            raise AuditError(
                f"Audit record for event={event!r} user={username!r} "
                f"could not be persisted: {exc}"
            ) from exc


# ── Triggers ──────────────────────────────────────────────────────────────

def install_guards(engine) -> None:
    """Block UPDATE and DELETE on audit_log at the database level.

    SQLite implementation uses triggers; Postgres should revoke the
    UPDATE/DELETE privileges from the application role instead.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        for op in ("UPDATE", "DELETE"):
            conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS audit_log_no_{op.lower()} "
                f"BEFORE {op} ON audit_log "
                f"BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
            ))


# ── Verification ──────────────────────────────────────────────────────────

def verify_chain(db) -> dict:
    """Recompute the hash chain and return the first broken link, if any.

    Returns
    -------
    {"intact": True, "first_bad_id": None}         – chain is valid
    {"intact": False, "first_bad_id": <int>}        – first corrupt row id
    """
    prev = ""
    for e in db.query(AuditLog).order_by(AuditLog.id.asc()).yield_per(500):
        expected = _hash(prev, e)
        if e.prev_hash != prev or e.entry_hash != expected:
            return {"intact": False, "first_bad_id": e.id}
        prev = e.entry_hash
    return {"intact": True, "first_bad_id": None}
