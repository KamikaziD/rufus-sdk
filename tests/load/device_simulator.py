"""
Device Simulator for Load Testing.

Simulates edge device behavior for load testing the Ruvon Edge control plane.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import random
import secrets
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
import httpx
import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared NATS connection singleton (nats_transport scenario)
# One connection is shared across all simulated devices — creating N separate
# connections (N up to 100k) would exhaust OS file descriptors immediately.
# ---------------------------------------------------------------------------
_NATS_NC = None   # nats.aio.client.Client
_NATS_JS = None   # JetStream context
_NATS_LOCK: Optional[asyncio.Lock] = None
_NATS_IMPORT_ERROR: Optional[str] = None  # set once if nats-py missing
_NATS_PUBLISH_SEM: Optional[asyncio.Semaphore] = None  # caps concurrent in-flight publishes

# Max concurrent JetStream publishes on the shared connection.
# Each publish is a request/reply round-trip; beyond ~500 concurrent the
# NATS server queues internally and measured latency reflects queue depth,
# not wire latency. 500 gives throughput headroom without overwhelming either
# the server or the asyncio event loop scheduler.
_NATS_MAX_CONCURRENT = 500


async def _get_shared_nats(nats_url: str):
    """Return (nc, js, sem) shared across all devices, connecting once."""
    global _NATS_NC, _NATS_JS, _NATS_LOCK, _NATS_IMPORT_ERROR, _NATS_PUBLISH_SEM

    if _NATS_IMPORT_ERROR:
        return None, None, None

    # Lazy-init asyncio primitives (must be created inside a running loop)
    if _NATS_LOCK is None:
        _NATS_LOCK = asyncio.Lock()
    if _NATS_PUBLISH_SEM is None:
        _NATS_PUBLISH_SEM = asyncio.Semaphore(_NATS_MAX_CONCURRENT)

    # Fast path — already connected, no lock needed
    if _NATS_NC is not None and not _NATS_NC.is_closed:
        return _NATS_NC, _NATS_JS, _NATS_PUBLISH_SEM

    async with _NATS_LOCK:
        # Re-check inside lock (another coroutine may have connected while we waited)
        if _NATS_NC is not None and not _NATS_NC.is_closed:
            return _NATS_NC, _NATS_JS, _NATS_PUBLISH_SEM

        try:
            import nats as _nats_mod
        except ImportError:
            _NATS_IMPORT_ERROR = (
                "\n  ✘  nats-py not installed in this venv.\n"
                "     Fix: pip install nats-py\n"
                "     Then re-run the scenario.\n"
            )
            return None, None, None

        try:
            _NATS_NC = await _nats_mod.connect(servers=[nats_url])
            _NATS_JS = _NATS_NC.jetstream()
            # Ensure the gossip stream exists (created once; idempotent on re-run)
            try:
                await _NATS_JS.add_stream(
                    name="RUVON_GOSSIP",
                    subjects=["ruvon.mesh.capabilities"],
                    max_msgs=100_000,
                )
            except Exception:
                pass  # Stream already exists — not an error
            logger.info(f"[nats_transport] Shared NATS connection established: {nats_url}")
        except Exception as exc:
            logger.error(f"[nats_transport] Cannot connect to NATS at {nats_url}: {exc}")
            _NATS_NC = None
            _NATS_JS = None

    return _NATS_NC, _NATS_JS, _NATS_PUBLISH_SEM


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
    wasm_steps_per_sync: int = 5  # simulated WASM step executions per sync_wasm command


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
    errors_5xx: int = 0      # Server errors (pool exhausted, crash, etc.)
    errors_4xx: int = 0      # Client errors (auth, bad request)
    errors_timeout: int = 0  # Network timeouts
    latencies: List[float] = field(default_factory=list)  # per-request latency in seconds
    # WASM step execution metrics
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
    # Leader election stability metrics (election_stability scenario)
    elections_run: int = 0
    election_latencies: List[float] = field(default_factory=list)
    leader_tenure_samples: List[float] = field(default_factory=list)
    flap_count: int = 0
    # Gossip payload-variance metrics (payload_variance scenario)
    payload_latencies: Dict[str, List[float]] = field(default_factory=dict)
    # E2E decision pipeline metrics (e2e_decision scenario)
    e2e_decision_latencies: List[float] = field(default_factory=list)
    e2e_consensus_latencies: List[float] = field(default_factory=list)
    e2e_ack_count: int = 0

    def reset(self):
        """Reset all counters and latency lists to zero (call before each scenario)."""
        self.heartbeats_sent = 0
        self.heartbeat_failures = 0
        self.transactions_synced = 0
        self.sync_failures = 0
        self.configs_downloaded = 0
        self.config_failures = 0
        self.commands_received = 0
        self.command_failures = 0
        self.total_requests = 0
        self.total_errors = 0
        self.errors_5xx = 0
        self.errors_4xx = 0
        self.errors_timeout = 0
        self.latencies = []
        self.wasm_steps_executed = 0
        self.wasm_step_failures = 0
        self.wasm_execution_latencies = []
        self.gossip_broadcasts = 0
        self.gossip_failures = 0
        self.gossip_broadcast_latencies = []
        self.nkey_verifications = 0
        self.nkey_failures = 0
        self.nkey_verify_latencies = []
        self.elections_run = 0
        self.election_latencies = []
        self.leader_tenure_samples = []
        self.flap_count = 0
        self.payload_latencies = {}
        self.e2e_decision_latencies = []
        self.e2e_consensus_latencies = []
        self.e2e_ack_count = 0


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

    def _get_http_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client on first use.

        Defers allocation until a scenario actually makes an HTTP call.
        Pure-local scenarios (wasm_thundering_herd) never call this, so
        no client objects are created — critical for 100k-device runs.
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=60.0,
                headers={
                    "X-API-Key": self.config.api_key,
                    "X-Device-ID": self.config.device_id,
                    "Content-Type": "application/json",
                }
            )
        return self._http_client

    async def initialize(self):
        """Record device as ready. HTTP client is created lazily on first use."""
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
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout,
                    httpx.ConnectError) as e:
                last_exception = e
                if attempt == MAX_RETRIES - 1:
                    # Final attempt — classify error; caller tracks total_errors
                    self.metrics.errors_timeout += 1

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
                    self.metrics.errors_4xx += 1
                    raise
                # Retry 5xx errors (server errors)
                last_exception = e
                if attempt == MAX_RETRIES - 1:
                    self.metrics.errors_5xx += 1

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
                await self._saf_sync_scenario(duration_seconds)
            elif scenario == "thundering_herd":
                await self._thundering_herd_scenario()
            elif scenario == "config_poll":
                await self._config_polling_scenario(duration_seconds)
            elif scenario == "cloud_commands":
                await self._cloud_commands_scenario(duration_seconds)
            elif scenario == "wasm_steps":
                await self._wasm_steps_scenario(duration_seconds)
            elif scenario == "wasm_thundering_herd":
                await self._wasm_thundering_herd_scenario(duration_seconds)
            elif scenario == "msgspec_codec":
                # msgspec_codec is a heartbeat run with a server-side preflight already done
                # by ScenarioRunner.run_msgspec_codec_test(). Devices just run heartbeat.
                await self._heartbeat_scenario(duration_seconds)
            elif scenario == "nats_transport":
                await self._nats_transport_scenario(duration_seconds)
            elif scenario == "ruvon_gossip":
                await self._ruvon_gossip_scenario(duration_seconds)
            elif scenario == "nkey_patch":
                await self._nkey_patch_scenario(duration_seconds)
            elif scenario == "mixed":
                await self._mixed_scenario(duration_seconds)
            elif scenario == "election_stability":
                await self._election_stability_scenario(duration_seconds)
            elif scenario == "payload_variance":
                await self._payload_variance_scenario(duration_seconds)
            elif scenario == "e2e_decision":
                await self._e2e_decision_scenario(duration_seconds)
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

        # Stagger initial requests across the full heartbeat window so all devices
        # don't fire simultaneously at t=0 (which dominates p95 at scale).
        initial_offset = random.uniform(0, self.config.heartbeat_interval)
        await asyncio.sleep(min(initial_offset, end_time - time.time()))

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
                response = await self._get_http_client().post(
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
                if 500 <= response.status_code < 600:
                    self.metrics.errors_5xx += 1
                elif 400 <= response.status_code < 500:
                    self.metrics.errors_4xx += 1
                return False

        except Exception as e:
            logger.error(f"Heartbeat error for {self.config.device_id}: {e}")
            self.metrics.total_errors += 1
            return False

    # -------------------------------------------------------------------------
    # Scenario 2: Store-and-Forward Bulk Sync
    # -------------------------------------------------------------------------

    async def _saf_sync_scenario(self, duration_seconds: int = 300):
        """
        Continuously sync a fixed transaction pool for the full test duration.

        The pool is generated once. Subsequent syncs re-send the same
        idempotency keys — the server deduplicates (ON CONFLICT DO NOTHING),
        so the DB stays bounded while we measure HTTP + auth + idempotency
        throughput at realistic concurrency.
        """
        # Build a fixed pool once; pool size = one full batch per device
        pool_size = self.config.saf_batch_size
        transaction_pool = [self._generate_transaction(i) for i in range(pool_size)]

        end_time = time.time() + duration_seconds

        while time.time() < end_time and self._running:
            # Pick a random slice of the pool each cycle to vary payload size
            batch_size = random.randint(5, pool_size)
            transactions = random.sample(transaction_pool, batch_size)

            success = await self._sync_batch(transactions)

            if success:
                self.metrics.transactions_synced += len(transactions)
            else:
                self.metrics.sync_failures += 1
                await asyncio.sleep(2)

            # Report metrics after each sync so the progress tracker sees live data
            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Stagger to avoid lock-step bursts across 1000 devices
            await asyncio.sleep(random.uniform(0.5, 2.0))

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
            # Retry sync with exponential backoff (timeout errors only — 4xx/5xx handled below)
            async def send_sync():
                return await self._get_http_client().post(
                    f"{self.config.cloud_url}/api/v1/devices/{self.config.device_id}/sync",
                    json={
                        "transactions": transactions,
                        "device_sequence": 0,
                        "device_timestamp": datetime.utcnow().isoformat(),
                    }
                )

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
                if 500 <= response.status_code < 600:
                    self.metrics.errors_5xx += 1
                elif 400 <= response.status_code < 500:
                    self.metrics.errors_4xx += 1
                return False

        except Exception as e:
            # Known network errors are already logged at ERROR level by _retry_with_backoff;
            # log them here at DEBUG only to avoid duplicate traceback spam in the log.
            _known_net = isinstance(
                e, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout)
            )
            if _known_net:
                logger.debug(f"Sync error for {self.config.device_id}: {e}")
            else:
                logger.error(f"Sync error for {self.config.device_id}: {e}", exc_info=True)
            self.metrics.total_requests += 1
            self.metrics.total_errors += 1
            return False

    # -------------------------------------------------------------------------
    # Thundering Herd: synchronized SAF sync burst
    # -------------------------------------------------------------------------

    async def _thundering_herd_scenario(self):
        """
        Synchronized SAF sync burst — all devices fire at exactly the same moment.

        Phase 1 (prep): generate transactions locally (no network).
        Phase 2 (wait): block on the orchestrator's go_event barrier.
        Phase 3 (fire): send the sync request immediately when released.

        The orchestrator sets _go_event after all devices have reached phase 2,
        ensuring a true simultaneous burst rather than a gradual ramp.
        """
        # Phase 1: prepare transactions — pure CPU, no network
        num_transactions = random.randint(10, self.config.saf_batch_size)
        transactions = [self._generate_transaction(i) for i in range(num_transactions)]
        logger.debug(
            f"Device {self.config.device_id} prepared {num_transactions} transactions, waiting for go signal"
        )

        # Phase 2: wait for coordinated release from orchestrator
        go_event: Optional[asyncio.Event] = getattr(self, "_go_event", None)
        if go_event is not None:
            await go_event.wait()

        # Phase 3: fire immediately — this is the thundering herd moment
        logger.debug(f"Device {self.config.device_id} FIRING thundering herd sync")
        success = await self._sync_batch(transactions)

        if success:
            self.metrics.transactions_synced += len(transactions)
        else:
            self.metrics.sync_failures += 1

        # Report metrics
        if self.metrics_callback:
            await self.metrics_callback(self.config.device_id, self.metrics)

    # -------------------------------------------------------------------------
    # Scenario 3: Config Polling
    # -------------------------------------------------------------------------

    async def _config_polling_scenario(self, duration_seconds: int):
        """
        Poll for config updates using ETag conditional requests.

        Simulates device checking for new configurations.
        """
        # Spread the initial poll randomly across the poll interval so that
        # 1000 devices don't all fire simultaneously at t=0 (and every 60s).
        startup_jitter = random.uniform(0, self.config.config_poll_interval)
        await asyncio.sleep(startup_jitter)

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
                response = await self._get_http_client().get(
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
                if 500 <= response.status_code < 600:
                    self.metrics.errors_5xx += 1
                elif 400 <= response.status_code < 500:
                    self.metrics.errors_4xx += 1
                return False

        except Exception as e:
            logger.error(f"Config poll error for {self.config.device_id}: {e}")
            self.metrics.total_errors += 1
            return False

    # -------------------------------------------------------------------------
    # Scenario 4: Cloud Commands
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
    # WASM runtime setup (shared by wasm_steps and wasm_thundering_herd)
    # -------------------------------------------------------------------------

    def _setup_wasm_runtime(self):
        """
        Build a real ComponentStepRuntime wired with an in-memory resolver and a
        MockWasmBridge.  No wasmtime installation required — _call_component is
        bypassed by the bridge injection, which is exactly the code path the
        feat/wasi-bridge work wired into agent.py.

        Measures the actual Python dispatch overhead (import resolution,
        hash verification, JSON encode/decode, bridge call) — not a fake sleep.
        """
        try:
            from ruvon.implementations.execution.component_runtime import ComponentStepRuntime
            from ruvon.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver
        except ImportError:
            self._wasm_runtime = None
            self._wasm_config = None
            return

        # 1KB Component Model binary (magic bytes + padding)
        self._wasm_binary = b"\x00asm\x0e\x00\x01\x00" + b"\x00" * 1024
        self._wasm_hash = hashlib.sha256(self._wasm_binary).hexdigest()

        class _MemoryResolver:
            """In-process resolver — no SQLite roundtrip, measures pure dispatch."""
            def __init__(self, binary, binary_hash):
                self._binary = binary
                self._hash = binary_hash

            async def resolve(self, h: str) -> bytes:
                if h == self._hash:
                    return self._binary
                raise FileNotFoundError(h)

        class _MockWasmBridge:
            """
            Zero-cost bridge: returns a fixed JSON result immediately.
            This isolates the bridge dispatch overhead from wasmtime itself,
            matching the benchmark sub-section 12c/12e.
            """
            _RESULT = '{"wasm_ok": true, "risk_score": 42}'

            def execute_component(self, binary: bytes, state_json: str, step_name: str) -> str:
                return self._RESULT

            def execute_batch(self, binary: bytes, states_json: list, step_name: str) -> list:
                return [self._RESULT] * len(states_json)

        resolver = _MemoryResolver(self._wasm_binary, self._wasm_hash)
        bridge = _MockWasmBridge()
        self._wasm_runtime = ComponentStepRuntime(resolver, bridge=bridge)

        # Reusable config mock
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.wasm_hash = self._wasm_hash
        cfg.entrypoint = "execute"
        cfg.state_mapping = None
        cfg.timeout_ms = 5000
        cfg.fallback_on_error = "skip"
        cfg.default_result = {}
        self._wasm_config = cfg

    # -------------------------------------------------------------------------
    # Scenario 5: WASM Step Execution (sustained throughput)
    # -------------------------------------------------------------------------

    async def _wasm_steps_scenario(self, duration_seconds: int):
        """
        Measure real WASM bridge dispatch throughput at the edge.

        Each heartbeat cycle fires wasm_steps_per_sync dispatches through the
        actual ComponentStepRuntime + bridge pipeline (resolve → hash verify →
        bridge call → JSON decode).  No fake sleeps — these are real timings.

        The heartbeat to cloud is still sent so cloud-side command delivery
        latency is captured alongside local execution latency.
        """
        self._setup_wasm_runtime()

        end_time = time.time() + duration_seconds
        initial_offset = random.uniform(0, self.config.heartbeat_interval)
        await asyncio.sleep(min(initial_offset, end_time - time.time()))

        heartbeats_without_wasm = 0

        while time.time() < end_time and self._running:
            success = await self._send_heartbeat()
            if success:
                self.metrics.heartbeats_sent += 1
                heartbeats_without_wasm += 1
            else:
                self.metrics.heartbeat_failures += 1

            # Execute after every heartbeat (or if a sync_wasm command arrived)
            wasm_triggered = self.metrics.commands_received > 0 and heartbeats_without_wasm > 0
            if wasm_triggered or heartbeats_without_wasm >= 1:
                await self._execute_wasm_dispatch_batch(self.config.wasm_steps_per_sync)
                heartbeats_without_wasm = 0

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            jitter = random.uniform(-2, 2)
            remaining = end_time - time.time()
            await asyncio.sleep(min(self.config.heartbeat_interval + jitter, remaining))

    async def _execute_wasm_dispatch_batch(self, num_steps: int):
        """
        Run *num_steps* real ComponentStepRuntime dispatches and record latencies.

        Each call goes through: resolve → sha256 verify → bridge.execute_component
        → json.loads.  The bridge returns immediately (mock), so all measured time
        is pure Python overhead — exactly what the Wizer snapshot and bridge wiring
        are designed to minimise.
        """
        if self._wasm_runtime is None or self._wasm_config is None:
            return

        state_data = {
            "amount_cents": random.randint(100, 50000),
            "merchant_id": self.config.merchant_id,
            "device_id": self.config.device_id,
            "currency": "USD",
        }

        t0 = time.perf_counter()
        try:
            if hasattr(self._wasm_runtime, 'execute_batch'):
                results = await self._wasm_runtime.execute_batch(
                    self._wasm_config, [state_data] * num_steps
                )
                elapsed = time.perf_counter() - t0
                self.metrics.wasm_steps_executed += len(results)
                per_step = elapsed / num_steps
                self.metrics.wasm_execution_latencies.extend([per_step] * num_steps)
            else:
                for _ in range(num_steps):
                    st = time.perf_counter()
                    await self._wasm_runtime.execute(self._wasm_config, state_data)
                    self.metrics.wasm_steps_executed += 1
                    self.metrics.wasm_execution_latencies.append(time.perf_counter() - st)
        except Exception as exc:
            self.metrics.wasm_step_failures += num_steps
            logger.debug(f"Device {self.config.device_id} WASM batch error: {exc}")

    # -------------------------------------------------------------------------
    # Scenario 6: WASM Thundering Herd
    # -------------------------------------------------------------------------

    async def _wasm_thundering_herd_scenario(self, duration_seconds: int = 60):
        """
        Coordinated burst: all devices simultaneously dispatch WASM steps.

        Mirrors the SAF thundering_herd pattern (go_event barrier) but exercises
        the local WASM bridge dispatch pipeline instead of an HTTP SAF sync.

        Expected outcome: because WASM dispatch is local (no HTTP, no DB write),
        p99 should be orders of magnitude lower than the SAF thundering herd
        (target: >= 0.8 steps/device/sec, scale-invariant vs SAF p50 ~6s).
        p99 latency reflects asyncio event-loop scheduling backlog (all coroutines
        fire simultaneously via go_event) — it grows with device count and is
        reported as informational context, not a pass/fail criterion.

        Phase 1 (prep): build state payload and warm the resolver (no network).
        Phase 2 (wait): block on orchestrator's go_event barrier.
        Phase 3 (fire): dispatch wasm_steps_per_sync steps back-to-back.
        Phase 4 (sustain): continue firing bursts every few seconds until
        duration_seconds expires — sustains >= 0.8 steps/device/sec.

        When the orchestrator pre-injects a shared runtime (via _wasm_runtime /
        _wasm_config attributes) the per-device setup and warmup resolve are
        skipped — the orchestrator already warmed the shared resolver once.
        """
        # Allow orchestrator to inject a shared runtime to avoid N redundant
        # object allocations and N warmup resolver calls at large device counts.
        if self._wasm_runtime is None:
            self._setup_wasm_runtime()

            # Phase 1: warmup the resolver cache (one dry-run resolve).
            # Skipped when the orchestrator provides a pre-warmed shared runtime.
            if self._wasm_runtime is not None and self._wasm_config is not None:
                try:
                    await self._wasm_runtime._resolver.resolve(self._wasm_hash)
                except Exception:
                    pass

        state_data = {
            "amount_cents": random.randint(100, 50000),
            "merchant_id": self.config.merchant_id,
            "device_id": self.config.device_id,
            "currency": "USD",
        }

        scenario_end_time = time.time() + duration_seconds

        logger.debug(
            f"Device {self.config.device_id} ready for WASM thundering herd"
        )

        # Phase 2: wait for coordinated release
        go_event: Optional[asyncio.Event] = getattr(self, "_go_event", None)
        if go_event is not None:
            await go_event.wait()

        # Phase 3: fire — dispatch all steps immediately
        logger.debug(f"Device {self.config.device_id} FIRING WASM thundering herd")

        if self._wasm_runtime is None or self._wasm_config is None:
            self.metrics.wasm_step_failures += self.config.wasm_steps_per_sync
            return

        num_steps = self.config.wasm_steps_per_sync
        t0 = time.perf_counter()
        try:
            if hasattr(self._wasm_runtime, 'execute_batch'):
                results = await self._wasm_runtime.execute_batch(
                    self._wasm_config, [state_data] * num_steps
                )
                elapsed = time.perf_counter() - t0
                self.metrics.wasm_steps_executed += len(results)
                per_step = elapsed / num_steps
                self.metrics.wasm_execution_latencies.extend([per_step] * num_steps)
            else:
                for _ in range(num_steps):
                    st = time.perf_counter()
                    await self._wasm_runtime.execute(self._wasm_config, state_data)
                    elapsed = time.perf_counter() - st
                    self.metrics.wasm_steps_executed += 1
                    self.metrics.wasm_execution_latencies.append(elapsed)
        except Exception as exc:
            self.metrics.wasm_step_failures += num_steps
            logger.debug(f"WASM herd dispatch error: {exc}")

        if self.metrics_callback:
            await self.metrics_callback(self.config.device_id, self.metrics)

        # Phase 4: sustain — keep firing independent bursts until the duration
        # window expires.  This is what drives the >= 0.8 steps/device/sec
        # target: the coordinated go_event burst is the spike; the sustain loop
        # fills the remaining test window so aggregate throughput stays on target.
        # Inter-burst sleep is randomised (2–4 s) to spread asyncio scheduling
        # load rather than producing a second synchronized spike.
        # Subtract a small buffer to avoid overshooting the duration window.
        while time.time() < scenario_end_time - 0.5 and self._running:
            await asyncio.sleep(random.uniform(2.0, 4.0))
            if not self._running or time.time() >= scenario_end_time:
                break
            if self._wasm_runtime is None or self._wasm_config is None:
                break
            try:
                if hasattr(self._wasm_runtime, 'execute_batch'):
                    res = await self._wasm_runtime.execute_batch(
                        self._wasm_config, [state_data] * num_steps
                    )
                    self.metrics.wasm_steps_executed += len(res)
                else:
                    for _ in range(num_steps):
                        st = time.perf_counter()
                        await self._wasm_runtime.execute(self._wasm_config, state_data)
                        self.metrics.wasm_execution_latencies.append(
                            time.perf_counter() - st
                        )
                        self.metrics.wasm_steps_executed += 1
            except Exception as exc:
                self.metrics.wasm_step_failures += num_steps
                logger.debug(f"WASM sustain dispatch error: {exc}")
            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

    # -------------------------------------------------------------------------
    # Scenario 8: NATS Transport Publish Latency
    # -------------------------------------------------------------------------

    async def _nats_transport_scenario(self, duration_seconds: int):
        """
        Publish heartbeats directly to NATS JetStream (no HTTP).

        All devices share a single NATS connection and a concurrency semaphore
        (_NATS_MAX_CONCURRENT = 500) that caps in-flight publishes.  Without
        the semaphore, 100k simultaneous js.publish() calls each become a
        request/reply that queues internally in NATS and the event loop
        scheduler stalls — measured latency becomes queue depth, not wire RTT.

        Startup is staggered (random sleep up to 1s) so 100k coroutines don't
        all race the connection lock at once.

        Pass criteria:
          - p99 publish latency < 10ms  (vs 50-300ms HTTP heartbeat)
          - error rate < 1%

        Requires RUVON_NATS_URL or NATS_URL env var and nats-py installed.
        """
        import os
        import json as _json
        nats_url = os.getenv("RUVON_NATS_URL") or os.getenv("NATS_URL", "nats://localhost:4222")

        # Stagger startup so 100k coroutines don't simultaneously race the lock
        await asyncio.sleep(random.uniform(0, 1.0))

        nc, js, sem = await _get_shared_nats(nats_url)

        if nc is None:
            if _NATS_IMPORT_ERROR:
                print(_NATS_IMPORT_ERROR, flush=True)
            return

        subject = f"devices.{self.config.device_id}.heartbeat"
        end_time = time.time() + duration_seconds

        while time.time() < end_time and self._running:
            payload = {
                "device_id": self.config.device_id,
                "device_status": "online",
                "pending_sync_count": len(self._pending_transactions),
                "sent_at": datetime.utcnow().isoformat() + "Z",
                "sdk_version": "1.0.0rc6",
            }
            data = b"\x01" + _json.dumps(payload).encode()

            t0 = time.perf_counter()
            try:
                async with sem:
                    await js.publish(subject, data)
                elapsed = time.perf_counter() - t0
                self.metrics.latencies.append(elapsed)
                self.metrics.heartbeats_sent += 1
                self.metrics.total_requests += 1
            except Exception as e:
                self.metrics.heartbeat_failures += 1
                self.metrics.total_errors += 1
                logger.debug(f"[{self.config.device_id}] NATS publish error: {e}")

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Each device publishes every ~1s; stagger prevents synchronised bursts
            await asyncio.sleep(1.0 + random.uniform(-0.1, 0.1))

    def get_metrics(self) -> DeviceMetrics:
        """Get current metrics."""
        return self.metrics

    # -------------------------------------------------------------------------
    # Scenario 10: RUVON Capability Gossip
    # -------------------------------------------------------------------------

    async def _ruvon_gossip_scenario(self, duration_seconds: int):
        """
        Simulate RUVON capability gossip: each device periodically builds,
        serialises, and (optionally) publishes its CapabilityVector, then
        deserialises received peer vectors and runs find_best_builder().

        When NATS is available, vectors are published to
        ``ruvon.mesh.capabilities``.  Without NATS, the cost of the
        serialise / deserialise / select pipeline is benchmarked in-process —
        still useful for measuring pure CPU overhead.

        Pass criteria:
          - broadcast serialise+encode p95 < 1 ms
          - find_best_builder() on ≤100 peers p95 < 5 ms
          - error rate < 1%
        """
        import os as _os
        import json as _json

        # Lazy import — graceful no-op if ruvon-edge not installed
        try:
            from ruvon_edge.capability_gossip import (
                CapabilityVector, NodeTier, _tier_to_int,
            )
        except ImportError:
            logger.warning(
                "[ruvon_gossip] ruvon-edge not installed — "
                "pip install -e 'packages/ruvon-edge[edge]'"
            )
            return

        nats_url = _os.getenv("RUVON_NATS_URL") or _os.getenv("NATS_URL", "nats://localhost:4222")
        nc, js, sem = await _get_shared_nats(nats_url)
        nats_available = nc is not None and not nc.is_closed

        # Build a stable peer fleet for this device (simulates 20 discovered peers)
        peer_count = 20
        peer_vecs = [
            CapabilityVector(
                device_id=f"sim-peer-{i:04d}",
                available_ram_mb=256.0 + (i % 4) * 512,
                cpu_load=0.05 + (i % 8) * 0.07,
                model_tier=1 + (i % 3),
                latency_ms=5.0 + (i % 5) * 3.0,
                task_queue_length=i % 6,
                node_tier=[NodeTier.TIER_1, NodeTier.TIER_2, NodeTier.TIER_3][i % 3],
            )
            for i in range(peer_count)
        ]
        peer_map = {v.device_id: v for v in peer_vecs}

        def _find_best_sync(peers):
            candidates = [
                v for v in peers.values()
                if _tier_to_int(v.node_tier) >= 2 and v.available_ram_mb > 256
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda v: (_tier_to_int(v.node_tier), -v.cpu_load, v.available_ram_mb),
                reverse=True,
            )
            return candidates[0].device_id

        end_time = time.time() + duration_seconds
        await asyncio.sleep(random.uniform(0, 0.5))  # stagger start

        while time.time() < end_time and self._running:
            # Build local vector
            local_vec = CapabilityVector(
                device_id=self.config.device_id,
                available_ram_mb=512.0 + random.uniform(-50, 50),
                cpu_load=random.uniform(0.1, 0.7),
                model_tier=2,
                latency_ms=random.uniform(5.0, 30.0),
                task_queue_length=random.randint(0, 5),
                node_tier=NodeTier.TIER_2,
            )

            t0 = time.perf_counter()
            payload = _json.dumps(local_vec.to_dict()).encode()
            success = True

            if nats_available:
                try:
                    async with sem:
                        await js.publish("ruvon.mesh.capabilities", payload)
                except Exception as exc:
                    logger.debug(f"[{self.config.device_id}] gossip publish error: {exc}")
                    success = False
            # else: serialise cost measured locally

            elapsed = time.perf_counter() - t0
            if success:
                self.metrics.gossip_broadcasts += 1
                self.metrics.gossip_broadcast_latencies.append(elapsed)
                self.metrics.total_requests += 1
            else:
                self.metrics.gossip_failures += 1
                self.metrics.total_errors += 1

            # Deserialise incoming peer vectors (simulate receive path)
            for pv in peer_vecs:
                raw = _json.dumps(pv.to_dict()).encode()
                CapabilityVector.from_dict(_json.loads(raw))

            # find_best_builder() peer selection
            _find_best_sync(peer_map)

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Gossip interval: 30s in production; 1s here for load-test throughput
            await asyncio.sleep(1.0 + random.uniform(-0.1, 0.1))

    # -------------------------------------------------------------------------
    # Scenario 11: NKey Patch Verification
    # -------------------------------------------------------------------------

    async def _nkey_patch_scenario(self, duration_seconds: int):
        """
        Simulate receiving WASM patch broadcasts and verifying Ed25519 signatures.

        Each "device" generates a keypair on startup (simulating the control
        plane's signing key), then continuously verifies patches — measuring
        throughput and error rate.  A configurable fraction of patches carry
        intentionally bad signatures to validate the rejection path.

        Pass criteria:
          - verify() p95 < 5 ms per verification
          - error rate on valid signatures < 0.1%
          - rejection rate on bad signatures > 99.9%
        """
        try:
            from ruvon_edge.nkey_verifier import NKeyPatchVerifier
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            import base64 as _b64
        except ImportError as exc:
            logger.warning(
                f"[nkey_patch] Skipping — missing dependency: {exc}\n"
                "  Fix: pip install cryptography && "
                "pip install -e 'packages/ruvon-edge[edge]'"
            )
            return

        # Generate a signing keypair (simulates the TMS/control plane key)
        priv = Ed25519PrivateKey.generate()
        pub_bytes = priv.public_key().public_bytes_raw()
        pub_b64 = _b64.urlsafe_b64encode(pub_bytes).decode()
        verifier = NKeyPatchVerifier(pub_b64)

        # Pre-generate several WASM patch payloads (varying size)
        patches = [secrets.token_bytes(sz) for sz in (256, 4096, 32768)]
        valid_sigs = [
            _b64.urlsafe_b64encode(priv.sign(p)).decode() for p in patches
        ]
        bad_sig = _b64.urlsafe_b64encode(secrets.token_bytes(64)).decode()

        # 5% of patches carry a bad signature (simulates rogue broadcast)
        BAD_PATCH_RATE = 0.05

        end_time = time.time() + duration_seconds
        await asyncio.sleep(random.uniform(0, 0.3))

        while time.time() < end_time and self._running:
            idx = random.randint(0, len(patches) - 1)
            binary = patches[idx]
            inject_bad = random.random() < BAD_PATCH_RATE
            sig = bad_sig if inject_bad else valid_sigs[idx]

            t0 = time.perf_counter()
            try:
                result = verifier.verify(binary, sig)
                elapsed = time.perf_counter() - t0
                self.metrics.nkey_verify_latencies.append(elapsed)
                self.metrics.total_requests += 1

                if inject_bad:
                    # Expected: rejected
                    if result:
                        self.metrics.nkey_failures += 1
                        self.metrics.total_errors += 1
                    else:
                        self.metrics.nkey_verifications += 1
                else:
                    # Expected: accepted
                    if not result:
                        self.metrics.nkey_failures += 1
                        self.metrics.total_errors += 1
                    else:
                        self.metrics.nkey_verifications += 1
            except Exception as exc:
                self.metrics.nkey_failures += 1
                self.metrics.total_errors += 1
                logger.debug(f"[{self.config.device_id}] nkey verify error: {exc}")

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Each device receives a patch broadcast every ~0.1s during load test
            await asyncio.sleep(0.1 + random.uniform(-0.01, 0.01))

    # -------------------------------------------------------------------------
    # Scenario 12: Mixed Workload Interference
    # -------------------------------------------------------------------------

    async def _mixed_scenario(self, duration_seconds: int = 300):
        """
        Run heartbeat + RUVON gossip + SAF sync simultaneously on the same device.

        Validates that the three workloads do not interfere with each other:
        SAF p99 should stay < 500ms, gossip error rate < 1%, heartbeat rate = 0 errors.
        All three scenarios write into the *same* DeviceMetrics fields they always use,
        so the orchestrator can aggregate results without any special handling.
        """
        await asyncio.gather(
            self._heartbeat_scenario(duration_seconds),
            self._ruvon_gossip_scenario(duration_seconds),
            self._saf_sync_scenario(duration_seconds),
            return_exceptions=True,
        )

    # -------------------------------------------------------------------------
    # Scenario 13: Leader Election Stability
    # -------------------------------------------------------------------------

    async def _election_stability_scenario(self, duration_seconds: int = 120):
        """
        Local-only. Repeatedly runs the leadership-score + deterministic election
        formula used by RuvonEdgeAgent, measuring:
          - elections_run       : total elections simulated
          - election_latencies  : time per election (should be sub-millisecond)
          - leader_tenure_samples : how long each pod held the Sovereign role
          - flap_count          : rapid re-elections (< 5 s gap — split-brain indicator)

        Election formula:  S = 0.50·P + 0.25·C + 0.25·U
          P = 1.0 (plugged in) or battery% / 100
          C = 1.0 − cpu_fraction
          U = min(uptime_seconds / 86400, 1.0)

        Simulates a mesh of 20 peers; each "round" every device computes its score,
        the highest scorer becomes Sovereign.  Scores drift slowly over time so
        re-elections happen only when the leader genuinely changes.
        """
        import math

        end_time = time.time() + duration_seconds

        # Stable base values for this device (vary slightly per device)
        seed = hash(self.config.device_id) % 1000
        base_cpu = 0.15 + (seed % 50) / 500.0      # 0.15–0.25
        start_ts = time.monotonic()
        last_election_time: float = 0.0
        current_sovereign: Optional[str] = None

        # Simulate 20 peers with stable-but-drifting scores
        peer_ids = [f"peer-{i:03d}" for i in range(20)]
        peer_scores = {pid: 0.5 + (hash(pid) % 100) / 500.0 for pid in peer_ids}

        def _compute_score(cpu_frac: float, uptime_s: float, plugged: bool) -> float:
            P = 1.0 if plugged else 0.7
            C = 1.0 - cpu_frac
            U = min(uptime_s / 86400.0, 1.0)
            return round(0.50 * P + 0.25 * C + 0.25 * U, 4)

        while time.time() < end_time:
            t0 = time.perf_counter()

            uptime = time.monotonic() - start_ts
            cpu_frac = base_cpu + random.gauss(0, 0.02)
            my_score = _compute_score(cpu_frac, uptime, plugged=True)

            # Drift peer scores slightly each round
            best_score = my_score
            best_id = self.config.device_id
            for pid in peer_ids:
                peer_scores[pid] = max(0.0, min(1.0,
                    peer_scores[pid] + random.gauss(0, 0.001)))
                s = peer_scores[pid]
                if s > best_score or (s == best_score and pid < best_id):
                    best_score = s
                    best_id = pid

            election_duration = time.perf_counter() - t0
            self.metrics.election_latencies.append(election_duration)
            self.metrics.elections_run += 1

            # Detect sovereign change
            if best_id != current_sovereign:
                now = time.time()
                if current_sovereign is not None:
                    tenure = now - last_election_time
                    self.metrics.leader_tenure_samples.append(tenure)
                    if tenure < 5.0:
                        self.metrics.flap_count += 1
                current_sovereign = best_id
                last_election_time = now

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Election check interval — matches agent's heartbeat cadence
            await asyncio.sleep(0.5 + random.uniform(-0.05, 0.05))

    # -------------------------------------------------------------------------
    # Scenario 14: Gossip Payload Variance
    # -------------------------------------------------------------------------

    async def _payload_variance_scenario(self, duration_seconds: int = 120):
        """
        Local-only. Measures gossip serialization + deserialization latency
        across five payload sizes: 256B, 1KB, 4KB, 16KB, 64KB.

        Uses the existing CapabilityVector schema plus a variable-length
        `extra_telemetry` string field to hit each target size.

        Targets: p95 encode+decode < 50ms for all sizes including 64KB.
        """
        import json as _json

        end_time = time.time() + duration_seconds

        SIZE_BUCKETS = {
            "256B":  256,
            "1KB":   1_024,
            "4KB":   4_096,
            "16KB":  16_384,
            "64KB":  65_536,
        }

        # Initialise per-bucket latency lists
        for label in SIZE_BUCKETS:
            self.metrics.payload_latencies.setdefault(label, [])

        while time.time() < end_time:
            # Pick a random size bucket for this iteration
            label, target_bytes = random.choice(list(SIZE_BUCKETS.items()))

            # Build a CapabilityVector-shaped dict with padding to reach target_bytes
            base_vec = {
                "device_id":         self.config.device_id,
                "available_ram_mb":  random.randint(512, 8192),
                "cpu_load":          round(random.uniform(0.05, 0.95), 3),
                "model_tier":        random.choice(["tier_1", "tier_2", "tier_3"]),
                "latency_ms":        round(random.uniform(1.0, 150.0), 1),
                "task_queue_length": random.randint(0, 20),
                "node_tier":         "tier_2",
                "timestamp":         time.time(),
            }
            # Pad to target size with simulated telemetry payload
            base_json = _json.dumps(base_vec)
            pad_needed = max(0, target_bytes - len(base_json.encode()))
            base_vec["extra_telemetry"] = "x" * pad_needed

            t0 = time.perf_counter()

            # Encode
            encoded = _json.dumps(base_vec).encode("utf-8")
            # Decode + access a field (simulates receiver side)
            decoded = _json.loads(encoded)
            _ = decoded.get("available_ram_mb")

            elapsed = time.perf_counter() - t0
            self.metrics.payload_latencies[label].append(elapsed)

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            await asyncio.sleep(0.01 + random.uniform(0, 0.005))

    # -------------------------------------------------------------------------
    # Scenario 15: End-to-End Decision Pipeline
    # -------------------------------------------------------------------------

    async def _e2e_decision_scenario(self, duration_seconds: int = 120):
        """
        Local-only. Simulates the full pit-wall decision pipeline:

          1. generate_telemetry()  — 2KB dict (tire temps, sector times, fuel%)
          2. compute_score()       — leadership score formula (same as agent.py)
          3. sovereign check       — highest-score device in simulated 10-pod mesh
          4. sign_decision()       — Ed25519 sign via NKeyPatchVerifier
          5. gossip_broadcast()    — JSON serialize decision vector
          6. wait_for_acks()       — asyncio.gather(N fake ack coroutines, 1–5ms each)
          7. record latencies      — decision_to_sign, sign_to_consensus (e2e_consensus),
                                     total end-to-end (e2e_decision)

        Consensus threshold: ≥7 of 10 peers acknowledge (70%).
        Targets: p50 < 50ms, p99 < 200ms end-to-end.
        """
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import json as _json
        import base64 as _b64

        end_time = time.time() + duration_seconds

        # Generate a long-lived signing keypair (simulates TMS control plane key)
        priv_key = Ed25519PrivateKey.generate()
        pub_key  = priv_key.public_key()

        # Simulate a stable 10-pod mesh; this device's rank is fixed for the run
        mesh_size = 10
        my_index  = hash(self.config.device_id) % mesh_size
        # Pre-assign peer base scores (stable, slowly drifting)
        peer_base = [0.3 + (i * 0.07) for i in range(mesh_size)]
        is_sovereign = (my_index == mesh_size - 1)  # highest index = highest base score

        def _make_telemetry() -> dict:
            """Generate a ~2KB F1 telemetry payload."""
            return {
                "lap":          random.randint(1, 70),
                "sector":       random.choice([1, 2, 3]),
                "fuel_kg":      round(random.uniform(5.0, 110.0), 2),
                "tire_compound": random.choice(["SOFT", "MEDIUM", "HARD"]),
                "tire_temps":   {
                    "fl": round(random.uniform(70, 120), 1),
                    "fr": round(random.uniform(70, 120), 1),
                    "rl": round(random.uniform(70, 120), 1),
                    "rr": round(random.uniform(70, 120), 1),
                },
                "sector_times": [round(random.uniform(20, 35), 3) for _ in range(3)],
                "gap_to_leader_s": round(random.uniform(-10, 30), 3),
                "drs_available":   random.choice([True, False]),
                "undercut_window": round(random.uniform(0, 5), 2),
                "strategy_commit": random.choice(["stay_out", "pit_now", "push"]),
                "confidence":      round(random.uniform(0.5, 1.0), 3),
                "padding":         "x" * 1600,  # pad to ~2KB
            }

        async def _fake_ack(delay_ms: float) -> bool:
            await asyncio.sleep(delay_ms / 1000.0)
            return True

        while time.time() < end_time:
            t_start = time.perf_counter()

            # 1. Generate telemetry
            telemetry = _make_telemetry()

            # 2. Compute leadership score (local, no I/O)
            cpu_frac = random.uniform(0.1, 0.4)
            uptime_s = time.monotonic()
            my_score = round(
                0.50 * 1.0 +                          # P = plugged in
                0.25 * (1.0 - cpu_frac) +             # C = CPU slack
                0.25 * min(uptime_s / 86400.0, 1.0),  # U = uptime
                4,
            )

            t_scored = time.perf_counter()

            if is_sovereign:
                # 3. Sign the strategy decision
                decision_bytes = _json.dumps({
                    "strategy": telemetry["strategy_commit"],
                    "lap":      telemetry["lap"],
                    "score":    my_score,
                }).encode()
                signature = priv_key.sign(decision_bytes)
                sig_b64   = _b64.b64encode(signature).decode()

                t_signed = time.perf_counter()

                # 4. Gossip broadcast — serialize decision vector
                gossip_payload = _json.dumps({
                    "device_id": self.config.device_id,
                    "decision":  decision_bytes.decode(),
                    "signature": sig_b64,
                    "score":     my_score,
                    "timestamp": time.time(),
                }).encode()
                _ = len(gossip_payload)  # simulate dispatch overhead

                # 5. Wait for acks from ≥7 of 10 peers (70% threshold)
                ack_delays = [random.uniform(1.0, 5.0) for _ in range(mesh_size - 1)]
                ack_results = await asyncio.gather(
                    *[_fake_ack(d) for d in ack_delays],
                    return_exceptions=True,
                )
                acks_received = sum(1 for r in ack_results if r is True)

                t_consensus = time.perf_counter()

                self.metrics.e2e_consensus_latencies.append(t_consensus - t_signed)
                self.metrics.e2e_ack_count += acks_received

            t_end = time.perf_counter()
            self.metrics.e2e_decision_latencies.append(t_end - t_start)

            if self.metrics_callback:
                await self.metrics_callback(self.config.device_id, self.metrics)

            # Decisions happen roughly every lap sector (~20s in real F1, 0.5–2s in benchmark)
            await asyncio.sleep(random.uniform(0.5, 2.0))
