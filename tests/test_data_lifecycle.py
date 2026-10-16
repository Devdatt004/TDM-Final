"""Step 16: secrets, encryption at rest, landing zone, retention, startup checks, backup."""
import os
os.environ.setdefault("TDM_AUTH_MODE", "development")

import base64
import json
import sqlite3
from datetime import datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from credentials import resolver
from credentials.vault_provider import VaultCredentialProvider
from metadata_store.db import Base, get_db
from metadata_store import audit as audit_mod
from metadata_store.models import AuditLog, SyntheticDataset, UploadedSource
from security import artifact_store, startup_checks
from api.routers import connectors
from api.services import retention_service
from api.main import app

ADMIN = {"X-Dev-User": "admin1", "X-Dev-Roles": "admin"}
STEWARD = {"X-Dev-User": "steward1", "X-Dev-Roles": "steward"}
K1, K2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()


# ── encryption at rest ───────────────────────────────────────────────────────

def test_encrypted_round_trip_hides_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k1:{K1}")
    path = tmp_path / "a.csv"
    artifact_store.write_text(str(path), "ssn\n123-45-6789\n")
    raw = path.read_bytes()
    assert raw.startswith(b"TDMENC1 k1\n") and b"123-45-6789" not in raw
    assert artifact_store.read_text(str(path)) == "ssn\n123-45-6789\n"


def test_tampering_and_unknown_keys_are_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k1:{K1}")
    path = tmp_path / "a.csv"
    artifact_store.write_text(str(path), "secret")
    data = bytearray(path.read_bytes())
    data[-5] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(artifact_store.ArtifactKeyError):
        artifact_store.read_text(str(path))
    artifact_store.write_text(str(path), "secret")
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k2:{K2}")
    with pytest.raises(artifact_store.ArtifactKeyError):
        artifact_store.read_text(str(path))


def test_key_rotation(tmp_path, monkeypatch):
    path = str(tmp_path / "a.csv")
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k1:{K1}")
    artifact_store.write_text(path, "data")
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k1:{K1},k2:{K2}")
    monkeypatch.setenv("TDM_ARTIFACT_ACTIVE_KEY_ID", "k2")
    assert artifact_store.read_text(path) == "data"           # old files still readable
    assert artifact_store.rotate_file(path) is True and artifact_store.key_id_of(path) == "k2"
    assert artifact_store.rotate_file(path) is False
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k2:{K2}")         # retire k1
    monkeypatch.delenv("TDM_ARTIFACT_ACTIVE_KEY_ID")
    assert artifact_store.read_text(path) == "data"


def test_missing_key_fails_closed_outside_development(tmp_path, monkeypatch):
    monkeypatch.delenv("TDM_ARTIFACT_KEYS", raising=False)
    monkeypatch.setenv("TDM_AUTH_MODE", "production")
    with pytest.raises(artifact_store.ArtifactKeyError):
        artifact_store.write_text(str(tmp_path / "a.csv"), "x")
    monkeypatch.setenv("TDM_AUTH_MODE", "development")
    artifact_store.write_text(str(tmp_path / "b.csv"), "x")    # dev: plaintext, still readable
    assert artifact_store.read_text(str(tmp_path / "b.csv")) == "x"


# ── API with keys configured ─────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k1:{K1}")
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
        yield c, Session
    finally:
        c.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        engine.dispose()


def test_generated_files_are_encrypted_and_download_decrypts(client):
    c, Session = client
    c.post("/api/v1/analyze/customers?sample_size=20&method=head", headers=STEWARD)
    g = c.post("/api/v1/generate/customers?rows=5", headers=STEWARD).json()
    db = Session()
    try:
        path = db.query(SyntheticDataset).one().file_path
    finally:
        db.close()
    raw = open(path, "rb").read()
    assert raw.startswith(b"TDMENC1 ") and b"customer_id" not in raw
    d = c.get(f"/api/v1/generate/download/{g['dataset_id']}", headers=STEWARD)
    assert d.status_code == 200 and d.text.startswith("customer_id")
    assert "attachment" in d.headers["content-disposition"]


def test_upload_landing_zone(client):
    c, Session = client
    content = "id,name\n1,Alice\n2,Bob\n"
    r = c.post("/api/v1/upload", headers=STEWARD, json={"filename": "../../etc/evil names.csv", "content": content})
    assert r.status_code == 200, r.text
    assert "file_path" not in r.json()
    db = Session()
    try:
        row = db.query(UploadedSource).one()
    finally:
        db.close()
    assert os.path.dirname(os.path.abspath(row.file_path)) == os.path.abspath(connectors.UPLOAD_DIR)
    assert "evil" not in os.path.basename(row.file_path)
    assert b"Alice" not in open(row.file_path, "rb").read()
    assert c.post(f"/api/v1/analyze/{r.json()['name']}?sample_size=10", headers=STEWARD).status_code == 200

    assert c.post("/api/v1/upload", headers=STEWARD,
                  json={"filename": "x.csv", "content": "a,b\n1,\x00\x01\n"}).status_code == 400
    assert c.post("/api/v1/upload", headers=STEWARD,
                  json={"filename": "x.exe", "content": "MZ"}).status_code == 400
    assert c.post("/api/v1/upload", headers=STEWARD,
                  json={"filename": "x.csv", "content": "a" * 5_000_001}).status_code == 413


def test_replacing_an_upload_removes_the_old_file(client):
    c, Session = client
    c.post("/api/v1/upload", headers=STEWARD, json={"filename": "same.csv", "content": "a\n1\n"})
    db = Session()
    first = db.query(UploadedSource).one().file_path
    db.close()
    c.post("/api/v1/upload", headers=STEWARD, json={"filename": "same.csv", "content": "a\n2\n"})
    db = Session()
    second = db.query(UploadedSource).one().file_path
    db.close()
    assert first != second and not os.path.exists(first) and os.path.exists(second)


# ── secrets ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref", ["env://WAREHOUSE_CREDS", "vault://secret/tdm/sources/warehouse"])
def test_valid_references(ref):
    assert resolver.validate_ref(ref) == ref


@pytest.mark.parametrize("ref", ["admin:hunter2", "env://", "vault://secret", "vault://secret/../x",
                                 "postgres://u:p@h/db", "env://A B"])
def test_literal_secrets_and_bad_references_are_rejected(ref):
    with pytest.raises(ValueError):
        resolver.validate_ref(ref)


def test_source_registry_refuses_plaintext_credentials(client):
    c, _ = client
    r = c.post("/api/v1/sources", headers=ADMIN, json={
        "name": "warehouse", "source_type": "postgresql", "host": "db.internal",
        "database_name": "dw", "credential_ref": "admin:hunter2"})
    assert r.status_code == 422 and "hunter2" not in r.text


def _vault(handler, **env):
    base = {"TDM_VAULT_ADDR": "https://vault.test", "TDM_VAULT_TOKEN": "s.supersecrettoken"}
    base.update(env)
    return VaultCredentialProvider(environ=base, transport=httpx.MockTransport(handler))


def test_vault_provider_reads_kv_v2():
    seen = {}

    def handler(request):
        seen["url"], seen["token"] = str(request.url), request.headers["X-Vault-Token"]
        return httpx.Response(200, json={"data": {"data": {"username": "svc", "password": "pw"}}})

    creds = _vault(handler).resolve("vault://secret/tdm/warehouse")
    assert creds == {"username": "svc", "password": "pw"}
    assert seen["url"] == "https://vault.test/v1/secret/data/tdm/warehouse"
    assert seen["token"] == "s.supersecrettoken"


@pytest.mark.parametrize("response,env", [
    (httpx.Response(403, json={"errors": ["permission denied"]}), {}),
    (httpx.Response(200, json={"data": {"data": {"username": "svc"}}}), {}),
    (httpx.Response(200, json={}), {"TDM_VAULT_ADDR": "http://vault.test"}),      # plain http refused
    (httpx.Response(200, json={}), {"TDM_VAULT_TOKEN": ""}),
])
def test_vault_failures_never_leak_the_token(response, env):
    with pytest.raises(ValueError) as exc:
        _vault(lambda request: response, **env).resolve("vault://secret/tdm/warehouse")
    assert "supersecrettoken" not in str(exc.value) and "pw" not in str(exc.value)


# ── retention ────────────────────────────────────────────────────────────────

def test_retention_purge_is_safe_and_audited(client, monkeypatch):
    c, Session = client
    c.post("/api/v1/analyze/customers?sample_size=20&method=head", headers=STEWARD)
    old = c.post("/api/v1/generate/customers?rows=5", headers=STEWARD).json()
    fresh = c.post("/api/v1/generate/customers?rows=5", headers=STEWARD).json()
    c.post("/api/v1/upload", headers=STEWARD, json={"filename": "old.csv", "content": "a\n1\n"})
    db = Session()
    try:
        ds = db.query(SyntheticDataset).filter_by(public_id=old["dataset_id"]).one()
        ds.created_at = datetime.utcnow() - timedelta(days=31)
        up = db.query(UploadedSource).one()
        up.uploaded_at = datetime.utcnow() - timedelta(days=31)
        old_file, upload_file = ds.file_path, up.file_path
        db.commit()
        os.remove(old_file)                                   # already gone: must not break the purge
        result = retention_service.purge_expired(db)
        assert result == {"datasets_purged": 1, "uploads_purged": 1, "errors": 0}
        assert not os.path.exists(upload_file)
        assert db.query(UploadedSource).count() == 0
        assert db.query(SyntheticDataset).filter_by(public_id=old["dataset_id"]).one().purged_at is not None
        assert db.query(AuditLog).filter(AuditLog.event == "Artifact Retention Purge").count() == 1
        assert retention_service.purge_expired(db) == {"datasets_purged": 0, "uploads_purged": 0, "errors": 0}
    finally:
        db.close()
    assert c.get(f"/api/v1/generate/download/{old['dataset_id']}", headers=STEWARD).status_code == 410
    assert c.get(f"/api/v1/generate/download/{fresh['dataset_id']}", headers=STEWARD).status_code == 200


# ── startup guardrails ───────────────────────────────────────────────────────

def _prod_env(**over):
    env = {
        "TDM_AUTH_MODE": "production",
        "TDM_JWT_SECRET": "x9" * 24,
        "TDM_ARTIFACT_KEYS": f"k1:{K1}",
        "TDM_PSEUDONYM_KEYS": "p1:" + base64.b64encode(b"P" * 32).decode(),
        "TDM_ALLOWED_ORIGINS": "https://tdm.example.org",
    }
    env.update(over)
    return env


def test_valid_production_config_starts():
    errors, warnings = startup_checks.check(_prod_env())
    assert errors == [] and any("SQLite" in w for w in warnings)


@pytest.mark.parametrize("over,needle", [
    ({"TDM_JWT_SECRET": "REPLACE_WITH_RANDOM_SECRET_NEVER_COMMIT_THIS"}, "TDM_JWT_SECRET"),
    ({"TDM_ARTIFACT_KEYS": ""}, "TDM_ARTIFACT_KEYS"),
    ({"TDM_PSEUDONYM_KEYS": ""}, "Pseudonymization"),
    ({"TDM_ALLOWED_ORIGINS": "*"}, "'*'"),
    ({"TDM_ALLOWED_ORIGINS": "http://localhost:5173"}, "Local origin"),
    ({"TDM_ALLOWED_ORIGINS": "http://tdm.example.org"}, "https"),
    ({"TDM_AUTH_MODE": "devel"}, "TDM_AUTH_MODE"),
])
def test_unsafe_production_config_is_refused(over, needle):
    errors, _ = startup_checks.check(_prod_env(**over))
    assert any(needle in e for e in errors), errors
    with pytest.raises(RuntimeError):
        startup_checks.enforce(_prod_env(**over))


# ── backup / restore ─────────────────────────────────────────────────────────

def test_encrypted_backup_and_verified_restore(tmp_path, monkeypatch):
    from scripts import backup_metadata
    monkeypatch.setenv("TDM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TDM_ARTIFACT_KEYS", f"k1:{K1}")
    db = tmp_path / "metadata_store.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE alembic_version (version_num TEXT)")
    con.execute("INSERT INTO alembic_version VALUES ('a9d3e5f7b2c1')")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('before')")
    con.commit()
    con.close()

    backup_file = backup_metadata.backup(str(tmp_path / "backups"))
    assert backup_file.endswith(".enc") and b"before" not in open(backup_file, "rb").read()

    con = sqlite3.connect(db)
    con.execute("UPDATE t SET v = 'after'")
    con.commit()
    con.close()
    assert backup_metadata.restore(backup_file) == "a9d3e5f7b2c1"
    con = sqlite3.connect(db)
    assert con.execute("SELECT v FROM t").fetchone()[0] == "before"
    con.close()
    assert os.path.exists(str(db) + ".pre-restore")

    corrupt = tmp_path / "corrupt.db"
    artifact_store.write_bytes(str(corrupt), b"not a database" * 100)
    with pytest.raises(Exception):
        backup_metadata.restore(str(corrupt))
