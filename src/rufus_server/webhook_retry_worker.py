"""Webhook retry worker for handling failed deliveries."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import signal

logger = logging.getLogger(__name__)


class WebhookRetryWorker:
    """
    Background worker for retrying failed webhook deliveries.

    Features:
    - Scans for failed deliveries periodically
    - Respects retry policies (max retries, backoff strategy)
    - Exponential or fixed backoff
    - Graceful shutdown
    """

    def __init__(
        self,
        webhook_service,
        scan_interval_seconds: int = 60,
        max_concurrent_retries: int = 10
    ):
        """
        Initialize retry worker.

        Args:
            webhook_service: WebhookService instance
            scan_interval_seconds: How often to scan for failed deliveries
            max_concurrent_retries: Max concurrent retry attempts
        """
        self.webhook_service = webhook_service
        self.scan_interval = scan_interval_seconds
        self.max_concurrent = max_concurrent_retries
        self.running = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Start the retry worker."""
        self.running = True
        logger.info(f"Webhook retry worker started (scan interval: {self.scan_interval}s)")

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            while self.running:
                try:
                    await self._scan_and_retry()
                except Exception as e:
                    logger.error(f"Error in retry worker: {e}", exc_info=True)

                # Wait for next scan or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.scan_interval
                    )
                except asyncio.TimeoutError:
                    pass  # Normal - continue to next scan

        finally:
            logger.info("Webhook retry worker stopped")

    async def stop(self):
        """Stop the retry worker gracefully."""
        logger.info("Stopping webhook retry worker...")
        self.running = False
        self._shutdown_event.set()

    async def _scan_and_retry(self):
        """Scan for failed deliveries and retry them."""
        logger.debug("Scanning for failed webhook deliveries...")

        # Get failed deliveries
        from rufus_server.webhook_service import WebhookStatus

        failed_deliveries = await self.webhook_service.get_delivery_history(
            status=WebhookStatus.FAILED,
            limit=100  # Process up to 100 failed deliveries per scan
        )

        if not failed_deliveries:
            logger.debug("No failed deliveries to retry")
            return

        logger.info(f"Found {len(failed_deliveries)} failed deliveries")

        # Group by webhook to get retry policies
        webhook_deliveries = {}
        for delivery in failed_deliveries:
            webhook_id = delivery['webhook_id']
            if webhook_id not in webhook_deliveries:
                webhook_deliveries[webhook_id] = []
            webhook_deliveries[webhook_id].append(delivery)

        # Retry deliveries with concurrency limit
        retry_tasks = []

        for webhook_id, deliveries in webhook_deliveries.items():
            # Get webhook to check retry policy
            webhook = await self.webhook_service.get_webhook(webhook_id)

            if not webhook or not webhook.is_active:
                logger.debug(f"Skipping inactive webhook: {webhook_id}")
                continue

            retry_policy = webhook.retry_policy or {}
            max_retries = retry_policy.get('max_retries', 3)
            initial_delay = retry_policy.get('initial_delay_seconds', 60)
            backoff_strategy = retry_policy.get('backoff_strategy', 'exponential')
            backoff_multiplier = retry_policy.get('backoff_multiplier', 2.0)
            max_delay = retry_policy.get('max_delay_seconds', 3600)

            for delivery in deliveries:
                attempt_count = delivery['attempt_count']

                # Check if exceeded max retries
                if attempt_count >= max_retries:
                    logger.debug(
                        f"Delivery {delivery['id']} exceeded max retries ({max_retries})"
                    )
                    continue

                # Calculate delay based on backoff strategy
                if backoff_strategy == 'exponential':
                    delay = min(
                        initial_delay * (backoff_multiplier ** attempt_count),
                        max_delay
                    )
                else:  # fixed
                    delay = initial_delay

                # Check if enough time has passed since last attempt
                created_at = delivery.get('created_at')
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))

                if datetime.utcnow() - created_at < timedelta(seconds=delay):
                    logger.debug(
                        f"Delivery {delivery['id']} not ready for retry "
                        f"(delay: {delay}s, attempt: {attempt_count})"
                    )
                    continue

                # Schedule retry
                retry_tasks.append(
                    self._retry_delivery(
                        delivery['id'],
                        webhook_id,
                        webhook.url,
                        delivery['event_type'],
                        delivery['event_data'],
                        webhook.secret,
                        webhook.headers
                    )
                )

                # Limit concurrent retries
                if len(retry_tasks) >= self.max_concurrent:
                    break

            if len(retry_tasks) >= self.max_concurrent:
                break

        if retry_tasks:
            logger.info(f"Retrying {len(retry_tasks)} deliveries...")
            await asyncio.gather(*retry_tasks, return_exceptions=True)
            logger.info(f"Completed {len(retry_tasks)} retry attempts")

    async def _retry_delivery(
        self,
        delivery_id: str,
        webhook_id: str,
        url: str,
        event_type: str,
        event_data: dict,
        secret: Optional[str] = None,
        custom_headers: Optional[dict] = None
    ):
        """Retry a failed webhook delivery."""
        try:
            logger.info(f"Retrying delivery {delivery_id} to {url}")

            # Parse event_data if it's a string
            if isinstance(event_data, str):
                import json
                event_data = json.loads(event_data)

            # Use the webhook service's delivery method
            from rufus_server.webhook_service import WebhookEvent

            # Convert event_type string to enum
            event_enum = WebhookEvent(event_type)

            await self.webhook_service._deliver_webhook(
                delivery_id=delivery_id,
                webhook_id=webhook_id,
                url=url,
                event_type=event_enum,
                event_data=event_data,
                secret=secret,
                custom_headers=custom_headers
            )

            logger.info(f"Successfully retried delivery {delivery_id}")

        except Exception as e:
            logger.error(f"Failed to retry delivery {delivery_id}: {e}")


async def run_retry_worker(
    webhook_service,
    scan_interval: int = 60,
    max_concurrent: int = 10
):
    """
    Run the webhook retry worker as a standalone process.

    Args:
        webhook_service: WebhookService instance
        scan_interval: Scan interval in seconds
        max_concurrent: Max concurrent retry attempts
    """
    worker = WebhookRetryWorker(
        webhook_service,
        scan_interval_seconds=scan_interval,
        max_concurrent_retries=max_concurrent
    )

    await worker.start()


# CLI entry point
async def main():
    """Main entry point for standalone retry worker."""
    import os
    import sys

    # Add project to path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
    from rufus_server.webhook_service import WebhookService

    # Get database URL from environment
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("Error: DATABASE_URL environment variable required")
        sys.exit(1)

    # Create persistence provider
    if db_url.startswith('postgresql'):
        persistence = PostgresPersistenceProvider(db_url)
    elif db_url.startswith('sqlite'):
        db_path = db_url.replace('sqlite:///', '')
        persistence = SQLitePersistenceProvider(db_path=db_path)
    else:
        print(f"Error: Unsupported database URL: {db_url}")
        sys.exit(1)

    await persistence.initialize()

    # Create webhook service
    webhook_service = WebhookService(persistence)

    # Get configuration from environment
    scan_interval = int(os.getenv('WEBHOOK_RETRY_SCAN_INTERVAL', '60'))
    max_concurrent = int(os.getenv('WEBHOOK_RETRY_MAX_CONCURRENT', '10'))

    print(f"Starting webhook retry worker...")
    print(f"  Database:        {db_url}")
    print(f"  Scan interval:   {scan_interval}s")
    print(f"  Max concurrent:  {max_concurrent}")
    print()

    try:
        await run_retry_worker(webhook_service, scan_interval, max_concurrent)
    finally:
        await webhook_service.close()
        await persistence.close()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
