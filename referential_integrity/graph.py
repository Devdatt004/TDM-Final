"""
referential_integrity/graph.py

Relationship Graph - Steps 1 and 2 of the Data Relationship Validation design.

  Step 1  Build the relationship graph: which child column points at which
          parent column (e.g. "insurance_claims.patient_id" ->
          "patients.patient_id").
  Step 2  Work out a parent-before-child generation order (a topological
          sort), so a child row is never generated before the parent it
          needs to reference.

Pure Python (no database, no SQLAlchemy) so it can be unit-tested on its own.
"""

from dataclasses import dataclass


# How a relationship became known to the platform.
#   declared    a FOREIGN KEY constraint exists in the source database (origin "discovered")
#   undeclared  a logical link nobody declared; a steward confirmed it (origin "manual")
DECLARED = "declared"
UNDECLARED = "undeclared"


def relationship_kind(origin: str) -> str:
    return DECLARED if origin == "discovered" else UNDECLARED


class CyclicRelationshipError(ValueError):
    """Two or more tables reference each other in a loop, so there is no
    valid parent-first order."""


@dataclass(frozen=True)
class Relationship:
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str
    origin: str = "discovered"      # "discovered" (declared FK) or "manual" (confirmed undeclared link)
    nullable: bool = True           # is the child FK column NULL-able?

    @property
    def child_key(self) -> str:
        return f"{self.child_table}.{self.child_column}"

    @property
    def parent_key(self) -> str:
        return f"{self.parent_table}.{self.parent_column}"

    @property
    def kind(self) -> str:
        return relationship_kind(self.origin)

    @property
    def is_self_reference(self) -> bool:
        return self.child_table == self.parent_table

    def to_dict(self) -> dict:
        return {
            "child_table": self.child_table, "child_column": self.child_column,
            "parent_table": self.parent_table, "parent_column": self.parent_column,
            "origin": self.origin, "nullable": self.nullable,
        }


class RelationshipGraph:
    def __init__(self, relationships):
        # de-duplicate on the child column (one FK per child column)
        seen, rels = set(), []
        for r in relationships:
            if r.child_key not in seen:
                seen.add(r.child_key)
                rels.append(r)
        self.relationships = rels

    # ---- lookups -------------------------------------------------------
    def parents_of(self, table):
        """Relationships where `table` is the CHILD (its foreign keys)."""
        return [r for r in self.relationships if r.child_table == table]

    def children_of(self, table):
        """Relationships where `table` is the PARENT."""
        return [r for r in self.relationships if r.parent_table == table]

    def referenced_columns(self, table):
        """Columns of `table` that other tables point at (must be unique keys)."""
        return {r.parent_column for r in self.children_of(table)}

    def tables(self):
        names = set()
        for r in self.relationships:
            names.add(r.child_table)
            names.add(r.parent_table)
        return names

    # ---- scope + ordering ------------------------------------------------
    def with_ancestors(self, tables):
        """The requested tables plus every table they (transitively) depend
        on. A child can't be generated without its parents, so asking for
        `insurance_claims` implies appointments, patients and doctors."""
        wanted, stack = set(tables), list(tables)
        while stack:
            t = stack.pop()
            for r in self.parents_of(t):
                if r.parent_table not in wanted:
                    wanted.add(r.parent_table)
                    stack.append(r.parent_table)
        return wanted

    def generation_order(self, tables):
        """Parent-first order (Kahn's algorithm). Self-references are ignored
        for ordering - they're handled row-by-row inside one table."""
        tables = set(tables)
        deps = {
            t: {r.parent_table for r in self.parents_of(t)
                if not r.is_self_reference and r.parent_table in tables}
            for t in tables
        }
        order, ready = [], sorted(t for t, d in deps.items() if not d)
        while ready:
            t = ready.pop(0)
            order.append(t)
            for other in sorted(tables):
                if t in deps[other]:
                    deps[other].discard(t)
                    if not deps[other] and other not in order and other not in ready:
                        ready.append(other)
            ready.sort()
        if len(order) != len(tables):
            stuck = sorted(tables - set(order))
            raise CyclicRelationshipError(
                "Circular relationship between tables: " + ", ".join(stuck)
                + ". Remove one of the foreign keys (or mark it as manual and "
                  "drop it) so a parent-first generation order exists."
            )
        return order

    def levels(self, tables):
        """Depth of each table (0 = no parents) - handy for showing the tree."""
        order = self.generation_order(tables)
        depth = {}
        for t in order:
            parents = [r.parent_table for r in self.parents_of(t)
                       if not r.is_self_reference and r.parent_table in depth]
            depth[t] = 1 + max((depth[p] for p in parents), default=-1)
        return depth

    # ---- cross-table consistency (Step 4) --------------------------------
    def derivations(self, table):
        """
        Foreign keys of `table` whose value must be COPIED from another
        foreign key's parent row instead of picked independently.

        Example: insurance_claims has FKs to appointments AND patients, and
        appointments itself points at patients. A claim's patient must be the
        patient of the claim's appointment - otherwise the join
        claim -> appointment -> patient disagrees with claim -> patient.

        Returns {derived_rel: (via_rel, via_parent_column)}: derive `derived_rel`
        by reading `via_parent_column` of the row `via_rel` points to.
        """
        rels = [r for r in self.parents_of(table) if not r.is_self_reference]
        out = {}
        for derived in rels:
            for via in rels:
                if via is derived:
                    continue
                for link in self.parents_of(via.parent_table):
                    if link.parent_table == derived.parent_table \
                            and link.parent_column == derived.parent_column \
                            and not link.is_self_reference \
                            and via not in out:            # don't derive from a derived FK
                        out[derived] = (via, link.child_column)
                        break
                if derived in out:
                    break
        return out

    def to_metadata_dict(self) -> dict:
        """The {"Claim.Patient_ID": "Patient.Patient_ID"} form stored as metadata."""
        return {r.child_key: r.parent_key for r in self.relationships}
