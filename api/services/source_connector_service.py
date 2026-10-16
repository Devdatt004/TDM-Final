"""
Source Registry -> connector bridge.

One place turns a registered ``Source`` row into a live connector, using the
existing ``ConnectorFactory`` / ``DBConnector`` contracts. Validation, table
discovery, profiling and synthetic generation all go through it, so every
operation talks to the SELECTED source's own database - never to a database
resolved by table name.

Credentials and connection URLs are never returned from this module.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from Connectors.factory import ConnectorFactory
from Connectors.db_connector import DB_TYPES, build_connection_url
from credentials.env_provider import EnvironmentCredentialProvider
from metadata_store.models import Source

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SourceConnectionError(Exception):
    """Raised when a source cannot be turned into a connector.

    ``code`` is "unsupported" (bad source type) or "config" (incomplete or
    unusable configuration). ``message`` is always safe to show to a user.
    """

    def __init__(self, message: str, code: str = "config"):
        super().__init__(message)
        self.message = message
        self.code = code


def _allowed_hosts() -> set[str]:
    raw = os.getenv("TDM_ALLOWED_DB_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _sqlite_url(database_name: str) -> str:
    """Build the SQLite URL for a registered file path.

    Relative paths are tried against the working directory first (the
    historical behaviour), then the data directory and the project root, so
    the platform works no matter where uvicorn is started from. A missing
    file is an error - SQLite would otherwise silently create an empty one.
    """
    raw = database_name.strip()
    if raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///"):]
    if raw in ("", ":memory:"):
        raise SourceConnectionError("SQLite source requires a database file path.")

    path = Path(raw)
    if not path.is_absolute() and not path.exists():
        data_dir = os.getenv("TDM_DATA_DIR")
        for base in ([Path(data_dir)] if data_dir else []) + [_PROJECT_ROOT]:
            if (base / path).exists():
                path = base / path
                break
    if not path.is_file():
        raise SourceConnectionError("SQLite database file was not found.")
    return f"sqlite:///{path.as_posix()}"


def build_source_connector(source: Source):
    """Return an UNCONNECTED connector for a registered source."""
    source_type = (source.source_type or "").strip().lower()
    if source_type not in DB_TYPES:
        raise SourceConnectionError(
            f"Unsupported source type: {source.source_type}", code="unsupported")

    if source_type == "sqlite":
        if not source.database_name:
            raise SourceConnectionError("SQLite source requires a database path.")
        return ConnectorFactory.create(
            source_type=source_type, connection_url=_sqlite_url(source.database_name))

    if not source.host:
        raise SourceConnectionError("Database host is required.")
    if not source.database_name:
        raise SourceConnectionError("Database name is required.")
    allowed = _allowed_hosts()
    if not allowed:
        raise SourceConnectionError("Database host allow-list is not configured.")
    if source.host.lower() not in allowed:
        raise SourceConnectionError("Database host is not on the allowed list.")
    if not source.credential_ref:
        raise SourceConnectionError("Credential reference is required.")
    try:
        credentials = EnvironmentCredentialProvider().resolve(source.credential_ref)
    except Exception:
        raise SourceConnectionError("Unable to resolve source credentials.")

    url = build_connection_url(
        db_type=source_type,
        host=source.host,
        port=source.port,
        database=source.database_name,
        username=credentials.get("username"),
        password=credentials.get("password"),
    )
    return ConnectorFactory.create(
        source_type=source_type,
        connection_url=url,
        connect_args=DB_TYPES[source_type].get("connect_args"),
    )


def get_registered_source(db: Session, source_id: str) -> Source:
    """Load an active registry record or raise 404."""
    source = (
        db.query(Source)
        .filter(Source.id == source_id, Source.status != "DELETED")
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")
    if (source.status or "").upper() == "DISABLED":
        raise HTTPException(status_code=409, detail="Source is disabled.")
    return source


@contextmanager
def open_source_connector(db: Session, source_id: str) -> Iterator[tuple[Source, Any]]:
    """Yield ``(source, connected_connector)`` and always dispose the engine.

    Raises HTTPException with a safe message for unknown sources (404),
    unusable configuration (400/422) and unreachable databases (503).
    """
    source = get_registered_source(db, source_id)
    try:
        connector = build_source_connector(source)
    except SourceConnectionError as exc:
        status = 400 if exc.code == "unsupported" else 422
        raise HTTPException(status_code=status, detail=exc.message)

    try:
        try:
            connector.connect()
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="The source database is unavailable or the connection failed.")
        yield source, connector
    finally:
        try:
            connector.close()
        except Exception:
            pass


def list_source_tables(db: Session, source_id: str) -> tuple[Source, list[str]]:
    """Discover the tables that actually exist in the selected source."""
    with open_source_connector(db, source_id) as (source, connector):
        try:
            tables = connector.list_documents()
        except Exception:
            raise HTTPException(status_code=503, detail="Could not list tables from the source.")
        return source, list(tables)


def _schema_of(source: Source) -> str | None:
    return (source.schema_name or None) if (source.source_type or "").lower() != "sqlite" else None


def _require_table(connector, source: Source, table_name: str) -> None:
    schema = _schema_of(source)
    try:
        names = connector.list_table_names(schema=schema)
    except Exception:
        raise HTTPException(status_code=503, detail="Could not list tables from the source.")
    if table_name not in names:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{table_name}' does not exist in source '{source.name}'.")


def assert_table_in_source(db: Session, source_id: str, table_name: str) -> Source:
    """404 unless ``table_name`` really belongs to the selected source."""
    with open_source_connector(db, source_id) as (source, connector):
        _require_table(connector, source, table_name)
        return source


def load_registered_source_data(db: Session, source_id: str, table_name: str, limit: int):
    """Sample rows + native column metadata from the selected source's DB.

    Read-only (SELECT ... LIMIT). Returns ``(source, rows, columns)``.
    """
    with open_source_connector(db, source_id) as (source, connector):
        _require_table(connector, source, table_name)
        schema = _schema_of(source)
        try:
            rows = connector.sample(table_name, limit=limit, schema=schema)
            columns = connector.describe_table(table_name, schema=schema)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not read table '{table_name}' from source '{source.name}'.") from exc
        return source, rows, columns


def validate_source_connection(db: Session, source_id: str) -> dict[str, Any]:
    """Validate a registered source (connect + discover tables + close)."""
    source = (
        db.query(Source)
        .filter(Source.id == source_id, Source.status != "DELETED")
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")

    source_type = (source.source_type or "").strip().lower()

    def result(valid: bool, message: str, tables=None) -> dict[str, Any]:
        return {
            "id": source.id,
            "valid": valid,
            "status": source.status,
            "connector": source_type,
            "tables": tables or [],
            "message": message,
        }

    try:
        connector = build_source_connector(source)
    except SourceConnectionError as exc:
        if exc.code == "unsupported":
            raise HTTPException(status_code=400, detail=exc.message)
        return result(False, exc.message)

    try:
        connector.connect()
        tables = connector.list_documents()
        return result(True, "Connection validation passed.", tables)
    except Exception:
        return result(False, "Connection validation failed.")
    finally:
        try:
            connector.close()
        except Exception:
            pass
