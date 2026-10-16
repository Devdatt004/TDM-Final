"""
referential_integrity/registry.py

Identifier Registry - Step 3. Remembers every key value that has been
generated so far, per (table, column), so that:

  * a child row can only ever be given a parent key that REALLY exists, and
  * one logical entity gets the same synthetic identifier in every table
    where it appears (John -> Alex everywhere, never John -> Alex in one
    table and John -> Sam in another).

The optional `source` argument records the real -> synthetic mapping
(P1001 -> P5001) for flows that transform existing rows (masking / subsetting).
Pure synthetic generation has no real key to record, so it registers
synthetic values only.
"""


class IdentifierRegistry:
    def __init__(self):
        self._values = {}      # (table, column) -> [synthetic values, in order]
        self._known = {}       # (table, column) -> set(values)   fast lookup
        self._forward = {}     # (table, column, source_value) -> synthetic value
        self._rows = {}        # (table, column) -> {value: row dict}

    def register(self, table, column, synthetic, source=None, row=None):
        key = (table, column)
        self._values.setdefault(key, []).append(synthetic)
        self._known.setdefault(key, set()).add(synthetic)
        if row is not None:
            self._rows.setdefault(key, {})[synthetic] = row
        if source is not None:
            self._forward[(table, column, source)] = synthetic

    def values(self, table, column):
        return list(self._values.get((table, column), []))

    def exists(self, table, column, value):
        return value in self._known.get((table, column), ())

    def row_for(self, table, column, value):
        """The generated parent row that owns this key value."""
        return self._rows.get((table, column), {}).get(value)

    def translate(self, table, column, source_value):
        """Real -> synthetic identifier, or None if it was never registered."""
        return self._forward.get((table, column, source_value))

    def size(self, table, column):
        return len(self._values.get((table, column), ()))
