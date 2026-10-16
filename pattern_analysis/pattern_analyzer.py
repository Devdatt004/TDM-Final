"""
pattern_analyzer.py

Standalone Pattern Analyzer (no rule engine / regex confidence logic here).

Its ONLY job: look at a column's values, figure out the common STRUCTURE
those values follow, and report it. It does NOT decide if something is
PII, and it does NOT assign a confidence score - that's a different
concern for a different component, later.

How pattern detection works:
  - Every character in a value is converted to one of 3 symbols:
      digit  -> D
      letter -> A
      anything else (symbols, spaces, punctuation) -> S
  - Example: "1995-05-12" -> "DDDDSDDSDD"
  - Values that share the same signature are grouped together and counted.
  - Each signature is then looked up in pattern_types.yaml to get a
    human-readable label (e.g. "DDDDSDDSDD" -> "DATE"). If the exact
    signature isn't in the lookup table, we fall back to a generic label
    ("NUMERIC", "TEXT", or "UNKNOWN") so the output is still meaningful.
"""

import os
import re
import yaml
from collections import Counter


def get_pattern(value: str) -> str:
    """Convert a value into its D/A/S structural signature."""
    chars = []
    for ch in str(value):
        if ch.isdigit():
            chars.append("D")
        elif ch.isalpha():
            chars.append("A")
        else:
            chars.append("S")
    return "".join(chars)


def collapse_pattern(pattern: str) -> str:
    """
    Collapse consecutive repeated symbols into one.
    e.g. "AAAASAAAAAADSAAAAAAASAAA" -> "ASADSASA"

    IMPORTANT: we only ever call this as a FALLBACK, for values that
    didn't already match a known exact pattern (see _classify_pattern
    below). That matters because collapsing throws away length info -
    e.g. a date ("DDDDSDDSDD") and an SSN ("DDDSDDSDDDD") BOTH collapse
    down to the same "DSDSD" shape. Collapsing is safe for cleaning up
    noisy free-text columns, but would break precise types like DATE/SSN
    if applied to them too. Known types are always matched on their
    exact, uncollapsed pattern first.
    """
    return re.sub(r"(.)\1+", r"\1", pattern)


class PatternAnalyzer:
    def __init__(self, pattern_types_path: str = None):
        if pattern_types_path is None:
            pattern_types_path = os.path.join(
                os.path.dirname(__file__), "pattern_types.yaml"
            )
        with open(pattern_types_path, "r") as f:
            data = yaml.safe_load(f)
        self.known_patterns = data.get("patterns", {})

    def _resolve(self, raw_pattern: str) -> tuple:
        """
        Two-tier resolution for a single value's raw pattern:

        TIER 1 - exact match: check the raw (uncollapsed) pattern against
        the known lookup table. This covers any structured identifier
        listed in pattern_types.yaml - DATE, SSN, PHONE, ZIP, and
        whatever industry-specific IDs have been added (healthcare's
        MRN, banking's ACCOUNT_NUMBER, etc.) - fields where exact length
        matters and is reliable.

        TIER 2 - fallback: if no exact match, collapse the pattern and
        classify it generically. This is where noisy, variable-length
        free text (names, emails, addresses) gets grouped sensibly
        instead of producing dozens of near-duplicate patterns.

        Returns: (grouping_key, pattern_type)
          grouping_key is what we count/group by - raw for known types,
          collapsed for everything else.
        """
        if raw_pattern in self.known_patterns:
            return raw_pattern, self.known_patterns[raw_pattern]

        collapsed = collapse_pattern(raw_pattern)
        symbols = set(collapsed)

        if symbols == {"A"}:
            pattern_type = "TEXT"
        elif symbols == {"D"}:
            pattern_type = "NUMERIC"
        elif symbols <= {"A", "S"}:
            pattern_type = "TEXT_WITH_SEPARATOR"   # e.g. emails, phrases, multi-word text
        elif symbols <= {"D", "S"}:
            pattern_type = "NUMERIC_WITH_SEPARATOR"
        else:
            pattern_type = "MIXED_ALPHANUMERIC"

        return collapsed, pattern_type

    def analyze_column(self, values: list) -> list:
        """
        Given all sampled values for ONE column, group them and report
        each distinct group found.

        Returns a list, sorted by count (most common group first):
          [
            {"pattern_type": "DATE", "pattern": "DDDDSDDSDD", "count": 3, "percentage": 100.0},
            ...
          ]

        Known structured types (DATE, SSN, PHONE, etc.) are grouped by
        their exact raw pattern - full precision, since length matters.
        Everything else is grouped by a COLLAPSED pattern, so variable-
        length free text (names, emails, addresses) doesn't fragment
        into dozens of near-identical entries that only differ by length.
        """
        non_null_values = [v for v in values if v is not None and str(v).strip() != ""]
        total = len(non_null_values)
        if total == 0:
            return []

        group_counts = Counter()       # grouping_key -> count
        group_types = {}                # grouping_key -> pattern_type

        for v in non_null_values:
            raw = get_pattern(v)
            grouping_key, pattern_type = self._resolve(raw)
            group_counts[grouping_key] += 1
            group_types[grouping_key] = pattern_type

        results = []
        for grouping_key, count in group_counts.items():
            results.append({
                "pattern_type": group_types[grouping_key],
                "pattern": grouping_key,
                "count": count,
                "percentage": round((count / total) * 100, 2),
            })

        results.sort(key=lambda r: r["count"], reverse=True)
        return results

    def analyze_table(self, rows: list) -> dict:
        """
        Given row-dictionaries (from connector.sample()), analyze EVERY
        column. Returns:
          { "dob": [ {pattern_type, pattern, count, percentage}, ... ], ... }
        """
        if not rows:
            return {}

        column_names = rows[0].keys()
        results = {}
        for col in column_names:
            values = [row[col] for row in rows]
            results[col] = self.analyze_column(values)
        return results


# ------------------------------------------------------------------
# Self-test: connector -> pattern analyzer
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "connectors"))
    from db_connector import DBConnector

    connector = DBConnector("sqlite:///hospital.db")
    connector.connect()
    rows = connector.sample("patients", limit=50)

    analyzer = PatternAnalyzer()
    results = analyzer.analyze_table(rows)

    print("\n--- Pattern Analysis results for 'patients' ---\n")
    for col, patterns in results.items():
        print(f"Column: {col}")
        for p in patterns:
            print(f"   Pattern Type : {p['pattern_type']}")
            print(f"   Pattern       : {p['pattern']}")
            print(f"   Count         : {p['count']}")
            print(f"   Percentage   : {p['percentage']}%")
            print()
