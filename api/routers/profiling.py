"""
api/routers/profiling.py

Profiling, schema catalog, and data dictionary endpoints.

RBAC mapping
------------
POST /analyze/{table_name}         – steward+ (data-intensive write operation)
                                     optional ?source_id=<registered source id>
                                     sampling: ?method=auto|head|random|stratified&seed=&stratify_by=
GET  /results/{run_id}             – reviewer+ (read profiling result)
GET  /results/{run_id}/metrics     – reviewer+ (aggregate column metrics, Step 11)
GET  /schema-catalog/{table_name}  – reviewer+ (read catalog)
GET  /data-dictionary              – reviewer+ (read dictionary)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from metadata_store.db import get_db
from metadata_store.models import AnalysisRun, ColumnProfile, SchemaCatalogEntry, DataDictionaryEntry
from Profiling.sampling import SamplingError, SamplingSpec
from api.services import source_service, profiling_service, validation_service, audit_service
from api.services.source_connector_service import get_registered_source
from api.auth.dependencies import (
    require_steward_or_admin,
    require_reviewer_or_above,
)
from api.auth.models import CurrentUser

router = APIRouter()


@router.post("/analyze/{table_name}")
def analyze(
    table_name: str,
    sample_size: int = 50,
    source_id: str | None = None,
    method: str = "auto",
    seed: int | None = 42,
    stratify_by: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    sample_size = validation_service.validate_sample_size(sample_size)
    try:
        spec = SamplingSpec(method=method, size=sample_size, seed=seed, stratify_by=stratify_by)
    except SamplingError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if source_id:
        source = get_registered_source(db, source_id)      # 404 / 409 before anything is logged
        source_type = f"Registered {source.source_type} source: {source.name}"
    else:
        source_type, _ = source_service.get_source_kind(db, table_name, user.username)
    entry = audit_service.log_activity_start(
        db, "Profiling", source=table_name, source_type=source_type, user=user.username
    )
    try:
        result = profiling_service.run_profiling(
            db, table_name, spec, user.username, source_id=source_id)
    except HTTPException as e:
        audit_service.log_activity_finish(db, entry, "failed", str(e.detail))
        raise
    except Exception as e:
        audit_service.log_activity_finish(db, entry, "failed", str(e))
        raise HTTPException(status_code=500, detail=f"Profiling failed: {e}")

    audit_service.log_activity_finish(
        db, entry, "complete",
        f"{result['rows_sampled']} rows sampled, {result['total_fields']} fields classified",
        fields=result["total_fields"],
    )
    return result


@router.get("/results/{run_id}")
def get_results(
    run_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    sensitivity = profiling_service.sensitivity_details(db, run.id)
    return {
        "run_id": run.id,
        "source_id": run.source_id,
        "source_table": run.source_table,
        "run_timestamp": run.run_timestamp.isoformat(),
        "sampling": _sampling(run),
        "columns": [
            {
                "column_name": c.column_name,
                "pattern_type": c.pattern_type,
                "pattern": c.pattern,
                "match_percentage": c.match_percentage,
                # Format verdict: does the value format clearly match a specific
                # known type? Not a sensitivity decision (see "sensitivity").
                "verdict": c.verdict,
                "null_percent": c.null_percent,
                "distinct_count": c.distinct_count,
                "sensitivity": sensitivity.get(c.column_name),
            }
            for c in run.columns
        ],
    }


def _sampling(run: AnalysisRun) -> dict:
    return {
        "method": run.sampling_method,
        "seed": run.sampling_seed,
        "stratify_by": run.stratify_by,
        "sample_rows": run.sample_size,
        "population_rows": run.population_rows,
        "rows_scanned": run.rows_scanned,
        "reproducible": run.sample_reproducible,
    }


@router.get("/results/{run_id}/metrics")
def get_metrics(
    run_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    profiles = db.query(ColumnProfile).filter(ColumnProfile.run_id == run_id).order_by(ColumnProfile.id).all()
    return {
        "run_id": run.id,
        "source_id": run.source_id,
        "source_table": run.source_table,
        "sampling": _sampling(run),
        "columns": [{"column_name": p.column_name, "metrics_version": p.metrics_version, **p.metrics}
                    for p in profiles],
    }


@router.get("/schema-catalog/{table_name}")
def get_schema_catalog(
    table_name: str,
    source_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    catalog_rows = db.query(SchemaCatalogEntry).filter(
        SchemaCatalogEntry.table_name == table_name,
        SchemaCatalogEntry.source_id == source_id,
    ).all()
    if not catalog_rows:
        raise HTTPException(
            status_code=404,
            detail=f"No schema catalog entries for '{table_name}' yet - run an analysis first.",
        )

    latest_run = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.source_table == table_name, AnalysisRun.source_id == source_id)
        .order_by(AnalysisRun.run_timestamp.desc())
        .first()
    )
    classifications = {c.column_name: c for c in latest_run.columns} if latest_run else {}
    sensitivity = profiling_service.sensitivity_details(db, latest_run.id) if latest_run else {}
    dictionary = {d.pattern_type: d for d in db.query(DataDictionaryEntry).all()}

    result = []
    for entry in catalog_rows:
        classification = classifications.get(entry.column_name)
        pattern_type = classification.pattern_type if classification else None
        dict_entry = dictionary.get(pattern_type)
        result.append({
            "column_name": entry.column_name,
            "data_type": entry.data_type,
            "pattern_type": pattern_type,
            "verdict": classification.verdict if classification else None,
            "business_name": dict_entry.business_name if dict_entry else None,
            # Dictionary default for this FORMAT (kept for reference) ...
            "sensitivity_level": dict_entry.sensitivity_level if dict_entry else None,
            # ... and the actual classification of THIS column (Step 8/9).
            "sensitivity": sensitivity.get(entry.column_name),
        })
    return {"table_name": table_name, "source_id": source_id, "columns": result}


@router.get("/data-dictionary")
def get_data_dictionary(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_reviewer_or_above()),
):
    entries = db.query(DataDictionaryEntry).order_by(DataDictionaryEntry.pattern_type).all()
    return [
        {
            "pattern_type": e.pattern_type,
            "business_name": e.business_name,
            "description": e.description,
            "sensitivity_level": e.sensitivity_level,
        }
        for e in entries
    ]
