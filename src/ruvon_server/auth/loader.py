"""
Auth provider factory.

Reads RUVON_AUTH_PROVIDER env var and instantiates the correct provider.
Called from main.py startup_event().
"""
import os
import logging
import importlib
from ruvon_server.auth.dependencies import set_provider

logger = logging.getLogger(__name__)


async def load_auth_provider() -> object:
    """Instantiate and return the configured auth provider."""
    provider_name = os.getenv('RUVON_AUTH_PROVIDER', 'disabled').lower().strip()

    if provider_name == 'disabled':
        from ruvon_server.auth.providers.disabled import DisabledProvider
        return DisabledProvider()

    elif provider_name == 'keycloak':
        from ruvon_server.auth.providers.keycloak import KeycloakProvider
        server_url = os.getenv('KEYCLOAK_SERVER_URL')
        realm = os.getenv('KEYCLOAK_REALM')
        client_id = os.getenv('KEYCLOAK_CLIENT_ID')
        audience = os.getenv('KEYCLOAK_AUDIENCE')
        if not (server_url and realm and client_id):
            raise ValueError(
                'KEYCLOAK_SERVER_URL, KEYCLOAK_REALM, and KEYCLOAK_CLIENT_ID must be set '
                'when RUVON_AUTH_PROVIDER=keycloak'
            )
        return KeycloakProvider(
            server_url=server_url,
            realm=realm,
            client_id=client_id,
            audience=audience,
        )

    elif provider_name == 'jwt':
        from ruvon_server.auth.providers.jwt import JWTProvider
        return JWTProvider(
            algorithm=os.getenv('JWT_ALGORITHM', 'HS256'),
            secret_key=os.getenv('JWT_SECRET_KEY'),
            public_key=os.getenv('JWT_PUBLIC_KEY'),
            issuer=os.getenv('JWT_ISSUER'),
        )

    elif provider_name == 'api_key':
        from ruvon_server.auth.providers.api_key import APIKeyProvider
        return APIKeyProvider()

    elif provider_name == 'custom':
        custom_path = os.getenv('RUVON_CUSTOM_AUTH_PROVIDER', '').strip()
        if not custom_path:
            raise ValueError(
                'RUVON_CUSTOM_AUTH_PROVIDER must be set when RUVON_AUTH_PROVIDER=custom. '
                'Example: RUVON_CUSTOM_AUTH_PROVIDER=my_app.auth.MyProvider'
            )
        module_path, _, class_name = custom_path.rpartition('.')
        module = importlib.import_module(module_path)
        provider_cls = getattr(module, class_name)
        logger.info('Loaded custom auth provider: %s', custom_path)
        return provider_cls()

    else:
        logger.warning("Unknown RUVON_AUTH_PROVIDER='%s', falling back to disabled.", provider_name)
        from ruvon_server.auth.providers.disabled import DisabledProvider
        return DisabledProvider()


_active_provider: object = None


def set_auth_provider(provider: object) -> None:
    global _active_provider
    _active_provider = provider
    set_provider(provider)


def get_auth_provider() -> object:
    return _active_provider
