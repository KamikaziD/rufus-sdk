"""
JWTProvider — generic JWT authentication (HS256 or RS256).

Required env vars (set when RUFUS_AUTH_PROVIDER=jwt):
  JWT_ALGORITHM    — HS256 (default) or RS256
  JWT_SECRET_KEY   — HMAC secret (HS256)
  JWT_PUBLIC_KEY   — PEM public key (RS256)
  JWT_ISSUER       — (optional) expected `iss` claim

Optional dependency: pip install 'rufus-sdk[auth]'  (python-jose[cryptography])
"""
import logging
from typing import Optional
from rufus_server.auth.provider import AuthUser

logger = logging.getLogger(__name__)

try:
    from jose import jwt
    _JOSE_AVAILABLE = True
except ImportError:
    _JOSE_AVAILABLE = False


class JWTProvider:
    def __init__(self, algorithm: str = 'HS256', secret_key: Optional[str] = None,
                 public_key: Optional[str] = None, issuer: Optional[str] = None):
        if not _JOSE_AVAILABLE:
            raise RuntimeError(
                "python-jose is required for JWTProvider. "
                "Install with: pip install 'rufus-sdk[auth]'"
            )
        self._algorithm = algorithm
        self._secret_key = secret_key
        self._public_key = public_key
        self._issuer = issuer
        self._key = public_key if algorithm.startswith('RS') else secret_key

    async def verify_token(self, token: str) -> Optional[AuthUser]:
        try:
            options = {}
            if self._issuer:
                options['issuer'] = self._issuer
            payload = jwt.decode(token, self._key, algorithms=[self._algorithm], options=options)
            return AuthUser(
                user_id=payload.get('sub', ''),
                org_id=payload.get('org_id'),
                roles=payload.get('roles', []),
                scopes=payload.get('scope', '').split() if payload.get('scope') else [],
            )
        except Exception as e:
            logger.warning('JWT verification failed: %s', e)
            return None

    async def get_anonymous_user(self, request: object) -> Optional[AuthUser]:
        return None

    async def close(self) -> None:
        return None
