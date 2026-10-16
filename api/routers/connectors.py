"""
api/routers/connectors.py

Data source connector endpoints (file upload, database connection).

RBAC mapping
------------
POST /upload                    – steward+  (add a data source)
GET  /connectors/db-types      – tester+   (see available DB types)
POST /connectors/db/connect    – steward+  (connect to external DB)
POST /connectors/db/disconnect – steward+  (disconnect external DB)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import os
import re
import secrets

from metadata_store.db import get_db
from metadata_store.models import UploadedSource
from Connectors.file_connector import (
    parse_file,
    safe_filename,
    file_type_for,
    MAX_UPLOAD_CHARS,
)
from Connectors.db_connector import (
    DB_TYPES,
    driver_installed,
    build_connection_url,
    DBConnector,
)
from Connectors import connection_registry
from security import artifact_store
from api.services import audit_service
from api.auth.dependencies import (
    require_steward_or_admin,
    require_tester_or_above,
)
from api.auth.models import CurrentUser


router = APIRouter()

_BINARY_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

UPLOAD_DIR = os.path.join(
    os.getenv("TDM_DATA_DIR", BASE_DIR),
    "uploaded_files",
)


class UploadPayload(BaseModel):
    filename: str
    content: str


@router.post("/upload")
def upload_source(
    payload: UploadPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    name = safe_filename(payload.filename)
    file_type = file_type_for(name)

    if file_type is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload a .csv, .xml or .txt file.",
        )

    if len(payload.content) > MAX_UPLOAD_CHARS:
        raise HTTPException(
            status_code=413,
            detail="File is too large (limit is about 5 MB).",
        )

    # Landing zone: text files only. NUL / control bytes mean a binary or
    # disguised file - reject before parsing or storing anything.
    if _BINARY_RE.search(payload.content):
        raise HTTPException(
            status_code=400,
            detail="File content is not plain text.",
        )

    entry = audit_service.log_activity_start(
        db,
        "File Upload",
        source=name,
        source_type=f"{file_type} File",
        user=user.username,
    )

    try:
        parsed = parse_file(name, payload.content)
    except ValueError as e:
        audit_service.log_activity_finish(
            db,
            entry,
            "failed",
            str(e),
        )
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    # Stored under a random name (never the user-supplied one) and encrypted
    # at rest; the display name lives only in the metadata row.
    extension = os.path.splitext(name)[1].lower()
    path = os.path.join(UPLOAD_DIR, f"{secrets.token_hex(16)}{extension}")

    try:
        artifact_store.write_text(path, payload.content)
    except (OSError, artifact_store.ArtifactKeyError) as e:
        audit_service.log_activity_finish(
            db,
            entry,
            "failed",
            f"Could not save file: {type(e).__name__}",
        )

        raise HTTPException(
            status_code=500,
            detail="Could not save file.",
        )

    row_count = len(parsed["rows"])
    column_count = len(parsed["columns"])

    existing = (
        db.query(UploadedSource)
        .filter(UploadedSource.name == name)
        .first()
    )

    replaced = existing is not None
    previous_path = existing.file_path if existing else None

    if existing:
        existing.file_type = file_type
        existing.file_path = path
        existing.row_count = row_count
        existing.column_count = column_count
        existing.size_bytes = os.path.getsize(path)
        existing.uploaded_at = datetime.utcnow()

    else:
        db.add(
            UploadedSource(
                name=name,
                file_type=file_type,
                file_path=path,
                row_count=row_count,
                column_count=column_count,
                size_bytes=os.path.getsize(path),
            )
        )

    db.commit()
    if previous_path and previous_path != path and os.path.isfile(previous_path):
        os.remove(previous_path)

    audit_service.log_activity_finish(
        db,
        entry,
        "complete",
        (
            f"{'Replaced' if replaced else 'Uploaded'} "
            f"{name}: {row_count} rows, {column_count} columns"
        ),
        fields=column_count,
        file_path=path,
    )

    return {
        "name": name,
        "file_type": file_type,
        "rows": row_count,
        "columns": column_count,
        "replaced": replaced,
    }


class DbConnectPayload(BaseModel):
    db_type: str
    host: str = ""
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str = ""
    schema_name: str | None = None


def _allowed_hosts():
    raw = os.getenv(
        "TDM_ALLOWED_DB_HOSTS",
        "",
    )

    return {
        host.strip().lower()
        for host in raw.split(",")
        if host.strip()
    }


@router.get("/connectors/db-types")
def db_connector_types(
    user: CurrentUser = Depends(require_tester_or_above()),
):
    types = [
        {
            "id": tid,
            "label": cfg["label"],
            "demo": bool(cfg.get("demo")),
            "default_port": cfg.get("default_port"),
            "database_label": cfg.get("database_label"),
            "driver_installed": driver_installed(tid),
            "pip_package": cfg.get("pip_package"),
        }
        for tid, cfg in DB_TYPES.items()
    ]

    return {
        "types": types,
        "active": connection_registry.public_view(
            connection_registry.get_active(user.username)
        ),
    }


@router.post("/connectors/db/connect")
def db_connect(
    payload: DbConnectPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    db_type = payload.db_type

    if db_type not in DB_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unknown database type.",
        )

    cfg = DB_TYPES[db_type]

    if cfg.get("demo"):
        raise HTTPException(
            status_code=400,
            detail="The demo database is always connected - just pick a table.",
        )

    if not driver_installed(db_type):
        raise HTTPException(
            status_code=400,
            detail=(
                f"The {cfg['label']} driver isn't installed on the server."
            ),
        )

    host = payload.host.strip()
    database = payload.database.strip()
    username = payload.username.strip()

    if not host or not username or not database:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Host, {cfg['database_label'].lower()} "
                f"and username are required."
            ),
        )

    # Step 4F:
    # The external database host allow-list must be configured.
    allowed = _allowed_hosts()

    if not allowed:
        raise HTTPException(
            status_code=500,
            detail="Database host allow-list is not configured.",
        )

    if host.lower() not in allowed:
        raise HTTPException(
            status_code=403,
            detail="This host is not on the allowed list for this portal.",
        )

    port = payload.port or cfg["default_port"]
    schema = (payload.schema_name or "").strip() or None

    target = (
        f"{cfg['label']} @ "
        f"{host}:{port}/{database}"
    )

    entry = audit_service.log_activity_start(
        db,
        "DB Connection",
        source=target,
        source_type="Database",
        user=user.username,
    )

    connector = None

    try:
        url = build_connection_url(
            db_type,
            host,
            port,
            database,
            username,
            payload.password,
        )

        connector = DBConnector(
            url,
            connect_args=cfg.get("connect_args"),
        )

        connector.connect()

        tables = connector.list_table_names(
            schema=schema
        )

    except Exception as e:
        message = (
            str(e).splitlines()[0][:300]
            if str(e)
            else e.__class__.__name__
        )

        if payload.password:
            message = message.replace(
                payload.password,
                "***",
            )

        audit_service.log_activity_finish(
            db,
            entry,
            "failed",
            message,
        )

        # Best-effort audit write for connection failures.
        # The primary connection failure should still be reported.
        try:
            audit_service.record_audit(
                db,
                "DB Connection",
                user,
                "failed",
                message,
                source=target,
                source_type="Database",
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not connect to "
                f"{cfg['label']}: {message}"
            ),
        )

    finally:
        if connector is not None:
            connector.close()

    connection_registry.set_active(
        user.username,
        {
            "db_type": db_type,
            "label": cfg["label"],
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "schema": schema,
            "tables": tables,
            "url": url,
            "connect_args": cfg.get("connect_args"),
        },
    )

    audit_service.log_activity_finish(
        db,
        entry,
        "complete",
        f"Connected - {len(tables)} tables found",
    )

    audit_service.record_audit(
        db,
        "DB Connection",
        user,
        "complete",
        "Connected",
        source=target,
        source_type="Database",
    )

    return {
        "active": connection_registry.public_view(
            connection_registry.get_active(user.username)
        )
    }


@router.post("/connectors/db/disconnect")
def db_disconnect(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    info = connection_registry.get_active(
        user.username
    )

    if info and connection_registry.clear_active(
        user.username
    ):
        entry = audit_service.log_activity_start(
            db,
            "DB Connection",
            user=user.username,
            source_type="Database",
            source=(
                f"{info['label']} @ "
                f"{info['host']}:{info['port']}/"
                f"{info['database']}"
            ),
        )

        audit_service.log_activity_finish(
            db,
            entry,
            "complete",
            "Disconnected",
        )

    return {
        "active": None
    }