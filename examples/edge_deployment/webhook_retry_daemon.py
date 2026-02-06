#!/usr/bin/env python3
"""
Webhook Retry Daemon - Background worker for retrying failed webhook deliveries.

Usage:
    python webhook_retry_daemon.py [--scan-interval 60] [--max-concurrent 10]

Environment Variables:
    DATABASE_URL                       - Database connection string (required)
    WEBHOOK_RETRY_SCAN_INTERVAL       - Scan interval in seconds (default: 60)
    WEBHOOK_RETRY_MAX_CONCURRENT      - Max concurrent retries (default: 10)

Examples:
    # Start with defaults
    DATABASE_URL=postgresql://localhost/rufus_edge python webhook_retry_daemon.py

    # Custom scan interval
    python webhook_retry_daemon.py --scan-interval 30

    # Custom concurrency
    python webhook_retry_daemon.py --max-concurrent 20

    # Run as systemd service
    systemctl start webhook-retry-daemon

    # Run as Docker container
    docker run -e DATABASE_URL=... webhook-retry-daemon
"""

import asyncio
import logging
import os
import sys
import argparse

# Add project to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus_server.webhook_service import WebhookService
from rufus_server.webhook_retry_worker import WebhookRetryWorker


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Webhook Retry Daemon')
    parser.add_argument(
        '--scan-interval',
        type=int,
        default=int(os.getenv('WEBHOOK_RETRY_SCAN_INTERVAL', '60')),
        help='Scan interval in seconds (default: 60)'
    )
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=int(os.getenv('WEBHOOK_RETRY_MAX_CONCURRENT', '10')),
        help='Max concurrent retries (default: 10)'
    )
    parser.add_argument(
        '--db-url',
        type=str,
        default=os.getenv('DATABASE_URL'),
        help='Database URL (default: from DATABASE_URL env var)'
    )

    args = parser.parse_args()

    # Validate database URL
    if not args.db_url:
        print("Error: DATABASE_URL environment variable or --db-url required")
        sys.exit(1)

    # Create persistence provider
    if args.db_url.startswith('postgresql'):
        persistence = PostgresPersistenceProvider(args.db_url)
    elif args.db_url.startswith('sqlite'):
        db_path = args.db_url.replace('sqlite:///', '')
        persistence = SQLitePersistenceProvider(db_path=db_path)
    else:
        print(f"Error: Unsupported database URL: {args.db_url}")
        sys.exit(1)

    await persistence.initialize()

    # Create webhook service
    webhook_service = WebhookService(persistence)

    # Create and start retry worker
    print("=" * 70)
    print("  Webhook Retry Daemon")
    print("=" * 70)
    print(f"\n  Database:        {args.db_url}")
    print(f"  Scan interval:   {args.scan_interval}s")
    print(f"  Max concurrent:  {args.max_concurrent}")
    print("\n  Status: RUNNING")
    print("  Press Ctrl+C to stop\n")
    print("=" * 70 + "\n")

    worker = WebhookRetryWorker(
        webhook_service,
        scan_interval_seconds=args.scan_interval,
        max_concurrent_retries=args.max_concurrent
    )

    try:
        await worker.start()
    except KeyboardInterrupt:
        print("\n\nReceived interrupt signal, shutting down...")
    finally:
        await worker.stop()
        await webhook_service.close()
        await persistence.close()
        print("Webhook retry daemon stopped\n")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
