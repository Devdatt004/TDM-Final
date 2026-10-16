"""
referential_integrity/service.py

Glue between the Data Relationship Validation engine (graph / engine / validator -
pure Python) and the rest of the platform (metadata store + source database
connector). api/main.py only calls the functions in here.

Pipeline (same as the design document):

  Source schema -> Relationship Discovery -> Relationship Graph (stored in
  metadata_store.db) -> Synthetic Generation (existing column generator) ->
  Relationship Engine -> Validation Engine -> Publish (CSV files)

Boundary kept: only SCHEMA metadata (tables, columns, primary/foreign keys)
and row COUNTS are read from the source. No real row values are read.
Datasets are published only if validation passes.
"""

import json
import random
from datetime import datetime

from sqlalchemy import column, func, inspect, select, table as sa_table, text

from metadata_store.models import (
    AnalysisRun, SyntheticDataset, TableRelationship, IntegrityRun,
)
from .graph import Relationship, RelationshipGraph, CyclicRelationshipError, relationship_kind
from .discovery import discover, candidate_parents, type_family, BASIS_TEXT
from .engine import ColumnSpec, TableSpec, generate_related
from .validator import validate

MAX_ROWS_PER_TABLE = 1000
PREVIEW_ROWS = 5


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _schema(connector):
    return discover(inspect(connector.engine))


def _source_counts(connector, schema):
    """COUNT(*) per table - aggregate only, no row values. Table names come
    from the inspector, never from user input."""
    counts = {}
    with connector.engine.connect() as conn:
        for t in schema.columns:
            try:
                counts[t] = int(conn.execute(select(func.count()).select_from(sa_table(t))).scalar() or 0)
            except Exception:
                counts[t] = None
    return counts


def _source_fanout(connector, graph, tables, counts):
    """Average children per parent measured on the source: non-null FK
    references / parent rows. Used only for the informational distribution check."""
    out = {}
    with connector.engine.connect() as conn:
        for r in graph.relationships:
            if r.child_table in tables and r.parent_table in tables and counts.get(r.parent_table):
                try:
                    refs = conn.execute(
                        select(func.count(column(r.child_column))).select_from(sa_table(r.child_table))).scalar() or 0
                    out[r.child_key] = refs / counts[r.parent_table]
                except Exception:
                    pass
    return out


def _default_rows(source_count):
    if not source_count:
        return 50
    return max(1, min(int(source_count), MAX_ROWS_PER_TABLE))


def _store_discovered(db, schema):
    """Replace the 'discovered' (declared) rows of THIS source's tables with what its
    schema declares now; manually added (undeclared) relationships are kept, and so are
    the relationships of other domains (table names are unique across domains)."""
    db.query(TableRelationship).filter(
        TableRelationship.origin == "discovered",
        TableRelationship.child_table.in_(list(schema.columns)),
    ).delete(synchronize_session=False)
    taken = {(r.child_table, r.child_column) for r in db.query(TableRelationship).all()}
    for r in schema.relationships:
        if (r.child_table, r.child_column) not in taken:
            db.add(TableRelationship(**r.to_dict()))
    db.commit()


def load_graph(db, tables=None):
    """The stored relationship graph. `tables` (a set of table names) limits it to one
    source/domain: only relationships whose child AND parent are in that set."""
    rows = db.query(TableRelationship).order_by(TableRelationship.id).all()
    if tables is not None:
        rows = [r for r in rows if r.child_table in tables and r.parent_table in tables]
    graph = RelationshipGraph([
        Relationship(r.child_table, r.child_column, r.parent_table, r.parent_column,
                     r.origin, bool(r.nullable))
        for r in rows
    ])
    return graph, rows


# ---------------------------------------------------------------------------
# Relationship graph - discovery / read / manual edits
# ---------------------------------------------------------------------------

def relationship_overview(db, connector, refresh=False):
    schema = _schema(connector)
    all_tables = set(schema.columns)
    graph, rows = load_graph(db, all_tables)
    if refresh or not rows:
        _store_discovered(db, schema)
        graph, rows = load_graph(db, all_tables)
    counts = _source_counts(connector, schema)

    cycle_error, levels = None, {}
    try:
        order = graph.generation_order(all_tables)
        levels = graph.levels(all_tables)
    except CyclicRelationshipError as e:
        order, cycle_error = sorted(all_tables), str(e)

    tables = []
    for t in order:
        tables.append({
            "name": t,
            "columns": len(schema.columns[t]),
            "primary_key": schema.pk_columns[t],
            "row_count": counts.get(t),
            "default_rows": _default_rows(counts.get(t)),
            "level": levels.get(t, 0),
            "parents": sorted({r.parent_table for r in graph.parents_of(t) if not r.is_self_reference}),
            "children": sorted({r.child_table for r in graph.children_of(t) if not r.is_self_reference}),
        })

    return {
        "relationships": [
            {"id": row.id, **Relationship(
                row.child_table, row.child_column, row.parent_table, row.parent_column,
                row.origin, bool(row.nullable)).to_dict(),
             "kind": relationship_kind(row.origin),
             "label": f"{row.child_table}.{row.child_column} -> {row.parent_table}.{row.parent_column}"}
            for row in rows
        ],
        "summary": {
            "declared": sum(1 for row in rows if relationship_kind(row.origin) == "declared"),
            "undeclared": sum(1 for row in rows if relationship_kind(row.origin) == "undeclared"),
        },
        "metadata_graph": graph.to_metadata_dict(),
        "generation_order": order,
        "tables": tables,
        "skipped": schema.skipped,
        "cycle_error": cycle_error,
    }


def relationship_health(db, connector):
    """Step 11 - integrity health of the SOURCE data for every stored relationship.

    Exact aggregates computed in the database (COUNT / COUNT DISTINCT / MAX of a
    grouped count); no row values leave the source. Table and column names come
    from the stored graph, which was built from the inspector, never from user input.
    """
    schema = _schema(connector)
    graph, _ = load_graph(db, set(schema.columns))
    out = []
    with connector.engine.connect() as conn:
        for r in graph.relationships:
            child = sa_table(r.child_table, column(r.child_column))
            parent = sa_table(r.parent_table, column(r.parent_column))
            cc, pc = child.c[r.child_column], parent.c[r.parent_column]
            try:
                child_rows = conn.execute(select(func.count()).select_from(child)).scalar() or 0
                refs = conn.execute(select(func.count(cc))).scalar() or 0
                orphans = conn.execute(
                    select(func.count(cc)).where(cc.is_not(None), cc.not_in(select(pc).where(pc.is_not(None))))
                ).scalar() or 0
                parent_rows = conn.execute(select(func.count(pc))).scalar() or 0
                parent_distinct = conn.execute(select(func.count(func.distinct(pc)))).scalar() or 0
                referenced = conn.execute(
                    select(func.count(func.distinct(cc))).where(cc.in_(select(pc)))).scalar() or 0
                per_parent = select(func.count().label("n")).where(cc.is_not(None)).group_by(cc).subquery()
                max_children = conn.execute(select(func.max(per_parent.c.n))).scalar() or 0
            except Exception:
                out.append({"relationship": f"{r.child_key} -> {r.parent_key}", "error": "could not be measured"})
                continue
            out.append({
                "relationship": f"{r.child_key} -> {r.parent_key}",
                "kind": r.kind,
                "child_rows": int(child_rows),
                "null_references": int(child_rows - refs),
                "orphan_references": int(orphans),
                "orphan_rate": round(orphans / refs, 4) if refs else 0.0,
                "parent_rows": int(parent_rows),
                "duplicate_parent_keys": int(parent_rows - parent_distinct),
                "parents_referenced": int(referenced),
                "parent_coverage": round(referenced / parent_distinct, 4) if parent_distinct else 0.0,
                "avg_children_per_parent": round((refs - orphans) / parent_distinct, 2) if parent_distinct else 0.0,
                "max_children_per_parent": int(max_children),
                "exact": True,
            })
    return {"relationships": out, "measured": len(out)}


MIN_INFERRED_MATCH = 95.0     # % of distinct child values that must exist in the parent


def suggest_relationships(db, connector):
    """Find relationships NOBODY DECLARED. A column is a candidate when its name follows a
    key convention (see discovery.candidate_parents: the same name as another table's
    single-column primary key, '<table>_id', or a role-prefixed key such as
    settlement_account_id), the types are compatible, and nearly every distinct value
    appears in the parent. Only distinct-value COUNTS are computed in the
    database - no row values are read. Suggestions are not saved; the user
    accepts the ones that are right (they then become 'manual' = undeclared relationships)."""
    schema = _schema(connector)
    taken = {(r.child_table, r.child_column) for r in db.query(TableRelationship).all()}
    parents = {t: pk[0] for t, pk in schema.pk_columns.items() if len(pk) == 1}

    suggestions = []
    with connector.engine.connect() as conn:
        for child, cols in schema.columns.items():
            for col in cols:
                cname = col["name"]
                if (child, cname) in taken or cname in schema.pk_columns.get(child, []):
                    continue
                for parent, pk, basis in candidate_parents(child, cname, parents):
                    pk_type = next(c["type"] for c in schema.columns[parent] if c["name"] == pk)
                    if type_family(col["type"]) != type_family(pk_type):
                        continue
                    ct, pt = sa_table(child, column(cname)), sa_table(parent, column(pk))
                    try:
                        distinct = conn.execute(select(func.count(func.distinct(ct.c[cname])))).scalar() or 0
                        if not distinct:
                            continue
                        matched = conn.execute(
                            select(func.count(func.distinct(ct.c[cname])))
                            .where(ct.c[cname].in_(select(pt.c[pk])))).scalar() or 0
                    except Exception:
                        continue
                    pct = round(100.0 * matched / distinct, 1)
                    if pct >= MIN_INFERRED_MATCH:
                        suggestions.append({
                            "child_table": child, "child_column": cname,
                            "parent_table": parent, "parent_column": pk,
                            "match_percent": pct, "distinct_values": int(distinct),
                            "orphan_values": int(distinct - matched),
                            "basis": basis,
                            "reason": BASIS_TEXT[basis] + " and its values exist in the parent",
                        })
    suggestions.sort(key=lambda x: (-x["match_percent"], x["child_table"], x["child_column"]))
    return suggestions


def add_manual_relationship(db, connector, child_table, child_column, parent_table, parent_column):
    schema = _schema(connector)
    for t, c in ((child_table, child_column), (parent_table, parent_column)):
        if t not in schema.columns:
            raise ValueError(f"Table '{t}' does not exist in the source database.")
        if c not in {col["name"] for col in schema.columns[t]}:
            raise ValueError(f"Column '{c}' does not exist in table '{t}'.")
    if db.query(TableRelationship).filter(
            TableRelationship.child_table == child_table,
            TableRelationship.child_column == child_column).first():
        raise ValueError(f"{child_table}.{child_column} already has a relationship.")

    nullable = next(c["nullable"] for c in schema.columns[child_table] if c["name"] == child_column)
    new = Relationship(child_table, child_column, parent_table, parent_column, "manual", nullable)
    graph, _ = load_graph(db, set(schema.columns))
    RelationshipGraph(graph.relationships + [new]).generation_order(set(schema.columns))  # raises on a cycle

    row = TableRelationship(**new.to_dict())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, **new.to_dict()}


def delete_manual_relationship(db, relationship_id):
    row = db.query(TableRelationship).filter(TableRelationship.id == relationship_id).first()
    if not row:
        raise LookupError("Relationship not found")
    if row.origin != "manual":
        raise ValueError("Discovered relationships come from the source schema and can't be deleted here. "
                         "Only manually added relationships can be removed.")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Generate a related set of tables + validate + publish
# ---------------------------------------------------------------------------

def _latest_run(db, table):
    return (db.query(AnalysisRun).filter(AnalysisRun.source_table == table)
            .order_by(AnalysisRun.run_timestamp.desc()).first())


def generate_related_dataset(db, connector, generator, tables, row_counts=None,
                             ensure_parent_coverage=True, seed=None, profile_fn=None):
    """
    tables     tables the user asked for; their parents are added automatically
    row_counts {table: rows}; missing tables default to the source's row count (max 1000)
    generator  the synthetic_generation.generator module (column value generator + CSV writer)
    profile_fn callable(table) run for any table that has no profiling run yet
    """
    row_counts = row_counts or {}
    if not tables:
        raise ValueError("Select at least one table.")
    schema = _schema(connector)
    unknown = [t for t in tables if t not in schema.columns]
    if unknown:
        raise ValueError(f"Unknown table(s): {', '.join(unknown)}")

    graph, _ = load_graph(db, set(schema.columns))
    if not graph.relationships:
        _store_discovered(db, schema)
        graph, _ = load_graph(db, set(schema.columns))

    scope = graph.with_ancestors(tables)
    order = graph.generation_order(scope)                # raises CyclicRelationshipError
    auto_included = [t for t in order if t not in tables]
    counts = _source_counts(connector, schema)

    rc = {}
    for t in order:
        n = row_counts.get(t) or _default_rows(counts.get(t))
        if not isinstance(n, int) or not 1 <= n <= MAX_ROWS_PER_TABLE:
            raise ValueError(f"Rows for '{t}' must be between 1 and {MAX_ROWS_PER_TABLE}.")
        rc[t] = n

    # column classifications come from the latest profiling run (profile on demand)
    specs, run_ids = {}, {}
    for t in order:
        run = _latest_run(db, t)
        if run is None and profile_fn is not None:
            profile_fn(t)
            run = _latest_run(db, t)
        if run is None:
            raise ValueError("One or more tables have not been profiled yet. Run Profiling first.")
        run_ids[t] = run.id
        found = {c.column_name: c for c in run.columns}
        specs[t] = TableSpec(
            name=t,
            columns=[ColumnSpec(
                name=c["name"], data_type=c["type"],
                pattern_type=found[c["name"]].pattern_type if c["name"] in found else "N/A",
                null_percent=found[c["name"]].null_percent if c["name"] in found else 0.0,
            ) for c in schema.columns[t]],
            pk_columns=schema.pk_columns[t],
            row_count=rc[t],
        )

    generator.reset_unique_pool(seed)
    result = generate_related(graph, specs, order, generator.generate_value,
                              rng=random.Random(seed),
                              ensure_parent_coverage=ensure_parent_coverage)
    report = validate(graph, result.tables, specs,
                      source_fanout=_source_fanout(connector, graph, set(order), counts))

    published = bool(report["passed"])
    table_info = []
    for t in order:
        rows = result.tables[t]
        info = {"name": t, "rows": len(rows), "auto_included": t in auto_included,
                "columns": [c.name for c in specs[t].columns],
                "preview": rows[:PREVIEW_ROWS], "dataset_id": None, "file_name": None}
        if published:
            file_name, file_path = generator.write_table_csv(t, info["columns"], rows)
            ds = SyntheticDataset(source_table=t, run_id=run_ids[t], row_count=len(rows), file_path=file_path)
            db.add(ds)
            db.flush()
            info["dataset_id"], info["file_name"] = ds.public_id, file_name
        table_info.append(info)

    response = {
        "published": published,
        "order": order,
        "auto_included": auto_included,
        "warnings": result.warnings,
        "shared_attributes": result.shared_attributes,
        "tables": table_info,
        "score": report["score"],
        "passed": report["passed"],
        "total_references": report["total_references"],
        "valid_references": report["valid_references"],
        "checks": report["checks"],
        "relationships": report["relationships"],
        "seed": seed,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    run = IntegrityRun(tables=",".join(order), total_rows=sum(rc.values()), score=report["score"],
                       passed=published, report_json="{}")
    db.add(run)
    db.flush()
    response["run_id"] = run.id
    run.report_json = json.dumps(response, default=str)
    db.commit()
    return response


def list_integrity_runs(db, limit=50):
    rows = db.query(IntegrityRun).order_by(IntegrityRun.created_at.desc()).limit(limit).all()
    return [{"run_id": r.id, "tables": r.tables.split(","), "total_rows": r.total_rows,
             "score": r.score, "passed": bool(r.passed), "created_at": r.created_at.isoformat() + "Z"}
            for r in rows]


def get_integrity_run(db, run_id):
    row = db.query(IntegrityRun).filter(IntegrityRun.id == run_id).first()
    if not row:
        raise LookupError("Integrity run not found")
    return json.loads(row.report_json)
