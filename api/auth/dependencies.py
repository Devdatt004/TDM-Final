"""
api/auth/dependencies.py

FastAPI dependency functions for authentication and RBAC.

Authentication flow
-------------------
    HTTP request
        ↓  Authorization: Bearer <token>
    get_current_user()
        ↓  validates JWT (or dev-mode header)
    CurrentUser
        ↓
    require_role(...)
        ↓
    endpoint logic

Auth modes (TDM_AUTH_MODE env var)
-----------------------------------
``production``  (default)
    Requires a signed JWT in the Authorization: Bearer header.
    The JWT must be issued by the configured TDM_JWT_ISSUER and
    targeted at TDM_JWT_AUDIENCE.
    The signing key is read from TDM_JWT_SECRET (HS256) or, for
    RS256/OIDC, from the issuer's JWKS endpoint (future extension).
    Missing or invalid tokens → HTTP 401.

``development``
    A lightweight development token is accepted:
        X-Dev-User: <username>
        X-Dev-Roles: admin,steward          (comma-separated, optional)
    NEVER use in production.  The server logs a warning at startup.

SECURITY NOTE: Never log the raw token.  Log only the username / user_id
extracted from it.
"""

from __future__ import annotations

import logging
import os
from typing import List

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jose import JWTError, jwt

from api.auth.models import ALL_ROLES, CurrentUser, ROLE_ADMIN

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
AUTH_MODE = os.getenv("TDM_AUTH_MODE", "production").lower()
JWT_SECRET = os.getenv("TDM_JWT_SECRET", "")
JWT_ISSUER = os.getenv("TDM_JWT_ISSUER", "")
JWT_AUDIENCE = os.getenv("TDM_JWT_AUDIENCE", "")
JWT_ALGORITHM = os.getenv("TDM_JWT_ALGORITHM", "HS256")

_bearer = HTTPBearer(auto_error=False)

if AUTH_MODE == "development":
    log.warning(
        "[TDM Auth] ⚠  Running in DEVELOPMENT auth mode "
        "(TDM_AUTH_MODE=development).  "
        "X-Dev-User / X-Dev-Roles headers are trusted WITHOUT a real token.  "
        "DO NOT use this in production."
    )


# ── Internal helpers ───────────────────────────────────────────────────────

def _decode_jwt(token: str) -> dict:
    """Decode and verify a JWT.  Raises HTTPException on failure."""
    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is not configured for JWT authentication "
                   "(TDM_JWT_SECRET not set).",
        )
    opts: dict = {}
    aud_opts: dict = {"audience": JWT_AUDIENCE} if JWT_AUDIENCE else {"options": {"verify_aud": False}}
    iss_opts: dict = {"issuer": JWT_ISSUER} if JWT_ISSUER else {}
    try:
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            **aud_opts,
            **iss_opts,
        )
    except JWTError as exc:
        log.warning("[TDM Auth] JWT validation failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _user_from_claims(claims: dict) -> CurrentUser:
    """Build a CurrentUser from decoded JWT claims."""
    user_id = claims.get("sub") or claims.get("uid") or ""
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("name")
        or user_id
    )
    raw_roles = claims.get("roles") or claims.get("tdm_roles") or []
    roles = [r for r in raw_roles if r in ALL_ROLES]
    return CurrentUser(user_id=user_id, username=username, roles=roles)


# ── Public FastAPI dependencies ────────────────────────────────────────────

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """FastAPI dependency: resolve the authenticated CurrentUser for a request.

    In ``production`` mode a valid Bearer JWT is required.
    In ``development`` mode the X-Dev-User header is accepted instead.
    """
    if AUTH_MODE == "development":
        dev_user = request.headers.get("X-Dev-User", "").strip()
        if dev_user:
            dev_roles_raw = request.headers.get("X-Dev-Roles", "").strip()
            dev_roles = [r.strip() for r in dev_roles_raw.split(",") if r.strip() in ALL_ROLES]
            return CurrentUser(
                user_id=f"dev:{dev_user}",
                username=dev_user,
                roles=dev_roles,
            )
        # In dev mode, fall through to JWT if no X-Dev-User provided

    # Production path — require Bearer token
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.  Provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _decode_jwt(credentials.credentials)
    return _user_from_claims(claims)


def require_role(*roles: str):
    """Return a FastAPI dependency that enforces that the current user holds
    at least one of the given roles.

    Usage::

        @router.post("/analyze/{table_name}")
        def analyze(
            table_name: str,
            user: CurrentUser = Depends(require_role("admin", "steward")),
        ):
            ...
    """
    def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(*roles):
            log.warning(
                "[TDM RBAC] Access denied for user=%s roles=%s required=%s",
                user.username, user.roles, roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden. Required role(s): {', '.join(roles)}.",
            )
        return user
    return _dependency


# ── Convenience role combiners ─────────────────────────────────────────────
# Pre-built dependency factories for common RBAC checks.

def require_admin():
    return require_role(ROLE_ADMIN)


def require_steward_or_admin():
    return require_role("admin", "steward")


def require_reviewer_or_above():
    return require_role("admin", "steward", "reviewer")


def require_tester_or_above():
    return require_role("admin", "steward", "reviewer", "tester")
