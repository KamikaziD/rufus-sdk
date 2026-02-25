"""
FastAPI Depends() factories for RBAC.

All functions delegate to the active provider singleton set by loader.py at
server startup.  If no provider has been set (e.g., during unit tests without
a running server), the implementation falls back to X-User-ID header reading
so tests don't break.
"""
from typing import Optional
from fastapi import Depends, HTTPException, Request
from rufus_server.auth.provider import AuthUser

_provider = None


def set_provider(provider: object) -> None:
    global _provider
    _provider = provider


async def get_current_user(request: Request) -> Optional[AuthUser]:
    if _provider is None:
        # Fallback: read X-User-ID / X-Org-ID headers (preserves legacy behaviour)
        user_id = request.headers.get('X-User-ID') or request.headers.get('x-user-id')
        org_id = request.headers.get('X-Org-ID') or request.headers.get('x-org-id')
        if user_id:
            return AuthUser(user_id=user_id, org_id=org_id)
        return None
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        return await _provider.verify_token(token)
    return await _provider.get_anonymous_user(request)


def require_role(*roles: str):
    async def _check(user: Optional[AuthUser] = Depends(get_current_user)) -> AuthUser:
        if user is None or not any(r in user.roles for r in roles):
            raise HTTPException(status_code=403, detail='Insufficient role')
        return user
    return _check


def require_scope(*scopes: str):
    async def _check(user: Optional[AuthUser] = Depends(get_current_user)) -> AuthUser:
        if user is None or not any(s in user.scopes for s in scopes):
            raise HTTPException(status_code=403, detail='Insufficient scope')
        return user
    return _check


async def require_admin(user: Optional[AuthUser] = Depends(get_current_user)) -> AuthUser:
    """Dependency that requires the current user to have the 'admin' role."""
    if user is None or "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
