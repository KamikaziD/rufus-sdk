"""
Device Simulator for Load Testing.

Simulates edge device behavior for load testing the Rufus Edge control plane.
"""

import asyncio
import hashlib
import hmac
import logging
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
import httpx
import psutil

logger = logging.getLogger(__name__)


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
            timeout=30.0,
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
        """Sync a batch of transactions to cloud."""
        try:
            response = await self._http_client.post(
                f"{self.config.cloud_url}/api/v1/devices/{self.config.device_id}/sync",
                json={
                    "transactions": transactions,
                    "device_sequence": 0,  # TODO: Track sequence
                    "device_timestamp": datetime.utcnow().isoformat(),
                }
            )

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
            logger.error(f"Sync error for {self.config.device_id}: {e}")
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
        """Poll for config updates."""
        try:
            headers = {}
            if self._current_config_etag:
                headers["If-None-Match"] = self._current_config_etag

            response = await self._http_client.get(
                f"{self.config.cloud_url}/api/v1/devices/{self.config.device_id}/config",
                headers=headers
            )

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
