"""
HashiCorp Vault (KV v2) credential provider.

Reference format:  vault://<mount>/<secret path>
                   e.g. vault://secret/tdm/sources/warehouse
The secret must hold ``username`` and ``password`` keys.

Configuration (environment / secret injection, never the metadata DB):
  TDM_VAULT_ADDR         https://vault.internal:8200
  TDM_VAULT_TOKEN        token, or
  TDM_VAULT_TOKEN_FILE   path to a file holding the token (e.g. an agent sink)
  TDM_VAULT_NAMESPACE    optional (Vault Enterprise)
  TDM_VAULT_CA_CERT      optional CA bundle for TLS verification

Credentials are fetched per connection and never cached, persisted or logged;
error messages never include the token or the secret.
"""

import os
import re

import httpx

from .base import CredentialProvider

_PATH_RE = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+)+$")
TIMEOUT_SECONDS = 5.0


class VaultCredentialProvider(CredentialProvider):

    def __init__(self, environ=None, transport=None):
        self.env = os.environ if environ is None else environ
        self.transport = transport              # injectable for tests

    def _token(self) -> str:
        token = self.env.get("TDM_VAULT_TOKEN", "").strip()
        token_file = self.env.get("TDM_VAULT_TOKEN_FILE", "").strip()
        if not token and token_file:
            with open(token_file, encoding="utf-8") as f:
                token = f.read().strip()
        if not token:
            raise ValueError("Vault token is not configured.")
        return token

    def resolve(self, credential_ref: str) -> dict:
        if not credential_ref.startswith("vault://"):
            raise ValueError("Unsupported credential reference.")
        path = credential_ref[len("vault://"):].strip("/")
        if not _PATH_RE.match(path) or ".." in path:
            raise ValueError("Invalid Vault secret path.")
        addr = self.env.get("TDM_VAULT_ADDR", "").rstrip("/")
        if not addr.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("TDM_VAULT_ADDR must be an https:// URL.")
        mount, _, secret_path = path.partition("/")

        headers = {"X-Vault-Token": self._token()}
        if self.env.get("TDM_VAULT_NAMESPACE"):
            headers["X-Vault-Namespace"] = self.env["TDM_VAULT_NAMESPACE"]
        kwargs = {"timeout": TIMEOUT_SECONDS, "headers": headers}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        else:
            kwargs["verify"] = self.env.get("TDM_VAULT_CA_CERT") or True
        try:
            with httpx.Client(**kwargs) as client:
                response = client.get(f"{addr}/v1/{mount}/data/{secret_path}")
        except httpx.HTTPError as exc:
            raise ValueError("Vault is unreachable.") from exc
        if response.status_code != 200:
            raise ValueError(f"Vault returned HTTP {response.status_code} for the credential reference.")
        data = (response.json().get("data") or {}).get("data") or {}
        if not data.get("username") or not data.get("password"):
            raise ValueError("Vault secret must contain 'username' and 'password'.")
        return {"username": data["username"], "password": data["password"]}
