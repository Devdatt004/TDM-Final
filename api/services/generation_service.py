import os
from sqlalchemy.orm import Session
from api.services.validation_service import validate_row_count
from api.services.audit_service import log_activity_start, log_activity_finish
from api.services.source_service import get_source_kind
from api.services.source_connector_service import assert_table_in_source
from fastapi import HTTPException
from sqlalchemy import desc
from metadata_store.models import AnalysisRun, ClassificationResult, ClassificationReview
from synthetic_generation import generator as synthetic_generator

def generate_synthetic_data_flow(db: Session, table_name: str, rows: int, purpose: str, username: str,
                                 source_id: str = None):
    validate_row_count(rows)

    # Enforce Step 9 against the latest profiling run for this exact source/table.
    latest_run_query = db.query(AnalysisRun).filter(AnalysisRun.source_table == table_name)
    if source_id is None:
        latest_run_query = latest_run_query.filter(AnalysisRun.source_id.is_(None))
    else:
        latest_run_query = latest_run_query.filter(AnalysisRun.source_id == source_id)
    latest_run = latest_run_query.order_by(desc(AnalysisRun.run_timestamp), desc(AnalysisRun.id)).first()
    if latest_run:
        classifications = db.query(ClassificationResult).filter(
            ClassificationResult.run_id == latest_run.id,
            ClassificationResult.review_required.is_(True),
        ).all()
        for classification in classifications:
            review = db.query(ClassificationReview).filter(
                ClassificationReview.classification_result_id == classification.id
            ).first()
            if not review or review.status != "APPROVED":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Human review is required before generating data for {table_name}. "
                        f"Column '{classification.column_name}' has review status "
                        f"'{review.status if review else 'MISSING'}'. Review and approve it first."
                    ),
                )

    activity_name = "Masking Preview" if purpose == "masking" else "Synthetic Data Generation"
    if source_id:
        # 404 unless the source exists AND the table really belongs to it.
        source = assert_table_in_source(db, source_id, table_name)
        source_type = f"Registered {source.source_type} source: {source.name}"
    else:
        source_type, _ = get_source_kind(db, table_name, username)
    entry = log_activity_start(db, activity_name, source=table_name, source_type=source_type, user=username)
    
    try:
        result = synthetic_generator.generate_synthetic_table(
            db, table_name, num_rows=rows, source_id=source_id)
    except Exception as e:
        log_activity_finish(db, entry, "failed", str(e))
        raise e

    output_path = os.path.join(synthetic_generator.OUTPUT_DIR, result["file_name"])
    log_activity_finish(
        db, entry, "complete",
        f"Generated {result['row_count']} rows -> {result['file_name']}",
        file_path=output_path,
    )
    return result
