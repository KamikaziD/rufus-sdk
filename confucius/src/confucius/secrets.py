import os
from typing import Optional, Protocol, Dict
from dotenv import load_dotenv

# Ensure env vars are loaded
load_dotenv()

class SecretsProvider(Protocol):
    """Protocol for fetching secrets."""
    def get_secret(self, key: str) -> Optional[str]:
        ...

class EnvSecretsProvider:
    """Fetches secrets from environment variables."""
    def get_secret(self, key: str) -> Optional[str]:
        return os.getenv(key)

class MockVaultSecretsProvider:
    """Mock provider for HashiCorp Vault/AWS Secrets Manager (Future placeholder)."""
    def __init__(self, secrets: Dict[str, str] = None):
        self.secrets = secrets or {}

    def get_secret(self, key: str) -> Optional[str]:
        return self.secrets.get(key)

_provider_instance: Optional[SecretsProvider] = None

def get_secrets_provider() -> SecretsProvider:
    """Factory to get the configured secrets provider."""
    global _provider_instance
    if _provider_instance is None:
        # Future: Check config to decide which provider to use
        # provider_type = os.getenv("SECRETS_PROVIDER", "env")
        _provider_instance = EnvSecretsProvider()
    return _provider_instance
