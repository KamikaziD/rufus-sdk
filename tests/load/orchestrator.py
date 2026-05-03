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

try:
    from tests.load.device_simulator import SimulatedEdgeDevice, DeviceConfig, DeviceMetrics
except ModuleNotFoundError:
    from device_simulator import SimulatedEdgeDevice, DeviceConfig, DeviceMetrics  # type: ignore[no-redef]

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

    # WASM step execution metrics (wasm_steps scenario)
    wasm_steps_executed: int = 0
    wasm_step_failures: int = 0
    wasm_execution_latencies: List[float] = field(default_factory=list)
    # RUVON capability gossip metrics
    gossip_broadcasts: int = 0
    gossip_failures: int = 0
    gossip_broadcast_latencies: List[float] = field(default_factory=list)
    # NKey patch verification metrics
    nkey_verifications: int = 0
    nkey_failures: int = 0
    nkey_verify_latencies: List[float] = field(default_factory=list)
    # Election stability metrics
    elections_run: int = 0
    election_latencies: List[float] = field(default_factory=list)
    leader_tenure_samples: List[float] = field(default_factory=list)
    flap_count: int = 0
    # Payload variance metrics (keyed by size label)
    payload_latencies: Dict[str, List[float]] = field(default_factory=dict)
    # E2E decision pipeline metrics
    e2e_decision_latencies: List[float] = field(default_factory=list)
    e2e_consensus_latencies: List[float] = field(default_factory=list)
    e2e_ack_count: int = 0

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
        idx = int(p * (len(s) - 1))
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
        if self.wasm_steps_executed > 0 or self.wasm_step_failures > 0:
            d["wasm_steps_executed"] = self.wasm_steps_executed
            d["wasm_step_failures"] = self.wasm_step_failures
            total_wasm = self.wasm_steps_executed + self.wasm_step_failures
            d["wasm_step_success_rate"] = (
                f"{self.wasm_steps_executed / total_wasm * 100:.2f}%"
                if total_wasm else "N/A"
            )
            if self.wasm_execution_latencies:
                wl = sorted(self.wasm_execution_latencies)
                idx_p50 = int(0.50 * (len(wl) - 1))
                idx_p95 = int(0.95 * (len(wl) - 1))
                idx_p99 = int(0.99 * (len(wl) - 1))
                d["wasm_exec_p50_ms"] = f"{wl[idx_p50] * 1000:.1f}"
                d["wasm_exec_p95_ms"] = f"{wl[idx_p95] * 1000:.1f}"
                d["wasm_exec_p99_ms"] = f"{wl[idx_p99] * 1000:.1f}"
        if self.gossip_broadcasts > 0 or self.gossip_failures > 0:
            total_gossip = self.gossip_broadcasts + self.gossip_failures
            d["gossip_broadcasts"] = self.gossip_broadcasts
            d["gossip_failures"] = self.gossip_failures
            d["gossip_success_rate"] = (
                f"{self.gossip_broadcasts / total_gossip * 100:.2f}%" if total_gossip else "N/A"
            )
            if self.gossip_broadcast_latencies:
                gl = sorted(self.gossip_broadcast_latencies)
                d["gossip_p95_ms"] = f"{gl[int(0.95 * (len(gl) - 1))] * 1000:.2f}"
                d["gossip_p99_ms"] = f"{gl[int(0.99 * (len(gl) - 1))] * 1000:.2f}"
        if self.nkey_verifications > 0 or self.nkey_failures > 0:
            total_nkey = self.nkey_verifications + self.nkey_failures
            d["nkey_verifications"] = self.nkey_verifications
            d["nkey_failures"] = self.nkey_failures
            d["nkey_success_rate"] = (
                f"{self.nkey_verifications / total_nkey * 100:.2f}%" if total_nkey else "N/A"
            )
            if self.nkey_verify_latencies:
                nl = sorted(self.nkey_verify_latencies)
                d["nkey_verify_p95_ms"] = f"{nl[int(0.95 * (len(nl) - 1))] * 1000:.2f}"
                d["nkey_verify_p99_ms"] = f"{nl[int(0.99 * (len(nl) - 1))] * 1000:.2f}"
        if self.elections_run > 0:
            d["elections_run"] = self.elections_run
            d["flap_count"] = self.flap_count
            if self.election_latencies:
                el = sorted(self.election_latencies)
                d["election_p95_ms"] = f"{el[int(0.95 * (len(el) - 1))] * 1000:.2f}"
                d["election_p99_ms"] = f"{el[int(0.99 * (len(el) - 1))] * 1000:.2f}"
            if self.leader_tenure_samples:
                ts = sorted(self.leader_tenure_samples)
                d["tenure_p50_s"] = f"{ts[int(0.50 * (len(ts) - 1))]:.1f}"
                d["tenure_p95_s"] = f"{ts[int(0.95 * (len(ts) - 1))]:.1f}"
        if self.payload_latencies:
            d["payload_latencies"] = {}
            for label, lats in sorted(self.payload_latencies.items()):
                sl = sorted(lats)
                d["payload_latencies"][label] = {
                    "p95_ms": f"{sl[int(0.95 * (len(sl) - 1))] * 1000:.2f}",
                    "p99_ms": f"{sl[int(0.99 * (len(sl) - 1))] * 1000:.2f}",
                    "samples": len(sl),
                }
        if self.e2e_decision_latencies:
            el = sorted(self.e2e_decision_latencies)
            d["e2e_decision_p50_ms"] = f"{el[int(0.50 * (len(el) - 1))] * 1000:.1f}"
            d["e2e_decision_p99_ms"] = f"{el[int(0.99 * (len(el) - 1))] * 1000:.1f}"
            d["e2e_ack_count"] = self.e2e_ack_count
        if self.e2e_consensus_latencies:
            cl = sorted(self.e2e_consensus_latencies)
            d["e2e_consensus_p50_ms"] = f"{cl[int(0.50 * (len(cl) - 1))] * 1000:.1f}"
            d["e2e_consensus_p99_ms"] = f"{cl[int(0.99 * (len(cl) - 1))] * 1000:.1f}"
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
        self._devices_registered: bool = False  # True only after _register_devices()

    async def setup_devices(
        self,
        num_devices: int,
        cleanup_first: bool = True,
        register_with_server: bool = True,
    ):
        """
        Setup devices for load testing (shared across scenarios).

        Args:
            num_devices: Number of devices to create
            cleanup_first: Whether to cleanup existing devices before setup
            register_with_server: Whether to register devices with the control plane.
                Set False for local-only scenarios (wasm_thundering_herd) to skip
                the N registration + N cleanup HTTP round-trips entirely.
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

        if register_with_server:
            # Clean up any existing load test devices (if requested)
            if cleanup_first:
                logger.info(f"Cleaning up existing load test devices...")
                await self._cleanup_devices()

            # Register devices with control plane (idempotent)
            logger.info(f"Registering {num_devices} devices with control plane...")
            await self._register_devices(idempotent=True)
            self._devices_registered = True
        else:
            logger.info(
                f"Skipping server registration for {num_devices} devices "
                f"(local-only scenario — no HTTP calls will be made)."
            )
            self._devices_registered = False

        logger.info(f"Device setup complete: {num_devices} devices ready")

    async def teardown_devices(self):
        """Teardown devices after all scenarios complete."""
        logger.info("Tearing down devices...")

        # Close HTTP clients (only those that were lazily created)
        if self._devices:
            await asyncio.gather(*[device.close() for device in self._devices])

        # Only hit the server if we actually registered devices there
        if self._devices_registered:
            logger.info("Cleaning up devices from server...")
            await self._cleanup_devices()
        else:
            logger.info("Skipping server cleanup — devices were never registered.")

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
            # Single scenario mode — skip server registration for local-only scenarios
            _local_only = scenario in ("wasm_thundering_herd", "nats_transport", "ruvon_gossip", "nkey_patch")
            await self.setup_devices(
                num_devices,
                cleanup_first=True,
                register_with_server=not _local_only,
            )

        # Reset per-device metrics so each scenario gets a clean slate.
        # DeviceMetrics accumulates across calls otherwise, making scenario N
        # include all data from scenarios 1…N-1.
        for device in self._devices:
            device.metrics.reset()
        self._aggregated_metrics.clear()

        # Start timer
        start_time = time.time()

        # For thundering herd: attach a shared asyncio.Event to every device.
        # Devices prepare their payload then block on the event; the orchestrator
        # releases all of them at once after a short prep window.
        go_event = None
        if scenario in ("thundering_herd", "wasm_thundering_herd"):
            go_event = asyncio.Event()
            for device in self._devices:
                device._go_event = go_event

        # For wasm_thundering_herd: build ONE shared runtime, warm it up once,
        # then inject it into every device so they skip per-device _setup_wasm_runtime()
        # and the N redundant warmup resolve calls.
        # At 100k devices this avoids creating 100k identical resolver/bridge/runtime
        # objects and eliminates 100k sequential SQLite-style resolve coroutines.
        if scenario == "wasm_thundering_herd" and self._devices:
            probe = self._devices[0]
            probe._setup_wasm_runtime()
            if probe._wasm_runtime is not None:
                # Warm the shared resolver once
                try:
                    await probe._wasm_runtime._resolver.resolve(probe._wasm_hash)
                except Exception:
                    pass
                shared_runtime = probe._wasm_runtime
                shared_config = probe._wasm_config
                shared_hash = probe._wasm_hash
                logger.info(
                    f"Shared WASM runtime ready (hash={shared_hash[:16]}…). "
                    f"Injecting into {len(self._devices):,} devices — "
                    f"skipping {len(self._devices):,} per-device warmup resolves."
                )
                for device in self._devices[1:]:
                    device._wasm_runtime = shared_runtime
                    device._wasm_config = shared_config
                    device._wasm_hash = shared_hash

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
            if scenario == "wasm_thundering_herd":
                logger.info(
                    f"WASM thundering herd prep window: {prep_seconds}s "
                    f"(devices warming WASM resolver...)"
                )
            else:
                logger.info(
                    f"Thundering herd prep window: {prep_seconds}s "
                    f"(devices generating transactions...)"
                )
            await asyncio.sleep(prep_seconds)
            if scenario == "wasm_thundering_herd":
                logger.info(
                    f"WASM THUNDERING HERD: Releasing {num_devices} simultaneous "
                    f"local WASM dispatches NOW (target: >= 0.8 steps/device/sec)"
                )
            else:
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
                results.wasm_steps_executed += metrics.wasm_steps_executed
                results.wasm_step_failures += metrics.wasm_step_failures
                results.wasm_execution_latencies.extend(metrics.wasm_execution_latencies)
                results.gossip_broadcasts += metrics.gossip_broadcasts
                results.gossip_failures += metrics.gossip_failures
                results.gossip_broadcast_latencies.extend(metrics.gossip_broadcast_latencies)
                results.nkey_verifications += metrics.nkey_verifications
                results.nkey_failures += metrics.nkey_failures
                results.nkey_verify_latencies.extend(metrics.nkey_verify_latencies)
                results.elections_run += metrics.elections_run
                results.election_latencies.extend(metrics.election_latencies)
                results.leader_tenure_samples.extend(metrics.leader_tenure_samples)
                results.flap_count += metrics.flap_count
                for label, lats in metrics.payload_latencies.items():
                    results.payload_latencies.setdefault(label, []).extend(lats)
                results.e2e_decision_latencies.extend(metrics.e2e_decision_latencies)
                results.e2e_consensus_latencies.extend(metrics.e2e_consensus_latencies)
                results.e2e_ack_count += metrics.e2e_ack_count

    async def _register_devices(self, idempotent: bool = True):
        """
        Register all devices with the control plane.

        Args:
            idempotent: If True, check if device exists before registering
        """
        import httpx
        import os

        registration_key = os.getenv(
            "RUVON_REGISTRATION_KEY", "demo-registration-key-2024")

        # Limit concurrent registrations to avoid exhausting the server's DB pool.
        # Default: 50 concurrent (matches server pool max_size default).
        concurrency = int(os.getenv("LOAD_TEST_SETUP_CONCURRENCY", "50"))
        semaphore = asyncio.Semaphore(concurrency)

        async def register_single_device(device):
            """Register a single device (idempotent)."""
            async with semaphore:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        # For idempotent mode: delete any pre-existing device so we always
                        # get a fresh API key back from registration (the GET endpoint never
                        # returns api_key, so re-use without deletion = 401 on SAF sync).
                        if idempotent:
                            check_response = await client.get(
                                f"{self.cloud_url}/api/v1/devices/{device.config.device_id}",
                                headers={"X-Registration-Key": registration_key}
                            )

                            if check_response.status_code == 200:
                                # Delete so re-registration returns a known key
                                await client.delete(
                                    f"{self.cloud_url}/api/v1/devices/{device.config.device_id}",
                                    headers={"X-Registration-Key": registration_key}
                                )
                                logger.debug(
                                    f"Device {device.config.device_id} existed — deleted for fresh key"
                                )

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
                            if device._http_client:
                                await device._http_client.aclose()
                            device._http_client = None  # Recreate lazily with new api_key
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
            "RUVON_REGISTRATION_KEY", "demo-registration-key-2024")

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
    async def run_wasm_steps_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 300,
    ) -> LoadTestResults:
        """Run Scenario 6: WASM Step Execution Throughput.

        Measures:
        - Cloud: sync_wasm command delivery via heartbeat
        - Edge:  simulated WASM step execution latency distribution
        """
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="wasm_steps",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_wasm_thundering_herd_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 1000,
    ) -> LoadTestResults:
        """Run WASM Thundering Herd: coordinated burst of local WASM dispatches.

        All devices fire simultaneously (go_event barrier) — no HTTP, no DB write.
        Pass criterion: success rate >= 99% + >= 0.8 steps/device/sec (scale-invariant).
        p99 latency reflects asyncio scheduler backlog, not WASM exec time — it grows
        with device count and is reported as informational context only.
        """
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="wasm_thundering_herd",
            duration_seconds=60,  # Single burst — duration is just the timeout guard
            skip_device_setup=True,
        )


    @staticmethod
    async def run_nats_transport_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run NATS transport scenario: devices publish heartbeats directly to JetStream.

        Measures JetStream publish ack latency (scale-aware p99 target:
        <10ms @<=100 devices, <25ms @<=1k, <50ms @<=10k, <150ms beyond).
        No HTTP calls, no server registration — pure NATS publish path.
        Requires RUVON_NATS_URL or NATS_URL env var.
        """
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=False,
            register_with_server=False,
        )
        return await orchestrator.run_scenario(
            scenario="nats_transport",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_ruvon_gossip_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run RUVON capability gossip scenario: local serialise/deserialise + peer selection.

        Pure-local — no HTTP, no server registration required.
        Pass criteria (enforced in device_simulator):
        - Broadcast serialise+encode p95 < 1 ms
        - find_best_builder() on ≤100 peers p95 < 5 ms
        - Error rate < 1%
        """
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=False,
            register_with_server=False,
        )
        return await orchestrator.run_scenario(
            scenario="ruvon_gossip",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_nkey_patch_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run NKey Ed25519 patch verification scenario.

        Pure-local — no HTTP, no server registration required.
        Devices continuously verify WASM patches (95% valid, 5% bad signature).
        Pass criteria (enforced in device_simulator):
        - verify() p95 < 5 ms per verification
        - Error rate on valid signatures < 0.1%
        - Rejection rate on bad signatures > 99.9%
        """
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=False,
            register_with_server=False,
        )
        return await orchestrator.run_scenario(
            scenario="nkey_patch",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_mixed_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 500,
        duration_seconds: int = 300,
    ) -> LoadTestResults:
        """Run mixed workload: heartbeat + gossip + SAF sync simultaneously on every device.

        Exercises interference between all three subsystems under concurrent load.
        Requires server registration (HTTP).
        Pass criteria: SAF p99 < 500ms, gossip error rate < 1%, heartbeat error rate = 0%.
        """
        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="mixed",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_election_stability_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run leader election stability scenario: local-only score + re-election loop.

        Measures elections/min, p95 election latency, tenure distribution, and flap rate.
        Pure-local — no HTTP, no server registration required.
        Pass criteria: elections/min < 5, p95 election latency < 1ms, flap_count = 0.
        """
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=False,
            register_with_server=False,
        )
        return await orchestrator.run_scenario(
            scenario="election_stability",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_payload_variance_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run gossip payload-variance scenario: encode+decode at 256B/1KB/4KB/16KB/64KB.

        Pure-local — no HTTP, no server registration required.
        Pass criteria: p95 encode+decode < 50ms even at 64KB.
        """
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=False,
            register_with_server=False,
        )
        return await orchestrator.run_scenario(
            scenario="payload_variance",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_e2e_decision_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 100,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run end-to-end decision pipeline: telemetry → score → sign → gossip → acks.

        Simulates full pit-wall sovereign decision path without HTTP/NATS calls.
        Pure-local — no HTTP, no server registration required.
        Pass criteria: p50 < 50ms, p99 < 200ms end-to-end decision-to-consensus.
        """
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=False,
            register_with_server=False,
        )
        return await orchestrator.run_scenario(
            scenario="e2e_decision",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )

    @staticmethod
    async def run_msgspec_codec_test(
        orchestrator: LoadTestOrchestrator,
        num_devices: int = 500,
        duration_seconds: int = 120,
    ) -> LoadTestResults:
        """Run msgspec codec variant: heartbeat load with msgspec serialization path.

        Identical to the heartbeat scenario but validates that the msgspec encode/decode
        path is live before starting. Use this to confirm throughput numbers after the
        msgspec DTO migration — compare req/s against the baseline heartbeat run.
        """
        try:
            import msgspec as _ms
            from ruvon.providers.dtos import WorkflowRecord
            _sample = WorkflowRecord(
                id="preflight",
                workflow_type="T",
                status="ACTIVE",
                current_step=0,
                state={},
                steps_config=[],
                state_model_path="t.S",
            )
            _ms.json.decode(_ms.json.encode(_sample), type=WorkflowRecord)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"[msgspec_codec_test] preflight failed ({exc}), running heartbeat path anyway"
            )

        await orchestrator.setup_devices(num_devices)
        return await orchestrator.run_scenario(
            scenario="heartbeat",
            duration_seconds=duration_seconds,
            skip_device_setup=True,
        )
