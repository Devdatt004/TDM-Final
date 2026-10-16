"""
referential_integrity/validator.py

Validation Engine - runs BEFORE a dataset is published and answers one
question: "would every join in this data still work?"

Checks (mirrors the design document):
  pk_unique          primary / referenced keys are unique and populated
  no_orphans         no child row points at a parent that does not exist
  required_fks       NOT NULL foreign keys are actually filled
  parent_child       every valid reference is accounted for; childless parents reported
  multi_level_joins  child -> parent -> grandparent ... resolves all the way up
  path_consistency   sibling FKs agree (claim.patient == claim's appointment's patient)
  attribute_consistency  identifier copies match the parent (claim.member_id == patient's)
  distribution       children-per-parent stays close to the source (informational)

Integrity score = valid foreign-key references / total non-null references x 100.
"""

from collections import Counter

from .engine import shared_attribute_links

DISTRIBUTION_TOLERANCE = 0.30      # +/-30 % of the source's avg children per parent
_MAX_EXAMPLES = 5


def _check(cid, name, status, detail, count=0):
    return {"id": cid, "name": name, "status": status, "detail": detail, "count": count}


def validate(graph, tables, specs, source_fanout=None):
    """
    tables        {table: [row dicts]}  (the generated data)
    specs         {table: TableSpec}    (for primary keys)
    source_fanout {"child.col": avg_children_per_parent}  measured on the source, optional
    """
    source_fanout = source_fanout or {}
    rels = [r for r in graph.relationships
            if r.child_table in tables and r.parent_table in tables]

    # index every referenced key column once: {(table, col): {value: row}}
    index = {}
    for r in rels:
        k = (r.parent_table, r.parent_column)
        if k not in index:
            index[k] = {row[r.parent_column]: row for row in tables[r.parent_table]
                        if row.get(r.parent_column) is not None}

    # ---- primary keys ------------------------------------------------------
    pk_problems = []
    for t, spec in specs.items():
        if t not in tables:
            continue
        cols = set(spec.pk_columns) | graph.referenced_columns(t)
        for c in cols:
            vals = [row.get(c) for row in tables[t]]
            nulls = sum(v is None for v in vals)
            dups = sum(n - 1 for n in Counter(v for v in vals if v is not None).values() if n > 1)
            if nulls or dups:
                pk_problems.append(f"{t}.{c}: {dups} duplicate, {nulls} empty")
    checks = [_check("pk_unique", "Keys are unique and populated",
                     "fail" if pk_problems else "pass",
                     "; ".join(pk_problems) or "Every primary/referenced key is unique and non-empty.",
                     len(pk_problems))]

    # ---- per-relationship reference check -----------------------------------
    rel_reports, total_refs, valid_refs = [], 0, 0
    orphan_total, required_null_total = 0, 0
    counts_mismatch = 0
    for r in rels:
        parents = index[(r.parent_table, r.parent_column)]
        vals = [row.get(r.child_column) for row in tables[r.child_table]]
        non_null = [v for v in vals if v is not None]
        nulls = len(vals) - len(non_null)
        orphans = [v for v in non_null if v not in parents]
        valid = len(non_null) - len(orphans)
        per_parent = Counter(v for v in non_null if v in parents)
        childless = len(parents) - len(per_parent)
        avg = (valid / len(parents)) if parents else 0.0
        total_refs += len(non_null)
        valid_refs += valid
        orphan_total += len(orphans)
        if not r.nullable:
            required_null_total += nulls
        if sum(per_parent.values()) != valid:
            counts_mismatch += 1
        rel_reports.append({
            "relationship": f"{r.child_key} -> {r.parent_key}",
            "child_table": r.child_table, "parent_table": r.parent_table,
            "child_rows": len(vals), "parent_rows": len(parents),
            "references": len(non_null), "valid_references": valid,
            "orphans": len(orphans), "null_references": nulls,
            "orphan_examples": [str(o) for o in orphans[:_MAX_EXAMPLES]],
            "children_per_parent": {
                "min": min(per_parent.values(), default=0) if childless == 0 else 0,
                "avg": round(avg, 2),
                "max": max(per_parent.values(), default=0),
            },
            "childless_parents": childless,
            "source_avg_children_per_parent": source_fanout.get(r.child_key),
        })

    checks.append(_check(
        "no_orphans", "No orphan child records",
        "fail" if orphan_total else "pass",
        f"{orphan_total} child row(s) reference a parent that does not exist." if orphan_total
        else f"All {total_refs} foreign-key references point to an existing parent.", orphan_total))
    checks.append(_check(
        "required_fks", "Every required foreign key is filled",
        "fail" if required_null_total else "pass",
        f"{required_null_total} NOT NULL foreign key value(s) are empty." if required_null_total
        else "No NOT NULL foreign key is empty.", required_null_total))

    childless_total = sum(x["childless_parents"] for x in rel_reports)
    if counts_mismatch:
        checks.append(_check("parent_child", "Parent-child counts are valid", "fail",
                             f"{counts_mismatch} relationship(s) where child counts do not add up.", counts_mismatch))
    else:
        note = (f" {childless_total} parent row(s) have no children (normal, e.g. an appointment "
                f"with no claim).") if childless_total else ""
        checks.append(_check("parent_child", "Parent-child counts are valid", "pass",
                             "Child counts reconcile with parent keys." + note, childless_total))

    # ---- multi-level joins ------------------------------------------------------
    memo = {}

    def resolves(table, row):
        """Does this row join all the way up through every non-null FK?"""
        key = (table, id(row))
        if key in memo:
            return memo[key]
        memo[key] = True                     # guards against self-reference loops
        ok = True
        for r in graph.parents_of(table):
            if r.parent_table not in tables:
                continue
            v = row.get(r.child_column)
            if v is None:
                continue
            parent = index.get((r.parent_table, r.parent_column), {}).get(v)
            if parent is None or (not r.is_self_reference and not resolves(r.parent_table, parent)):
                ok = False
                break
        memo[key] = ok
        return ok

    broken, examined = 0, 0
    for t, rows in tables.items():
        if graph.parents_of(t):
            examined += len(rows)
            broken += sum(not resolves(t, row) for row in rows)
    checks.append(_check(
        "multi_level_joins", "Multi-level joins work",
        "fail" if broken else "pass",
        f"{broken} of {examined} child rows break somewhere up their parent chain." if broken
        else f"All {examined} child rows join cleanly up to their top-level parents.", broken))

    # ---- sibling-FK consistency ---------------------------------------------------
    mismatches, checked_paths = 0, 0
    for t in tables:
        for d, (via, via_col) in graph.derivations(t).items():
            if via.parent_table not in tables:
                continue
            checked_paths += 1
            for row in tables[t]:
                a, b = row.get(d.child_column), row.get(via.child_column)
                if a is None or b is None:
                    continue
                via_row = index.get((via.parent_table, via.parent_column), {}).get(b)
                if via_row is None:
                    mismatches += 1
                elif via_row.get(via_col) is not None and via_row.get(via_col) != a:
                    mismatches += 1          # (an empty value on the via side leaves nothing to disagree with)
    if checked_paths:
        checks.append(_check(
            "path_consistency", "Related keys agree across paths",
            "fail" if mismatches else "pass",
            f"{mismatches} row(s) where two paths to the same parent disagree (e.g. claim.patient vs "
            f"claim -> appointment -> patient)." if mismatches
            else f"{checked_paths} multi-path relationship(s) are consistent.", mismatches))

    # ---- shared identifier attributes ------------------------------------------------
    attr_bad, attr_links = 0, 0
    for t in tables:
        for col_name, r, parent_col in shared_attribute_links(graph, specs, t):
            if r.parent_table not in tables:
                continue
            attr_links += 1
            for row in tables[t]:
                fk_val = row.get(r.child_column)
                parent = index.get((r.parent_table, r.parent_column), {}).get(fk_val) if fk_val is not None else None
                if parent is not None and parent.get(parent_col) != row.get(col_name):
                    attr_bad += 1
    if attr_links:
        checks.append(_check(
            "attribute_consistency", "Shared identifiers match their parent",
            "fail" if attr_bad else "pass",
            f"{attr_bad} row(s) carry an identifier that differs from their parent's." if attr_bad
            else f"{attr_links} shared identifier column(s) (e.g. member id) match the parent record.", attr_bad))

    # ---- distribution (informational, never affects the score) ---------------------
    drift = []
    for x in rel_reports:
        src = x["source_avg_children_per_parent"]
        if src and abs(x["children_per_parent"]["avg"] - src) / src > DISTRIBUTION_TOLERANCE:
            drift.append(f"{x['relationship']}: {x['children_per_parent']['avg']} vs source {round(src, 2)}")
    if any(x["source_avg_children_per_parent"] for x in rel_reports):
        checks.append(_check(
            "distribution", "Children-per-parent stays realistic",
            "warn" if drift else "pass",
            ("Differs from the source by more than 30%: " + "; ".join(drift)) if drift
            else "Average children per parent is within 30% of the source.", len(drift)))
    else:
        checks.append(_check("distribution", "Children-per-parent stays realistic", "info",
                             "No source statistics available to compare against."))

    score = round(100.0 * valid_refs / total_refs, 2) if total_refs else 100.0
    hard = ("pk_unique", "no_orphans", "required_fks", "parent_child", "multi_level_joins", "path_consistency",
            "attribute_consistency")
    passed = score == 100.0 and all(c["status"] != "fail" for c in checks if c["id"] in hard)
    return {
        "score": score, "passed": passed,
        "total_references": total_refs, "valid_references": valid_refs,
        "checks": checks, "relationships": rel_reports,
    }
