"""
Banking & Financial Services domain + declared / undeclared data relationships.

Run from the project root:   python -m pytest tests/test_banking_domain.py   (or run this file directly)
Pure Python + sqlite3 (+ PyYAML for the pattern analyzer) - needs no FastAPI / SQLAlchemy / Faker.
"""
import copy, os, random, sqlite3, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sample_domains import banking, registry
from referential_integrity.graph import Relationship, RelationshipGraph, relationship_kind
from referential_integrity.discovery import discover, candidate_parents, type_family
from referential_integrity.engine import ColumnSpec, TableSpec, generate_related
from referential_integrity.validator import validate
from pattern_analysis.pattern_analyzer import PatternAnalyzer

_TMP = tempfile.mkdtemp(prefix="tdm_bank_")
DB = os.path.join(_TMP, "banking.db")
COUNTS = banking.build_banking_db(DB, seed=7)
MIN_MATCH = 95.0     # same threshold as relationship suggestions in the app


def _con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


class _Inspector:    # the 4 methods SQLAlchemy's Inspector offers, backed by sqlite3
    def __init__(self): self.c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    def get_table_names(self): return [r[0] for r in self.c.execute("select name from sqlite_master where type='table'")]
    def get_pk_constraint(self, t): return {"constrained_columns": [r[1] for r in self.c.execute(f"pragma table_info({t})") if r[5]]}
    def get_columns(self, t): return [{"name": r[1], "type": r[2], "nullable": not r[3]} for r in self.c.execute(f"pragma table_info({t})")]
    def get_foreign_keys(self, t): return [{"constrained_columns": [r[3]], "referred_table": r[2], "referred_columns": [r[4]]} for r in self.c.execute(f"pragma foreign_key_list({t})")]


def _suggest(schema, declared):
    """What the app's 'Find undeclared relationships' does, with sqlite3 doing the counting."""
    taken = {(r.child_table, r.child_column) for r in declared}
    parents = {t: pk[0] for t, pk in schema.pk_columns.items() if len(pk) == 1}
    con, found = _con(), []
    for child, cols in schema.columns.items():
        for col in cols:
            name = col["name"]
            if (child, name) in taken or name in schema.pk_columns[child]:
                continue
            for parent, pk, basis in candidate_parents(child, name, parents):
                pk_type = next(c["type"] for c in schema.columns[parent] if c["name"] == pk)
                if type_family(col["type"]) != type_family(pk_type):
                    continue
                distinct = con.execute(f"select count(distinct {name}) from {child}").fetchone()[0]
                if not distinct:
                    continue
                matched = con.execute(f"select count(distinct {name}) from {child} where {name} in (select {pk} from {parent})").fetchone()[0]
                pct = round(100.0 * matched / distinct, 1)
                if pct >= MIN_MATCH:
                    found.append({"child": child, "column": name, "parent": parent, "key": pk, "basis": basis,
                                  "match_percent": pct, "orphans": distinct - matched})
    return found


# ---------------------------------------------------------------- the schema
def test_banking_database_is_built_with_eleven_tables():
    assert set(COUNTS) == {"branches", "products", "customers", "accounts", "cards", "transactions", "loans",
                           "loan_repayments", "securities", "portfolios", "trades"}
    assert all(0 < n <= 1000 for n in COUNTS.values()), COUNTS     # platform generates at most 1000 rows/table


def test_build_is_deterministic_for_a_seed():
    other = os.path.join(_TMP, "again.db")
    banking.build_banking_db(other, seed=7)
    a, b = sqlite3.connect(DB), sqlite3.connect(other)
    for t in COUNTS:
        assert a.execute(f"select * from {t}").fetchall() == b.execute(f"select * from {t}").fetchall()


def test_domain_table_names_do_not_collide_with_healthcare():
    healthcare = set(registry.list_tables("healthcare"))
    assert healthcare == {"doctors", "patients", "appointments", "insurance_claims"}
    assert not healthcare & set(COUNTS)
    registry.check_table_names_disjoint()
    assert registry.domain_of_table("patients") == "healthcare"
    assert registry.domain_of_table("transactions") in ("banking", None)   # None only if banking.db is not shipped
    assert registry.connection_string("healthcare") == "sqlite:///hospital.db"


# --------------------------------------------------------- sample-data realism
def test_card_numbers_are_luhn_valid_and_aadhaar_numbers_verhoeff_valid():
    c = _con()
    cards = [r[0] for r in c.execute("select card_number from cards")]
    aad = [r[0] for r in c.execute("select aadhaar_number from customers")]
    assert all(banking.luhn_valid(x) for x in cards)
    assert all(banking.verhoeff_valid(x) for x in aad)
    assert banking.verhoeff_valid("2363") and not banking.verhoeff_valid("2364")      # standard test vector
    assert not banking.luhn_valid("4111-1111-1111-1112") and not banking.verhoeff_valid("2345 6789 0123")
    cols = {r[1] for r in c.execute("pragma table_info(cards)")}
    assert not {"cvv", "pin", "cvc"} & cols                            # never store card security codes


def test_sensitive_columns_are_recognised_by_the_pattern_analyzer():
    c, analyzer = _con(), PatternAnalyzer()
    expect = {"customers": {"pan_number": "PAN_NUMBER", "aadhaar_number": "AADHAAR_NUMBER", "phone": "PHONE", "dob": "DATE"},
              "accounts": {"account_number": "ACCOUNT_NUMBER"},
              "cards": {"card_number": "CREDIT_CARD", "linked_account_no": "ACCOUNT_NUMBER"},
              "branches": {"ifsc_code": "IFSC_CODE"}}
    for table, cols in expect.items():
        result = analyzer.analyze_table([dict(r) for r in c.execute(f"select * from {table}")])
        for col, want in cols.items():
            top = result[col][0]
            assert top["pattern_type"] == want and top["percentage"] >= 90, (table, col, top)


# ----------------------------------------------- declared relationships (FKs)
def test_declared_foreign_keys_are_discovered_exactly():
    d = discover(_Inspector())
    got = {(r.child_table, r.child_column, r.parent_table, r.parent_column) for r in d.relationships}
    assert got == set(banking.DECLARED_RELATIONSHIPS)
    assert all(r.origin == "discovered" and r.kind == "declared" for r in d.relationships)
    assert not d.skipped


def test_declared_graph_orders_parents_first_and_scopes_ancestors():
    d = discover(_Inspector())
    g = RelationshipGraph(d.relationships)
    order = g.generation_order(set(d.columns))
    for parent, child in [("customers", "accounts"), ("branches", "accounts"), ("accounts", "cards"),
                          ("accounts", "transactions"), ("loans", "loan_repayments"), ("securities", "trades"),
                          ("portfolios", "trades")]:
        assert order.index(parent) < order.index(child), (parent, child)
    # asking for trades pulls in everything it depends on - and nothing else
    assert g.with_ancestors(["trades"]) == {"trades", "portfolios", "securities", "customers"}


# --------------------------------------------- undeclared relationships (logical)
def test_candidate_matching_conventions():
    pk = {"accounts": "account_id", "cards": "card_id", "customers": "customer_id", "things": "id", "ab": "xyz"}
    basis = lambda col, child="t": {p: b for p, _, b in candidate_parents(child, col, pk)}
    assert basis("card_id") == {"cards": "same_name"}
    assert basis("debit_account_id") == {"accounts": "role_prefixed"}
    assert basis("settlement_account_id") == {"accounts": "role_prefixed"}
    assert basis("customer_id", child="customers") == {}                  # never the table's own key
    assert basis("owner_id") == {}                                        # the generic key 'id' is not role-matched
    assert basis("account_no") == {} and basis("amount") == {}
    assert candidate_parents("t", "account_id", {"accounts": "ACCOUNT_ID"})[0][2] == "same_name"   # case-insensitive
    assert type_family("INTEGER") == "number" and type_family("VARCHAR(20)") == "text"


def test_undeclared_relationships_are_suggested_and_nothing_else():
    d = discover(_Inspector())
    found = _suggest(d, d.relationships)
    got = {(x["child"], x["column"], x["parent"], x["key"]) for x in found}
    assert got == set(banking.UNDECLARED_RELATIONSHIPS), got
    by_col = {x["column"]: x for x in found}
    assert by_col["card_id"]["basis"] == "same_name"
    assert {by_col[c]["basis"] for c in ("disbursement_account_id", "debit_account_id", "settlement_account_id")} == {"role_prefixed"}
    assert by_col["card_id"]["match_percent"] == 100.0 and by_col["card_id"]["orphans"] == 0
    # legacy data: the repayment debit accounts include purged accounts -> orphans are reported, not hidden
    debit = by_col["debit_account_id"]
    assert MIN_MATCH <= debit["match_percent"] < 100.0 and debit["orphans"] == banking.LEGACY_ORPHAN_ACCOUNTS
    # the natural-key copy is a real link but not to a primary key: it must NOT be auto-suggested
    assert not any(x["column"] == "linked_account_no" for x in found)


def test_undeclared_links_really_hold_in_the_source_data():
    c = _con()
    q = lambda sql: c.execute(sql).fetchone()[0]
    assert q("select count(*) from transactions t join cards k on k.card_id=t.card_id where k.account_id != t.account_id") == 0
    assert q("select count(*) from transactions where card_id is not null") > 0
    assert q("select count(*) from transactions where card_id is null") > 0                # the link is optional
    assert q("select count(*) from loans l join accounts a on a.account_id=l.disbursement_account_id where a.customer_id != l.customer_id") == 0
    assert q("select count(*) from portfolios p join accounts a on a.account_id=p.settlement_account_id where a.customer_id != p.customer_id") == 0
    assert q("select count(*) from cards k join accounts a on a.account_id=k.account_id where a.account_number != k.linked_account_no") == 0
    assert q("select count(*) from loan_repayments r where r.debit_account_id not in (select account_id from accounts)") > 0   # legacy orphans


# --------------------------------------- generating related data with them
def _specs_and_graph(declared_only, null_card_pct=60.0, rows=80):
    d = discover(_Inspector())
    rels = list(d.relationships)
    if not declared_only:
        for ch, col, pa, pk in banking.UNDECLARED_RELATIONSHIPS:
            nullable = next(c["nullable"] for c in d.columns[ch] if c["name"] == col)
            rels.append(Relationship(ch, col, pa, pk, "manual", nullable))
    g = RelationshipGraph(rels)
    order = g.generation_order(set(d.columns))
    pattern = {"account_number": "ACCOUNT_NUMBER", "linked_account_no": "ACCOUNT_NUMBER", "card_number": "CREDIT_CARD"}
    specs = {t: TableSpec(t, [ColumnSpec(c["name"], c["type"], pattern.get(c["name"], "TEXT"),
                                         null_card_pct if (t, c["name"]) == ("transactions", "card_id") else 0.0)
                              for c in d.columns[t]], d.pk_columns[t], rows) for t in order}
    return d, g, order, specs


def _value(name, pattern, dtype):
    n = random.Random().randint(10 ** 10, 10 ** 11 - 1)
    if pattern == "ACCOUNT_NUMBER":
        return str(n)
    return random.Random().randint(1, 10 ** 6) if "INT" in dtype.upper() else f"{name[:3]}{n % 100000}"


def _load(order, d, tables):
    m = sqlite3.connect(":memory:")
    for t in order:
        cols = [c["name"] for c in d.columns[t]]
        m.execute(f"create table {t} ({','.join(cols)})")
        m.executemany(f"insert into {t} values ({','.join('?' * len(cols))})", [tuple(r[c] for c in cols) for r in tables[t]])
    return m


def test_declared_plus_undeclared_generation_is_fully_consistent():
    d, g, order, specs = _specs_and_graph(declared_only=False)
    res = generate_related(g, specs, order, _value, random.Random(5))
    report = validate(g, res.tables, specs)
    assert report["score"] == 100.0 and report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert {c["id"] for c in report["checks"]} >= {"no_orphans", "required_fks", "multi_level_joins", "path_consistency"}
    m = _load(order, d, res.tables)
    q = lambda sql: m.execute(sql).fetchone()[0]
    n_txn = len(res.tables["transactions"])
    # transaction -> account -> customer works for every row, even those with NO card (card_id is NULL)
    assert q("select count(*) from transactions t join accounts a on a.account_id=t.account_id join customers c on c.customer_id=a.customer_id") == n_txn
    assert q("select count(*) from transactions where card_id is null") > 0 and q("select count(*) from transactions where card_id is not null") > 0
    assert q("select count(*) from transactions where account_id is null") == 0
    # a card transaction is on the card's own account
    assert q("select count(*) from transactions t join cards k on k.card_id=t.card_id where k.account_id != t.account_id") == 0
    # loan -> disbursement account -> same customer; repayments are debited from the loan's account
    assert q("select count(*) from loans l join accounts a on a.account_id=l.disbursement_account_id where a.customer_id != l.customer_id") == 0
    assert q("select count(*) from loan_repayments r join loans l on l.loan_id=r.loan_id where r.debit_account_id != l.disbursement_account_id") == 0
    assert q("select count(*) from portfolios p join accounts a on a.account_id=p.settlement_account_id where a.customer_id != p.customer_id") == 0
    # the denormalised natural-key copy matches the account it belongs to (shared-identifier check)
    assert q("select count(*) from cards k join accounts a on a.account_id=k.account_id where a.account_number != k.linked_account_no") == 0
    assert any(s.startswith("cards.linked_account_no") for s in res.shared_attributes)
    # no orphan survives in the SYNTHETIC data, unlike the legacy source
    assert q("select count(*) from loan_repayments where debit_account_id not in (select account_id from accounts)") == 0


def test_without_the_undeclared_links_the_synthetic_data_is_inconsistent():
    """Why undeclared relationships matter: with only the declared FKs, a card can be 'used' on an account it does not belong to."""
    d, g, order, specs = _specs_and_graph(declared_only=True)
    res = generate_related(g, specs, order, _value, random.Random(5))
    m = _load(order, d, res.tables)
    bad_card = m.execute("select count(*) from transactions t where t.card_id is not null and "
                         "not exists (select 1 from cards k where k.card_id=t.card_id and k.account_id=t.account_id)").fetchone()[0]
    bad_loan = m.execute("select count(*) from loans l where not exists "
                         "(select 1 from accounts a where a.account_id=l.disbursement_account_id and a.customer_id=l.customer_id)").fetchone()[0]
    assert bad_card > 0 and bad_loan > 0


# ------------------------------------------- engine / validator behaviour
def _tiny(null_pct):
    rels = [Relationship("b", "a_id", "a", "id", nullable=False), Relationship("c", "a_id", "a", "id", nullable=False),
            Relationship("c", "b_id", "b", "id", nullable=True)]
    g = RelationshipGraph(rels)
    cols = {"a": ["id"], "b": ["id", "a_id"], "c": ["id", "a_id", "b_id"]}
    specs = {t: TableSpec(t, [ColumnSpec(n, "INTEGER", "N/A", null_pct if (t, n) == ("c", "b_id") else 0.0) for n in cs],
                          ["id"], 40) for t, cs in cols.items()}
    return g, specs


def test_required_foreign_key_is_filled_when_its_sibling_foreign_key_is_empty():
    for pct in (0.0, 50.0, 100.0):
        g, specs = _tiny(pct)
        res = generate_related(g, specs, g.generation_order(g.tables()), lambda *a: 1, random.Random(3))
        rows = res.tables["c"]
        assert all(r["a_id"] is not None for r in rows), pct
        report = validate(g, res.tables, specs)
        assert report["passed"] and report["score"] == 100.0, (pct, report["checks"])
        b = {r["id"]: r for r in res.tables["b"]}
        assert all(b[r["b_id"]]["a_id"] == r["a_id"] for r in rows if r["b_id"] is not None)   # still consistent when a path exists
    g, specs = _tiny(100.0)
    rows = generate_related(g, specs, g.generation_order(g.tables()), lambda *a: 1, random.Random(3)).tables["c"]
    assert all(r["b_id"] is None for r in rows)


def test_validator_still_flags_a_real_path_disagreement():
    g, specs = _tiny(0.0)
    res = generate_related(g, specs, g.generation_order(g.tables()), lambda *a: 1, random.Random(3))
    bad = copy.deepcopy(res.tables)
    b = {r["id"]: r for r in bad["b"]}
    row = bad["c"][0]
    row["a_id"] = next(a["id"] for a in bad["a"] if a["id"] != b[row["b_id"]]["a_id"])
    r = validate(g, bad, specs)
    assert not r["passed"] and any(c["id"] == "path_consistency" and c["status"] == "fail" for c in r["checks"])


def test_relationship_kind_labels():
    assert relationship_kind("discovered") == "declared" and relationship_kind("manual") == "undeclared"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok  ", name)
