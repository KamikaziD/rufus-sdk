import os
import time
from typing import Dict, Any, Optional, Tuple
from ruvon.providers.secrets import SecretsProvider
from dotenv import load_dotenv

# Ensure env vars are loaded (useful for local development/testing)
load_dotenv()

class EnvironmentSecretsProvider(SecretsProvider):
    """
    An implementation of SecretsProvider that retrieves secrets from environment variables
    and includes basic in-memory caching.
    """
    def __init__(self, ttl: int = 300): # Default TTL of 5 minutes
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._ttl = ttl
        self._initialized = False

    async def initialize(self):
        """Initializes the provider (no-op for environment variables)."""
        self._initialized = True
        # print("EnvironmentSecretsProvider initialized.")
        pass

    async def close(self):
        """Closes any resources (no-op for environment variables)."""
        self._initialized = False
        self._cache.clear()
        # print("EnvironmentSecretsProvider closed.")
        pass

    async def get_secret(self, key: str) -> str:
        """Retrieves a secret by its key, using cache if available."""
        if not self._initialized:
            await self.initialize()

        # Check cache first
        if key in self._cache:
            value, expires_at = self._cache[key]
            if time.time() < expires_at:
                # print(f"Retrieving secret '{key}' from cache.")
                return value
            else:
                # print(f"Cache for secret '{key}' expired.")
                del self._cache[key] # Expired, remove from cache

        # Fetch from environment variable
        secret_value = os.getenv(key)
        if secret_value is None:
            raise ValueError(f"Secret '{key}' not found in environment variables.")

        # Cache the secret
        self._cache[key] = (secret_value, time.time() + self._ttl)
        # print(f"Fetched secret '{key}' from environment variables and cached.")
        return secret_value

# Global instance (can be replaced/configured by DI framework)
_secrets_provider_instance: Optional[EnvironmentSecretsProvider] = None

def get_environment_secrets_provider(ttl: int = 300) -> EnvironmentSecretsProvider:
    global _secrets_provider_instance
    if _secrets_provider_instance is None:
        _secrets_provider_instance = EnvironmentSecretsProvider(ttl)
    return _secrets_provider_instance
