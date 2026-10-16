"""Step 11: bounded/stratified sampling, aggregate metrics, RI health."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

from collections import Counter
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from Profiling.aggregate_metrics import K_MIN, column_metrics
from Profiling.sampling import SamplingError, SamplingSpec, draw_from_rows, select_rows
from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from api.main import app

STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
REVIEWER = {"X-Dev-User": "reviewer1", "X-Dev-Roles": "reviewer"}


# ── metrics on known fixtures ────────────────────────────────────────────────

def test_numeric_metrics_match_known_fixture():
    m = column_metrics(list(range(1, 101)), sensitive=False, population_rows=100)
    assert m["inferred_type"] == "numeric"
    assert m["numeric"]["min"] == 1 and m["numeric"]["max"] == 100
    assert m["numeric"]["quantiles"]["p50"] == pytest.approx(50.5)
    assert m["numeric"]["quantiles"]["p05"] == pytest.approx(5.95)
    assert m["numeric"]["mean"] == pytest.approx(50.5)
    assert sum(m["numeric"]["histogram"]["counts"]) == 100
    assert m["cardinality"] == "unique" and m["sample_based"] is False


def test_null_heavy_and_empty_columns():
    m = column_metrics([None] * 95 + ["x"] * 5, sensitive=False)
    assert m["null_rate"] == 0.95 and m["cardinality"] == "constant"
    empty = column_metrics([None, "", "  "], sensitive=False)
    assert empty["cardinality"] == "empty" and empty["length"] is None and empty["null_rate"] == 1.0


def test_high_cardinality_text_reports_shapes_not_values():
    values = [f"user{i}@example.com" for i in range(500)]
    m = column_metrics(values, sensitive=False)
    assert m["cardinality"] == "unique" and m["top_values"] is None
    assert all("@" in f["signature"] and "user" not in f["signature"] for f in m["formats"])


def test_small_categories_are_suppressed():
    values = ["A"] * 10 + ["B"] * K_MIN + ["rare"] * (K_MIN - 1)
    m = column_metrics(values, sensitive=False)
    assert {v["value"] for v in m["top_values"]} == {"A", "B"}
    assert "fewer than" in m["top_values_suppressed"]


def test_sensitive_columns_hide_values_and_extremes():
    dobs = [date(1940 + i % 60, 1 + i % 12, 1 + i % 28) for i in range(200)]
    m = column_metrics(dobs, sensitive=True)
    assert m["inferred_type"] == "datetime"
    assert "min" not in m["datetime"] and "max" not in m["datetime"]
    assert all(len(q) == 7 for q in m["datetime"]["quantiles"].values())      # YYYY-MM only
    balances = [1000.0 * i for i in range(200)]
    n = column_metrics(balances, sensitive=True)["numeric"]
    assert "min" not in n and "max" not in n and "histogram" not in n
    names = ["Alice"] * 50 + ["Bob"] * 50
    assert column_metrics(names, sensitive=True)["top_values"] is None


def test_pre_1970_dates_and_zero_padded_codes():
    m = column_metrics(["1931-05-02", "1955-12-31", "2001-01-01"], sensitive=False)
    assert m["inferred_type"] == "datetime" and m["datetime"]["min"].startswith("1931")
    zips = column_metrics(["01234", "02345", "00501"], sensitive=False)
    assert zips["inferred_type"] == "text"


# ── sampling ─────────────────────────────────────────────────────────────────

def _rows(n):
    return [{"id": i, "grp": "rare" if i % 50 == 0 else "common"} for i in range(n)]


def test_random_sampling_is_reproducible_and_capped():
    pool = _rows(1000)
    spec = SamplingSpec(method="random", size=30, seed=7)
    a, b = select_rows(pool, spec, "random"), select_rows(pool, spec, "random")
    assert a == b and len(a) == 30
    assert select_rows(pool, SamplingSpec(method="random", size=30, seed=8), "random") != a
    rows, info = draw_from_rows(_rows(50_000), SamplingSpec(method="random", size=20, pool_cap=1000))
    assert len(rows) == 20 and info["rows_scanned"] == 1000 and info["reproducible"] is False


def test_stratified_sampling_keeps_rare_strata():
    pool = _rows(1000)                       # 2 % "rare"
    sample = select_rows(pool, SamplingSpec(method="stratified", size=20, stratify_by="grp"), "stratified")
    counts = Counter(r["grp"] for r in sample)
    assert len(sample) == 20 and counts["rare"] >= 1
    with pytest.raises(SamplingError):
        select_rows(pool, SamplingSpec(method="stratified", size=20, stratify_by="id"), "stratified")
    with pytest.raises(SamplingError):
        select_rows(pool, SamplingSpec(method="stratified", size=20, stratify_by="nope"), "stratified")


def test_auto_avoids_full_scans_of_large_tables():
    spec = SamplingSpec()
    assert spec.resolve(500) == "random"
    assert spec.resolve(spec.pool_cap + 1) == "head"
    assert spec.resolve(None) == "head"
    with pytest.raises(SamplingError):
        SamplingSpec(method="bogus")


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    audit_mod.install_guards(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def test_profiling_persists_versioned_metrics_without_raw_pii(client):
    r = client.post("/analyze/customers?sample_size=100&method=random&seed=3", headers=STEWARD)
    assert r.status_code == 200, r.text
    sampling = r.json()["sampling"]
    assert sampling["method"] == "random" and sampling["seed"] == 3 and sampling["reproducible"] is True
    run_id = r.json()["run_id"]

    m = client.get(f"/results/{run_id}/metrics", headers=REVIEWER)
    assert m.status_code == 200, m.text
    body = m.json()
    assert body["sampling"]["population_rows"] == sampling["population_rows"]
    cols = {c["column_name"]: c for c in body["columns"]}
    assert cols["email"]["sensitive"] is True and cols["email"]["top_values"] is None
    assert all(c["metrics_version"] == "1.0" for c in cols.values())
    # Same seed -> same metrics (reproducible run).
    again = client.post("/analyze/customers?sample_size=100&method=random&seed=3", headers=STEWARD).json()
    m2 = client.get(f"/results/{again['run_id']}/metrics", headers=REVIEWER).json()
    assert [c for c in m2["columns"]] == [c for c in body["columns"]]


def test_invalid_sampling_request_is_rejected(client):
    assert client.post("/analyze/customers?method=stratified", headers=STEWARD).status_code == 422
    assert client.post("/analyze/customers?method=stratified&stratify_by=customer_id",
                       headers=STEWARD).status_code == 422


def test_relationship_health_reports_exact_aggregates(client):
    assert client.post("/relationships/refresh?domain=healthcare", headers=STEWARD).status_code == 200
    r = client.get("/relationships/health?domain=healthcare", headers=REVIEWER)
    assert r.status_code == 200, r.text
    rels = {x["relationship"]: x for x in r.json()["relationships"]}
    appt = rels["appointments.patient_id -> patients.patient_id"]
    assert appt["orphan_references"] == 0 and appt["duplicate_parent_keys"] == 0
    assert 0 < appt["parent_coverage"] <= 1 and appt["max_children_per_parent"] >= 1
