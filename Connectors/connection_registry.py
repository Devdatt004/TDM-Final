"""
connection_registry.py

Remembers each signed-in user's active EXTERNAL database connection (Oracle /
MSSQL / PostgreSQL / MySQL) between requests, so after "Connect" the user can
pick a table and profile it without typing credentials again.

Deliberately IN MEMORY ONLY:
  - the password never touches disk or the metadata database;
  - it is dropped when the user signs out, after IDLE_MINUTES of no use, or
    when the server restarts (the user just clicks Connect again).

One active connection per user; connecting to another database replaces it.
"""

import os
import threading
from datetime import datetime, timedelta

IDLE_MINUTES = int(os.getenv("TDM_CONNECTION_IDLE_MINUTES", "60"))

_lock = threading.Lock()
_active = {}   # username -> connection info dict


def set_active(username: str, info: dict) -> None:
    info = dict(info, connected_at=datetime.utcnow(), last_used=datetime.utcnow())
    with _lock:
        _active[username] = info


def get_active(username: str):
    """The user's live connection (refreshing its idle timer), or None."""
    if not username:
        return None
    with _lock:
        info = _active.get(username)
        if info is None:
            return None
        if datetime.utcnow() - info["last_used"] > timedelta(minutes=IDLE_MINUTES):
            del _active[username]
            return None
        info["last_used"] = datetime.utcnow()
        return info


def clear_active(username: str) -> bool:
    with _lock:
        return _active.pop(username, None) is not None


def public_view(info: dict | None):
    """What the API may show the browser: everything EXCEPT the URL (it holds the password)."""
    if not info:
        return None
    return {
        "db_type": info["db_type"], "label": info["label"], "host": info["host"],
        "port": info["port"], "database": info["database"], "username": info["username"],
        "schema": info.get("schema"), "tables": info["tables"],
        "connected_at": info["connected_at"].isoformat() + "Z",
    }
