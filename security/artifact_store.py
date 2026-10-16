"""
security/artifact_store.py

Step 16 - encryption at rest for files the platform writes: uploaded sources,
synthetic and masked datasets.

File format
    b"TDMENC1 " + key_id + b"\\n" + Fernet token        (AES-128-CBC + HMAC-SHA256)
Files without the header are legacy plaintext and are still readable, so an
existing deployment keeps working and can be migrated with rotate_file().

Keys
    TDM_ARTIFACT_KEYS           "kid:<Fernet key>[,kid:<Fernet key>]"
    TDM_ARTIFACT_ACTIVE_KEY_ID  kid used for new files (default: first)
Generate a key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Without keys, development mode writes plaintext (one warning); every other
mode refuses to write (fail closed). Keys are never logged or persisted.
"""

import logging
import os
import re
import tempfile

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

MAGIC = b"TDMENC1 "
_KID_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
_warned = False


class ArtifactKeyError(RuntimeError):
    """Keys missing/invalid, or a file cannot be decrypted with the loaded keys."""


def _keys(environ=None) -> tuple:
    env = os.environ if environ is None else environ
    raw = env.get("TDM_ARTIFACT_KEYS", "").strip()
    if not raw:
        return {}, None
    keys = {}
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        kid, sep, key = entry.partition(":")
        if not sep or not _KID_RE.match(kid):
            raise ArtifactKeyError("TDM_ARTIFACT_KEYS entries must look like 'kid:<fernet key>'.")
        try:
            keys[kid] = Fernet(key.strip().encode())
        except Exception as exc:
            raise ArtifactKeyError(f"Artifact key '{kid}' is not a valid Fernet key.") from exc
    active = env.get("TDM_ARTIFACT_ACTIVE_KEY_ID", "").strip() or next(iter(keys))
    if active not in keys:
        raise ArtifactKeyError(f"Active artifact key '{active}' is not configured.")
    return keys, active


def encryption_enabled() -> bool:
    return bool(_keys()[0])


def encrypt(data: bytes) -> bytes:
    global _warned
    keys, active = _keys()
    if not keys:
        if os.getenv("TDM_AUTH_MODE", "production").lower() != "development":
            raise ArtifactKeyError("TDM_ARTIFACT_KEYS is not configured; refusing to write unencrypted data.")
        if not _warned:
            logger.warning("[TDM Artifacts] TDM_ARTIFACT_KEYS not set - writing PLAINTEXT files (development only).")
            _warned = True
        return data
    return MAGIC + active.encode() + b"\n" + keys[active].encrypt(data)


def decrypt(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        return blob                                   # legacy plaintext
    header, _, token = blob.partition(b"\n")
    kid = header[len(MAGIC):].decode(errors="replace")
    keys, _ = _keys()
    fernet = keys.get(kid)
    if fernet is None:
        raise ArtifactKeyError(f"File was encrypted with key '{kid}', which is not loaded.")
    try:
        return fernet.decrypt(token)
    except InvalidToken as exc:
        raise ArtifactKeyError("File failed integrity check (tampered or wrong key).") from exc


def key_id_of(path: str):
    with open(path, "rb") as f:
        head = f.readline()
    return head[len(MAGIC):].strip().decode() if head.startswith(MAGIC) else None


def write_bytes(path: str, data: bytes) -> None:
    """Atomic write (temp file + rename) so a crash never leaves a partial file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encrypt(data))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return decrypt(f.read())


def write_text(path: str, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def read_text(path: str) -> str:
    return read_bytes(path).decode("utf-8")


def rotate_file(path: str) -> bool:
    """Re-encrypt with the active key (also encrypts legacy plaintext).
    Returns True if the file changed."""
    keys, active = _keys()
    if not keys:
        raise ArtifactKeyError("No artifact keys configured.")
    if key_id_of(path) == active:
        return False
    write_bytes(path, read_bytes(path))
    return True
