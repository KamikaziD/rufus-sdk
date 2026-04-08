#!/usr/bin/env python3
"""
Command Retry Worker

Background daemon that processes failed commands with retry policies.
Runs continuously and re-queues commands that are ready for retry.

Usage:
    # Run as daemon
    python -m ruvon_server.retry_worker

    # Custom interval
    python -m ruvon_server.retry_worker --interval 30

    # One-shot (process once and exit)
    python -m ruvon_server.retry_worker --once
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('rufus.retry_worker')


async def run_retry_worker(
    db_url: str,
    interval_seconds: int = 60,
    run_once: bool = False
):
    """
    Run the retry worker daemon.

    Args:
        db_url: PostgreSQL connection URL
        interval_seconds: Time between retry checks (default: 60)
        run_once: If True, process once and exit
    """
    from ruvon_server.device_service import DeviceService
    from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider

    # Initialize persistence
    logger.info(f"Connecting to database: {db_url}")
    persistence = PostgresPersistenceProvider(db_url=db_url)
    await persistence.initialize()

    # Initialize device service
    device_service = DeviceService(persistence=persistence)

    logger.info(f"Retry worker started (interval: {interval_seconds}s)")

    try:
        iteration = 0
        while True:
            iteration += 1
            start_time = datetime.utcnow()

            try:
                # Process retries
                stats = await device_service.process_retries()

                retries_processed = stats.get('retries_processed', 0)
                if retries_processed > 0:
                    logger.info(f"Iteration #{iteration}: Processed {retries_processed} retries")
                else:
                    logger.debug(f"Iteration #{iteration}: No retries pending")

            except Exception as e:
                logger.error(f"Error processing retries: {e}", exc_info=True)

            # Exit if run_once mode
            if run_once:
                logger.info("One-shot mode: Exiting after single run")
                break

            # Calculate sleep time (maintain fixed interval)
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            sleep_time = max(0, interval_seconds - elapsed)

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Shutting down retry worker...")
    finally:
        await persistence.close()
        logger.info("Retry worker stopped")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Rufus Command Retry Worker'
    )
    parser.add_argument(
        '--db-url',
        default=os.getenv('DATABASE_URL', 'postgresql://rufus:rufus@localhost:5433/rufus'),
        help='PostgreSQL connection URL'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='Seconds between retry checks (default: 60)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Process retries once and exit'
    )

    args = parser.parse_args()

    # Validate interval
    if args.interval < 5:
        logger.error("Interval must be at least 5 seconds")
        sys.exit(1)

    if args.interval > 3600:
        logger.warning("Interval > 1 hour is unusually long")

    try:
        await run_retry_worker(
            db_url=args.db_url,
            interval_seconds=args.interval,
            run_once=args.once
        )
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
