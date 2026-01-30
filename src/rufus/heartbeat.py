"""
Heartbeat Manager for Zombie Workflow Detection & Recovery.

Provides worker-side heartbeat tracking to detect crashed workers and mark
zombie workflows. This is part of the Tier 2 architecture enhancement for
production reliability.
"""

import asyncio
import logging
import os
import platform
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Protocol

logger = logging.getLogger(__name__)


class HeartbeatPersistence(Protocol):
    """Protocol for persistence providers supporting heartbeat operations."""

    async def upsert_heartbeat(
        self,
        workflow_id: uuid.UUID,
        worker_id: str,
        current_step: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Upsert heartbeat record for a workflow.

        Args:
            workflow_id: ID of the workflow being processed
            worker_id: Identifier of the worker
            current_step: Name of the current step (optional)
            metadata: Additional context (PID, hostname, etc.)
        """
        ...

    async def delete_heartbeat(self, workflow_id: uuid.UUID) -> None:
        """
        Delete heartbeat record when workflow completes or step finishes.

        Args:
            workflow_id: ID of the workflow
        """
        ...

    async def get_stale_heartbeats(
        self,
        stale_threshold_seconds: int = 120
    ) -> list[Dict[str, Any]]:
        """
        Find workflows with stale heartbeats (potential zombies).

        Args:
            stale_threshold_seconds: Consider heartbeats older than this as stale

        Returns:
            List of stale heartbeat records with workflow details
        """
        ...


class HeartbeatManager:
    """
    Manages worker heartbeats to detect zombie workflows.

    The HeartbeatManager runs a background task that periodically sends
    heartbeats while a workflow step is executing. If a worker crashes,
    the heartbeat will become stale and can be detected by the ZombieScanner.

    Usage:
        # Start heartbeat when beginning step execution
        heartbeat = HeartbeatManager(persistence, workflow_id, worker_id)
        await heartbeat.start(current_step="Process_Payment")

        try:
            # Execute step function
            result = await execute_step(...)
        finally:
            # Stop heartbeat when done
            await heartbeat.stop()
    """

    def __init__(
        self,
        persistence: HeartbeatPersistence,
        workflow_id: uuid.UUID,
        worker_id: Optional[str] = None,
        heartbeat_interval_seconds: int = 30
    ):
        """
        Initialize HeartbeatManager.

        Args:
            persistence: Persistence provider with heartbeat support
            workflow_id: ID of the workflow being processed
            worker_id: Worker identifier (auto-generated if None)
            heartbeat_interval_seconds: How often to send heartbeats (default: 30s)
        """
        self.persistence = persistence
        self.workflow_id = workflow_id
        self.worker_id = worker_id or self._generate_worker_id()
        self.heartbeat_interval = heartbeat_interval_seconds

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._current_step: Optional[str] = None
        self._metadata: Dict[str, Any] = {}

    def _generate_worker_id(self) -> str:
        """Generate a unique worker identifier."""
        hostname = platform.node()
        pid = os.getpid()
        return f"{hostname}-{pid}-{uuid.uuid4().hex[:8]}"

    async def start(
        self,
        current_step: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Start sending heartbeats.

        Args:
            current_step: Name of the step being executed
            metadata: Additional context to include in heartbeats
        """
        if self._running:
            logger.warning(
                f"Heartbeat already running for workflow {self.workflow_id}"
            )
            return

        self._current_step = current_step
        self._metadata = metadata or {}
        self._metadata.update({
            "hostname": platform.node(),
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat()
        })

        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            f"Started heartbeat for workflow {self.workflow_id}, "
            f"worker {self.worker_id}, step {current_step}"
        )

    async def stop(self) -> None:
        """
        Stop sending heartbeats and clean up heartbeat record.

        This should be called when a step completes successfully or fails.
        """
        if not self._running:
            return

        self._running = False

        # Cancel the background task
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Delete the heartbeat record
        try:
            await self.persistence.delete_heartbeat(self.workflow_id)
            logger.info(
                f"Stopped heartbeat for workflow {self.workflow_id}, "
                f"worker {self.worker_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to delete heartbeat for workflow {self.workflow_id}: {e}"
            )

    async def _heartbeat_loop(self) -> None:
        """Background task that sends periodic heartbeats."""
        while self._running:
            try:
                await self._send_heartbeat()
            except Exception as e:
                logger.error(
                    f"Failed to send heartbeat for workflow {self.workflow_id}: {e}"
                )

            # Wait for next interval
            try:
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break

    async def _send_heartbeat(self) -> None:
        """Send a single heartbeat to the database."""
        try:
            await self.persistence.upsert_heartbeat(
                workflow_id=self.workflow_id,
                worker_id=self.worker_id,
                current_step=self._current_step,
                metadata=self._metadata
            )

            logger.debug(
                f"Heartbeat sent for workflow {self.workflow_id}, "
                f"step {self._current_step}"
            )
        except Exception as e:
            # Log but don't crash - heartbeat failure shouldn't stop execution
            logger.error(
                f"Failed to upsert heartbeat for workflow {self.workflow_id}: {e}"
            )

    async def __aenter__(self):
        """Context manager support for automatic cleanup."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        await self.stop()
        return False
