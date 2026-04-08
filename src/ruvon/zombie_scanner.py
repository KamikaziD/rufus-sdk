"""
Zombie Workflow Scanner for detecting and recovering crashed workflows.

The ZombieScanner finds workflows with stale heartbeats (workers that have
crashed) and marks them as FAILED_WORKER_CRASH. This is part of the Tier 2
architecture enhancement for production reliability.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol, List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ZombieScannerPersistence(Protocol):
    """Protocol for persistence providers supporting zombie scanning."""

    async def get_stale_heartbeats(
        self,
        stale_threshold_seconds: int = 120
    ) -> List[Dict[str, Any]]:
        """Find workflows with stale heartbeats."""
        ...

    async def mark_workflow_as_crashed(
        self,
        workflow_id: uuid.UUID,
        reason: str
    ) -> None:
        """Mark a workflow as failed due to worker crash."""
        ...

    async def delete_heartbeat(self, workflow_id: uuid.UUID) -> None:
        """Delete heartbeat record."""
        ...


class ZombieScanner:
    """
    Scans for zombie workflows and marks them as crashed.

    A zombie workflow is one where the worker crashed while processing a step,
    leaving the workflow in RUNNING state with a stale heartbeat.

    Usage:
        # Create scanner
        scanner = ZombieScanner(persistence)

        # Scan once
        zombies = await scanner.scan(stale_threshold_seconds=120)

        # Recover zombies (mark as FAILED_WORKER_CRASH)
        recovered = await scanner.recover(zombies)

        # Or scan and recover in one step
        recovered = await scanner.scan_and_recover()

        # Run continuously as background daemon
        await scanner.run_daemon(scan_interval_seconds=60)
    """

    def __init__(
        self,
        persistence: ZombieScannerPersistence,
        stale_threshold_seconds: int = 120
    ):
        """
        Initialize ZombieScanner.

        Args:
            persistence: Persistence provider with zombie scanning support
            stale_threshold_seconds: Heartbeats older than this are considered stale
        """
        self.persistence = persistence
        self.stale_threshold = stale_threshold_seconds
        self._running = False
        self._daemon_task: Optional[asyncio.Task] = None

    async def scan(
        self,
        stale_threshold_seconds: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan for zombie workflows.

        Args:
            stale_threshold_seconds: Override default stale threshold

        Returns:
            List of zombie workflow records
        """
        threshold = stale_threshold_seconds or self.stale_threshold

        try:
            zombies = await self.persistence.get_stale_heartbeats(threshold)

            if zombies:
                logger.warning(
                    f"Found {len(zombies)} zombie workflows with stale heartbeats "
                    f"(older than {threshold}s)"
                )
            else:
                logger.debug("No zombie workflows found")

            return zombies

        except Exception as e:
            logger.error(f"Error scanning for zombie workflows: {e}")
            return []

    async def recover(
        self,
        zombies: List[Dict[str, Any]],
        dry_run: bool = False
    ) -> int:
        """
        Recover zombie workflows by marking them as FAILED_WORKER_CRASH.

        Args:
            zombies: List of zombie workflow records from scan()
            dry_run: If True, only log what would be done without making changes

        Returns:
            Number of workflows recovered
        """
        recovered_count = 0

        for zombie in zombies:
            workflow_id = zombie.get('workflow_id')
            worker_id = zombie.get('worker_id')
            current_step = zombie.get('current_step')
            last_heartbeat = zombie.get('last_heartbeat')

            if not workflow_id:
                logger.warning(f"Skipping zombie record with no workflow_id: {zombie}")
                continue

            # Convert workflow_id to UUID if it's a string
            if isinstance(workflow_id, str):
                try:
                    workflow_id = uuid.UUID(workflow_id)
                except ValueError:
                    logger.error(f"Invalid workflow_id format: {workflow_id}")
                    continue

            reason = (
                f"Worker crash detected. Worker {worker_id} stopped sending "
                f"heartbeats while processing step '{current_step}'. "
                f"Last heartbeat: {last_heartbeat}"
            )

            if dry_run:
                logger.info(
                    f"[DRY RUN] Would mark workflow {workflow_id} as "
                    f"FAILED_WORKER_CRASH: {reason}"
                )
                recovered_count += 1
            else:
                try:
                    # Mark workflow as crashed
                    await self.persistence.mark_workflow_as_crashed(
                        workflow_id,
                        reason
                    )

                    # Clean up the stale heartbeat
                    await self.persistence.delete_heartbeat(workflow_id)

                    logger.info(
                        f"Marked workflow {workflow_id} as FAILED_WORKER_CRASH. "
                        f"Worker: {worker_id}, Step: {current_step}"
                    )

                    recovered_count += 1

                except Exception as e:
                    logger.error(
                        f"Failed to recover workflow {workflow_id}: {e}"
                    )

        return recovered_count

    async def scan_and_recover(
        self,
        stale_threshold_seconds: Optional[int] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Scan for zombies and recover them in one operation.

        Args:
            stale_threshold_seconds: Override default stale threshold
            dry_run: If True, only report what would be done

        Returns:
            Summary dictionary with scan results
        """
        start_time = datetime.now(timezone.utc)

        # Scan for zombies
        zombies = await self.scan(stale_threshold_seconds)

        # Recover zombies
        recovered_count = await self.recover(zombies, dry_run=dry_run)

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        summary = {
            "scan_time": start_time.isoformat(),
            "duration_seconds": duration,
            "zombies_found": len(zombies),
            "zombies_recovered": recovered_count,
            "dry_run": dry_run,
            "stale_threshold_seconds": stale_threshold_seconds or self.stale_threshold
        }

        logger.info(
            f"Zombie scan complete: {len(zombies)} found, {recovered_count} recovered "
            f"in {duration:.2f}s"
        )

        return summary

    async def run_daemon(
        self,
        scan_interval_seconds: int = 60,
        stale_threshold_seconds: Optional[int] = None
    ) -> None:
        """
        Run zombie scanner as continuous background daemon.

        Args:
            scan_interval_seconds: How often to scan for zombies
            stale_threshold_seconds: Override default stale threshold
        """
        if self._running:
            logger.warning("Zombie scanner daemon already running")
            return

        self._running = True
        logger.info(
            f"Starting zombie scanner daemon: scan every {scan_interval_seconds}s, "
            f"threshold {stale_threshold_seconds or self.stale_threshold}s"
        )

        while self._running:
            try:
                await self.scan_and_recover(
                    stale_threshold_seconds=stale_threshold_seconds,
                    dry_run=False
                )
            except Exception as e:
                logger.error(f"Error in zombie scanner daemon: {e}")

            # Wait for next scan
            try:
                await asyncio.sleep(scan_interval_seconds)
            except asyncio.CancelledError:
                break

        logger.info("Zombie scanner daemon stopped")

    def stop_daemon(self) -> None:
        """Stop the background daemon if running."""
        if self._running:
            self._running = False
            logger.info("Stopping zombie scanner daemon...")

    async def __aenter__(self):
        """Context manager support - does not auto-start daemon."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.stop_daemon()
        if self._daemon_task:
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        return False
