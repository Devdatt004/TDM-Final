"""
metadata_store/models.py

These two tables ARE our "materialized view" - they store the RESULT
of running the Pattern Analyzer, not a live recomputation. Every time
POST /analyze runs, we INSERT fresh rows here. Every time someone reads
the dashboard (GET /summary, GET /results), we just SELECT from these
tables - fast, no recomputation, no touching hospital.db again.

  AnalysisRun    - one row per "Run Analysis" click (a whole table scan)
  ColumnResult   - one row per COLUMN within that run (the actual
                    pattern/type/verdict for that column)

This is the same document_entity/field_entity idea from the original
repo structure you were given, just named for our specific use case.
"""

import secrets
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, UniqueConstraint, JSON
from sqlalchemy.orm import relationship
from metadata_store.db import Base
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
)

class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, index=True)
    source_table = Column(String, nullable=False)     # e.g. "patients"
    # Registered Source (sources.id) the table was profiled from. NULL for
    # legacy/demo/uploaded-file runs that predate the Source Registry.
    source_id = Column(String, nullable=True, index=True)
    sample_size = Column(Integer, nullable=False)
    total_fields = Column(Integer, nullable=False)
    high_confidence_count = Column(Integer, nullable=False)
    needs_review_count = Column(Integer, nullable=False)
    status = Column(String, default="complete")
    run_timestamp = Column(DateTime, default=datetime.utcnow)

    # Step 11 - how the sample was drawn, so metrics are reproducible/explainable.
    sampling_method = Column(String, nullable=True)        # head / random / stratified
    sampling_seed = Column(Integer, nullable=True)
    stratify_by = Column(String, nullable=True)
    population_rows = Column(Integer, nullable=True)       # COUNT(*) of the table, if known
    rows_scanned = Column(Integer, nullable=True)          # size of the pool the sample came from
    sample_reproducible = Column(Boolean, nullable=True)

    # This lets us do run.columns to get all ColumnResult rows for this run,
    # without writing a manual SQL join every time.
    columns = relationship("ColumnResult", back_populates="run", cascade="all, delete-orphan")


class ColumnResult(Base):
    __tablename__ = "column_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False)
    column_name = Column(String, nullable=False)
    pattern_type = Column(String, nullable=False)
    pattern = Column(String, nullable=False)
    match_percentage = Column(Float, nullable=False)
    verdict = Column(String, nullable=False)   # "high_confidence" or "needs_review"

    # Profiling stats (from profiler.py) - added so the dashboard shows
    # BOTH what a column's structure looks like (pattern analysis) AND
    # its basic statistics (profiling), which is a separate signal.
    null_percent = Column(Float, nullable=False, default=0.0)
    distinct_count = Column(Integer, nullable=False, default=0)

    run = relationship("AnalysisRun", back_populates="columns")


class IdempotencyRecord(Base):
    """Step 15 - stored outcome of a POST/PATCH sent with an Idempotency-Key.
    ``status_code`` NULL means the first request is still running."""
    __tablename__ = "idempotency_records"

    id = Column(Integer, primary_key=True)
    scope = Column(String(64), nullable=False)          # sha256 of the caller's credentials
    key = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)    # sha256 of method, path, query, body
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)


class ColumnProfile(Base):
    """Step 11 - aggregate metrics for one column of one profiling run.
    Aggregates only (see Profiling/aggregate_metrics.py); never raw rows."""
    __tablename__ = "column_profiles"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    column_name = Column(String, nullable=False)
    metrics_version = Column(String, nullable=False)
    metrics = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("run_id", "column_name", name="uq_column_profiles_run_column"),)


class ClassificationResult(Base):
    """Sensitivity classification associated with a profiling run."""
    __tablename__ = "classification_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id = Column(String, nullable=True, index=True)
    source_version = Column(String, nullable=True, index=True)
    table_name = Column(String, nullable=False, index=True)
    column_name = Column(String, nullable=False, index=True)

    # Pattern and sensitivity remain separate classification dimensions.
    pattern_type = Column(String, nullable=True)
    pattern_confidence = Column(Float, nullable=True)
    sensitivity = Column(String, nullable=False, default="unknown")
    sensitivity_confidence = Column(Float, nullable=False, default=0.0)
    evidence = Column(JSON, nullable=False, default=list)
    detected_types = Column(JSON, nullable=False, default=list)

    classification_status = Column(
        String, nullable=False, default="unknown"
    )
    review_required = Column(Boolean, nullable=False, default=False)
    rule_pack_version = Column(String, nullable=False, default="1.0.0")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    run = relationship("AnalysisRun")



class ClassificationReview(Base):
    """Human review decision for a sensitivity classification result."""
    __tablename__ = "classification_reviews"

    id = Column(Integer, primary_key=True, index=True)
    classification_result_id = Column(
        Integer,
        ForeignKey("classification_results.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(String, nullable=False, default="PENDING", index=True)
    proposed_pattern_type = Column(String, nullable=True)
    proposed_sensitivity = Column(String, nullable=False, default="unknown")
    final_pattern_type = Column(String, nullable=True)
    final_sensitivity = Column(String, nullable=True)
    reviewer_user_id = Column(String, nullable=True)
    reviewer_username = Column(String, nullable=True)
    decision_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    reviewed_at = Column(DateTime, nullable=True)

    classification = relationship("ClassificationResult")


class SchemaCatalogEntry(Base):
    """
    Schema Catalog - TDD Section 3.1 ("Metadata & Knowledge...schema
    catalog") and Section 7.1's hierarchy (Source System -> Schema
    Catalog -> Table Catalog -> Column Catalog). Our MVP has one source
    system (hospital.db), so this flattens straight to one row per
    (table, column) pair with its NATIVE source data type.

    Populated automatically inside POST /analyze from the connector's own
    introspection (db_connector.list_entities()) - never hand-typed, so it
    can never drift from the real source schema. This is the piece that
    was missing before: column_results records what a column's VALUES
    look like (pattern/verdict); this records what the column IS
    (its declared type), independent of any analysis run.
    """
    __tablename__ = "schema_catalog"

    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String, nullable=False, index=True)
    # Registered Source the catalog entry was read from (NULL = legacy flow).
    source_id = Column(String, nullable=True, index=True)
    column_name = Column(String, nullable=False)
    data_type = Column(String, nullable=False)   # native source type, e.g. "VARCHAR(50)", "INTEGER"
    updated_at = Column(DateTime, default=datetime.utcnow)


class DataDictionaryEntry(Base):
    """
    Data Dictionary - TDD Section 3.1 ("...data dictionary...business
    glossary"). One row per PATTERN TYPE the Pattern Analyzer can produce
    (SSN, DATE, PHONE, ...), not per column - a business-friendly name,
    plain-English description, and default sensitivity level.

    Seeded once (see metadata_store/seed.py) from the same
    pattern_analysis/pattern_types.yaml the analyzer already uses, plus
    hand-written business context. Every column later classified with a
    given pattern_type looks its meaning up here - that lookup IS the
    "reuse" the catalog exists for, instead of re-describing what an SSN
    is on every single column that turns out to contain one.
    """
    __tablename__ = "data_dictionary"

    id = Column(Integer, primary_key=True, index=True)
    pattern_type = Column(String, unique=True, nullable=False, index=True)
    business_name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    sensitivity_level = Column(String, nullable=False)  # e.g. "PHI", "PII", "Non-sensitive"


class SyntheticDataset(Base):
    """
    One row per synthetic-generation job - the SyntheticDataset entity
    named in TDD Section 9's MVP entity list. Tracks what was generated,
    from which analysis run (so we know which schema/classifications it
    was generated against), how many rows, and where the output file is
    so the frontend can offer it for download.
    """
    __tablename__ = "synthetic_datasets"

    id = Column(Integer, primary_key=True, index=True)
    # Random, unguessable id used in download links and API responses. The
    # integer id stays internal - sequential ids (1, 2, 3...) can be guessed.
    public_id = Column(String, unique=True, nullable=False, index=True,
                       default=lambda: secrets.token_urlsafe(16))
    source_table = Column(String, nullable=False)
    # Registered Source the dataset was generated for (NULL = legacy flow).
    source_id = Column(String, nullable=True, index=True)
    run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False)
    row_count = Column(Integer, nullable=False)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Release-gate evidence: {"plausibility": {...}, "privacy": {...}} - aggregate
    # reports including the rule versions applied (Steps 12/13). Never row values.
    validation_report = Column(JSON, nullable=True)
    # Step 13 release gate: RELEASED / BLOCKED (privacy gate failed) / OVERRIDDEN.
    # NULL = created before the gate existed.
    release_status = Column(String, nullable=True, index=True)
    override_by = Column(String, nullable=True)
    override_reason = Column(Text, nullable=True)
    override_at = Column(DateTime, nullable=True)
    # Step 16: when the retention purge deleted the file (row kept for lineage).
    purged_at = Column(DateTime, nullable=True)


class ActivityLog(Base):
    """
    One row per platform ACTIVITY (Profiling, File Upload, Synthetic Data
    Generation, Masking Preview, Log Cleanup). Powers three things:
      - the "Recent runs" table (activity name column)
      - the dashboard's "Recent activity" card (what is happening now)
      - the Logs tab

    A row is inserted as "running" when the activity starts and updated to
    "complete" / "failed" when it ends. Rows older than the retention
    window (see metadata_store/activity.py) are deleted automatically.
    Times are stored as naive UTC, like the rest of this store.
    """
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    activity = Column(String, nullable=False)          # e.g. "Profiling"
    source = Column(String, nullable=True)             # table or file name
    source_type = Column(String, nullable=True)        # "DB Table", "CSV File", ...
    fields = Column(Integer, nullable=True)            # column count, when relevant
    status = Column(String, nullable=False, default="running")
    message = Column(String, nullable=True)
    file_path = Column(String, nullable=True)          # file written/read by the activity
    username = Column(String, nullable=True, index=True)  # WHO performed it (actor; "system" for automatic jobs)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class UploadedSource(Base):
    """A CSV / XML / text file uploaded as a data source. The raw file is
    kept on disk (file_path); this row is what makes it appear in every
    table dropdown alongside the database tables."""
    __tablename__ = "uploaded_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    file_type = Column(String, nullable=False)         # "CSV" | "XML" | "Text"
    file_path = Column(String, nullable=False)
    row_count = Column(Integer, nullable=False)
    column_count = Column(Integer, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

class Source(Base):
    """
    Registered data source.

    A Source represents a logical source known to the TDM platform.
    Connection details are referenced through credential_ref rather than
    storing plaintext passwords in metadata.
    """
    __tablename__ = "sources"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    source_type = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)

    # Non-secret connection information.
    host = Column(String, nullable=True)
    port = Column(Integer, nullable=True)
    database_name = Column(String, nullable=True)
    schema_name = Column(String, nullable=True)

    # Reference to credentials managed outside the metadata database.
    credential_ref = Column(String, nullable=True)

    # REGISTERED / ACTIVE / DISABLED / DELETED
    status = Column(String, nullable=False, default="ACTIVE", index=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

class TableRelationship(Base):
    """
    The Relationship Graph, stored as metadata - one row per foreign key
    (child column -> parent column), e.g. insurance_claims.patient_id ->
    patients.patient_id. Filled by relationship discovery (origin =
    "discovered", read from the source database's declared foreign keys) or
    added by hand for databases that don't declare their keys (origin =
    "manual"). In the UI these are DECLARED (discovered) and UNDECLARED (manual) relationships. Re-running discovery replaces the discovered rows and keeps
    the manual ones. The Data Relationship Validation engine reads THIS table, not
    the source database, when it generates.
    """
    __tablename__ = "table_relationships"
    __table_args__ = (UniqueConstraint("child_table", "child_column", name="uq_relationship_child"),)

    id = Column(Integer, primary_key=True, index=True)
    child_table = Column(String, nullable=False, index=True)
    child_column = Column(String, nullable=False)
    parent_table = Column(String, nullable=False, index=True)
    parent_column = Column(String, nullable=False)
    origin = Column(String, nullable=False, default="discovered")   # "discovered" | "manual"
    nullable = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class IntegrityRun(Base):
    """
    One row per related-dataset generation: which tables were generated,
    the validation report (score + every check) and the SyntheticDataset ids
    of the files that were written. The report is stored as JSON so it can be
    re-opened later without regenerating anything.
    """
    __tablename__ = "integrity_runs"

    id = Column(Integer, primary_key=True, index=True)
    tables = Column(String, nullable=False)          # comma-separated, in generation order
    total_rows = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=False, default=0.0)
    passed = Column(Boolean, nullable=False, default=False)
    report_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditLog(Base):
    """
    Immutable, append-only record of security-relevant operational events (
    sign-outs, user administration, database connections, file downloads).

    Kept apart from ActivityLog on purpose: ActivityLog is operational (it is
    purged after N days and can be cleaned up from the Logs tab); this table
    is never purged, has no update/delete endpoint, and database triggers
    (see metadata_store/audit.py) refuse UPDATE and DELETE. Each row stores a
    hash of the previous row, so editing history out-of-band is detectable.

    Step-3 additions
    ----------------
    user_id  : stable opaque user identifier (JWT sub / dev user id).
               Stored separately from username so identity survives renames.
    role     : the role(s) the actor held at the time of the action
               (comma-separated string).  Captures the privilege level used.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    username = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=True, index=True)     # Step 3: stable actor id
    role = Column(String, nullable=True)                    # Step 3: role at time of action
    event = Column(String, nullable=False)          # "Login", "Logout", "User Management", ...
    target = Column(String, nullable=True)          # what it was done to
    target_type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="complete")
    detail = Column(String, nullable=True)
    prev_hash = Column(String, nullable=False, default="")
    entry_hash = Column(String, nullable=False, default="")

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
# Step 6 - Workflow Management
# ============================================================

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "step_order",
            name="uq_workflow_steps_order",
        ),
    )

    id = Column(String, primary_key=True, index=True)
    workflow_id = Column(
        String,
        ForeignKey("workflows.id"),
        nullable=False,
        index=True,
    )
    step_order = Column(Integer, nullable=False)
    job_type = Column(String, nullable=False)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(String, primary_key=True, index=True)
    workflow_id = Column(
        String,
        ForeignKey("workflows.id"),
        nullable=False,
        index=True,
    )
    source_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="QUEUED", index=True)
    current_step_order = Column(Integer, nullable=False, default=1)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


class WorkflowStepRun(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "workflow_step_id",
            name="uq_workflow_step_run",
        ),
    )

    id = Column(String, primary_key=True, index=True)
    workflow_run_id = Column(
        String,
        ForeignKey("workflow_runs.id"),
        nullable=False,
        index=True,
    )
    workflow_step_id = Column(
        String,
        ForeignKey("workflow_steps.id"),
        nullable=False,
        index=True,
    )
    job_id = Column(
        String,
        ForeignKey("jobs.id"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="QUEUED", index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

# ============================================================
# Step 7 - Rule Registry
# ============================================================

class Rule(Base):
    """Stable identity and lifecycle metadata for a reusable platform rule."""
    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("rule_key", name="uq_rules_rule_key"),)

    id = Column(String, primary_key=True, index=True)
    rule_key = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False, index=True)
    rule_type = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="DRAFT", index=True)
    current_version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deactivated_at = Column(DateTime, nullable=True)

    versions = relationship(
        "RuleVersion", back_populates="rule", cascade="all, delete-orphan",
        order_by="RuleVersion.version_number",
    )


class RuleVersion(Base):
    """Immutable snapshot of one version of a rule definition."""
    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_number", name="uq_rule_versions_rule_version"),
    )

    id = Column(String, primary_key=True, index=True)
    rule_id = Column(String, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    definition = Column(JSON, nullable=False)
    change_summary = Column(String(1000), nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    rule = relationship("Rule", back_populates="versions")
