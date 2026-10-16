"""
scripts/seed_reviews_demo.py

Inserts a rich set of demo review items directly into the DB, covering
a variety of sensitivity levels and pattern types — so the Human Review
tab has meaningful data to show right away.

Run from the TDM Platform project root:
    python scripts/seed_reviews_demo.py
"""

import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("TDM_AUTH_MODE", "development")

from datetime import datetime, timedelta
from metadata_store.db import SessionLocal
from metadata_store.models import (
    AnalysisRun, ColumnResult, ClassificationResult, ClassificationReview
)

DEMO_ITEMS = [
    # (table, column, pattern_type, sensitivity, confidence, evidence_label)
    ("patients",         "ssn",              "SSN",            "sensitive",     0.62, "Partial SSN pattern match"),
    ("patients",         "email",            "EMAIL",          "sensitive",     0.71, "Email-like strings found"),
    ("patients",         "notes",            "FREE_TEXT",      "unknown",       0.38, "Unstructured text — manual review needed"),
    ("patients",         "gender",           "CATEGORICAL",    "unknown",       0.55, "Low-entropy categorical; may encode PII"),
    ("doctors",          "npi_number",       "IDENTIFIER",     "sensitive",     0.58, "Numeric ID — possible NPI"),
    ("doctors",          "phone_office",     "PHONE",          "sensitive",     0.67, "Phone number detected"),
    ("appointments",     "diagnosis_code",   "ICD_CODE",       "sensitive",     0.49, "ICD-10 code suspected"),
    ("appointments",     "remarks",          "FREE_TEXT",      "unknown",       0.33, "Free-text clinical notes"),
    ("insurance_claims", "claim_amount",     "CURRENCY",       "unknown",       0.44, "Monetary value — sensitivity unclear"),
    ("insurance_claims", "provider_id",      "IDENTIFIER",     "sensitive",     0.51, "Provider reference ID"),
    ("customers",        "pan_number",       "PAN_NUMBER",     "sensitive",     0.60, "Indian tax ID pattern"),
    ("customers",        "aadhaar",          "AADHAAR_NUMBER", "sensitive",     0.55, "12-digit numeric — possible Aadhaar"),
    ("customers",        "address_line2",    "FREE_TEXT",      "unknown",       0.41, "Partial address data"),
    ("accounts",         "ifsc_code",        "IFSC_CODE",      "sensitive",     0.72, "IFSC bank code detected"),
    ("transactions",     "narration",        "FREE_TEXT",      "unknown",       0.36, "Payment narration — may contain PII"),
    ("transactions",     "merchant_name",    "ENTITY_NAME",    "unknown",       0.48, "Named entity — needs review"),
    ("loans",            "collateral_desc",  "FREE_TEXT",      "unknown",       0.30, "Collateral description text"),
    ("loans",            "co_borrower_id",   "IDENTIFIER",     "sensitive",     0.53, "Co-borrower reference ID"),
]

def main():
    db = SessionLocal()
    try:
        existing = db.query(ClassificationReview).count()
        print(f"[seed_reviews_demo] Existing review rows: {existing}")

        # Find or create a synthetic "demo seed" analysis run for each table
        table_run_ids = {}

        for (table, column, pattern_type, sensitivity, confidence, evidence_label) in DEMO_ITEMS:
            if table not in table_run_ids:
                # Check if a run already exists for this table (from previous profiling)
                run = (
                    db.query(AnalysisRun)
                    .filter(AnalysisRun.source_table == table)
                    .order_by(AnalysisRun.run_timestamp.desc())
                    .first()
                )
                if not run:
                    run = AnalysisRun(
                        source_table=table,
                        source_id=None,
                        sample_size=100,
                        total_fields=10,
                        high_confidence_count=5,
                        needs_review_count=5,
                        status="complete",
                        sampling_method="head",
                        sampling_seed=42,
                        run_timestamp=datetime.utcnow() - timedelta(hours=2),
                    )
                    db.add(run)
                    db.flush()
                table_run_ids[table] = run.id

            run_id = table_run_ids[table]

            # Skip if this (run_id, column_name) classification already exists
            already = (
                db.query(ClassificationResult)
                .filter(
                    ClassificationResult.run_id == run_id,
                    ClassificationResult.column_name == column,
                )
                .first()
            )
            if already:
                # Check if review already exists
                rev = (
                    db.query(ClassificationReview)
                    .filter(ClassificationReview.classification_result_id == already.id)
                    .first()
                )
                if not rev:
                    db.add(ClassificationReview(
                        classification_result_id=already.id,
                        status="PENDING",
                        proposed_pattern_type=already.pattern_type,
                        proposed_sensitivity=already.sensitivity,
                        created_at=datetime.utcnow() - timedelta(minutes=30),
                    ))
                    print(f"  + review for existing  {table}.{column}")
                else:
                    print(f"  ~ skip (review exists) {table}.{column}")
                continue

            # Insert ClassificationResult
            clf = ClassificationResult(
                run_id=run_id,
                source_id=None,
                source_version=None,
                table_name=table,
                column_name=column,
                pattern_type=pattern_type,
                pattern_confidence=confidence,
                sensitivity=sensitivity,
                sensitivity_confidence=confidence,
                evidence=[{"rule": "demo_seed", "label": evidence_label}],
                detected_types=[pattern_type],
                classification_status="needs_review",
                review_required=True,
                rule_pack_version="1.0.0",
                created_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.add(clf)
            db.flush()

            # Insert ClassificationReview
            rev = ClassificationReview(
                classification_result_id=clf.id,
                status="PENDING",
                proposed_pattern_type=pattern_type,
                proposed_sensitivity=sensitivity,
                created_at=datetime.utcnow() - timedelta(minutes=45),
            )
            db.add(rev)
            print(f"  + {table}.{column}  [{pattern_type}]  sensitivity={sensitivity}  confidence={confidence:.0%}")

        db.commit()

        total = db.query(ClassificationReview).count()
        print(f"\n[seed_reviews_demo] Done. Total review items in DB: {total}")
        print("  Open the Human Review tab and click Refresh to see them.")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
