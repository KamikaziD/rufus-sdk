"""
APIKeyProvider — static API key authentication.

Keys are sent as:
  Authorization: Bearer <key>
  X-API-Key: <key>   (checked by get_anonymous_user if no Bearer header)

Configure via env var:
  RUVON_API_KEYS=key1:user1:role1,role2;key2:user2:admin

Format per entry:  <api-key>:<user_id>[:<comma-separated-roles>]
Entries are separated by semicolons.
"""
import os
import logging
from typing import Optional, Dict
from ruvon_server.auth.provider import AuthUser

logger = logging.getLogger(__name__)


def _parse_api_keys(raw: str) -> Dict[str, AuthUser]:
    result = {}
    for entry in raw.split(';'):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(':')
        if len(parts) < 2:
            logger.warning('Invalid RUVON_API_KEYS entry (expected key:user[:roles]): %s', entry)
            continue
        key, user_id = parts[0].strip(), parts[1].strip()
        roles = [r.strip() for r in parts[2].split(',')] if len(parts) > 2 else []
        result[key] = AuthUser(user_id=user_id, roles=roles)
    return result


class APIKeyProvider:
    def __init__(self, api_keys_env: str = ''):
        raw = api_keys_env or os.getenv('RUVON_API_KEYS', '')
        self._keys: Dict[str, AuthUser] = _parse_api_keys(raw) if raw else {}

    async def verify_token(self, token: str) -> Optional[AuthUser]:
        return self._keys.get(token)

    async def get_anonymous_user(self, request: object) -> Optional[AuthUser]:
        headers = getattr(request, 'headers', {})
        api_key = headers.get('X-API-Key') or headers.get('x-api-key')
        if api_key:
            return self._keys.get(api_key)
        return None

    async def close(self) -> None:
        return None
