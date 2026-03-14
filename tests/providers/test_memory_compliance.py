"""In-memory persistence implementation compliance test."""

import pytest
import pytest_asyncio

from rufus.implementations.persistence.memory import InMemoryPersistence
from tests.providers.base_persistence_compliance import BasePersistenceCompliance


class TestMemoryCompliance(BasePersistenceCompliance):
    @pytest_asyncio.fixture
    async def provider(self):
        p = InMemoryPersistence()
        await p.initialize()
        yield p
        await p.close()
