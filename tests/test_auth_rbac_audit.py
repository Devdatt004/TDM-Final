"""
tests/test_auth_rbac_audit.py

Step-3 tests: Authentication, RBAC, audit hardening, hash-chain integrity,
and concurrency safety.

Test design
-----------
- Uses FastAPI TestClient (via httpx) in development auth mode
  (X-Dev-User / X-Dev-Roles headers) so no real JWT signing key is needed.
- Uses SQLite with StaticPool so all connections share the same in-memory DB
  (required for SQLite :memory: to work correctly across sessions).
- Existing 4 referential-integrity tests are NOT touched.

Run all tests:
    python -m pytest tests/ -v
"""

import os
import threading

import pytest

# ── Force development auth mode for all tests ──────────────────────────────
os.environ["TDM_AUTH_MODE"] = "development"

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.audit import AuditError
from metadata_store.models import AuditLog


# ── In-memory test database (StaticPool = single shared connection) ────────
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)
audit_mod.install_guards(_engine)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Import app AFTER env var and session setup
from api.main import app  # noqa: E402

app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture()
def client():
    """TestClient backed by the in-memory test DB."""
    with __import__("starlette.testclient", fromlist=["TestClient"]).TestClient(
        app, raise_server_exceptions=True
    ) as c:
        yield c


@pytest.fixture()
def db():
    """Direct DB session for inspection."""
    session = _TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health endpoint — public, no auth required
# ─────────────────────────────────────────────────────────────────────────────

def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Authentication — unauthenticated access is rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_unauthenticated_protected_endpoint_returns_401(client):
    """No X-Dev-User header → 401 on a protected endpoint."""
    r = client.get("/tables")
    assert r.status_code == 401, r.text


def test_unauthenticated_summary_returns_401(client):
    r = client.get("/summary")
    assert r.status_code == 401


def test_unauthenticated_logs_returns_401(client):
    r = client.get("/logs")
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 3. Authentication — valid dev header succeeds
# ─────────────────────────────────────────────────────────────────────────────

def test_dev_auth_admin_can_access_protected_endpoint(client):
    r = client.get("/tables", headers={"X-Dev-User": "alice", "X-Dev-Roles": "admin"})
    assert r.status_code == 200, r.text


def test_dev_auth_steward_can_access_tables(client):
    r = client.get("/tables", headers={"X-Dev-User": "bob", "X-Dev-Roles": "steward"})
    assert r.status_code == 200, r.text


def test_dev_auth_reviewer_can_access_summary(client):
    r = client.get("/summary", headers={"X-Dev-User": "carol", "X-Dev-Roles": "reviewer"})
    assert r.status_code == 200, r.text


def test_dev_auth_tester_can_access_tables(client):
    r = client.get("/tables", headers={"X-Dev-User": "dave", "X-Dev-Roles": "tester"})
    assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────────
# 4. Authentication — no recognized role → forbidden on admin-only endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_dev_user_with_no_roles_cannot_access_admin_endpoint(client):
    """Dev user with no recognised roles cannot access admin endpoints."""
    r = client.get("/audit", headers={"X-Dev-User": "eve", "X-Dev-Roles": ""})
    assert r.status_code == 403, r.text


# ─────────────────────────────────────────────────────────────────────────────
# 5. RBAC — role-based access control
# ─────────────────────────────────────────────────────────────────────────────

def test_tester_cannot_access_admin_only_audit_log(client):
    r = client.get("/audit", headers={"X-Dev-User": "tester1", "X-Dev-Roles": "tester"})
    assert r.status_code == 403


def test_reviewer_cannot_access_audit_log(client):
    r = client.get("/audit", headers={"X-Dev-User": "rev1", "X-Dev-Roles": "reviewer"})
    assert r.status_code == 403


def test_steward_cannot_access_audit_log(client):
    r = client.get("/audit", headers={"X-Dev-User": "stew1", "X-Dev-Roles": "steward"})
    assert r.status_code == 403


def test_admin_can_access_audit_log(client):
    r = client.get("/audit", headers={"X-Dev-User": "admin1", "X-Dev-Roles": "admin"})
    assert r.status_code == 200, r.text


def test_tester_cannot_access_logs_purge(client):
    r = client.post("/logs/purge", headers={"X-Dev-User": "tester2", "X-Dev-Roles": "tester"})
    assert r.status_code == 403


def test_reviewer_cannot_purge_logs(client):
    r = client.post("/logs/purge", headers={"X-Dev-User": "rev2", "X-Dev-Roles": "reviewer"})
    assert r.status_code == 403


def test_admin_can_purge_logs(client):
    r = client.post("/logs/purge", headers={"X-Dev-User": "admin2", "X-Dev-Roles": "admin"})
    assert r.status_code == 200, r.text


def test_reviewer_can_view_logs(client):
    r = client.get("/logs", headers={"X-Dev-User": "rev3", "X-Dev-Roles": "reviewer"})
    assert r.status_code == 200, r.text


def test_tester_cannot_view_logs(client):
    """Tester role does not include log viewing."""
    r = client.get("/logs", headers={"X-Dev-User": "tester3", "X-Dev-Roles": "tester"})
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 6. Audit — actor identity captured correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_record_captures_user_identity(db):
    """Direct audit.record() writes username, user_id, and role."""
    audit_mod.record(
        db,
        event="TestEvent",
        username="testuser",
        status="complete",
        detail="unit test",
        target="test_table",
        target_type="DB Table",
        user_id="dev:testuser",
        role="steward",
    )
    entry = db.query(AuditLog).filter(AuditLog.event == "TestEvent").first()
    assert entry is not None
    assert entry.username == "testuser"
    assert entry.user_id == "dev:testuser"
    assert entry.role == "steward"
    assert entry.status == "complete"


def test_audit_record_is_not_system_for_authenticated_user(db):
    """Authenticated-user audit records must not use the 'system' identity."""
    audit_mod.record(
        db,
        event="AuthenticatedAction",
        username="alice",
        user_id="dev:alice",
        role="admin",
    )
    entry = db.query(AuditLog).filter(AuditLog.event == "AuthenticatedAction").first()
    assert entry.username != "system"
    assert entry.user_id != "system"


def test_system_audit_record_uses_system_identity(db):
    """Background system tasks use username='system'."""
    audit_mod.record(
        db,
        event="SystemCleanup",
        username="system",
        user_id="system",
        role=None,
    )
    entry = db.query(AuditLog).filter(AuditLog.event == "SystemCleanup").first()
    assert entry.username == "system"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Audit — failure is NOT silently ignored
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_failure_raises_audit_error():
    """AuditError is raised (not silently swallowed) when a DB write fails."""
    from unittest.mock import MagicMock

    # Build a mock session whose .add() raises a DB error
    mock_session = MagicMock()
    mock_session.query.return_value.order_by.return_value.first.return_value = None
    mock_session.add.side_effect = Exception("Simulated DB failure")

    with pytest.raises(AuditError):
        audit_mod.record(mock_session, event="ShouldFail", username="ghost")



# ─────────────────────────────────────────────────────────────────────────────
# 8. Audit — hash-chain integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_chain_is_intact_after_multiple_records(db):
    """After several writes the chain must verify cleanly."""
    for i in range(5):
        audit_mod.record(
            db,
            event=f"ChainEvent_{i}",
            username="chainuser",
            user_id="dev:chainuser",
            role="steward",
        )
    result = audit_mod.verify_chain(db)
    assert result["intact"] is True
    assert result["first_bad_id"] is None


def test_audit_chain_detects_tampering():
    """Out-of-band corruption of an entry_hash breaks chain verification."""
    # Use a separate engine WITHOUT the append-only triggers so we can tamper
    tamper_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TamperSession = sessionmaker(bind=tamper_engine)
    Base.metadata.create_all(bind=tamper_engine)
    # Do NOT install triggers so we can tamper

    s = TamperSession()
    audit_mod.record(s, event="BeforeTamper", username="u1", user_id="dev:u1")
    audit_mod.record(s, event="AfterTamper", username="u2", user_id="dev:u2")

    # Tamper directly with raw SQL (no trigger)
    s.execute(text("UPDATE audit_log SET entry_hash = 'tampered' WHERE event = 'BeforeTamper'"))
    s.commit()

    result = audit_mod.verify_chain(s)
    s.close()
    tamper_engine.dispose()

    assert result["intact"] is False
    assert result["first_bad_id"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 9. Audit — concurrent-safe chaining
# ─────────────────────────────────────────────────────────────────────────────

def test_concurrent_audit_writes_produce_valid_chain():
    """Simulate concurrent writes to ensure the threading lock prevents
    duplicate prev_hash usage and the resulting chain is intact."""
    conc_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ConSession = sessionmaker(bind=conc_engine)
    Base.metadata.create_all(bind=conc_engine)
    # No triggers — we want to test the lock, not the triggers

    errors = []

    def _write(i):
        s = ConSession()
        try:
            audit_mod.record(
                s, event=f"ConcurrentEvent_{i}",
                username="concuser", user_id="dev:concuser", role="tester",
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Audit write errors: {errors}"

    verify_session = ConSession()
    result = audit_mod.verify_chain(verify_session)
    verify_session.close()
    conc_engine.dispose()

    assert result["intact"] is True, (
        f"Chain broken after concurrent writes: first_bad_id={result['first_bad_id']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 10. SYSTEM_USER replacement — audit_service captures real user
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_service_captures_real_user_not_system(db):
    """record_audit() with a CurrentUser writes real identity, not 'system'."""
    from api.services import audit_service
    from api.auth.models import CurrentUser

    user = CurrentUser(user_id="dev:realuser", username="realuser", roles=["steward"])
    audit_service.record_audit(
        db, "PortalAction", user, "complete", "did something"
    )

    entry = db.query(AuditLog).filter(AuditLog.event == "PortalAction").first()
    assert entry is not None, "PortalAction audit entry not written"
    assert entry.username == "realuser", f"Expected 'realuser', got {entry.username!r}"
    assert entry.username != "system", "Authenticated user action was recorded as system!"
    assert entry.user_id == "dev:realuser"
    assert entry.role == "steward"


def test_audit_log_endpoint_shows_real_user(client, db):
    """The /audit endpoint returns entries with real user identity."""
    from api.services import audit_service
    from api.auth.models import CurrentUser

    user = CurrentUser(user_id="dev:endpointuser", username="endpointuser", roles=["admin"])
    audit_service.record_audit(
        db, "EndpointTest", user, "complete", "checking endpoint"
    )

    r = client.get("/audit", headers={"X-Dev-User": "admin3", "X-Dev-Roles": "admin"})
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    action_entries = [e for e in entries if e["event"] == "EndpointTest"]
    assert action_entries, "EndpointTest audit entry not returned by /audit"
    entry = action_entries[0]
    assert entry["user"] == "endpointuser"
    assert entry["user"] != "system"
    assert entry["user_id"] == "dev:endpointuser"
    assert entry["role"] == "admin"
