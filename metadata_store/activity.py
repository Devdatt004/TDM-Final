"""
metadata_store/activity.py

Everything about "what is the platform doing / who is using it":

  - activity logging   (log_start / log_finish - every entry records WHICH
                        portal user performed it)
  - log retention      (purge_old_logs - logs older than N days are deleted)
  - user presence      (touch_user / presence_stats - for signed-in users)

Kept out of api/main.py so the endpoints stay short and this logic can be
tested on its own.
"""

import os
from datetime import datetime, timedelta


from metadata_store.models import ActivityLog, AnalysisRun

# ---- Retention -------------------------------------------------------
# Logs older than this many days are deleted automatically (checked at
# startup and then every LOG_PURGE_INTERVAL_SECONDS). Override without
# touching code:  set TDM_LOG_RETENTION_DAYS=10
LOG_RETENTION_DAYS = int(os.getenv("TDM_LOG_RETENTION_DAYS", "5"))
LOG_PURGE_INTERVAL_SECONDS = 3600

# Housekeeping/audit entries are kept out of the dashboard's Recent
# activity / Recent runs and activity counters. Authentication is not part
# of this deployment, so the list is intentionally empty.
AUDIT_ACTIVITIES = ()

# Shown as the user for jobs the platform runs by itself (e.g. log cleanup).
SYSTEM_USER = "system"

# In-memory record of the last cleanup (resets when the server restarts,
# but the cleanup itself runs again at every startup).
purge_state = {"last_purge_at": None, "last_purge_deleted": 0}


# A job still "running" after this long (e.g. the server restarted mid-job) is
# shown as "interrupted" instead of running forever.
STALE_RUNNING_MINUTES = 10


def status_of(entry):
    if entry.status == "running":
        touched = entry.updated_at or entry.created_at
        if touched and datetime.utcnow() - touched > timedelta(minutes=STALE_RUNNING_MINUTES):
            return "interrupted"
    return entry.status


def iso_utc(dt):
    """Naive-UTC datetime -> ISO string with a trailing Z, so the browser
    converts it to the viewer's local time correctly (without the Z, JS
    would treat it as already-local and show the wrong hour)."""
    return dt.isoformat() + "Z" if dt else None


# ---------------------------------------------------------------------
# Activity logging
# ---------------------------------------------------------------------

def log_start(db, activity, source=None, source_type=None, user=None):
    """`user` is the actor performing the activity."""
    entry = ActivityLog(
        activity=activity, source=source, source_type=source_type, username=user,
        status="running", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_finish(db, entry, status, message=None, fields=None, file_path=None):
    """Mark an activity complete/failed. Never raises - a logging problem
    must not turn a successful operation into an error."""
    try:
        db.rollback()  # clear any half-finished transaction from the caller
        entry = db.merge(entry)
        entry.status = status
        entry.message = (message or "")[:500]
        if fields is not None:
            entry.fields = fields
        if file_path:
            entry.file_path = file_path
        entry.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()


def backfill_from_runs(db):
    """One-time: if the activity log is empty but earlier profiling runs
    exist (from before this feature), show those runs in Recent runs too -
    only those inside the retention window, since older logs would be
    purged straight away."""
    if db.query(ActivityLog).count() > 0:
        return
    cutoff = datetime.utcnow() - timedelta(days=LOG_RETENTION_DAYS)
    runs = db.query(AnalysisRun).filter(AnalysisRun.run_timestamp >= cutoff).all()
    for r in runs:
        db.add(ActivityLog(
            activity="Profiling", source=r.source_table, source_type="DB Table",
            fields=r.total_fields, status=r.status or "complete",
            message="Imported from earlier run history",
            created_at=r.run_timestamp, updated_at=r.run_timestamp,
        ))
    db.commit()


# ---------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------

def purge_old_logs(db, days=None):
    """Delete activity-log rows older than `days` (default: the retention
    setting). Only LOG ENTRIES are removed - uploaded files, generated
    output files and profiling results are left alone. Returns the number
    of rows deleted."""
    days = LOG_RETENTION_DAYS if days is None else days
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = db.query(ActivityLog).filter(ActivityLog.created_at < cutoff).delete()
    db.commit()
    purge_state["last_purge_at"] = datetime.utcnow()
    purge_state["last_purge_deleted"] = deleted
    if deleted:
        log_finish(db, log_start(db, "Log Cleanup", source="activity_log", user=SYSTEM_USER),
                   "complete", f"Deleted {deleted} log entries older than {days} days")
    return deleted
