import os

from .base import CredentialProvider


class EnvironmentCredentialProvider(CredentialProvider):

    def resolve(self, credential_ref: str) -> dict:
        if not credential_ref:
            return {}

        if not credential_ref.startswith("env://"):
            raise ValueError(
                f"Unsupported credential reference: {credential_ref}"
            )

        key = credential_ref[len("env://"):].strip()

        if not key:
            raise ValueError("Credential reference is empty.")

        value = os.getenv(key)

        if not value:
            raise ValueError(
                f"Credential environment variable '{key}' is not configured."
            )

        # Expected format:
        # username:password
        if ":" not in value:
            raise ValueError(
                f"Credential environment variable '{key}' has invalid format."
            )

        username, password = value.split(":", 1)

        return {
            "username": username,
            "password": password,
        }