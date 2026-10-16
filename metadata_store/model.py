from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
)

from metadata_store.db import Base


class UploadedSource(Base):
    __tablename__ = "uploaded_sources"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(
        String,
        unique=True,
        nullable=False,
        index=True,
    )

    file_type = Column(
        String,
        nullable=False,
    )

    file_path = Column(
        String,
        nullable=False,
    )

    row_count = Column(
        Integer,
        nullable=False,
    )

    column_count = Column(
        Integer,
        nullable=False,
    )

    size_bytes = Column(
        Integer,
        nullable=False,
        default=0,
    )

    uploaded_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    username = Column(
        String,
        nullable=True,
        index=True,
    )

    user_id = Column(
        String,
        nullable=True,
        index=True,
    )

    role = Column(
        String,
        nullable=True,
        index=True,
    )

    event = Column(
        String,
        nullable=False,
    )

    target = Column(
        String,
        nullable=True,
    )

    target_type = Column(
        String,
        nullable=True,
    )

    status = Column(
        String,
        nullable=True,
    )

    detail = Column(
        Text,
        nullable=True,
    )

    prev_hash = Column(
        String,
        nullable=True,
    )

    entry_hash = Column(
        String,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class SchemaCatalogEntry(Base):
    __tablename__ = "schema_catalog"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    source = Column(
        String,
        nullable=False,
        index=True,
    )

    table_name = Column(
        String,
        nullable=False,
        index=True,
    )

    column_name = Column(
        String,
        nullable=False,
    )

    data_type = Column(
        String,
        nullable=True,
    )

    nullable = Column(
        String,
        nullable=True,
    )

    is_primary_key = Column(
        String,
        nullable=True,
    )

    is_foreign_key = Column(
        String,
        nullable=True,
    )

    foreign_table = Column(
        String,
        nullable=True,
    )

    foreign_column = Column(
        String,
        nullable=True,
    )


class Source(Base):
    __tablename__ = "sources"

    id = Column(
        String,
        primary_key=True,
        index=True,
    )

    name = Column(
        String,
        unique=True,
        nullable=False,
        index=True,
    )

    source_type = Column(
        String,
        nullable=False,
        index=True,
    )

    description = Column(
        String,
        nullable=True,
    )

    host = Column(
        String,
        nullable=True,
    )

    port = Column(
        Integer,
        nullable=True,
    )

    database_name = Column(
        String,
        nullable=True,
    )

    schema_name = Column(
        String,
        nullable=True,
    )

    credential_ref = Column(
        String,
        nullable=True,
    )

    status = Column(
        String,
        nullable=False,
        default="ACTIVE",
        index=True,
    )

    created_by = Column(
        String,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    deleted_at = Column(
        DateTime,
        nullable=True,
    )


# ============================================================
# Step 5 - Job Management
# ============================================================

class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        String,
        primary_key=True,
        index=True,
    )

    job_type = Column(
        String,
        nullable=False,
        index=True,
    )

    source_id = Column(
        String,
        nullable=True,
        index=True,
    )

    status = Column(
        String,
        nullable=False,
        default="QUEUED",
        index=True,
    )

    created_by = Column(
        String,
        nullable=True,
        index=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    started_at = Column(
        DateTime,
        nullable=True,
    )

    completed_at = Column(
        DateTime,
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    result = Column(
        Text,
        nullable=True,
    )

# ============================================================
# Step 5 - Job Management
# ============================================================

class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        String,
        primary_key=True,
        index=True,
    )

    job_type = Column(
        String,
        nullable=False,
        index=True,
    )

    source_id = Column(
        String,
        nullable=True,
        index=True,
    )

    status = Column(
        String,
        nullable=False,
        default="QUEUED",
        index=True,
    )

    created_by = Column(
        String,
        nullable=True,
        index=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    started_at = Column(
        DateTime,
        nullable=True,
    )

    completed_at = Column(
        DateTime,
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    result = Column(
        Text,
        nullable=True,
    )    