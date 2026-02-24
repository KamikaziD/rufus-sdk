"""
RBAC Provider Protocol and AuthUser model.

Providers implement the RBACProvider Protocol (structural subtyping — no
inheritance required).  Each provider implements three async methods:

  verify_token(token)         — validate a Bearer token and return AuthUser
  get_anonymous_user(request) — called when no Bearer token is present;
                                the disabled provider reads X-User-ID headers
                                here; real auth providers return None
  close()                     — cleanup (close HTTP clients, etc.)
"""
from typing import Protocol, Optional, runtime_checkable
from pydantic import BaseModel


class AuthUser(BaseModel):
    """Authenticated user context.  Superset of the legacy UserContext model."""
    user_id: str
    org_id: Optional[str] = None
    roles: list = []
    scopes: list = []
    metadata: dict = {}


@runtime_checkable
class RBACProvider(Protocol):
    async def verify_token(self, token: str) -> Optional[AuthUser]: ...
    async def get_anonymous_user(self, request: object) -> Optional[AuthUser]: ...
    async def close(self) -> None: ...
