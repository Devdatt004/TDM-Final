"""
referential_integrity/discovery.py

Relationship Discovery - Step 1. Reads the FOREIGN KEY declarations straight
from the source database's own schema (schema metadata only - no row values)
using a SQLAlchemy Inspector, and returns:

  relationships   every single-column foreign key, as Relationship objects
  pk_columns      {table: [primary key columns]}
  columns         {table: [{"name", "type", "nullable"}, ...]} in source order
  skipped         foreign keys that could not be used, with the reason
                  (composite keys are not supported yet)

The inspector is passed in (rather than created here) so this module stays
independent of how the connection was made, and can be tested with a stand-in.
"""

from dataclasses import dataclass, field

from .graph import Relationship


@dataclass
class DiscoveryResult:
    relationships: list
    pk_columns: dict
    columns: dict
    skipped: list = field(default_factory=list)


def discover(inspector) -> DiscoveryResult:
    tables = list(inspector.get_table_names())
    pk_columns, columns = {}, {}
    for t in tables:
        pk_columns[t] = list(inspector.get_pk_constraint(t).get("constrained_columns") or [])
        columns[t] = [
            {"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True))}
            for c in inspector.get_columns(t)
        ]

    relationships, skipped = [], []
    for t in tables:
        nullable = {c["name"]: c["nullable"] for c in columns[t]}
        for fk in inspector.get_foreign_keys(t):
            child_cols = fk.get("constrained_columns") or []
            parent = fk.get("referred_table")
            parent_cols = [c for c in (fk.get("referred_columns") or []) if c] or pk_columns.get(parent, [])
            if parent not in tables:
                skipped.append({"table": t, "reason": f"references unknown table '{parent}'"})
                continue
            if len(child_cols) != 1 or len(parent_cols) != 1:
                skipped.append({"table": t, "reason": (
                    f"composite foreign key ({', '.join(child_cols)}) -> {parent}"
                    f"({', '.join(parent_cols)}) is not supported yet")})
                continue
            relationships.append(Relationship(
                child_table=t, child_column=child_cols[0],
                parent_table=parent, parent_column=parent_cols[0],
                origin="discovered", nullable=nullable.get(child_cols[0], True)))
    return DiscoveryResult(relationships, pk_columns, columns, skipped)


# ---------------------------------------------------------------------------
# Undeclared relationships - which parent keys could a column point at?
# ---------------------------------------------------------------------------

BASIS_SAME_NAME = "same_name"          # patient_id  -> patients.patient_id
BASIS_TABLE_ID = "table_id"            # patient_id  -> patients.<any key>   ('<table>_id')
BASIS_ROLE_PREFIXED = "role_prefixed"  # settlement_account_id -> accounts.account_id

BASIS_TEXT = {
    BASIS_SAME_NAME: "column name matches the parent's key",
    BASIS_TABLE_ID: "column name follows the '<table>_id' convention",
    BASIS_ROLE_PREFIXED: "column name is a role-prefixed copy of the parent's key",
}


def _singular(name: str) -> str:
    return name[:-1] if name.endswith("s") else name


def candidate_parents(child_table: str, column_name: str, parent_keys: dict) -> list:
    """
    Name-based candidates for a column nobody declared a foreign key on.

    parent_keys   {table: single-column primary key name}
    returns       [(parent_table, parent_key, basis)] - at most one entry per parent table;
                  the caller still has to check types and that the VALUES exist in the parent.

    Three conventions, strongest first:
      same_name        the column is named exactly like the parent's key
      table_id         '<table>_id' or '<singular table>_id'
      role_prefixed    '<role>_<parent key>', e.g. settlement_account_id, debit_account_id,
                       disbursement_account_id -> accounts.account_id. The generic key 'id' is
                       excluded, or every '..._id' column would match every table.
    """
    col = column_name.lower()
    out = []
    for parent, pk in parent_keys.items():
        if parent == child_table:
            continue
        key = pk.lower()
        if col == key:
            basis = BASIS_SAME_NAME
        elif col in (f"{_singular(parent)}_id".lower(), f"{parent}_id".lower()):
            basis = BASIS_TABLE_ID
        elif key != "id" and len(key) > 3 and col.endswith("_" + key) and len(col) > len(key) + 1:
            basis = BASIS_ROLE_PREFIXED
        else:
            continue
        out.append((parent, pk, basis))
    return out


def type_family(type_str) -> str:
    """Coarse SQL type bucket, so an INTEGER column is never matched to a TEXT key."""
    t = (type_str or "").upper()
    if any(k in t for k in ("INT", "NUM", "DEC", "FLOAT", "REAL", "DOUBLE")):
        return "number"
    if any(k in t for k in ("CHAR", "TEXT", "CLOB", "STRING")):
        return "text"
    return t or "other"
