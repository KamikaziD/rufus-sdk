"""
Tests for HeartbeatManager - Zombie Workflow Detection & Recovery

Tests cover:
- Heartbeat creation and updates
- Automatic heartbeat sending
- Heartbeat cleanup on completion
- Context manager usage
- Worker crash simulation
- Stale heartbeat detection
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, AsyncMock, patch

from rufus.heartbeat import HeartbeatManager, HeartbeatPersistence


class MockHeartbeatPersistence:
    """Mock persistence provider for testing heartbeats."""

    def __init__(self):
        self.heartbeats: Dict[str, Dict[str, Any]] = {}
        self.upsert_count = 0
        self.delete_count = 0

    async def upsert_heartbeat(
        self,
        workflow_id: uuid.UUID,
        worker_id: str,
        current_step: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Mock upsert heartbeat."""
        self.upsert_count += 1
        self.heartbeats[str(workflow_id)] = {
            'workflow_id': str(workflow_id),
            'worker_id': worker_id,
            'last_heartbeat': datetime.now(timezone.utc),
            'current_step': current_step,
            'metadata': metadata or {}
        }

    async def delete_heartbeat(self, workflow_id: uuid.UUID) -> None:
        """Mock delete heartbeat."""
        self.delete_count += 1
        if str(workflow_id) in self.heartbeats:
            del self.heartbeats[str(workflow_id)]

    async def get_stale_heartbeats(
        self,
        stale_threshold_seconds: int = 120
    ) -> List[Dict[str, Any]]:
        """Mock get stale heartbeats."""
        return []


@pytest.fixture
def mock_persistence():
    """Fixture providing mock persistence."""
    return MockHeartbeatPersistence()


@pytest.fixture
def workflow_id():
    """Fixture providing a workflow ID."""
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_heartbeat_manager_initialization(mock_persistence, workflow_id):
    """Test HeartbeatManager initialization."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        worker_id="test-worker-123",
        heartbeat_interval_seconds=30
    )

    assert manager.workflow_id == workflow_id
    assert manager.worker_id == "test-worker-123"
    assert manager.heartbeat_interval == 30
    assert manager._running is False


@pytest.mark.asyncio
async def test_heartbeat_manager_auto_worker_id(mock_persistence, workflow_id):
    """Test automatic worker ID generation."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id
    )

    assert manager.worker_id is not None
    assert len(manager.worker_id) > 0
    # Should contain hostname-pid-random pattern
    parts = manager.worker_id.split('-')
    assert len(parts) >= 3


@pytest.mark.asyncio
async def test_heartbeat_start_and_stop(mock_persistence, workflow_id):
    """Test starting and stopping heartbeats."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        heartbeat_interval_seconds=1  # Fast interval for testing
    )

    # Start heartbeat
    await manager.start(current_step="Test_Step", metadata={"test": "value"})

    assert manager._running is True
    assert manager._current_step == "Test_Step"
    assert manager._metadata["test"] == "value"

    # Wait for at least one heartbeat
    await asyncio.sleep(0.1)

    # Should have sent at least one heartbeat
    assert mock_persistence.upsert_count >= 1
    assert str(workflow_id) in mock_persistence.heartbeats

    # Stop heartbeat
    await manager.stop()

    assert manager._running is False
    assert mock_persistence.delete_count == 1
    assert str(workflow_id) not in mock_persistence.heartbeats


@pytest.mark.asyncio
async def test_heartbeat_periodic_sending(mock_persistence, workflow_id):
    """Test that heartbeats are sent periodically."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        heartbeat_interval_seconds=0.1  # Very fast for testing
    )

    await manager.start(current_step="Test_Step")

    # Wait for multiple heartbeat intervals
    await asyncio.sleep(0.35)

    # Should have sent multiple heartbeats
    assert mock_persistence.upsert_count >= 3

    await manager.stop()


@pytest.mark.asyncio
async def test_heartbeat_context_manager(mock_persistence, workflow_id):
    """Test using HeartbeatManager as context manager."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        heartbeat_interval_seconds=0.1
    )

    async with manager:
        # Should have started
        assert manager._running is True

        # Wait for a heartbeat
        await asyncio.sleep(0.15)

        assert mock_persistence.upsert_count >= 1

    # Should have stopped and cleaned up
    assert manager._running is False
    assert mock_persistence.delete_count == 1


@pytest.mark.asyncio
async def test_heartbeat_double_start_warning(mock_persistence, workflow_id, caplog):
    """Test warning when starting already-running heartbeat."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id
    )

    await manager.start()

    # Try to start again - should warn but not crash
    await manager.start()

    await manager.stop()


@pytest.mark.asyncio
async def test_heartbeat_metadata_includes_system_info(mock_persistence, workflow_id):
    """Test that heartbeat metadata includes system information."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id
    )

    custom_metadata = {"custom_key": "custom_value"}
    await manager.start(current_step="Test_Step", metadata=custom_metadata)

    await asyncio.sleep(0.1)

    # Check metadata includes both custom and system info
    heartbeat = mock_persistence.heartbeats[str(workflow_id)]
    metadata = heartbeat['metadata']

    assert metadata['custom_key'] == "custom_value"
    assert 'hostname' in metadata
    assert 'pid' in metadata
    assert 'started_at' in metadata

    await manager.stop()


@pytest.mark.asyncio
async def test_heartbeat_stop_without_start(mock_persistence, workflow_id):
    """Test stopping heartbeat that was never started."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id
    )

    # Should not crash
    await manager.stop()

    assert mock_persistence.delete_count == 0


@pytest.mark.asyncio
async def test_heartbeat_persistence_failure_handling(workflow_id):
    """Test graceful handling of persistence failures."""

    class FailingPersistence:
        async def upsert_heartbeat(self, *args, **kwargs):
            raise Exception("Database connection failed")

        async def delete_heartbeat(self, *args, **kwargs):
            pass

    manager = HeartbeatManager(
        persistence=FailingPersistence(),
        workflow_id=workflow_id,
        heartbeat_interval_seconds=0.1
    )

    # Should not crash even if persistence fails
    await manager.start(current_step="Test_Step")
    await asyncio.sleep(0.25)  # Wait for heartbeat attempts
    await manager.stop()


@pytest.mark.asyncio
async def test_heartbeat_worker_crash_simulation(mock_persistence, workflow_id):
    """Test simulating worker crash (heartbeat not cleaned up)."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        heartbeat_interval_seconds=0.1
    )

    await manager.start(current_step="Processing_Payment")
    await asyncio.sleep(0.15)

    # Simulate crash - stop without cleanup
    manager._running = False
    if manager._task:
        manager._task.cancel()
        try:
            await manager._task
        except asyncio.CancelledError:
            pass

    # Heartbeat should still exist (not cleaned up)
    assert str(workflow_id) in mock_persistence.heartbeats
    assert mock_persistence.delete_count == 0

    # This is what ZombieScanner would detect
    heartbeat = mock_persistence.heartbeats[str(workflow_id)]
    assert heartbeat['current_step'] == "Processing_Payment"


@pytest.mark.asyncio
async def test_heartbeat_concurrent_workflows(mock_persistence):
    """Test managing heartbeats for multiple workflows concurrently."""
    workflow_ids = [uuid.uuid4() for _ in range(5)]
    managers = [
        HeartbeatManager(
            persistence=mock_persistence,
            workflow_id=wf_id,
            heartbeat_interval_seconds=0.1
        )
        for wf_id in workflow_ids
    ]

    # Start all heartbeats
    await asyncio.gather(*[
        mgr.start(current_step=f"Step_{i}")
        for i, mgr in enumerate(managers)
    ])

    await asyncio.sleep(0.2)

    # All workflows should have heartbeats
    assert len(mock_persistence.heartbeats) == 5

    # Stop all heartbeats
    await asyncio.gather(*[mgr.stop() for mgr in managers])

    # All heartbeats should be cleaned up
    assert len(mock_persistence.heartbeats) == 0
    assert mock_persistence.delete_count == 5


@pytest.mark.asyncio
async def test_heartbeat_with_step_transitions(mock_persistence, workflow_id):
    """Test heartbeat behavior across step transitions."""
    manager = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        heartbeat_interval_seconds=0.1
    )

    # Step 1
    await manager.start(current_step="Step_1")
    await asyncio.sleep(0.15)
    await manager.stop()

    initial_upserts = mock_persistence.upsert_count

    # Step 2 (new heartbeat manager as would happen in real workflow)
    manager2 = HeartbeatManager(
        persistence=mock_persistence,
        workflow_id=workflow_id,
        heartbeat_interval_seconds=0.1
    )
    await manager2.start(current_step="Step_2")
    await asyncio.sleep(0.15)
    await manager2.stop()

    # Should have sent heartbeats for both steps
    assert mock_persistence.upsert_count > initial_upserts
    assert mock_persistence.delete_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
