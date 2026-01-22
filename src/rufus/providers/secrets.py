from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

class SecretsProvider(ABC):
    """Abstracts the retrieval and caching of secrets."""

    @abstractmethod
    async def get_secret(self, key: str) -> str:
        """Retrieves a secret by its key."""
        pass

    @abstractmethod
    async def initialize(self):
        """Initializes the secrets provider (e.g., connects to a secrets manager)."""
        pass

    @abstractmethod
    async def close(self):
        """Closes any open connections or resources."""
        pass
