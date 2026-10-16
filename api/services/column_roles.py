"""
api/services/column_roles.py

Shared vocabulary for what a column IS, used by masking (Step 10) and the
privacy gate (Step 13): join keys and direct-identifier types.
"""

import re

# Most specific first: a column carrying several detected types maps to the first match.
IDENTIFIER_TYPES = (
    "SSN", "AADHAAR_NUMBER", "PAN_NUMBER", "MRN", "INSURANCE_ID", "NPI",
    "CREDIT_CARD", "CREDIT_CARD_CANDIDATE", "ACCOUNT_NUMBER", "EMAIL", "PHONE",
)
KEY_NAME_RE = re.compile(r"(^id$|_id$)", re.IGNORECASE)


def graph_key_columns(graph, table: str) -> set:
    """Columns of ``table`` that are FKs or referenced keys in the relationship graph."""
    cols = {r.child_column for r in graph.relationships if r.child_table == table}
    return cols | set(graph.referenced_columns(table))


def is_key(graph_keys: set, column: str) -> bool:
    return column in graph_keys or bool(KEY_NAME_RE.search(column))


def identifier_type(classification):
    """First IDENTIFIER_TYPES entry among a classification's pattern/detected types."""
    candidates = [classification.pattern_type] + list(classification.detected_types or [])
    for id_type in IDENTIFIER_TYPES:
        if id_type in candidates:
            return id_type
    return None
