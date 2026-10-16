
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.services.source_service import load_source_data
from api.services.source_connector_service import load_registered_source_data
from api.services.classification_service import (
    classify_column,
    classify_column_sensitivity,
)
from pattern_analysis.pattern_analyzer import PatternAnalyzer
from Profiling.profiler import profile_table
from Profiling import sampling
from Profiling.aggregate_metrics import METRICS_VERSION, table_metrics
from metadata_store.models import (
    ColumnProfile,
    SchemaCatalogEntry,
    AnalysisRun,
    ColumnResult,
    ClassificationResult,
    ClassificationReview,
)


RULE_PACK_VERSION = "1.0.0"


def run_profiling(
    db: Session,
    table_name: str,
    sample_size,
    username: str = None,
    source_id: str = None,
):
    """Profile a table and persist structural and sensitivity results separately.

    ``sample_size`` is a row count (head sample, historical behaviour) or a
    Profiling.sampling.SamplingSpec. Registered sources use their updated_at
    timestamp as a source-version identifier. The legacy name-based flow
    remains supported.
    """
    source_version = None
    spec = sampling.as_spec(sample_size)

    if source_id:
        source, rows, catalog_columns, sample_info = load_registered_source_data(
            db, source_id, table_name, spec
        )
        if source.updated_at is not None:
            source_version = source.updated_at.isoformat()
    else:
        try:
            rows, catalog_columns, sample_info = load_source_data(
                db, table_name, spec, username
            )
        except sampling.SamplingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not read '{table_name}': {exc}",
            ) from exc

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"'{table_name}' has no rows",
        )

    if catalog_columns:
        db.query(SchemaCatalogEntry).filter(
            SchemaCatalogEntry.table_name == table_name,
            SchemaCatalogEntry.source_id == source_id,
        ).delete()

        for col in catalog_columns:
            db.add(
                SchemaCatalogEntry(
                    table_name=table_name,
                    source_id=source_id,
                    column_name=col["name"],
                    data_type=col["type"],
                )
            )

    analyzer = PatternAnalyzer()
    pattern_results = analyzer.analyze_table(rows)
    profile_results = profile_table(rows)

    column_entries = []
    classification_entries = []
    high_confidence_count = 0

    for col, patterns in pattern_results.items():
        top = patterns[0] if patterns else None

        # Preserve the existing structural-pattern verdict.
        verdict = classify_column(top)
        if verdict == "high_confidence":
            high_confidence_count += 1

        profile = profile_results.get(col, {})

        column_entries.append(
            {
                "column_name": col,
                "pattern_type": top["pattern_type"] if top else "N/A",
                "pattern": top["pattern"] if top else "",
                "match_percentage": top["percentage"] if top else 0.0,
                "verdict": verdict,
                "null_percent": profile.get("null_percent", 0.0),
                "distinct_count": profile.get("distinct_count", 0),
            }
        )

        # Sensitivity classification is independent of the legacy verdict.
        sample_values = [
            row.get(col)
            for row in rows
            if row.get(col) is not None
        ]

        sensitivity_result = classify_column_sensitivity(
            column_name=col,
            top_pattern=top,
            sample_values=sample_values,
        )

        classification_entries.append(
            {
                "source_id": source_id,
                "source_version": source_version,
                "table_name": table_name,
                "column_name": col,
                "pattern_type": sensitivity_result["pattern_type"],
                "pattern_confidence": (
                    float(top["percentage"]) / 100.0
                    if top
                    and isinstance(top.get("percentage"), (int, float))
                    else None
                ),
                "sensitivity": sensitivity_result["sensitivity"],
                "sensitivity_confidence": sensitivity_result["confidence"],
                "evidence": sensitivity_result["evidence"],
                "detected_types": sensitivity_result["detected_types"],
                "classification_status": sensitivity_result[
                    "classification_status"
                ],
                "review_required": sensitivity_result["review_required"],
                "rule_pack_version": RULE_PACK_VERSION,
            }
        )

    total_fields = len(column_entries)
    needs_review_count = total_fields - high_confidence_count

    sensitive_columns = {
        e["column_name"]: e["sensitivity"] == "sensitive" for e in classification_entries
    }
    metrics = table_metrics(rows, sensitive_columns, sample_info["population_rows"])

    run = AnalysisRun(
        source_table=table_name,
        source_id=source_id,
        sample_size=len(rows),
        sampling_method=sample_info["method"],
        sampling_seed=sample_info["seed"],
        stratify_by=sample_info["stratify_by"],
        population_rows=sample_info["population_rows"],
        rows_scanned=sample_info["rows_scanned"],
        sample_reproducible=sample_info["reproducible"],
        total_fields=total_fields,
        high_confidence_count=high_confidence_count,
        needs_review_count=needs_review_count,
        status="complete",
        run_timestamp=datetime.utcnow(),
    )

    try:
        db.add(run)
        db.flush()

        for entry in column_entries:
            db.add(ColumnResult(run_id=run.id, **entry))

        for column_name, column_metrics in metrics.items():
            db.add(ColumnProfile(run_id=run.id, column_name=column_name,
                                 metrics_version=METRICS_VERSION, metrics=column_metrics))

        for entry in classification_entries:
            classification = ClassificationResult(run_id=run.id, **entry)
            db.add(classification)
            db.flush()
            if classification.review_required:
                db.add(ClassificationReview(
                    classification_result_id=classification.id,
                    status="PENDING",
                    proposed_pattern_type=classification.pattern_type,
                    proposed_sensitivity=classification.sensitivity,
                ))

        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise

    return {
        "run_id": run.id,
        "source_id": source_id,
        "source_version": source_version,
        "source_table": table_name,
        "total_fields": total_fields,
        "rows_sampled": len(rows),
        "sampling": sample_info,
    }


def sensitivity_details(db: Session, run_id: int) -> dict:
    """{column_name: sensitivity result + its human-review state} for one run.

    This is the Step 8 classification (name/pattern/value/NER evidence with a
    confidence score), as opposed to the legacy format ``verdict``.
    """
    rows = (
        db.query(ClassificationResult, ClassificationReview)
        .outerjoin(ClassificationReview,
                   ClassificationReview.classification_result_id == ClassificationResult.id)
        .filter(ClassificationResult.run_id == run_id)
        .all()
    )
    return {
        c.column_name: {
            "sensitivity": c.sensitivity,
            "sensitivity_confidence": c.sensitivity_confidence,
            "evidence": list(c.evidence or []),
            "detected_types": list(c.detected_types or []),
            "classification_status": c.classification_status,
            "review_required": c.review_required,
            "review_id": r.id if r else None,
            "review_status": r.status if r else None,
            "reviewer_username": r.reviewer_username if r else None,
            "rule_pack_version": c.rule_pack_version,
        }
        for c, r in rows
    }
