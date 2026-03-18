"""
Device Simulator for Load Testing.

Simulates edge device behavior for load testing the Rufus Edge control plane.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
import httpx
import psutil

logger = logging.getLogger(__name__)


# Retry configuration (can be overridden by environment variables)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
INITIAL_BACKOFF = float(os.getenv("INITIAL_BACKOFF", "1.0"))  # seconds
MAX_BACKOFF = float(os.getenv("MAX_BACKOFF", "10.0"))  # seconds
BACKOFF_MULTIPLIER = float(os.getenv("BACKOFF_MULTIPLIER", "2.0"))


@dataclass
class DeviceConfig:
    """Configuration for simulated device."""
    device_id: str
    cloud_url: str
    api_key: str
    device_type: str = "pos_terminal"
    merchant_id: str = "merchant_001"
    heartbeat_interval: int = 30  # seconds
    saf_batch_size: int = 50
    config_poll_interval: int = 60  # seconds


@dataclass
class DeviceMetrics:
    """Metrics collected from simulated device."""
    heartbeats_sent: int = 0
    heartbeat_failures: int = 0
    transactions_synced: int = 0
    sync_failures: int = 0
    configs_downloaded: int = 0
    config_failures: int = 0
    commands_received: int = 0
    command_failures: int = 0
    total_requests: int = 0
    total_errors: int = 0
    latencies: List[float] = field(default_factory=list)  # per-request latency in seconds


class SimulatedEdgeDevice:
    """
    Simulates an edge device for load testing.

    Supports scenarios:
    - Heartbeat reporting
    - Store-and-Forward sync
    - Config polling
    - Model downloads
    - Cloud command handling
    - Workflow execution
    """

    def __init__(
        self,
        config: DeviceConfig,
        metrics_callback: Optional[Callable[[str, DeviceMetrics], None]] = None
    ):
        """
        Initialize simulated device.

        Args:
            config: Device configuration
            metrics_callback: Optional callback for metrics reporting
        """
        self.config = config
        self.metrics = DeviceMetrics()
        self.metrics_callback = metrics_callback
        self._http_client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._current_config_etag: Optional[str] = None
        self._pending_transactions: List[Dict[str, Any]] = []

    async def initialize(self):
        """Initialize HTTP client."""
        self._http_client = httpx.AsyncClient(
            timeout=60.0,  # Increased for load testing
            headers={
                "X-API-Key": self.config.api_key,
                "X-Device-ID": self.config.device_id,
                "Content-Type": "application/json",
            }
        )
        logger.info(f"Device {self.config.device_id} initialized")

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()

    async def _retry_with_backoff(
        self,
        operation_name: str,
        coro_func,
        *args,
        **kwargs
    ):
        """
        Execute operation with exponential backoff retry.

        Args:
            operation_name: Name of operation for logging
            coro_func: Coroutine function to execute
            *args, **kwargs: Arguments to pass to coro_func

        Returns:
            Result from coro_func

        Raises:
            Last exception if all retries exhausted
        """
        backoff = INITIAL_BACKOFF
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                return await coro_func(*args, **kwargs)
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
                last_exception = e
                self.metrics.total_errors += 1

                if attempt < MAX_RETRIES - 1:
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, backoff * 0.1)
                    sleep_time = min(backoff + jitter, MAX_BACKOFF)

                    logger.warning(
                        f"Device {self.config.device_id} {operation_name} failed "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                        f"Retrying in {sleep_time:.2f}s..."
                    )

                    await asyncio.sleep(sleep_time)
                    backoff *= BACKOFF_MULTIPLIER
                else:
                    logger.error(
                        f"Device {self.config.device_id} {operation_name} failed "
                        f"after {MAX_RETRIES} attempts: {e}"
                    )
            except httpx.HTTPStatusError as e:
                # Don't retry 4xx errors (client errors)
                if 400 <= e.response.status_code < 500:
                    logger.error(
                        f"Device {self.config.device_id} {operation_name} failed "
                        f"with client error {e.response.status_code}: {e}"
                    )
                    self.metrics.total_errors += 1
                    raise
                # Retry 5xx errors (server errors)
                last_exception = e
                self.metrics.total_errors += 1

                if attempt < MAX_RETRIES - 1:
                    jitter = random.uniform(0, backoff * 0.1)
                    sleep_time = min(backoff + jitter, MAX_BACKOFF)

                    logger.warning(
                        f"Device {self.config.device_id} {operation_name} failed "
                        f"with server error {e.response.status_code} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Retrying in {sleep_time:.2f}s..."
                    )

                    await asyncio.sleep(sleep_time)
                    backoff *= BACKOFF_MULTIPLIER
                else:
                    logger.error(
                        f"Device {self.config.device_id} {operation_name} failed "
                        f"after {MAX_RETRIES} attempts with status {e.response.status_code}"
                    )
            except Exception as e:
                # Unexpected errors - log and re-raise
                logger.error(
                    f"Device {self.config.device_id} {operation_name} failed "
                    f"with unexpected error: {e}"
                )
                self.metrics.total_errors += 1
                raise

        # All retries exhausted
        raise last_exception

    async def run_scenario(self, scenario: str, duration_seconds: int = 600):
        """
        Run a specific test scenario.

        Args:
            scenario: Scenario name (heartbeat, saf_sync, config_poll, etc.)
            duration_seconds: How long to run (default: 10 minutes)
        """
        self._running = True
        start_time = time.time()

        try:
            if scenario == "heartbeat":
                await self._heartbeat_scenario(duration_seconds)
            elif scenario == "saf_sync":
                await self._saf_sync_scenario()
            elif scenario == "config_poll":
                await self._config_polling_scenario(duration_seconds)
            elif scenario == "model_update":
                await self._model_update_scenario()
            elif scenario == "cloud_commands":
                await self._cloud_commands_scenario(duration_seconds)
            elif scenario == "workflow_execution":
                await self._workflow_execution_scenario(duration_seconds)
            else:
                logger.error(f"Unknown scenario: {scenario}")

        except asyncio.CancelledError:
            logger.info(f"Device {self.config.device_id} scenario cancelled")
        finally:
            self._running = False
            elapsed = time.time() - start_time
            logger.info(
                f"Device {self.config.device_id} completed {scenario} "
                f"in {elapsed:.1f}s - {self.metrics}"
            )

    # -------------------------------------------------------------------------
    # Scenario 1: Concurrent Device Heartbeats
    # -------------------------------------------------------------------------

    async def _heartbeat_scenario(self, duration_seconds: int):
        """
        Send heartbeats at regular intervals.

        Simulates real device reporting health metrics to cloud.
        """
        end_time = time.time() + duration_seconds

        while time.time() < end_time and self._running:
            success = await self._send_heartbeat()
            if success:
                self.metrics.heartbeats_sent += 1
            else:
                self.metrics.heartbeat_failures += 1

            # Report metrics
            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Wait for next heartbeat (with small jitter)
            jitter = random.uniform(-2, 2)
            await asyncio.sleep(self.config.heartbeat_interval + jitter)

    async def _send_heartbeat(self) -> bool:
        """Send heartbeat to cloud control plane."""
        try:
            # Simulate device metrics
            cpu_percent = random.uniform(10, 60)
            memory_percent = random.uniform(30, 70)
            disk_percent = random.uniform(20, 80)

            # Retry heartbeat with exponential backoff
            async def send_heartbeat():
                response = await self._http_client.post(
                    f"{self.config.cloud_url}/api/v1/devices/{self.config.device_id}/heartbeat",
                    json={
                        "device_status": "online",
                        "metrics": {
                            "cpu_percent": cpu_percent,
                            "memory_percent": memory_percent,
                            "disk_percent": disk_percent,
                            "pending_sync_count": len(self._pending_transactions),
                            "uptime_seconds": random.randint(3600, 86400),
                        }
                    }
                )
                response.raise_for_status()
                return response

            t0 = time.perf_counter()
            response = await self._retry_with_backoff("heartbeat", send_heartbeat)
            self.metrics.latencies.append(time.perf_counter() - t0)
            self.metrics.total_requests += 1

            if response.status_code == 200:
                # Check for pending commands in response
                data = response.json()
                if "commands" in data and data["commands"]:
                    self.metrics.commands_received += len(data["commands"])
                    # Simulate command processing
                    await self._process_commands(data["commands"])
                return True
            else:
                logger.warning(
                    f"Heartbeat failed for {self.config.device_id}: "
                    f"HTTP {response.status_code}"
                )
                self.metrics.total_errors += 1
                return False

        except Exception as e:
            logger.error(f"Heartbeat error for {self.config.device_id}: {e}")
            self.metrics.total_errors += 1
            return False

    # -------------------------------------------------------------------------
    # Scenario 2: Store-and-Forward Bulk Sync
    # -------------------------------------------------------------------------

    async def _saf_sync_scenario(self):
        """
        Generate offline transactions and sync to cloud.

        Simulates device going offline, queuing transactions, then syncing.
        """
        # Step 1: Generate offline transactions
        num_transactions = random.randint(50, 150)
        logger.info(
            f"Device {self.config.device_id} generating {num_transactions} "
            f"offline transactions"
        )

        for i in range(num_transactions):
            transaction = self._generate_transaction(i)
            self._pending_transactions.append(transaction)

        # Step 2: Sync to cloud in batches
        while self._pending_transactions and self._running:
            batch = self._pending_transactions[:self.config.saf_batch_size]
            success = await self._sync_batch(batch)

            if success:
                # Remove synced transactions
                self._pending_transactions = self._pending_transactions[len(batch):]
                self.metrics.transactions_synced += len(batch)
            else:
                self.metrics.sync_failures += 1
                # Retry after delay
                await asyncio.sleep(5)

        logger.info(
            f"Device {self.config.device_id} completed SAF sync: "
            f"{self.metrics.transactions_synced} synced"
        )

    def _generate_transaction(self, index: int) -> Dict[str, Any]:
        """Generate a simulated SAF transaction."""
        transaction_id = f"{self.config.device_id}-txn-{index:06d}"
        idempotency_key = f"{self.config.device_id}:{transaction_id}"

        # Simulate encrypted payload
        payload_data = {
            "amount_cents": random.randint(100, 50000),
            "currency": "USD",
            "card_last_four": f"{random.randint(1000, 9999)}",
            "merchant_id": self.config.merchant_id,
        }

        encrypted_blob = hashlib.sha256(
            str(payload_data).encode()
        ).hexdigest()

        return {
            "transaction_id": transaction_id,
            "idempotency_key": idempotency_key,
            "encrypted_blob": encrypted_blob,
            "encryption_key_id": "default",
            "hmac": self._calculate_hmac(transaction_id, encrypted_blob, "default"),
        }

    def _calculate_hmac(
        self,
        transaction_id: str,
        encrypted_blob: str,
        encryption_key_id: str
    ) -> str:
        """Calculate HMAC for transaction."""
        hmac_input = f"{transaction_id}|{encrypted_blob}|{encryption_key_id}"
        return hmac.new(
            self.config.api_key.encode('utf-8'),
            hmac_input.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _sync_batch(self, transactions: List[Dict[str, Any]]) -> bool:
        """Sync a batch of transactions to cloud with retry logic."""
        try:
            # Retry sync with exponential backoff
            async def send_sync():
                response = await self._http_client.post(
                    f"{self.config.cloud_url}/api/v1/devices/{self.config.device_id}/sync",
                    json={
                        "transactions": transactions,
                        "device_sequence": 0,  # TODO: Track sequence
                        "device_timestamp": datetime.utcnow().isoformat(),
                    }
                )
                response.raise_for_status()
                return response

            t0 = time.perf_counter()
            response = await self._retry_with_backoff("SAF sync", send_sync)
            self.metrics.latencies.append(time.perf_counter() - t0)
            self.metrics.total_requests += 1

            if response.status_code == 200:
                data = response.json()
                logger.debug(
                    f"Batch sync for {self.config.device_id}: "
                    f"{len(data.get('accepted', []))} accepted, "
                    f"{len(data.get('rejected', []))} rejected"
                )
                return True
            else:
                logger.warning(
                    f"Sync failed for {self.config.device_id}: "
                    f"HTTP {response.status_code}"
                )
                self.metrics.total_errors += 1
                return False

        except Exception as e:
            logger.error(f"Sync error for {self.config.device_id}: {e}", exc_info=True)
            self.metrics.total_errors += 1
            return False

    # -------------------------------------------------------------------------
    # Scenario 3: Config Polling
    # -------------------------------------------------------------------------

    async def _config_polling_scenario(self, duration_seconds: int):
        """
        Poll for config updates using ETag conditional requests.

        Simulates device checking for new configurations.
        """
        end_time = time.time() + duration_seconds

        while time.time() < end_time and self._running:
            success = await self._poll_config()
            if success:
                self.metrics.configs_downloaded += 1
            else:
                self.metrics.config_failures += 1

            # Report metrics
            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Wait for next poll (with jitter)
            jitter = random.uniform(-5, 5)
            await asyncio.sleep(self.config.config_poll_interval + jitter)

    async def _poll_config(self) -> bool:
        """Poll for config updates with retry logic."""
        try:
            headers = {}
            if self._current_config_etag:
                headers["If-None-Match"] = self._current_config_etag

            # Retry config poll with exponential backoff
            async def poll_config():
                response = await self._http_client.get(
                    f"{self.config.cloud_url}/api/v1/devices/{self.config.device_id}/config",
                    headers=headers
                )
                # Don't raise for 304 (Not Modified) - that's expected
                if response.status_code not in [200, 304]:
                    response.raise_for_status()
                return response

            t0 = time.perf_counter()
            response = await self._retry_with_backoff("config poll", poll_config)
            self.metrics.latencies.append(time.perf_counter() - t0)
            self.metrics.total_requests += 1

            if response.status_code == 200:
                # New config available
                data = response.json()
                self._current_config_etag = response.headers.get("ETag")
                logger.debug(
                    f"Config updated for {self.config.device_id}: "
                    f"ETag={self._current_config_etag}"
                )
                return True
            elif response.status_code == 304:
                # Config unchanged (ETag match)
                logger.debug(f"Config unchanged for {self.config.device_id}")
                return True
            else:
                logger.warning(
                    f"Config poll failed for {self.config.device_id}: "
                    f"HTTP {response.status_code}"
                )
                self.metrics.total_errors += 1
                return False

        except Exception as e:
            logger.error(f"Config poll error for {self.config.device_id}: {e}")
            self.metrics.total_errors += 1
            return False

    # -------------------------------------------------------------------------
    # Scenario 4: Model Updates
    # -------------------------------------------------------------------------

    async def _model_update_scenario(self):
        """
        Download model update (simulated).

        Simulates delta update or full download.
        """
        # Simulate model update check
        model_name = "fraud_detection"
        use_delta = random.random() < 0.8  # 80% use delta

        logger.info(
            f"Device {self.config.device_id} updating model {model_name} "
            f"(delta={use_delta})"
        )

        # Simulate download time based on size
        if use_delta:
            download_size_mb = 8
            download_time = download_size_mb / 2  # 2 MB/s
        else:
            download_size_mb = 50
            download_time = download_size_mb / 2

        await asyncio.sleep(download_time)

        logger.info(
            f"Device {self.config.device_id} model update complete "
            f"({download_size_mb}MB in {download_time:.1f}s)"
        )

    # -------------------------------------------------------------------------
    # Scenario 5: Cloud Commands
    # -------------------------------------------------------------------------

    async def _cloud_commands_scenario(self, duration_seconds: int):
        """
        Receive and process cloud commands via heartbeat.

        Simulates cloud-to-device command delivery.
        """
        # Use heartbeat scenario (commands come via heartbeat response)
        await self._heartbeat_scenario(duration_seconds)

    async def _process_commands(self, commands: List[Dict[str, Any]]):
        """Process commands received from cloud."""
        for cmd in commands:
            command_type = cmd.get("command_type")
            command_id = cmd.get("command_id")

            logger.debug(
                f"Device {self.config.device_id} processing command: "
                f"{command_type} (id={command_id})"
            )

            # Simulate command processing
            await asyncio.sleep(random.uniform(0.1, 0.5))

            # Report command completion (in real impl)
            # For load testing, we skip this to avoid extra requests

    # -------------------------------------------------------------------------
    # Scenario 6: Workflow Execution
    # -------------------------------------------------------------------------

    async def _workflow_execution_scenario(self, duration_seconds: int):
        """
        Execute workflows concurrently.

        Simulates local workflow execution on edge device.
        """
        num_workflows = random.randint(5, 15)
        logger.info(
            f"Device {self.config.device_id} executing {num_workflows} workflows"
        )

        tasks = [
            self._execute_workflow(i)
            for i in range(num_workflows)
        ]

        await asyncio.gather(*tasks)

    async def _execute_workflow(self, workflow_index: int):
        """Execute a single workflow (simulated)."""
        workflow_id = f"{self.config.device_id}-wf-{workflow_index:03d}"

        # Simulate workflow steps
        num_steps = random.randint(3, 7)
        for step in range(num_steps):
            # Simulate step execution time
            step_time = random.uniform(0.1, 1.0)
            await asyncio.sleep(step_time)

        logger.debug(
            f"Workflow {workflow_id} completed ({num_steps} steps)"
        )

    def get_metrics(self) -> DeviceMetrics:
        """Get current metrics."""
        return self.metrics
