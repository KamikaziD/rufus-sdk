"""
Scheduler Daemon

Background process that executes scheduled commands.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


class SchedulerDaemon:
    """
    Background daemon for processing scheduled commands.

    Periodically checks for schedules due for execution and dispatches them.
    """

    def __init__(self, schedule_service, check_interval_seconds: int = 60):
        """
        Initialize scheduler daemon.

        Args:
            schedule_service: ScheduleService instance
            check_interval_seconds: How often to check for due schedules (default: 60s)
        """
        self.schedule_service = schedule_service
        self.check_interval_seconds = check_interval_seconds
        self.running = False
        self._task = None

    async def start(self):
        """Start the scheduler daemon."""
        if self.running:
            logger.warning("Scheduler daemon already running")
            return

        self.running = True
        logger.info(
            f"Starting scheduler daemon (check interval: {self.check_interval_seconds}s)"
        )

        while self.running:
            try:
                await self._check_and_execute_schedules()
            except Exception as e:
                logger.error(f"Error in scheduler daemon: {e}", exc_info=True)

            # Wait before next check
            await asyncio.sleep(self.check_interval_seconds)

        logger.info("Scheduler daemon stopped")

    async def stop(self):
        """Stop the scheduler daemon."""
        logger.info("Stopping scheduler daemon...")
        self.running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_and_execute_schedules(self):
        """Check for due schedules and execute them."""
        try:
            stats = await self.schedule_service.process_due_schedules()

            if stats["processed"] > 0:
                logger.info(
                    f"Processed {stats['processed']} scheduled commands "
                    f"(failed: {stats['failed']}, skipped: {stats['skipped']})"
                )
            else:
                logger.debug("No schedules due for execution")

        except Exception as e:
            logger.error(f"Failed to process schedules: {e}", exc_info=True)


async def run_scheduler_daemon(
    db_url: str,
    check_interval_seconds: int = 60,
    run_once: bool = False
):
    """
    Run the scheduler daemon.

    Args:
        db_url: Database connection URL
        check_interval_seconds: Check interval (default: 60s)
        run_once: If True, run once and exit (for testing)
    """
    from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
    from .schedule_service import ScheduleService
    from .device_service import DeviceService
    from .broadcast_service import BroadcastService

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    logger.info(f"Initializing scheduler daemon (db: {db_url})")

    # Initialize persistence
    persistence = PostgresPersistenceProvider(db_url=db_url)
    await persistence.initialize()

    # Initialize services
    device_service = DeviceService(persistence)
    broadcast_service = BroadcastService(persistence, device_service)
    schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    if run_once:
        # Run once and exit (for testing)
        logger.info("Running scheduler once...")
        stats = await schedule_service.process_due_schedules()
        logger.info(f"Processed {stats['processed']} schedules")
        await persistence.close()
        return stats

    # Create daemon
    daemon = SchedulerDaemon(schedule_service, check_interval_seconds)

    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(daemon.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Run daemon
        await daemon.start()
    finally:
        await persistence.close()


def main():
    """CLI entry point for scheduler daemon."""
    import argparse

    parser = argparse.ArgumentParser(description="Ruvon Scheduler Daemon")
    parser.add_argument(
        "--db-url",
        required=True,
        help="Database connection URL (postgresql://...)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Check interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run once and exit (for testing)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_scheduler_daemon(
            db_url=args.db_url,
            check_interval_seconds=args.interval,
            run_once=args.run_once
        ))
    except KeyboardInterrupt:
        logger.info("Scheduler daemon interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
