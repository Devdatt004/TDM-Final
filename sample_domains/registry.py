"""
sample_domains/registry.py

The built-in demo source databases, one per industry domain. Stdlib only.

    healthcare  -> hospital.db   (patients, doctors, appointments, insurance_claims)
    banking     -> banking.db    (Banking & Financial Services, 11 tables)

Table names are unique ACROSS domains. That is what lets the shared metadata
store keep one relationship graph without a domain column: every relationship
belongs to the domain that owns its tables. `check_table_names_disjoint()`
enforces it.

Connection strings are relative to the working directory, exactly like the
original "sqlite:///hospital.db" - the app is started from the project root.
"""

import os
import sqlite3

DEFAULT_DOMAIN = "healthcare"

DOMAINS = {
    "healthcare": {
        "label": "Healthcare",
        "db_file": "hospital.db",
        "description": "Patients, doctors, appointments and insurance claims.",
    },
    "banking": {
        "label": "Banking & Financial Services",
        "db_file": "banking.db",
        "description": "Customers, accounts, cards, transactions, lending and capital-markets trades.",
    },
}


def connection_string(domain: str) -> str:
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain '{domain}'. Available: {', '.join(DOMAINS)}")
    return f"sqlite:///{DOMAINS[domain]['db_file']}"


def db_path(domain: str) -> str:
    return connection_string(domain)[len("sqlite:///"):]


def is_available(domain: str) -> bool:
    return domain in DOMAINS and os.path.exists(db_path(domain))


def available_domains() -> list:
    """[{key, label, description, tables}] for every domain whose database file exists."""
    return [{"key": k, "label": d["label"], "description": d["description"], "tables": list_tables(k)}
            for k, d in DOMAINS.items() if is_available(k)]


def list_tables(domain: str) -> list:
    """Table names straight from sqlite_master (no SQLAlchemy needed)."""
    con = sqlite3.connect(f"file:{db_path(domain)}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    finally:
        con.close()


def domain_of_table(table: str):
    """The domain whose database owns `table`, or None."""
    for key in DOMAINS:
        if is_available(key) and table in list_tables(key):
            return key
    return None


def check_table_names_disjoint() -> None:
    seen = {}
    for key in DOMAINS:
        if not is_available(key):
            continue
        for t in list_tables(key):
            if t in seen:
                raise ValueError(f"Table '{t}' exists in both '{seen[t]}' and '{key}'. "
                                 "Table names must be unique across built-in domains.")
            seen[t] = key


def ensure_domain_databases() -> list:
    """Create missing built-in demo databases. Returns created domain keys."""
    created = []
    if not is_available("healthcare"):
        from .healthcare import build_healthcare_db
        build_healthcare_db(db_path("healthcare"))
        created.append("healthcare")
    if not is_available("banking"):
        from .banking import build_banking_db
        build_banking_db(db_path("banking"))
        created.append("banking")
    return created
