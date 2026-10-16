"""
Resolve a source's credential_ref to connection credentials (Step 16).

The source registry stores only a REFERENCE; this is the single place that
turns one into a secret, at connection time.

  env://NAME            environment variable NAME holding "username:password"
  vault://mount/path    HashiCorp Vault KV v2 secret with username/password
"""

import re

from .env_provider import EnvironmentCredentialProvider
from .vault_provider import VaultCredentialProvider

_REF_RE = re.compile(r"^(env://[A-Za-z_][A-Za-z0-9_]{0,127}|vault://[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+)+)$")

PROVIDERS = {
    "env://": EnvironmentCredentialProvider,
    "vault://": VaultCredentialProvider,
}


def validate_ref(credential_ref: str) -> str:
    """Accept only well-formed references - never a literal secret."""
    ref = (credential_ref or "").strip()
    if not _REF_RE.match(ref) or ".." in ref:
        raise ValueError(
            "credential_ref must be a reference such as env://SOURCE_DB_CREDENTIALS or "
            "vault://secret/tdm/sources/<name> - never the credentials themselves.")
    return ref


def resolve(credential_ref: str) -> dict:
    ref = validate_ref(credential_ref)
    for scheme, provider in PROVIDERS.items():
        if ref.startswith(scheme):
            return provider().resolve(ref)
    raise ValueError("Unsupported credential reference.")
