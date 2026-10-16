"""
scripts/seed_reviews.py

Seeds realistic human-review items by running profiling on all available
demo tables (healthcare + banking). Profiling automatically creates
ClassificationReview rows for any column whose classification confidence
is below the high-confidence threshold.

Run from the TDM Platform project root:
    python scripts/seed_reviews.py
"""

import sys
import os

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "Connectors"))
sys.path.insert(0, os.path.join(ROOT, "Profiling"))
sys.path.insert(0, os.path.join(ROOT, "pattern_analysis"))
sys.path.insert(0, os.path.join(ROOT, "agents"))
sys.path.insert(0, os.path.join(ROOT, "synthetic_generation"))

os.environ.setdefault("TDM_AUTH_MODE", "development")

# ── Imports ──────────────────────────────────────────────────────────────────
from metadata_store.db import SessionLocal
from metadata_store.models import (
    ClassificationResult,
    ClassificationReview,
    AnalysisRun,
)
from api.services.profiling_service import run_profiling
from Profiling.sampling import SamplingSpec

TABLES = [
    "patients",
    "doctors",
    "appointments",
    "insurance_claims",
    "customers",
    "accounts",
    "transactions",
    "loans",
]

SAMPLE_SIZE = 100


def main():
    db = SessionLocal()
    try:
        existing = db.query(ClassificationReview).count()
        if existing > 0:
            print(f"[seed_reviews] {existing} review(s) already exist — skipping seed.")
            print("  To re-seed, delete the existing reviews from the DB first.")
            return

        print(f"[seed_reviews] Profiling {len(TABLES)} tables to generate review items...\n")

        spec = SamplingSpec(method="head", size=SAMPLE_SIZE, seed=42)
        total_reviews = 0

        for table in TABLES:
            try:
                result = run_profiling(db, table, spec, username="seed-script")
                run_id = result["run_id"]

                # Count how many reviews were created for this run
                reviews = (
                    db.query(ClassificationReview)
                    .join(ClassificationResult,
                          ClassificationReview.classification_result_id == ClassificationResult.id)
                    .filter(ClassificationResult.run_id == run_id)
                    .count()
                )
                total_reviews += reviews
                print(f"  OK  {table:25s}  run_id={run_id}  "
                      f"fields={result['total_fields']}  review_items={reviews}")

            except Exception as exc:
                print(f"  FAIL  {table:25s}  FAILED: {exc}")

        print(f"\n[seed_reviews] Done. {total_reviews} review item(s) created in total.")
        print("  Open the Human Review tab and refresh to see them.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
