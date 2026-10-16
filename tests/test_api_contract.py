"""Step 15: /api/v1 contract - OpenAPI snapshot, error envelope, aliases,
pagination bounds and idempotency."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.models import AnalysisRun
from api.main import app
from scripts.export_openapi import SNAPSHOT, current_schema, render

ADMIN = {"X-Dev-User": "admin1", "X-Dev-Roles": "admin"}
STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
TESTER = {"X-Dev-User": "tester1", "X-Dev-Roles": "tester"}


@pytest.fixture()
def env():
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
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, Session
    finally:
        client.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


# ── OpenAPI ──────────────────────────────────────────────────────────────────

def test_openapi_matches_committed_contract():
    with open(SNAPSHOT, encoding="utf-8") as f:
        committed = f.read()
    assert render(current_schema()) == committed, (
        "The /api/v1 contract changed. If intentional, run `python scripts/export_openapi.py` "
        "and commit docs/openapi-v1.json.")


def test_openapi_documents_only_versioned_paths():
    paths = current_schema()["paths"]
    assert paths and all(p.startswith("/api/v1/") for p in paths)


# ── error envelope ───────────────────────────────────────────────────────────

def _assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"] and body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "detail" in body                         # existing clients keep working


def test_error_envelope_for_each_failure_class(env, monkeypatch):
    client, _ = env
    _assert_error(client.get("/api/v1/reviews"), 401, "unauthenticated")
    _assert_error(client.post("/api/v1/plausibility/catalogue/healthcare/import", headers=TESTER), 403, "forbidden")
    _assert_error(client.get("/api/v1/results/999999", headers=ADMIN), 404, "not_found")
    _assert_error(client.post("/api/v1/agent/ask", headers=ADMIN, json={}), 422, "validation_error")
    _assert_error(client.post("/api/v1/mask/doctors?rows=5", headers=STEWARD), 409, "conflict")

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr("api.routers.core.source_service.list_all_sources", boom)
    r = client.get("/api/v1/tables", headers=ADMIN)
    _assert_error(r, 500, "internal_error")
    assert "secret internal detail" not in r.text


def test_request_id_is_echoed_when_safe(env):
    client, _ = env
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    generated = client.get("/health", headers={"X-Request-ID": "bad id\n<script>"}).headers["X-Request-ID"]
    assert generated != "bad id\n<script>" and len(generated) == 32


# ── aliases and deprecation ──────────────────────────────────────────────────

def test_legacy_alias_and_v1_share_one_handler(env):
    client, _ = env
    legacy = client.get("/data-dictionary", headers=ADMIN)
    v1 = client.get("/api/v1/data-dictionary", headers=ADMIN)
    assert legacy.status_code == v1.status_code == 200 and legacy.json() == v1.json()
    assert legacy.headers["Deprecation"] == "true" and "Sunset" in legacy.headers
    assert legacy.headers["Link"] == '</api/v1/data-dictionary>; rel="successor-version"'
    assert "Deprecation" not in v1.headers
    assert "Deprecation" not in client.get("/health").headers


# ── pagination ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,key", [
    ("/api/v1/rules", "rules"), ("/api/v1/sources", "sources"), ("/api/v1/jobs", "jobs"),
    ("/api/v1/workflows", "workflows"), ("/api/v1/datasets", "items"),
])
def test_list_endpoints_are_bounded(env, path, key):
    client, _ = env
    r = client.get(f"{path}?limit=2&offset=0", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["limit"] == 2 and body["offset"] == 0 and "total" in body and key in body
    _assert_error(client.get(f"{path}?limit=501", headers=ADMIN), 422, "validation_error")
    _assert_error(client.get(f"{path}?offset=-1", headers=ADMIN), 422, "validation_error")


def test_dataset_list_pages_through_results(env):
    client, _ = env
    client.post("/api/v1/analyze/customers?sample_size=20&method=head", headers=STEWARD)
    for _ in range(3):
        assert client.post("/api/v1/generate/customers?rows=5", headers=STEWARD).status_code == 200
    first = client.get("/api/v1/datasets?limit=2", headers=ADMIN).json()
    second = client.get("/api/v1/datasets?limit=2&offset=2", headers=ADMIN).json()
    assert first["total"] == 3 and len(first["items"]) == 2 and len(second["items"]) == 1
    assert {d["dataset_id"] for d in first["items"]}.isdisjoint({d["dataset_id"] for d in second["items"]})


# ── idempotency ──────────────────────────────────────────────────────────────

def test_idempotent_retry_does_not_create_a_second_run(env):
    client, Session = env
    h = dict(STEWARD, **{"Idempotency-Key": "profile-customers-1"})
    first = client.post("/api/v1/analyze/customers?sample_size=10&method=head", headers=h)
    again = client.post("/api/v1/analyze/customers?sample_size=10&method=head", headers=h)
    assert first.status_code == again.status_code == 200
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.json()["run_id"] == first.json()["run_id"]
    db = Session()
    try:
        assert db.query(AnalysisRun).count() == 1
    finally:
        db.close()

    conflict = client.post("/api/v1/analyze/customers?sample_size=11&method=head", headers=h)
    _assert_error(conflict, 409, "conflict")

    other_user = dict(ADMIN, **{"Idempotency-Key": "profile-customers-1"})
    assert client.post("/api/v1/analyze/customers?sample_size=10&method=head",
                       headers=other_user).headers.get("Idempotent-Replayed") is None


def test_failed_requests_are_not_cached_and_keys_are_validated(env):
    client, _ = env
    h = dict(STEWARD, **{"Idempotency-Key": "mask-1"})
    assert client.post("/api/v1/mask/doctors?rows=5", headers=h).status_code == 409   # not profiled
    retry = client.post("/api/v1/mask/doctors?rows=5", headers=h)
    assert retry.headers.get("Idempotent-Replayed") is None
    _assert_error(client.post("/api/v1/mask/doctors?rows=5",
                              headers=dict(STEWARD, **{"Idempotency-Key": "bad key!"})), 422, "validation_error")
