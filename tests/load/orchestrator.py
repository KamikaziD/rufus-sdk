"""
Load Test Orchestrator.

Orchestrates simulated devices for load testing scenarios.
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
import json

from tests.load.device_simulator import SimulatedEdgeDevice, DeviceConfig, DeviceMetrics

logger = logging.getLogger(__name__)


@dataclass
class LoadTestResults:
    """Results from a load test run."""
    scenario: str
    num_devices: int
    duration_seconds: float
    total_requests: int = 0
    total_errors: int = 0
    error_rate: float = 0.0
    requests_per_second: float = 0.0

    # Scenario-specific metrics
    heartbeats_sent: int = 0
    heartbeat_failures: int = 0
    transactions_synced: int = 0
    sync_failures: int = 0
    configs_downloaded: int = 0
    config_failures: int = 0
    commands_received: int = 0

    # Error breakdown (thundering herd / capacity analysis)
    errors_5xx: int = 0      # Server errors — pool exhaustion, crashes
    errors_4xx: int = 0      # Client errors — auth, bad request
    errors_timeout: int = 0  # Network timeouts

    # Per-device metrics
    device_metrics: Dict[str, DeviceMetrics] = field(default_factory=dict)

    # Latency tracking (if enabled)
    request_latencies: List[float] = field(default_factory=list)

    def calculate_summary(self):
        """Calculate summary statistics."""
        if self.duration_seconds > 0:
            self.requests_per_second = self.total_requests / self.duration_seconds

        if self.total_requests > 0:
            self.error_rate = (self.total_errors / self.total_requests) * 100

    def latency_percentile(self, p: float) -> float:
        """Return the p-th percentile latency in milliseconds (0–1 scale)."""
        if not self.request_latencies:
            return 0.0
        s = sorted(self.request_latencies)
        idx = int(len(s) * p)
        return s[min(idx, len(s) - 1)] * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = {
            "scenario": self.scenario,
            "num_devices": self.num_devices,
            "duration_seconds": self.duration_seconds,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": f"{self.error_rate:.2f}%",
            "requests_per_second": f"{self.requests_per_second:.1f}",
            "heartbeats_sent": self.heartbeats_sent,
            "heartbeat_failures": self.heartbeat_failures,
            "transactions_synced": self.transactions_synced,
            "sync_failures": self.sync_failures,
            "configs_downloaded": self.configs_downloaded,
            "config_failures": self.config_failures,
            "commands_received": self.commands_received,
            "success_rate": f"{100 - self.error_rate:.2f}%",
        }
        if self.request_latencies:
            d["latency_p50_ms"] = f"{self.latency_percentile(0.50):.1f}"
            d["latency_p95_ms"] = f"{self.latency_percentile(0.95):.1f}"
            d["latency_p99_ms"] = f"{self.latency_percentile(0.99):.1f}"
            d["latency_max_ms"] = f"{max(self.request_latencies) * 1000:.1f}"
            d["latency_samples"] = len(self.request_latencies)
        d["errors_5xx"] = self.errors_5xx
        d["errors_4xx"] = self.errors_4xx
        d["errors_timeout"] = self.errors_timeout
        return d


class LoadTestOrchestrator:
    """
    Orchestrates load testing with simulated devices.

    Features:
    - Spawn multiple simulated devices concurrently
    - Collect and aggregate metrics
    - Support for different test scenarios
    - Progress reporting
    - Results export (JSON)
    """

    def __init__(
        self,
        cloud_url: str,
        base_api_key: str = "test_api_key",
        device_type: str = "pos_terminal",
        merchant_id: str = "merchant_load_test"
    ):
        """
        Initialize orchestrator.

        Args:
            cloud_url: Cloud control plane URL
            base_api_key: Base API key for devices
            device_type: Type of devices to simulate
            merchant_id: Merchant ID for all devices
        """
        self.cloud_url = cloud_url
        self.base_api_key = base_api_key
        self.device_type = device_type
        self.merchant_id = merchant_id

        self._devices: List[SimulatedEdgeDevice] = []
        self._metrics_lock = asyncio.Lock()
        self._aggregated_metrics: Dict[str, DeviceMetrics] = {}

    async def setup_devices(self, num_devices: int, cleanup_first: bool = True):
        """
        Setup devices for load testing (shared across scenarios).

        Args:
            num_devices: Number of devices to create
            cleanup_first: Whether to cleanup existing devices before setup
        """
        logger.info(f"Setting up {num_devices} devices for load testing...")

        # Create devices with consistent IDs (no scenario in name)
        self._devices = []
        for i in range(num_devices):
            device_id = f"load-test-{i:05d}"  # Same ID across all scenarios
            api_key = f"{self.base_api_key}_{i}"

            config = DeviceConfig(
                device_id=device_id,
                cloud_url=self.cloud_url,
                api_key=api_key,
                device_type=self.device_type,
                merchant_id=self.merchant_id,
            )

            device = SimulatedEdgeDevice(
                config=config,
                metrics_callback=self._metrics_callback
            )

            self._devices.append(device)

        # Initialize all devices
        logger.info(f"Initializing {num_devices} HTTP clients...")
        await asyncio.gather(*[device.initialize() for device in self._devices])

        # Clean up any existing load test devices (if requested)
        if cleanup_first:
            logger.info(f"Cleaning up existing load test devices...")
            await self._cleanup_devices()

        # Register devices with control plane (idempotent)
        logger.info(f"Registering {num_devices} devices with control plane...")
        await self._register_devices(idempotent=True)

        logger.info(f"Device setup complete: {num_devices} devices ready")

    async def teardown_devices(self):
        """Teardown devices after all scenarios complete."""
        logger.info("Tearing down devices...")

        # Close HTTP clients
        if self._devices:
            await asyncio.gather(*[device.close() for device in self._devices])

        # Cleanup from server
        logger.info("Cleaning up devices from server...")
        await self._cleanup_devices()

        logger.info("Device teardown complete")

    async def run_scenario(
        self,
        scenario: str,
        duration_seconds: int = 600,
        progress_callback: Optional[callable] = None,
        skip_device_setup: bool = False
    ) -> LoadTestResults:
        """
        Run a load test scenario.

        Args:
            scenario: Scenario name (heartbeat, saf_sync, config_poll, etc.)
            duration_seconds: How long to run (seconds)
            progress_callback: Optional callback for progress updates
            skip_device_setup: If True, use existing devices (for multi-scenario tests)

        Returns:
            LoadTestResults with aggregated metrics
        """
        num_devices = len(self._devices) if self._devices else 0

        logger.info(
            f"Starting load test: scenario={scenario}, "
            f"devices={num_devices}, duration={duration_seconds}s"
        )

        # Create results object
        results = LoadTestResults(
            scenario=scenario,
            num_devices=num_devices,
            duration_seconds=0  # Will be updated
        )

        # Setup devices if not skipped (for single-scenario tests)
        if not skip_device_setup and not self._devices:
            raise ValueError(
                "No devices available. Call setup_devices() first or set skip_device_setup=False")
        elif not skip_device_setup:
            # Single scenario mode - setup and cleanup
            await self.setup_devices(num_devices, cleanup_first=True)

        # Start timer
        start_time = time.time()

        # For thundering herd: attach a shared asyncio.Event to every device.
        # Devices prepare their payload then block on the event; the orchestrator
        # releases all of them at once after a short prep window.
        go_event = None
        if scenario == "thundering_herd":
            go_event = asyncio.Event()
            for device in self._devices:
                device._go_event = go_event

        # Run scenario on all devices concurrently (as tasks so the event loop
        # can interleave them before the go_event fires)
        logger.info(f"Running scenario {scenario} on {num_devices} devices...")
        device_tasks = [
            asyncio.create_task(device.run_scenario(scenario, duration_seconds))
            for device in self._devices
        ]

        all_tasks = list(device_tasks)
        if progress_callback:
            all_tasks.append(asyncio.create_task(
                self._report_progress(progress_callback, duration_seconds)
            ))

        if go_event is not None:
            # Give all devices time to reach their wait point (prep phase)
            prep_seconds = min(5, max(2, num_devices // 200))
            logger.info(
                f"Thundering herd prep window: {prep_seconds}s "
                f"(devices generating transactions...)"
            )
            await asyncio.sleep(prep_seconds)
            logger.info(
                f"THUNDERING HERD: Releasing {num_devices} simultaneous SAF syncs NOW"
            )
            go_event.set()

        try:
            await asyncio.gather(*all_tasks)
        except Exception as e:
            logger.error(f"Error during load test: {e}")

        # Calculate duration
        results.duration_seconds = time.time() - start_time

        # Aggregate metrics
        await self._aggregate_metrics(results)

        # Cleanup devices if not skipped (single scenario mode)
        if not skip_device_setup:
            logger.info("Closing devices...")
            await asyncio.gather(*[device.close() for device in self._devices])

        # Calculate summary
        results.calculate_summary()

        logger.info(
            f"Load test complete: {results.total_requests} requests, "
            f"{results.error_rate:.2f}% error rate, "
            f"{results.requests_per_second:.1f} req/sec"
        )

        return results

    async def _metrics_callback(self, device_id: str, metrics: DeviceMetrics):
        """Callback for device metrics updates."""
        async with self._metrics_lock:
            self._aggregated_metrics[device_id] = metrics

    async def _aggregate_metrics(self, results: LoadTestResults):
        """Aggregate metrics from all devices."""
        async with self._metrics_lock:
            for device_id, metrics in self._aggregated_metrics.items():
                results.device_metrics[device_id] = metrics

                # Aggregate totals
                results.heartbeats_sent += metrics.heartbeats_sent
                results.heartbeat_failures += metrics.heartbeat_failures
                results.transactions_synced += metrics.transactions_synced
                results.sync_failures += metrics.sync_failures
                results.configs_downloaded += metrics.configs_downloaded
                results.config_failures += metrics.config_failures
                results.commands_received += metrics.commands_received
                results.total_requests += metrics.total_requests
                results.total_errors += metrics.total_errors
                results.errors_5xx += metrics.errors_5xx
                results.errors_4xx += metrics.errors_4xx
                results.errors_timeout += metrics.errors_timeout
                results.request_latencies.extend(metrics.latencies)

    async def _register_devices(self, idempotent: bool = True):
        """
        Register all devices with the control plane.

        Args:
            idempotent: If True, check if device exists before registering
        """
        import httpx
        import os

        registration_key = os.getenv(
            "RUFUS_REGISTRATION_KEY", "demo-registration-key-2024")

        # Limit concurrent registrations to avoid exhausting the server's DB pool.
        # Default: 50 concurrent (matches server pool max_size default).
        concurrency = int(os.getenv("LOAD_TEST_SETUP_CONCURRENCY", "50"))
        semaphore = asyncio.Semaphore(concurrency)

        async def register_single_device(device):
            """Register a single device (idempotent)."""
            async with semaphore:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        # Check if device already exists (idempotent mode)
                        if idempotent:
                            check_response = await client.get(
                                f"{self.cloud_url}/api/v1/devices/{device.config.device_id}",
                                headers={"X-Registration-Key": registration_key}
                            )

                            if check_response.status_code == 200:
                                data = check_response.json()
                                existing_api_key = data.get("api_key")
                                if existing_api_key:
                                    device.config.api_key = existing_api_key
                                    await device._http_client.aclose()
                                    device._http_client = httpx.AsyncClient(
                                        timeout=60.0,
                                        headers={
                                            "X-API-Key": device.config.api_key,
                                            "X-Device-ID": device.config.device_id,
                                            "Content-Type": "application/json",
                                        }
                                    )
                                    logger.debug(
                                        f"Device {device.config.device_id} already registered (using existing)")
                                    return True

                        # Register new device
                        response = await client.post(
                            f"{self.cloud_url}/api/v1/devices/register",
                            headers={
                                "X-Registration-Key": registration_key,
                                "Content-Type": "application/json"
                            },
                            json={
                                "device_id": device.config.device_id,
                                "device_type": device.config.device_type,
                                "device_name": f"Load Test Device {device.config.device_id}",
                                "merchant_id": device.config.merchant_id,
                                "location": "load-test-environment",
                                "capabilities": ["payment_processing", "offline_mode"],
                                "firmware_version": "1.0.0-loadtest",
                                "sdk_version": "1.0.0"
                            }
                        )

                        if response.status_code == 200:
                            data = response.json()
                            device.config.api_key = data.get("api_key", device.config.api_key)
                            await device._http_client.aclose()
                            device._http_client = httpx.AsyncClient(
                                timeout=60.0,
                                headers={
                                    "X-API-Key": device.config.api_key,
                                    "X-Device-ID": device.config.device_id,
                                    "Content-Type": "application/json",
                                }
                            )
                            logger.debug(f"Registered device {device.config.device_id}")
                            return True
                        elif response.status_code == 400 and "already registered" in response.text:
                            logger.debug(
                                f"Device {device.config.device_id} already registered (via 400)")
                            return True
                        else:
                            logger.error(
                                f"Failed to register device {device.config.device_id}: "
                                f"HTTP {response.status_code} - {response.text}"
                            )
                            return False

                except Exception as e:
                    logger.error(
                        f"Error registering device {device.config.device_id}: {e}", exc_info=True)
                    return False

        # Register all devices in parallel
        results = await asyncio.gather(*[
            register_single_device(device) for device in self._devices
        ])

        successful = sum(1 for r in results if r)
        logger.info(
            f"Registered {successful}/{len(self._devices)} devices successfully")

        if successful < len(self._devices):
            logger.warning(
                f"{len(self._devices) - successful} devices failed to register")

    async def _cleanup_devices(self):
        """Clean up existing load test devices."""
        import httpx
        import os

        registration_key = os.getenv(
            "RUFUS_REGISTRATION_KEY", "demo-registration-key-2024")

        concurrency = int(os.getenv("LOAD_TEST_SETUP_CONCURRENCY", "50"))
        semaphore = asyncio.Semaphore(concurrency)

        async def delete_single_device(device):
            """Delete a single device if it exists."""
            async with semaphore:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.delete(
                            f"{self.cloud_url}/api/v1/devices/{device.config.device_id}",
                            headers={"X-Registration-Key": registration_key}
                        )

                        if response.status_code == 200:
                            logger.debug(f"Deleted existing device {device.config.device_id}")
                            return True
                        elif response.status_code == 404:
                            logger.debug(f"Device {device.config.device_id} not found (already clean)")
                            return True
                        else:
                            logger.warning(
                                f"Failed to delete device {device.config.device_id}: "
                                f"HTTP {response.status_code}"
                            )
                            return False

                except Exception as e:
                    logger.debug(
                        f"Error deleting device {device.config.device_id}: {e}", exc_info=True)
                    return False

        # Delete all devices in parallel
        results = await asyncio.gather(*[
            delete_single_device(device) for device in self._devices
        ])

        cleaned = sum(1 for r in results if r)
        logger.info(f"Cleaned up {cleaned}/{len(self._devices)} devices")

    async def _report_progress(self, callback: callable, duration_seconds: int):
        """Report progress periodically."""
        start_time = time.time()
        report_interval = 10  # Report every 10 seconds

        while time.time() - start_time < duration_seconds:
            await asyncio.sleep(report_interval)

            elapsed = time.time() - start_time
            progress_pct = (elapsed / duration_seconds) * 100

            # Calculate current metrics
            async with self._metrics_lock:
                total_requests = sum(
                    m.total_requests for m in self._aggregated_metrics.values()
                )
                total_errors = sum(
                    m.total_errors for m in self._aggregated_metrics.values()
                )

            callback({
                "elapsed_seconds": elapsed,
                "progress_percent": progress_pct,
                "total_requests": total_requests,
                "total_errors": total_errors,
                "requests_per_second": total_requests / elapsed if elapsed > 0 else 0,
            })

    def export_results(self, results: LoadTestResults, output_file: str):
        """
        Export results to JSON file.

        Args:
            results: LoadTestResults to export
            output_file: Path to output JSON file
        """
        with open(output_file, 'w') as f:
            json.dump(results.to_dict(), f, indent=2)

        logger.info(f"Results exported to {output_file}")


class ScenarioRunner:
    """Helper class for running predefined test scenarios."""

    @staticmethod
    async def run_heartbeat_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 1000,
        duration_seconds: int = 600
    ) -> LoadTestResults:
        """Run Scenario 1: Concurrent Device Heartbeats."""
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="heartbeat",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_saf_sync_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 500
    ) -> LoadTestResults:
        """Run Scenario 2: Store-and-Forward Bulk Sync."""
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="saf_sync",
            duration_seconds=300,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_config_poll_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 1000,
        duration_seconds: int = 600
    ) -> LoadTestResults:
        """Run Scenario 3: Config Rollout."""
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="config_poll",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_model_update_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 1000
    ) -> LoadTestResults:
        """Run Scenario 4: Model Distribution."""
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="model_update",
            duration_seconds=300,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_cloud_commands_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 1000,
        duration_seconds: int = 600
    ) -> LoadTestResults:
        """Run Scenario 5: Cloud Command Distribution."""
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="cloud_commands",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_workflow_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 300
    ) -> LoadTestResults:
        """Run Scenario 6: Concurrent Workflow Execution."""
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="workflow_execution",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )
