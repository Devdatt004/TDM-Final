"""
api/auth/models.py

Defines the CurrentUser dataclass — the canonical authenticated-user
object that flows through the application.

Design decisions
----------------
- Pure dataclass, no ORM dependency: stays testable and portable.
- Contains user_id, username, roles; deliberately no password / secret.
- ``tenant_id`` is reserved as a future extension point (single-tenant
  MVP — see SECURITY.md). Set to None for all current requests.
- ``is_system`` distinguishes background/system actions from human ones,
  so audit records are never misattributed.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


# Canonical roles.  Keep in sync with SECURITY.md.
ROLE_ADMIN = "admin"
ROLE_STEWARD = "steward"
ROLE_REVIEWER = "reviewer"
ROLE_TESTER = "tester"

ALL_ROLES = {ROLE_ADMIN, ROLE_STEWARD, ROLE_REVIEWER, ROLE_TESTER}


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated principal for one request.

    Attributes
    ----------
    user_id   : stable opaque identifier (sub from JWT, or dev user id).
    username  : human-readable display name.
    roles     : list of role strings (see constants above).
    tenant_id : reserved for future multi-tenant support; always None now.
    is_system : True only for background/daemon processes, never for
                real HTTP requests.
    """

    user_id: str
    username: str
    roles: List[str] = field(default_factory=list)
    tenant_id: Optional[str] = None      # Future multi-tenant hook
    is_system: bool = False

    def has_role(self, *required_roles: str) -> bool:
        """Return True if the user holds at least one of the given roles."""
        return bool(set(self.roles) & set(required_roles))


# ── System / background identity ──────────────────────────────────────────
# Used ONLY for background tasks (log purge, seed, backfill).
# Never injected into HTTP request pipelines.
SYSTEM_ACTOR = CurrentUser(
    user_id="system",
    username="system",
    roles=[],
    is_system=True,
)
