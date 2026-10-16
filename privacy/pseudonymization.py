"""
privacy/pseudonymization.py

Step 10 - keyed deterministic pseudonymization (HMAC-SHA-256).

    token = "pz_" + key_id + "_" + base32(HMAC(key, DOMAIN || namespace || canonical(value)))[:26]

Properties
  * Same key + namespace + canonical value  -> same token (joins survive).
  * Different namespace or key              -> unrelated token (no cross-linking).
  * Without the key, tokens cannot be recomputed from guessed inputs, which is
    why a plain hash is NOT used: SSNs, MRNs and account numbers are
    low-entropy and trivially enumerable.

This is pseudonymization, not encryption and not anonymization: anyone holding
the key can test guesses, and the remaining columns may still identify a
person. See docs/PSEUDONYMIZATION.md for the threat model.

Key material
  TDM_PSEUDONYM_KEYS           "kid:base64key[,kid:base64key...]"  (>= 32 bytes each)
  TDM_PSEUDONYM_ACTIVE_KEY_ID  kid used for new tokens (defaults to the first)

Keys come only from the environment / secret injection. They are never
logged, persisted, returned by the API or sent to agents. In development auth
mode with no keys configured, an ephemeral per-process key is generated (tokens
then change on every restart); in any other mode a missing key is an error.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "pz"
_DOMAIN = b"tdm-pseudonym-v1"
_DIGEST_CHARS = 26                      # 130 bits of base32 - ample for collision resistance
_MIN_KEY_BYTES = 32
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
_TOKEN_RE = re.compile(rf"^{TOKEN_PREFIX}_([A-Za-z0-9]{{1,16}})_([a-z2-7]{{{_DIGEST_CHARS}}})$")


class PseudonymizationError(ValueError):
    """Invalid input or configuration. Messages never contain the value or key."""


@dataclass(frozen=True)
class _Keyring:
    keys: dict          # kid -> bytes
    active_key_id: str
    ephemeral: bool = False


# ── Canonicalization ─────────────────────────────────────────────────────────

def canonicalize(value: Any) -> Optional[bytes]:
    """Map equivalent representations of an identifier onto one byte string.

    * None and blank strings -> None (callers keep nulls as nulls; a null is
      not an identifier and must not collapse to one shared token).
    * Strings: Unicode NFKC, trimmed, internal whitespace collapsed to one space.
      Case is preserved - identifiers such as PAN numbers are case-significant
      in some sources; normalise case upstream if a namespace needs it.
    * Integers, integral floats/Decimals -> plain decimal digits (42, 42.0 and
      "42" are the same identifier; "042" is not). Non-integral numbers keep their repr.
    * bytes -> decoded as UTF-8 then treated as a string.
    * tuple/list -> composite id; each part canonicalized and length-prefixed so
      ("ab","c") and ("a","bc") never collide. Any null part makes it null.
    * bool and anything else -> rejected (ambiguous as an identifier).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise PseudonymizationError("Booleans are not identifiers.")
    if isinstance(value, (tuple, list)):
        if not value:
            raise PseudonymizationError("Composite identifier has no parts.")
        parts = [canonicalize(v) for v in value]
        if any(p is None for p in parts):
            return None
        return b"C" + b"".join(len(p).to_bytes(4, "big") + p for p in parts)
    if isinstance(value, int):
        return b"N" + str(value).encode()
    if isinstance(value, (float, Decimal)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise PseudonymizationError("NaN/inf are not identifiers.")
        if value == int(value):
            return b"N" + str(int(value)).encode()
        return b"N" + repr(float(value)).encode()
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PseudonymizationError("Binary identifier is not valid UTF-8.") from exc
    if isinstance(value, str):
        text = " ".join(unicodedata.normalize("NFKC", value).split())
        if not text:
            return None
        # "42" and 42 are the same identifier, but leading zeros are kept:
        # "00123" and "123" can be different account numbers.
        if text.isascii() and text.isdigit():
            return b"N" + text.encode()
        return b"S" + text.encode("utf-8")
    raise PseudonymizationError(f"Unsupported identifier type: {type(value).__name__}.")


# ── Keyring ──────────────────────────────────────────────────────────────────

def _parse_keys(raw: str) -> dict:
    keys = {}
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        kid, sep, b64 = entry.partition(":")
        kid = kid.strip()
        if not sep or not _KEY_ID_RE.match(kid):
            raise PseudonymizationError("TDM_PSEUDONYM_KEYS entries must look like 'kid:base64key'.")
        try:
            material = base64.b64decode(b64.strip(), validate=True)
        except Exception as exc:
            raise PseudonymizationError(f"Key '{kid}' is not valid base64.") from exc
        if len(material) < _MIN_KEY_BYTES:
            raise PseudonymizationError(f"Key '{kid}' must be at least {_MIN_KEY_BYTES} bytes.")
        if kid in keys:
            raise PseudonymizationError(f"Key id '{kid}' is defined twice.")
        keys[kid] = material
    return keys


def load_keyring(environ=None) -> _Keyring:
    env = os.environ if environ is None else environ
    raw = env.get("TDM_PSEUDONYM_KEYS", "").strip()
    if not raw:
        if env.get("TDM_AUTH_MODE", "production").lower() == "development":
            logger.warning("[TDM Pseudonymization] No TDM_PSEUDONYM_KEYS set - using an "
                           "ephemeral development key; tokens will change on restart.")
            return _Keyring({"dev": secrets.token_bytes(_MIN_KEY_BYTES)}, "dev", ephemeral=True)
        raise PseudonymizationError("TDM_PSEUDONYM_KEYS is not configured.")
    keys = _parse_keys(raw)
    if not keys:
        raise PseudonymizationError("TDM_PSEUDONYM_KEYS contains no keys.")
    active = env.get("TDM_PSEUDONYM_ACTIVE_KEY_ID", "").strip() or next(iter(keys))
    if active not in keys:
        raise PseudonymizationError(f"Active key id '{active}' is not in TDM_PSEUDONYM_KEYS.")
    return _Keyring(keys, active)


class Pseudonymizer:
    """Deterministic keyed tokenizer. Holds keys in memory only; repr hides them."""

    def __init__(self, keyring: Optional[_Keyring] = None):
        self._keyring = keyring or load_keyring()

    def __repr__(self) -> str:
        return f"Pseudonymizer(active_key_id={self.active_key_id!r}, key_ids={self.key_ids!r})"

    @property
    def active_key_id(self) -> str:
        return self._keyring.active_key_id

    @property
    def key_ids(self) -> list:
        return sorted(self._keyring.keys)

    @property
    def ephemeral(self) -> bool:
        return self._keyring.ephemeral

    def pseudonymize(self, value: Any, namespace: str, key_id: Optional[str] = None) -> Optional[str]:
        """Token for ``value`` in ``namespace``; None stays None."""
        if not isinstance(namespace, str) or not _NAMESPACE_RE.match(namespace):
            raise PseudonymizationError(
                "Namespace must be lowercase letters/digits/'_'/'.', start with a letter, max 64 chars.")
        kid = key_id or self._keyring.active_key_id
        key = self._keyring.keys.get(kid)
        if key is None:
            raise PseudonymizationError(f"Unknown key id '{kid}'.")
        canonical = canonicalize(value)
        if canonical is None:
            return None
        message = _DOMAIN + b"\x00" + namespace.encode() + b"\x00" + canonical
        digest = hmac.new(key, message, hashlib.sha256).digest()
        encoded = base64.b32encode(digest).decode().lower().rstrip("=")[:_DIGEST_CHARS]
        return f"{TOKEN_PREFIX}_{kid}_{encoded}"

    def pseudonymize_many(self, values: Iterable[Any], namespace: str) -> list:
        return [self.pseudonymize(v, namespace) for v in values]

    def matches(self, token: str, value: Any, namespace: str) -> bool:
        """Constant-time check that ``token`` was derived from ``value`` (any known key)."""
        parsed = parse_token(token)
        if parsed is None or parsed[0] not in self._keyring.keys:
            return False
        expected = self.pseudonymize(value, namespace, key_id=parsed[0])
        return expected is not None and hmac.compare_digest(expected, token)

    def rotation_pairs(self, value: Any, namespace: str) -> dict:
        """Tokens for ``value`` under every loaded key - used when backfilling
        from source after a rotation so old and new tokens can be linked."""
        return {kid: self.pseudonymize(value, namespace, key_id=kid) for kid in self.key_ids}


def parse_token(token: Any) -> Optional[tuple]:
    """(key_id, digest) for a well-formed token, else None."""
    if not isinstance(token, str):
        return None
    m = _TOKEN_RE.match(token)
    return (m.group(1), m.group(2)) if m else None


def is_token(value: Any) -> bool:
    return parse_token(value) is not None


_default: Optional[Pseudonymizer] = None


def get_pseudonymizer() -> Pseudonymizer:
    """Process-wide instance (keys are read once)."""
    global _default
    if _default is None:
        _default = Pseudonymizer()
    return _default


def reset_pseudonymizer() -> None:
    """Drop the cached instance - for tests and key-rotation reloads."""
    global _default
    _default = None
