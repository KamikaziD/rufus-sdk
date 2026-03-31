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
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
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
                await self._saf_sync_scenario()
            elif scenario == "thundering_herd":
                await self._thundering_herd_scenario()
            elif scenario == "config_poll":
                await self._config_polling_scenario(duration_seconds)
            elif scenario == "cloud_commands":
                await self._cloud_commands_scenario(duration_seconds)
            elif scenario == "wasm_steps":
                await self._wasm_steps_scenario(duration_seconds)
            elif scenario == "wasm_thundering_herd":
                await self._wasm_thundering_herd_scenario()
            elif scenario == "msgspec_codec":
                # msgspec_codec is a heartbeat run with a server-side preflight already done
                # by ScenarioRunner.run_msgspec_codec_test(). Devices just run heartbeat.
                await self._heartbeat_scenario(duration_seconds)
            elif scenario == "nats_transport":
                await self._nats_transport_scenario(duration_seconds)
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
                response = await self._get_http_client().post(
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
                if 500 <= response.status_code < 600:
                    self.metrics.errors_5xx += 1
                elif 400 <= response.status_code < 500:
                    self.metrics.errors_4xx += 1
                return False

        except Exception as e:
            logger.error(f"Sync error for {self.config.device_id}: {e}", exc_info=True)
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
            from rufus.implementations.execution.component_runtime import ComponentStepRuntime
            from rufus.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver
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

    async def _wasm_thundering_herd_scenario(self):
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

        Requires RUFUS_NATS_URL or NATS_URL env var and nats-py installed.
        """
        import os
        import json as _json
        nats_url = os.getenv("RUFUS_NATS_URL") or os.getenv("NATS_URL", "nats://localhost:4222")

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
                "sdk_version": "1.0.0rc5",
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
