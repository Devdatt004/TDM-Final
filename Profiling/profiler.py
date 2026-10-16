"""
profiler.py

Phase 2 of the pipeline: PROFILING.

Given a list of sampled rows (from our connector), compute basic statistics
per column. This tells us WHAT a column looks like, before we try to guess
WHAT KIND of sensitive data it might be (that's the rule engine's job, next).

Three signals per column:
  1. null_percent      - how much of the data is missing
  2. distinct_count     - how many unique values appear
  3. format_signature  - a "fingerprint" of the value's shape
"""

import re
from collections import Counter


def get_format_signature(value: str) -> str:
    """
    Turns a value into a shape fingerprint by replacing:
      - each digit with 'D'
      - each letter with 'A'
      - keeping punctuation/spaces as-is

    Examples:
      "796-24-9797"          -> "DDD-DD-DDDD"
      "noor.taylor1@outlook.com" -> "AAAA.AAAAAAA-A@AAAAAAA.AAA"  (roughly)
      "(314) 500-8123"        -> "(DDD) DDD-DDDD"

    Why this matters: two SSNs will always produce the SAME signature
    ("DDD-DD-DDDD"), even though the actual digits differ. That consistency
    is what makes this useful as a detection signal later.
    """
    if value is None:
        return ""

    value = str(value)
    signature_chars = []
    for ch in value:
        if ch.isdigit():
            signature_chars.append("D")
        elif ch.isalpha():
            signature_chars.append("A")
        else:
            signature_chars.append(ch)  # keep punctuation, spaces, symbols
    return "".join(signature_chars)


def profile_column(values: list) -> dict:
    """
    Given all sampled values for ONE column, compute the 3 profiling signals.
    'values' is a plain Python list, e.g. ["796-24-9797", "754-74-4258", None]
    """
    total_count = len(values)
    null_count = sum(1 for v in values if v is None or str(v).strip() == "")
    non_null_values = [v for v in values if v is not None and str(v).strip() != ""]

    null_percent = round((null_count / total_count) * 100, 2) if total_count > 0 else 0.0
    distinct_count = len(set(non_null_values))

    # Compute format signatures for every non-null value, then find the
    # MOST COMMON one - that's the "dominant shape" of this column.
    signatures = [get_format_signature(v) for v in non_null_values]
    signature_counts = Counter(signatures)
    dominant_signature = signature_counts.most_common(1)[0][0] if signatures else ""
    # What fraction of values actually match that dominant shape?
    # (A column where every value matches the same shape is a strong signal
    # it's a structured field like SSN/phone, not freeform text.)
    dominant_signature_ratio = (
        round(signature_counts[dominant_signature] / len(signatures), 2)
        if signatures else 0.0
    )

    return {
        "total_count": total_count,
        "null_percent": null_percent,
        "distinct_count": distinct_count,
        "dominant_format_signature": dominant_signature,
        "dominant_signature_ratio": dominant_signature_ratio,  # 0.0 to 1.0
    }


def profile_table(rows: list) -> dict:
    """
    Given a list of row-dictionaries (exactly what our connector's sample()
    method returns), profile EVERY column found in those rows.

    Returns a dict like:
      {
        "ssn": { ...profile... },
        "email": { ...profile... },
        ...
      }
    """
    if not rows:
        return {}

    column_names = rows[0].keys()
    profiles = {}

    for col in column_names:
        values = [row[col] for row in rows]
        profiles[col] = profile_column(values)

    return profiles


# ------------------------------------------------------------------
# Self-test: run the connector + profiler together
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os

    # Allow importing db_connector.py from the connectors/ folder
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "connectors"))
    from db_connector import DBConnector

    connector = DBConnector("sqlite:///hospital.db")
    connector.connect()

    # Pull a bigger sample this time (50 rows) so stats are more meaningful
    rows = connector.sample("patients", limit=50)

    profiles = profile_table(rows)

    print("\n--- Profiling results for 'patients' ---\n")
    for col, stats in profiles.items():
        print(f"Column: {col}")
        print(f"   total_count               : {stats['total_count']}")
        print(f"   null_percent              : {stats['null_percent']}%")
        print(f"   distinct_count             : {stats['distinct_count']}")
        print(f"   dominant_format_signature : {stats['dominant_format_signature']}")
        print(f"   dominant_signature_ratio  : {stats['dominant_signature_ratio']}")
        print()
