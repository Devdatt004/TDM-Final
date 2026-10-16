"""
synthetic_generation/generator.py

Synthetic Data Generation - the second big requirement from the TDD
(Section 3.1: "Synthetic Generation - produces synthetic data...").
This is the MVP slice of that layer: generate a small, realistic-looking
CSV for one table, using the classifications already sitting in the
metadata store, so nothing here has to re-guess what a column is.

How it decides what to put in each column (in priority order):
  1. The column's PATTERN TYPE from the most recent AnalysisRun
     (e.g. "SSN", "PHONE", "DATE") - this is the strongest signal,
     since it describes the actual STRUCTURE the real values had.
  2. If the pattern type is generic ("TEXT", "NUMERIC", ...), fall back
     to a heuristic on the COLUMN NAME (e.g. a column called "email"
     gets fake.email(), even though its pattern type was just
     TEXT_WITH_SEPARATOR).
  3. If neither gives a specific answer, fall back to the column's
     native SQL data type from the Schema Catalog (numeric vs text).

Nothing here reads real values out of hospital.db - only the metadata
(pattern types + native types) already materialized by /analyze. That's
the same "operate on metadata, not raw source data" boundary the rest of
the platform keeps to.

Uses Faker (https://faker.readthedocs.io) - open source, matches the
"open-source stack for the initial demo" requirement.
"""

import os
import csv
from datetime import datetime

from faker import Faker
from sqlalchemy.orm import Session

from metadata_store.models import AnalysisRun, SchemaCatalogEntry, SyntheticDataset

fake = Faker()

# Same TDM_DATA_DIR override as metadata_store/db.py - defaults to the
# project root locally, points at a persistent disk when hosted.
OUTPUT_DIR = os.path.join(
    os.getenv("TDM_DATA_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "synthetic_output",
)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _generate_value(column_name: str, pattern_type: str, data_type: str):
    """
    Produce ONE synthetic value for a column, using pattern_type first,
    then a column-name heuristic, then the native data_type as a last
    resort. See module docstring for the full priority order.
    """
    name = (column_name or "").lower()
    dtype = (data_type or "").upper()

    # ---- 1. Specific structural pattern types - highest confidence ----
    if pattern_type == "SSN":
        return fake.ssn()
    if pattern_type == "DATE":
        return fake.date_of_birth(minimum_age=0, maximum_age=95).isoformat() \
            if "dob" in name or "birth" in name else fake.date_this_decade().isoformat()
    if pattern_type == "PHONE":
        return fake.phone_number()
    if pattern_type == "ZIP_CODE":
        return fake.zipcode()
    if pattern_type == "ZIP_PLUS4":
        return fake.zipcode_plus4()
    if pattern_type == "MRN":
        return f"MRN{fake.unique.random_number(digits=6, fix_len=True)}"
    if pattern_type == "INSURANCE_ID":
        return fake.bothify(text="??#########").upper()
    if pattern_type == "CREDIT_CARD":
        return fake.numerify("####-####-####-####")
    if pattern_type == "ACCOUNT_NUMBER":
        return str(fake.unique.random_number(digits=11, fix_len=True))
    if pattern_type == "IFSC_CODE":
        return f"{fake.bothify('????').upper()}0{fake.numerify('######')}"
    if pattern_type == "PAN_NUMBER":
        return fake.bothify(text="?????####?").upper()
    if pattern_type == "AADHAAR_NUMBER":
        return fake.numerify("#### #### ####")

    # ---- 2. Generic pattern types - use the column name as a hint ----
    if "email" in name:
        return fake.email()
    NON_PERSON_NAME_HINTS = ("insurance", "bank", "company", "provider", "employer", "vendor", "organization")
    if "name" in name and any(hint in name for hint in NON_PERSON_NAME_HINTS):
        return fake.company()
    if "name" in name:
        return fake.name()
    if "address" in name:
        return fake.address().replace("\n", ", ")
    if "city" in name:
        return fake.city()
    if "state" in name:
        return fake.state_abbr()
    if name.endswith("_id") or name == "id":
        return fake.unique.random_number(digits=6, fix_len=True)
    if "age" in name:
        return fake.random_int(min=0, max=95)

    if pattern_type == "TEXT":
        return fake.word().capitalize()
    if pattern_type == "TEXT_WITH_SEPARATOR":
        return fake.sentence(nb_words=3).rstrip(".")
    if pattern_type == "NUMERIC":
        return fake.random_int(min=1, max=9999)
    if pattern_type == "NUMERIC_WITH_SEPARATOR":
        return fake.numerify("###-###")
    if pattern_type == "MIXED_ALPHANUMERIC":
        return fake.bothify(text="??#####").upper()

    # ---- 3. Last resort - fall back on the native SQL type ----
    if any(t in dtype for t in ("INT", "FLOAT", "REAL", "NUMERIC", "DECIMAL")):
        return fake.random_int(min=1, max=9999)
    return fake.word().capitalize()


def generate_synthetic_table(db: Session, table_name: str, num_rows: int = 50,
                             source_id: str = None) -> dict:
    """
    Generate `num_rows` of synthetic data for `table_name`, based on the
    MOST RECENT analysis run for that table (raises if there isn't one -
    Section 4.1 of the TDD: "synthetic data cannot [be produced] from a
    source that has not yet been classified"). Writes a CSV file and
    records a SyntheticDataset row, then returns a small JSON-friendly
    preview so the frontend doesn't have to re-open the file.

    ``source_id`` scopes everything to one registered Source: only that
    source's analysis run and schema catalog are used, and the dataset is
    recorded against it. ``None`` is the legacy (demo / uploaded file) flow.
    Nothing here connects to, or writes to, the source database.
    """
    run = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.source_table == table_name, AnalysisRun.source_id == source_id)
        .order_by(AnalysisRun.run_timestamp.desc(), AnalysisRun.id.desc())
        .first()
    )
    if not run:
        raise ValueError(
            "This source has not been profiled yet. Run Profiling first - synthetic "
            "data is generated FROM classification results, not from scratch."
        )

    # Look up each column's native data type from the Schema Catalog, if
    # it's been populated (it is, automatically, by /analyze).
    catalog_rows = (
        db.query(SchemaCatalogEntry)
        .filter(SchemaCatalogEntry.table_name == table_name,
                SchemaCatalogEntry.source_id == source_id)
        .all()
    )
    data_types = {c.column_name: c.data_type for c in catalog_rows}

    columns = run.columns  # ColumnResult rows for this run
    fake.unique.clear()   # fresh unique-value pool per generation job

    rows = []
    for _ in range(num_rows):
        row = {}
        for col in columns:
            row[col.column_name] = _generate_value(
                col.column_name, col.pattern_type, data_types.get(col.column_name, "")
            )
        rows.append(row)

    # ---- Write the CSV file ----
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"{table_name}_synthetic_{timestamp}.csv"
    file_path = os.path.join(OUTPUT_DIR, file_name)

    fieldnames = [c.column_name for c in columns]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ---- Materialize the SyntheticDataset record ----
    dataset = SyntheticDataset(
        source_table=table_name,
        source_id=source_id,
        run_id=run.id,
        row_count=num_rows,
        file_path=file_path,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return {
        "dataset_id": dataset.public_id,
        "source_id": source_id,
        "source_table": table_name,
        "run_id": run.id,
        "row_count": num_rows,
        "preview": rows[:10],
        "file_name": file_name,
    }


# ---------------------------------------------------------------------
# Helpers used by the Data Relationship Validation engine (referential_integrity/)
# ---------------------------------------------------------------------

def generate_value(column_name: str, pattern_type: str, data_type: str):
    """Public name for the per-column value generator, so other engines can
    reuse it for the NON-key columns of a table."""
    return _generate_value(column_name, pattern_type, data_type)


def reset_unique_pool(seed=None):
    """Start a fresh Faker unique-value pool (and optionally make the run
    reproducible) before generating a related set of tables."""
    fake.unique.clear()
    if seed is not None:
        fake.seed_instance(seed)


def write_table_csv(table_name: str, fieldnames: list, rows: list, kind: str = "synthetic") -> tuple:
    """Write rows to synthetic_output/<table>_<kind>_<timestamp>.csv
    (same naming as generate_synthetic_table). Returns (file_name, file_path)."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"{table_name}_{kind}_{timestamp}.csv"
    file_path = os.path.join(OUTPUT_DIR, file_name)
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return file_name, file_path
