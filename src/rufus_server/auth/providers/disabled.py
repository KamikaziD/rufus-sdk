"""
DisabledProvider — default auth provider.

Preserves existing X-User-ID / X-Org-ID header-based behaviour exactly.
Never raises 401.  Roles and scopes are always empty (no enforcement).
"""
from typing import Optional
from rufus_server.auth.provider import AuthUser


class DisabledProvider:
    """No-op provider that reads X-User-ID / X-Org-ID headers."""

    async def verify_token(self, token: str) -> Optional[AuthUser]:
        return None

    async def get_anonymous_user(self, request: object) -> Optional[AuthUser]:
        headers = getattr(request, 'headers', {})
        user_id = headers.get('X-User-ID') or headers.get('x-user-id')
        org_id = headers.get('X-Org-ID') or headers.get('x-org-id')
        if user_id:
            return AuthUser(user_id=user_id, org_id=org_id)
        return None

    async def close(self) -> None:
        return None
