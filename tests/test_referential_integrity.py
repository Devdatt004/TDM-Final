"""
Run from the project root:   python -m pytest tests/   (or: python tests/test_referential_integrity.py)
Pure Python + sqlite3 - needs no FastAPI / SQLAlchemy / Faker.
Uses the real hospital.db schema and proves the joins with real SQL.
"""
import copy, itertools, os, random, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from referential_integrity.graph import RelationshipGraph, Relationship, CyclicRelationshipError
from referential_integrity.discovery import discover
from referential_integrity.engine import ColumnSpec, TableSpec, generate_related
from referential_integrity.validator import validate

DB = os.path.join(ROOT, "hospital.db")


class _Inspector:   # the 4 methods SQLAlchemy's Inspector offers, backed by sqlite3
    def __init__(self): self.c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    def get_table_names(self): return [r[0] for r in self.c.execute("select name from sqlite_master where type='table'")]
    def get_pk_constraint(self, t): return {"constrained_columns": [r[1] for r in self.c.execute(f"pragma table_info({t})") if r[5]]}
    def get_columns(self, t): return [{"name": r[1], "type": r[2], "nullable": not r[3]} for r in self.c.execute(f"pragma table_info({t})")]
    def get_foreign_keys(self, t): return [{"constrained_columns": [r[3]], "referred_table": r[2], "referred_columns": [r[4]]} for r in self.c.execute(f"pragma foreign_key_list({t})")]


PATTERNS = {"insurance_member_id": "INSURANCE_ID", "member_id": "INSURANCE_ID"}
_counter = itertools.count(1)


def _value(name, pattern, dtype):
    return next(_counter) if "INT" in dtype.upper() else f"{name[:3]}{next(_counter)}"


def _build(rows=None):
    d = discover(_Inspector())
    g = RelationshipGraph(d.relationships)
    order = g.generation_order(g.tables())
    specs = {t: TableSpec(t, [ColumnSpec(c["name"], c["type"], PATTERNS.get(c["name"], "TEXT")) for c in d.columns[t]],
                          d.pk_columns[t], (rows or {}).get(t, 60)) for t in order}
    res = generate_related(g, specs, order, _value, random.Random(11))
    return d, g, order, specs, res


def test_discovery_and_order():
    d, g, order, *_ = _build()
    assert g.to_metadata_dict()["insurance_claims.patient_id"] == "patients.patient_id"
    assert order.index("patients") < order.index("appointments") < order.index("insurance_claims")
    assert order.index("doctors") < order.index("appointments")


def test_generated_data_has_full_integrity_and_real_joins_work():
    d, g, order, specs, res = _build()
    report = validate(g, res.tables, specs)
    assert report["score"] == 100.0 and report["passed"]
    m = sqlite3.connect(":memory:")
    for t in order:
        cols = [c["name"] for c in d.columns[t]]
        m.execute(f"create table {t} ({','.join(cols)})")
        m.executemany(f"insert into {t} values ({','.join('?' * len(cols))})", [tuple(r[c] for c in cols) for r in res.tables[t]])
    joined = m.execute("select count(*) from insurance_claims c join appointments a on a.appointment_id=c.appointment_id "
                       "join patients p on p.patient_id=a.patient_id and p.patient_id=c.patient_id "
                       "join doctors d on d.doctor_id=a.doctor_id").fetchone()[0]
    assert joined == len(res.tables["insurance_claims"])
    same_member = m.execute("select count(*) from insurance_claims c join patients p on p.patient_id=c.patient_id "
                            "where c.member_id = p.insurance_member_id").fetchone()[0]
    assert same_member == len(res.tables["insurance_claims"])


def test_validator_catches_orphans_and_inconsistency():
    _, g, _, specs, res = _build()
    bad = copy.deepcopy(res.tables)
    bad["insurance_claims"][0]["patient_id"] = 999999
    r = validate(g, bad, specs)
    assert not r["passed"] and r["score"] < 100
    assert {c["id"] for c in r["checks"] if c["status"] == "fail"} >= {"no_orphans", "multi_level_joins"}


def test_cycle_is_rejected():
    g = RelationshipGraph([Relationship("a", "b_id", "b", "id"), Relationship("b", "a_id", "a", "id")])
    try:
        g.generation_order({"a", "b"})
        assert False, "expected CyclicRelationshipError"
    except CyclicRelationshipError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok  ", name)
