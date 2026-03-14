"""SQLite implementation compliance test."""

import pytest
import pytest_asyncio

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from tests.providers.base_persistence_compliance import BasePersistenceCompliance


class TestSQLiteCompliance(BasePersistenceCompliance):
    @pytest_asyncio.fixture
    async def provider(self, tmp_path):
        p = SQLitePersistenceProvider(db_path=str(tmp_path / "compliance_test.db"))
        await p.initialize()
        yield p
        await p.close()
