"""
security/startup_checks.py

Step 16/17 - refuse to start a non-development deployment that is missing its
secrets or has unsafe settings. Development mode only logs warnings.
"""

import logging
import os

logger = logging.getLogger(__name__)

VALID_AUTH_MODES = {"production", "development"}
_PLACEHOLDER_MARKERS = ("REPLACE", "CHANGE_ME", "CHANGEME", "EXAMPLE")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def check(environ=None) -> tuple:
    """(errors, warnings) for the given environment."""
    env = os.environ if environ is None else environ
    errors, warnings = [], []
    mode = env.get("TDM_AUTH_MODE", "production").lower()
    if mode not in VALID_AUTH_MODES:
        errors.append(f"TDM_AUTH_MODE must be one of {sorted(VALID_AUTH_MODES)}.")
        return errors, warnings
    if mode == "development":
        warnings.append("Development auth mode: X-Dev-User headers are trusted. Never expose this deployment.")
        return errors, warnings

    secret = env.get("TDM_JWT_SECRET", "")
    if len(secret) < 32 or any(m in secret.upper() for m in _PLACEHOLDER_MARKERS):
        errors.append("TDM_JWT_SECRET must be a real random secret of at least 32 characters.")

    from security import artifact_store
    try:
        keys, _ = artifact_store._keys(env)
        if not keys:
            errors.append("TDM_ARTIFACT_KEYS is required (files are encrypted at rest).")
    except artifact_store.ArtifactKeyError as exc:
        errors.append(str(exc))

    from privacy.pseudonymization import PseudonymizationError, load_keyring
    try:
        load_keyring(env)
    except PseudonymizationError as exc:
        errors.append(f"Pseudonymization keys: {exc}")

    origins = [o.strip() for o in env.get("TDM_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if not origins:
        errors.append("TDM_ALLOWED_ORIGINS must list the production frontend origin(s).")
    for origin in origins:
        if origin == "*":
            errors.append("TDM_ALLOWED_ORIGINS must not contain '*'.")
        elif any(h in origin for h in _LOCAL_HOSTS):
            errors.append(f"Local origin '{origin}' is not allowed in production.")
        elif not origin.startswith("https://"):
            errors.append(f"Origin '{origin}' must use https://.")

    db_dir = env.get("TDM_DATA_DIR", "")
    warnings.append("Metadata store is SQLite" + (f" in {db_dir}" if db_dir else "") +
                    ": single writer and not encrypted by itself. Keep TDM_DATA_DIR on an encrypted "
                    "volume and back it up with scripts/backup_metadata.py (see docs/DATA_LIFECYCLE.md).")
    return errors, warnings


def enforce(environ=None) -> None:
    errors, warnings = check(environ)
    for w in warnings:
        logger.warning("[TDM Startup] %s", w)
    if errors:
        raise RuntimeError("Refusing to start - unsafe configuration:\n  - " + "\n  - ".join(errors))
