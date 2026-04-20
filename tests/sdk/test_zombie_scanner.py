"""
Tests for ZombieScanner - Detecting and Recovering Crashed Workflows

Tests cover:
- Scanning for stale heartbeats
- Marking workflows as FAILED_WORKER_CRASH
- Dry-run mode
- Continuous daemon mode
- Recovery statistics
- Error handling
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from unittest.mock import Mock, AsyncMock, patch

from ruvon.zombie_scanner import ZombieScanner, ZombieScannerPersistence


class MockZombiePersistence:
    """Mock persistence provider for testing zombie scanner."""

    def __init__(self):
        self.stale_heartbeats: List[Dict[str, Any]] = []
        self.crashed_workflows: List[uuid.UUID] = []
        self.deleted_heartbeats: List[uuid.UUID] = []
        self.scan_count = 0
        self.mark_count = 0

    async def get_stale_heartbeats(
        self,
        stale_threshold_seconds: int = 120
    ) -> List[Dict[str, Any]]:
        """Mock get stale heartbeats."""
        self.scan_count += 1
        # Filter by threshold
        stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)
        return [
            hb for hb in self.stale_heartbeats
            if datetime.fromisoformat(hb['last_heartbeat']) < stale_cutoff
        ]

    async def mark_workflow_as_crashed(
        self,
        workflow_id: uuid.UUID,
        reason: str
    ) -> None:
        """Mock mark workflow as crashed."""
        self.mark_count += 1
        self.crashed_workflows.append(workflow_id)

    async def delete_heartbeat(self, workflow_id: uuid.UUID) -> None:
        """Mock delete heartbeat."""
        self.deleted_heartbeats.append(workflow_id)

    def add_stale_heartbeat(
        self,
        workflow_id: uuid.UUID,
        worker_id: str,
        current_step: str,
        minutes_stale: int = 5
    ):
        """Helper to add a stale heartbeat."""
        last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=minutes_stale)
        self.stale_heartbeats.append({
            'workflow_id': str(workflow_id),
            'worker_id': worker_id,
            'last_heartbeat': last_heartbeat.isoformat(),
            'current_step': current_step,
            'step_started_at': last_heartbeat.isoformat(),
            'metadata': {},
            'workflow_type': 'TestWorkflow',
            'status': 'RUNNING',
            'workflow_current_step': 1
        })


@pytest.fixture
def mock_persistence():
    """Fixture providing mock persistence."""
    return MockZombiePersistence()


@pytest.mark.asyncio
async def test_zombie_scanner_initialization(mock_persistence):
    """Test ZombieScanner initialization."""
    scanner = ZombieScanner(
        persistence=mock_persistence,
        stale_threshold_seconds=120
    )

    assert scanner.persistence == mock_persistence
    assert scanner.stale_threshold == 120
    assert scanner._running is False


@pytest.mark.asyncio
async def test_zombie_scanner_no_zombies(mock_persistence):
    """Test scanning when no zombies exist."""
    scanner = ZombieScanner(mock_persistence)

    zombies = await scanner.scan()

    assert len(zombies) == 0
    assert mock_persistence.scan_count == 1


@pytest.mark.asyncio
async def test_zombie_scanner_find_single_zombie(mock_persistence):
    """Test finding a single zombie workflow."""
    workflow_id = uuid.uuid4()
    mock_persistence.add_stale_heartbeat(
        workflow_id=workflow_id,
        worker_id="crashed-worker-123",
        current_step="Process_Payment",
        minutes_stale=5
    )

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    assert len(zombies) == 1
    assert zombies[0]['workflow_id'] == str(workflow_id)
    assert zombies[0]['worker_id'] == "crashed-worker-123"
    assert zombies[0]['current_step'] == "Process_Payment"


@pytest.mark.asyncio
async def test_zombie_scanner_find_multiple_zombies(mock_persistence):
    """Test finding multiple zombie workflows."""
    workflow_ids = [uuid.uuid4() for _ in range(5)]

    for i, wf_id in enumerate(workflow_ids):
        mock_persistence.add_stale_heartbeat(
            workflow_id=wf_id,
            worker_id=f"worker-{i}",
            current_step=f"Step_{i}",
            minutes_stale=10
        )

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    assert len(zombies) == 5


@pytest.mark.asyncio
async def test_zombie_scanner_stale_threshold(mock_persistence):
    """Test stale threshold filtering."""
    # Add one very stale heartbeat (10 minutes)
    old_workflow = uuid.uuid4()
    mock_persistence.add_stale_heartbeat(
        workflow_id=old_workflow,
        worker_id="worker-1",
        current_step="Step_1",
        minutes_stale=10
    )

    # Scan with threshold of 5 minutes - should find it
    scanner = ZombieScanner(mock_persistence, stale_threshold_seconds=300)
    zombies = await scanner.scan()

    assert len(zombies) == 1

    # Clear and add fresh heartbeat (1 minute)
    mock_persistence.stale_heartbeats.clear()
    mock_persistence.add_stale_heartbeat(
        workflow_id=uuid.uuid4(),
        worker_id="worker-2",
        current_step="Step_2",
        minutes_stale=1
    )

    # Scan with same threshold - should not find it
    zombies = await scanner.scan()
    assert len(zombies) == 0


@pytest.mark.asyncio
async def test_zombie_scanner_recover_dry_run(mock_persistence):
    """Test recovery in dry-run mode (no actual changes)."""
    workflow_id = uuid.uuid4()
    mock_persistence.add_stale_heartbeat(
        workflow_id=workflow_id,
        worker_id="crashed-worker",
        current_step="Payment",
        minutes_stale=5
    )

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    # Recover in dry-run mode
    recovered = await scanner.recover(zombies, dry_run=True)

    assert recovered == 1
    assert mock_persistence.mark_count == 0  # Should NOT have marked
    assert len(mock_persistence.crashed_workflows) == 0


@pytest.mark.asyncio
async def test_zombie_scanner_recover_actual(mock_persistence):
    """Test actual recovery (marking as crashed)."""
    workflow_id = uuid.uuid4()
    mock_persistence.add_stale_heartbeat(
        workflow_id=workflow_id,
        worker_id="crashed-worker",
        current_step="Payment",
        minutes_stale=5
    )

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    # Actual recovery
    recovered = await scanner.recover(zombies, dry_run=False)

    assert recovered == 1
    assert mock_persistence.mark_count == 1
    assert workflow_id in mock_persistence.crashed_workflows
    assert workflow_id in mock_persistence.deleted_heartbeats


@pytest.mark.asyncio
async def test_zombie_scanner_scan_and_recover(mock_persistence):
    """Test combined scan and recover operation."""
    workflow_ids = [uuid.uuid4() for _ in range(3)]

    for i, wf_id in enumerate(workflow_ids):
        mock_persistence.add_stale_heartbeat(
            workflow_id=wf_id,
            worker_id=f"worker-{i}",
            current_step=f"Step_{i}",
            minutes_stale=5
        )

    scanner = ZombieScanner(mock_persistence, stale_threshold_seconds=120)
    summary = await scanner.scan_and_recover(dry_run=False)

    assert summary['zombies_found'] == 3
    assert summary['zombies_recovered'] == 3
    assert summary['dry_run'] is False
    assert summary['stale_threshold_seconds'] == 120
    assert 'scan_time' in summary
    assert 'duration_seconds' in summary


@pytest.mark.asyncio
async def test_zombie_scanner_invalid_workflow_id(mock_persistence):
    """Test handling of invalid workflow ID format."""
    # Add zombie with invalid UUID
    mock_persistence.stale_heartbeats.append({
        'workflow_id': 'not-a-valid-uuid',
        'worker_id': 'worker-1',
        'current_step': 'Step_1',
        'last_heartbeat': datetime.now(timezone.utc).isoformat(),
        'metadata': {}
    })

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    # Should handle gracefully
    recovered = await scanner.recover(zombies, dry_run=False)

    assert recovered == 0  # Should skip invalid UUID


@pytest.mark.asyncio
async def test_zombie_scanner_missing_workflow_id(mock_persistence):
    """Test handling of zombie record with missing workflow_id."""
    # Add zombie with no workflow_id
    mock_persistence.stale_heartbeats.append({
        'worker_id': 'worker-1',
        'current_step': 'Step_1',
        'last_heartbeat': datetime.now(timezone.utc).isoformat()
    })

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    # Should handle gracefully
    recovered = await scanner.recover(zombies, dry_run=False)

    assert recovered == 0  # Should skip record with no workflow_id


@pytest.mark.asyncio
async def test_zombie_scanner_recovery_failure_handling(mock_persistence):
    """Test handling of recovery failures."""
    workflow_id = uuid.uuid4()
    mock_persistence.add_stale_heartbeat(
        workflow_id=workflow_id,
        worker_id="worker-1",
        current_step="Step_1",
        minutes_stale=5
    )

    # Make mark_workflow_as_crashed fail
    async def failing_mark(*args, **kwargs):
        raise Exception("Database error")

    original_mark = mock_persistence.mark_workflow_as_crashed
    mock_persistence.mark_workflow_as_crashed = failing_mark

    scanner = ZombieScanner(mock_persistence)
    zombies = await scanner.scan()

    # Should handle failure gracefully
    recovered = await scanner.recover(zombies, dry_run=False)

    assert recovered == 0  # Should not count as recovered

    # Restore original
    mock_persistence.mark_workflow_as_crashed = original_mark


@pytest.mark.asyncio
async def test_zombie_scanner_daemon_mode_start_stop():
    """Test starting and stopping daemon mode."""
    mock_persistence = MockZombiePersistence()
    scanner = ZombieScanner(mock_persistence)

    # Start daemon in background
    daemon_task = asyncio.create_task(
        scanner.run_daemon(scan_interval_seconds=0.1, stale_threshold_seconds=60)
    )

    # Let it run for a bit
    await asyncio.sleep(0.35)

    # Should have scanned multiple times
    assert mock_persistence.scan_count >= 3

    # Stop daemon
    scanner.stop_daemon()

    # Wait for task to finish
    try:
        await asyncio.wait_for(daemon_task, timeout=1.0)
    except asyncio.TimeoutError:
        daemon_task.cancel()


@pytest.mark.asyncio
async def test_zombie_scanner_daemon_error_handling():
    """Test daemon continues running after errors."""

    class FailingPersistence:
        def __init__(self):
            self.scan_attempts = 0

        async def get_stale_heartbeats(self, *args, **kwargs):
            self.scan_attempts += 1
            if self.scan_attempts < 3:
                raise Exception("Temporary failure")
            return []

        async def mark_workflow_as_crashed(self, *args, **kwargs):
            pass

        async def delete_heartbeat(self, *args, **kwargs):
            pass

    persistence = FailingPersistence()
    scanner = ZombieScanner(persistence)

    # Start daemon
    daemon_task = asyncio.create_task(
        scanner.run_daemon(scan_interval_seconds=0.1)
    )

    # Wait for multiple scan attempts
    await asyncio.sleep(0.35)

    # Should have attempted multiple scans despite errors
    assert persistence.scan_attempts >= 3

    # Stop daemon
    scanner.stop_daemon()

    try:
        await asyncio.wait_for(daemon_task, timeout=1.0)
    except asyncio.TimeoutError:
        daemon_task.cancel()


@pytest.mark.asyncio
async def test_zombie_scanner_context_manager(mock_persistence):
    """Test using ZombieScanner as context manager."""
    async with ZombieScanner(mock_persistence) as scanner:
        zombies = await scanner.scan()
        assert len(zombies) == 0

    # Should clean up properly (stop daemon if running)
    assert scanner._running is False


@pytest.mark.asyncio
async def test_zombie_scanner_summary_structure(mock_persistence):
    """Test scan summary contains expected fields."""
    scanner = ZombieScanner(mock_persistence)
    summary = await scanner.scan_and_recover()

    # Check all expected fields
    assert 'scan_time' in summary
    assert 'duration_seconds' in summary
    assert 'zombies_found' in summary
    assert 'zombies_recovered' in summary
    assert 'dry_run' in summary
    assert 'stale_threshold_seconds' in summary

    # Check types
    assert isinstance(summary['scan_time'], str)
    assert isinstance(summary['duration_seconds'], (int, float))
    assert isinstance(summary['zombies_found'], int)
    assert isinstance(summary['zombies_recovered'], int)
    assert isinstance(summary['dry_run'], bool)
    assert isinstance(summary['stale_threshold_seconds'], int)


@pytest.mark.asyncio
async def test_zombie_scanner_batch_recovery(mock_persistence):
    """Test recovering large batch of zombies."""
    # Create 100 zombie workflows
    workflow_ids = [uuid.uuid4() for _ in range(100)]

    for i, wf_id in enumerate(workflow_ids):
        mock_persistence.add_stale_heartbeat(
            workflow_id=wf_id,
            worker_id=f"worker-{i % 10}",  # 10 different workers
            current_step=f"Step_{i % 5}",   # 5 different steps
            minutes_stale=5
        )

    scanner = ZombieScanner(mock_persistence)
    summary = await scanner.scan_and_recover(dry_run=False)

    assert summary['zombies_found'] == 100
    assert summary['zombies_recovered'] == 100
    assert len(mock_persistence.crashed_workflows) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
