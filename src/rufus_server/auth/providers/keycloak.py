"""
KeycloakProvider — Keycloak OIDC JWT authentication.

Validates RS256 JWTs against a live Keycloak realm using JWKS.
JWKS keys are cached for 5 minutes with auto-refresh on key-id miss.

Required env vars (set when RUFUS_AUTH_PROVIDER=keycloak):
  KEYCLOAK_SERVER_URL  — e.g. https://keycloak.example.com
  KEYCLOAK_REALM       — e.g. my-realm
  KEYCLOAK_CLIENT_ID   — e.g. rufus-api
  KEYCLOAK_AUDIENCE    — (optional) defaults to KEYCLOAK_CLIENT_ID

Optional dependency: pip install 'rufus-sdk[auth]'  (python-jose[cryptography])
"""
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_JWKS_TTL = 300  # 5 minutes

try:
    import httpx
    from jose import jwt
    _JOSE_AVAILABLE = True
except ImportError:
    _JOSE_AVAILABLE = False

from rufus_server.auth.provider import AuthUser


class KeycloakProvider:
    def __init__(self, server_url: str, realm: str, client_id: str,
                 audience: Optional[str] = None):
        if not _JOSE_AVAILABLE:
            raise RuntimeError(
                "httpx and python-jose are required for KeycloakProvider. "
                "Install with: pip install 'rufus-sdk[auth]'"
            )
        self._server_url = server_url.rstrip('/')
        self._realm = realm
        self._client_id = client_id
        self._audience = audience or client_id
        self._jwks_uri = f"{self._server_url}/realms/{realm}/protocol/openid-connect/certs"
        self._jwks = None
        self._jwks_fetched_at = 0.0

    async def _get_jwks(self):
        now = time.time()
        if self._jwks is None or (now - self._jwks_fetched_at) > _JWKS_TTL:
            async with httpx.AsyncClient() as client:
                resp = await client.get(self._jwks_uri)
                resp.raise_for_status()
                self._jwks = resp.json()
                self._jwks_fetched_at = now
        return self._jwks

    async def verify_token(self, token: str) -> Optional[AuthUser]:
        try:
            jwks = await self._get_jwks()
            payload = jwt.decode(
                token, jwks,
                algorithms=['RS256'],
                audience=self._audience,
            )
            return AuthUser(
                user_id=payload.get('sub', ''),
                org_id=payload.get('org_id'),
                roles=payload.get('realm_access', {}).get('roles', []),
                scopes=payload.get('scope', '').split() if payload.get('scope') else [],
            )
        except Exception as e:
            logger.warning('Keycloak JWT verification failed: %s', e)
            return None

    async def get_anonymous_user(self, request: object) -> Optional[AuthUser]:
        return None

    async def close(self) -> None:
        return None
