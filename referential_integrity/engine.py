"""
referential_integrity/engine.py

Data Relationship Engine - the piece that sits AFTER the per-column value
generator and enforces the relationships:

  1. tables are generated parent-first (order comes from graph.py);
  2. primary / referenced key columns get unique synthetic identifiers;
  3. every foreign key is filled by picking a key that already exists in the
     Identifier Registry - so an orphan can never be produced;
  4. foreign keys that must agree with each other (claim.patient_id vs the
     patient of claim.appointment_id) are COPIED from the same parent row;
     identifier columns that describe the same fact (claim.member_id vs
     patient.insurance_member_id) are copied from the parent too.

Ordinary (non-key) columns are still produced by the existing column
generator; it is passed in as `value_fn`, so this module has no dependency
on Faker, SQLAlchemy or the metadata store.
"""

import random
from dataclasses import dataclass, field

from .registry import IdentifierRegistry

_NUMERIC_TYPES = ("INT", "SERIAL")


@dataclass
class ColumnSpec:
    name: str
    data_type: str = ""
    pattern_type: str = "N/A"
    null_percent: float = 0.0        # from the profiling run; only used for FK columns


@dataclass
class TableSpec:
    name: str
    columns: list
    pk_columns: list = field(default_factory=list)
    row_count: int = 50


@dataclass
class GenerationResult:
    tables: dict            # table -> list of row dicts
    registry: IdentifierRegistry
    order: list
    warnings: list
    shared_attributes: list = field(default_factory=list)


def _is_integer(data_type):
    return any(t in (data_type or "").upper() for t in _NUMERIC_TYPES)


# Structured IDENTIFIER patterns (see pattern_analysis/pattern_types.yaml) that describe the
# same real-world attribute wherever they appear. If a child table holds one of these and its
# parent table holds exactly one column of the same pattern, the child copies the parent's
# value: a claim's member id must be the member id of the claim's patient. Dates, phones and
# zip codes are deliberately NOT here - two DATE columns are rarely the same fact.
IDENTITY_PATTERNS = {"MRN", "INSURANCE_ID", "SSN", "ACCOUNT_NUMBER", "CREDIT_CARD",
                     "PAN_NUMBER", "AADHAAR_NUMBER"}


def shared_attribute_links(graph, specs, table):
    """[(child_column, relationship, parent_column)] - non-key columns of `table` that must
    carry the same value as a column of the parent row the table's foreign key points at."""
    spec = specs[table]
    rels = [r for r in graph.parents_of(table) if not r.is_self_reference and r.parent_table in specs]
    fk_cols = {r.child_column for r in graph.parents_of(table)}
    own_keys = set(spec.pk_columns) | graph.referenced_columns(table)
    links = []
    for col in spec.columns:
        if col.pattern_type not in IDENTITY_PATTERNS or col.name in fk_cols or col.name in own_keys:
            continue
        for r in rels:
            parent = specs[r.parent_table]
            parent_keys = set(parent.pk_columns) | graph.referenced_columns(r.parent_table)
            matches = [c.name for c in parent.columns
                       if c.pattern_type == col.pattern_type and c.name not in parent_keys]
            if len(matches) == 1:
                links.append((col.name, r, matches[0]))
                break
    return links


def _make_key(col, index, used, value_fn):
    """One unique synthetic identifier for a key column."""
    if _is_integer(col.data_type):
        return index + 1                                  # 1, 2, 3 ...
    for _ in range(25):                                   # keep the realistic pattern if we can
        candidate = value_fn(col.name, col.pattern_type, col.data_type)
        if candidate not in used:
            return candidate
    return f"{col.name.upper()}-{index + 1:06d}"          # guaranteed-unique fallback


def _build_pool(values, n, rng, unique, ensure_coverage):
    """n parent keys to hand out to n child rows."""
    if unique:                                            # 1:1 (child PK is the FK)
        return rng.sample(values, n)
    if ensure_coverage and n >= len(values):              # every parent gets >= 1 child
        pool = list(values)
        pool += rng.choices(values, k=n - len(values))
        rng.shuffle(pool)
        return pool
    return rng.choices(values, k=n)


def generate_related(graph, specs, order, value_fn, rng=None, ensure_parent_coverage=True):
    rng = rng or random.Random()
    registry = IdentifierRegistry()
    out, warnings, shared_attributes = {}, [], []

    for table in order:
        spec = specs[table]
        colmap = {c.name: c for c in spec.columns}
        rels = graph.parents_of(table)
        fk_cols = {r.child_column for r in rels}
        self_rels = [r for r in rels if r.is_self_reference]
        derived = graph.derivations(table)
        primary = [r for r in rels if not r.is_self_reference and r not in derived]

        key_cols = (set(spec.pk_columns) | graph.referenced_columns(table)) & set(colmap)
        gen_key_cols = key_cols - fk_cols               # keys we mint ourselves
        pk_is_fk = set(spec.pk_columns) & fk_cols       # 1:1 child tables

        # ---- how many rows, and which parent key each row will point at ----
        n = spec.row_count
        pools = {}
        for r in primary:
            parent_vals = registry.values(r.parent_table, r.parent_column)
            if not parent_vals:
                raise ValueError(
                    f"'{table}.{r.child_column}' references {r.parent_key}, but "
                    f"'{r.parent_table}' produced no rows to reference.")
            if r.child_column in pk_is_fk and n > len(parent_vals):
                warnings.append(
                    f"{table}: limited to {len(parent_vals)} rows because "
                    f"{r.child_column} is both its primary key and a foreign key to {r.parent_table}.")
                n = len(parent_vals)
        for r in primary:
            pools[r.child_column] = _build_pool(
                registry.values(r.parent_table, r.parent_column), n, rng,
                unique=r.child_column in pk_is_fk, ensure_coverage=ensure_parent_coverage)

        # ---- build the rows ------------------------------------------------
        links = shared_attribute_links(graph, specs, table)
        shared_attributes.extend(
            f"{table}.{c} <- {r.parent_table}.{pc}" for c, r, pc in links)
        used = {c: set() for c in gen_key_cols}
        rows = []
        for i in range(n):
            row = {}
            for col in spec.columns:
                if col.name in gen_key_cols:
                    v = _make_key(col, i, used[col.name], value_fn)
                    used[col.name].add(v)
                    row[col.name] = v
                elif col.name not in fk_cols:
                    row[col.name] = value_fn(col.name, col.pattern_type, col.data_type)
                else:
                    row[col.name] = None

            done = set()
            for r in primary:                                       # 1. independent FKs
                null_pct = colmap[r.child_column].null_percent if r.child_column in colmap else 0.0
                keep_null = r.nullable and null_pct > 0 and rng.random() * 100 < null_pct
                row[r.child_column] = None if keep_null else pools[r.child_column][i]
                done.add(r.child_column)

            pending = dict(derived)                                 # 2. FKs copied from a sibling FK's parent row
            while pending:
                progressed = False
                for d, (via, via_col) in list(pending.items()):
                    if via.child_column not in done:
                        continue
                    via_val = row[via.child_column]
                    parent_row = registry.row_for(via.parent_table, via.parent_column, via_val) \
                        if via_val is not None else None
                    value = parent_row.get(via_col) if parent_row else None
                    if value is None and not d.nullable:
                        # Nothing to copy (the sibling FK is empty, e.g. a transaction with no card)
                        # but this FK is required: pick any existing parent instead of leaving NULL.
                        candidates = registry.values(d.parent_table, d.parent_column)
                        value = rng.choice(candidates) if candidates else None
                    row[d.child_column] = value
                    done.add(d.child_column)
                    del pending[d]
                    progressed = True
                if not progressed:                                  # unresolved chain - leave NULL
                    for d in pending:
                        row[d.child_column] = None
                    break

            for r in self_rels:                                     # 3. hierarchy inside one table
                earlier = [x[r.parent_column] for x in rows]
                null_pct = colmap[r.child_column].null_percent if r.child_column in colmap else 0.0
                if earlier:
                    keep_null = r.nullable and null_pct > 0 and rng.random() * 100 < null_pct
                    row[r.child_column] = None if keep_null else rng.choice(earlier)
                else:
                    row[r.child_column] = None if r.nullable else row[r.parent_column]

            for col_name, r, parent_col in links:                   # 4. same entity -> same value
                fk_val = row.get(r.child_column)
                parent_row = registry.row_for(r.parent_table, r.parent_column, fk_val) \
                    if fk_val is not None else None
                if parent_row is not None:
                    row[col_name] = parent_row.get(parent_col)
            rows.append(row)

        out[table] = rows
        for col in key_cols:                                        # remember the identifiers
            for row in rows:
                if row[col] is not None:
                    registry.register(table, col, row[col], row=row)

    return GenerationResult(tables=out, registry=registry, order=list(order),
                            warnings=warnings, shared_attributes=shared_attributes)
