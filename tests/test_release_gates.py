"""Step 17: production must not trust development auth; deploy smoke test."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

from datetime import datetime, timedelta

from jose import jwt
from starlette.testclient import TestClient

from api.auth import dependencies
from api.main import app
from scripts.smoke_test import run

SECRET = "s" * 48


def _production(monkeypatch):
    monkeypatch.setattr(dependencies, "AUTH_MODE", "production")
    monkeypatch.setattr(dependencies, "JWT_SECRET", SECRET)


def test_production_rejects_development_headers(monkeypatch):
    _production(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/v1/reviews", headers={"X-Dev-User": "mallory", "X-Dev-Roles": "admin"})
    assert r.status_code == 401


def test_production_accepts_a_signed_token(monkeypatch):
    _production(monkeypatch)
    token = jwt.encode({"sub": "u1", "preferred_username": "alice", "roles": ["reviewer"],
                        "exp": datetime.utcnow() + timedelta(minutes=5)}, SECRET, algorithm="HS256")
    r = TestClient(app).get("/api/v1/data-dictionary", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


def test_smoke_script_passes_against_a_production_configured_app(monkeypatch):
    _production(monkeypatch)
    token = jwt.encode({"sub": "u1", "preferred_username": "smoke", "roles": ["reviewer"],
                        "exp": datetime.utcnow() + timedelta(minutes=5)}, SECRET, algorithm="HS256")
    assert run(TestClient(app), token) == []


def test_smoke_script_fails_when_dev_auth_is_live():
    # The default test configuration IS development mode - the smoke test must catch that.
    assert "development auth headers are NOT trusted" in run(TestClient(app))
