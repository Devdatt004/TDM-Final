"""
api/services/masking_service.py

Step 10 - deterministic masking of real source rows.

Each column of the latest profiling run is given exactly one action:

  tokenize (key)        join keys: columns in the relationship graph, or named
                        id / *_id. Namespace is the ROOT parent key, so a parent
                        key and every child FK pointing at it get the same token
                        and joins survive masking across separately masked tables.
  tokenize (identifier) direct identifiers (SSN, MRN, account/card numbers, email,
                        phone, ...). Namespace per identifier type, so the same SSN
                        masks identically in every table.
  substitute            other sensitive data (names, addresses, birth dates, free
                        text with person/location entities) -> Faker value.
  passthrough           no sensitivity evidence, or a reviewer approved the column
                        as not sensitive. Listed in the response so nothing is
                        passed through silently.

The Step 9 review gate applies: masking is refused while any review-required
column of the latest run is not APPROVED. Raw source values are never written
to the output file, the response, logs or the metadata store.
"""

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.services.audit_service import log_activity_finish, log_activity_start
from api.services.column_roles import graph_key_columns, identifier_type, is_key
from api.services.generation_service import assert_review_cleared
from api.services.source_connector_service import load_registered_source_data
from api.services.source_service import get_source_kind, load_source_data
from api.services.validation_service import validate_row_count
from metadata_store.models import ClassificationResult, SchemaCatalogEntry, SyntheticDataset
from privacy.pseudonymization import PseudonymizationError, get_pseudonymizer
from referential_integrity.service import load_graph
from synthetic_generation import generator as synthetic_generator

def _namespace(*parts: str) -> str:
    raw = ".".join(parts).lower()
    ns = re.sub(r"[^a-z0-9_.]", "_", raw)
    if not ns[:1].isalpha():
        ns = "n" + ns
    return ns[:64]


def _root_key(graph, table: str, column: str) -> str:
    """Follow child FK -> parent key until the top of the chain."""
    seen = set()
    key = (table, column)
    while key not in seen:
        seen.add(key)
        parent = next((r for r in graph.relationships
                       if r.child_table == key[0] and r.child_column == key[1]), None)
        if parent is None:
            break
        key = (parent.parent_table, parent.parent_column)
    return f"{key[0]}.{key[1]}"


def plan_columns(graph, table_name: str, columns: list, classifications: dict) -> dict:
    """{column: {"action": ..., "namespace": ..., "reason": ...}} for every column."""
    graph_keys = graph_key_columns(graph, table_name)
    plan = {}
    for col in columns:
        c = classifications.get(col)
        reviewed_not_sensitive = (
            c is not None and c.classification_status == "approved" and c.sensitivity != "sensitive")

        if is_key(graph_keys, col):
            root = (_root_key(graph, table_name, col) if col in graph_keys else col)
            plan[col] = {"action": "tokenize", "namespace": _namespace("key", root),
                         "reason": "join key"}
        elif reviewed_not_sensitive:
            plan[col] = {"action": "passthrough", "reason": "reviewer approved as not sensitive"}
        elif c is not None and c.sensitivity == "sensitive":
            id_type = identifier_type(c)
            if id_type:
                plan[col] = {"action": "tokenize", "namespace": _namespace("id", id_type),
                             "reason": f"identifier ({id_type})"}
            else:
                plan[col] = {"action": "substitute",
                             "reason": "sensitive: " + ", ".join(c.detected_types or [c.pattern_type or "evidence"])}
        else:
            plan[col] = {"action": "passthrough", "reason": "no sensitivity evidence"}
    return plan


def _load_rows(db: Session, table_name: str, rows: int, username: str, source_id: str):
    if source_id:
        _, data, _, _ = load_registered_source_data(db, source_id, table_name, rows)
        return data
    try:
        data, _, _ = load_source_data(db, table_name, rows, username)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read '{table_name}'.") from exc
    return data


def mask_table(db: Session, table_name: str, rows: int, username: str, source_id: str = None) -> dict:
    validate_row_count(rows)
    run = assert_review_cleared(db, table_name, source_id, action="masking data")
    if run is None:
        raise HTTPException(status_code=409, detail=(
            f"'{table_name}' has not been profiled yet. Run Profiling first - masking "
            "decisions come from classification results."))

    try:
        pseudonymizer = get_pseudonymizer()
    except PseudonymizationError as exc:
        raise HTTPException(status_code=503, detail=f"Pseudonymization is not configured: {exc}") from exc

    classifications = {
        c.column_name: c for c in db.query(ClassificationResult).filter(ClassificationResult.run_id == run.id)
    }
    columns = [c.column_name for c in run.columns]
    graph, _ = load_graph(db)
    plan = plan_columns(graph, table_name, columns, classifications)
    data_types = {
        e.column_name: e.data_type for e in db.query(SchemaCatalogEntry).filter(
            SchemaCatalogEntry.table_name == table_name, SchemaCatalogEntry.source_id == source_id)
    }

    source_type = get_source_kind(db, table_name, username)[0] if not source_id else f"Registered source {source_id}"
    entry = log_activity_start(db, "Masking", source=table_name, source_type=source_type, user=username)
    try:
        source_rows = _load_rows(db, table_name, rows, username, source_id)
        masked = []
        for row in source_rows:
            out = {}
            for col in columns:
                step = plan[col]
                value = row.get(col)
                if step["action"] == "tokenize":
                    out[col] = pseudonymizer.pseudonymize(value, step["namespace"])
                elif step["action"] == "substitute":
                    out[col] = None if value is None else synthetic_generator.generate_value(
                        col, classifications[col].pattern_type, data_types.get(col, ""))
                else:
                    out[col] = value
            masked.append(out)

        # Step 13: masked rows are row-aligned with source_rows.
        from api.services import plausibility_service, privacy_service
        privacy = privacy_service.assess_masked(
            db, table_name, masked, source_rows, plan,
            domain=plausibility_service.domain_for(table_name, source_id), source_id=source_id)
        status = privacy_service.release_status(privacy)
        file_name, file_path = synthetic_generator.write_table_csv(table_name, columns, masked, kind="masked")
        dataset = SyntheticDataset(source_table=table_name, source_id=source_id, run_id=run.id,
                                   row_count=len(masked), file_path=file_path, release_status=status,
                                   validation_report={"passed": True, "plausibility": None,
                                                      "privacy": privacy, "release_status": status})
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
    except HTTPException as exc:
        log_activity_finish(db, entry, "failed", str(exc.detail))
        raise
    except PseudonymizationError as exc:
        log_activity_finish(db, entry, "failed", str(exc))
        raise HTTPException(status_code=422, detail=f"Masking failed: {exc}") from exc
    except Exception as exc:
        # Never echo exception text: driver errors can contain row values.
        log_activity_finish(db, entry, "failed", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Masking failed.") from exc

    log_activity_finish(db, entry, "complete", f"Masked {len(masked)} rows -> {file_name}", file_path=file_path)
    return {
        "dataset_id": dataset.public_id,
        "source_id": source_id,
        "source_table": table_name,
        "run_id": run.id,
        "row_count": len(masked),
        "file_name": file_name,
        "key_id": pseudonymizer.active_key_id,
        "ephemeral_key": pseudonymizer.ephemeral,
        "columns": [{"column": col, **plan[col]} for col in columns],
        "passthrough_columns": [col for col in columns if plan[col]["action"] == "passthrough"],
        "release_status": status,
        "privacy": privacy,
        "preview": masked[:10] if status != "BLOCKED" else [],
    }
