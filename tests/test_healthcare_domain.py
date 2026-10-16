import sqlite3

from sample_domains.healthcare import DEFAULT_SIZES, build_healthcare_db
from sample_domains import registry


def _tables(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        con.close()


def test_healthcare_builder_creates_expected_tables_and_rows(tmp_path):
    path = tmp_path / "hospital.db"
    counts = build_healthcare_db(str(path), seed=2026)
    assert set(counts) == {"patients", "doctors", "appointments", "insurance_claims"}
    assert counts == DEFAULT_SIZES
    assert _tables(path) == set(DEFAULT_SIZES)


def test_healthcare_builder_is_deterministic_for_a_seed(tmp_path):
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    build_healthcare_db(str(first), seed=77)
    build_healthcare_db(str(second), seed=77)
    a, b = sqlite3.connect(first), sqlite3.connect(second)
    try:
        for table in ("patients", "doctors", "appointments", "insurance_claims"):
            assert a.execute(f"SELECT * FROM {table}").fetchall() == b.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        a.close()
        b.close()


def test_healthcare_foreign_keys_and_claim_member_relationships_are_valid(tmp_path):
    path = tmp_path / "hospital.db"
    build_healthcare_db(str(path), seed=123)
    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert con.execute("""
            SELECT COUNT(*) FROM insurance_claims c
            JOIN appointments a ON a.appointment_id = c.appointment_id
            JOIN patients p ON p.patient_id = c.patient_id AND p.patient_id = a.patient_id
            WHERE c.member_id = p.insurance_member_id
        """).fetchone()[0] == DEFAULT_SIZES["insurance_claims"]
    finally:
        con.close()


def test_registry_rebuilds_missing_healthcare_database(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    created = registry.ensure_domain_databases()
    assert "healthcare" in created
    assert registry.is_available("healthcare")
    assert set(registry.list_tables("healthcare")) == set(DEFAULT_SIZES)
