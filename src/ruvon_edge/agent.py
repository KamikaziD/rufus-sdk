"""
RufusEdgeAgent - Main agent class for fintech edge devices.

This is the primary interface for running Rufus on POS terminals,
ATMs, mobile readers, and other edge devices.
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import time
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime

from ruvon.builder import WorkflowBuilder
from ruvon.workflow import Workflow
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.observability.logging import LoggingObserver
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine

from ruvon_edge.models import (
    PaymentState,
    SAFTransaction,
    DeviceConfig,
    DeviceHealth,
    DeviceStatus,
    TransactionStatus,
)
from ruvon_edge.sync_manager import SyncManager
from ruvon_edge.config_manager import ConfigManager
from ruvon_edge.workflow_sync import EdgeWorkflowSyncer
from ruvon_edge.platform.base import PlatformAdapter
from ruvon_edge.nkey_verifier import NKeyPatchVerifier
from ruvon_edge.capability_gossip import (
    CapabilityGossipManager,
    NodeTier,
    classify_node_tier,
)

logger = logging.getLogger(__name__)

# Minimum available RAM (MB) required to safely load a WASM binary into the
# wasmtime JIT engine.  Below this threshold the node delegates via
# ruvon.mesh.build.request instead of attempting the hot-swap locally.
_MIN_WASM_LOAD_RAM_MB = 128


class RufusEdgeAgent:
    """
    Edge agent for fintech devices.

    This agent runs on POS terminals, ATMs, mobile readers, and kiosks.
    It provides:
    - Offline workflow execution with SQLite
    - Store-and-Forward for offline transactions
    - Config polling from cloud control plane
    - Automatic sync when connectivity is restored

    Example:
        agent = RufusEdgeAgent(
            device_id="pos-001",
            cloud_url="https://control.example.com",
            db_path="/var/lib/rufus/edge.db",
        )
        await agent.start()

        result = await agent.execute_workflow(
            "PaymentAuthorization",
            {"amount": "25.00", "card_token": "tok_xxx"}
        )
    """

    def __init__(
        self,
        device_id: str,
        cloud_url: str,
        api_key: Optional[str] = None,
        db_path: str = "ruvon_edge.db",
        encryption_key: Optional[str] = None,
        config_poll_interval: int = 60,
        sync_interval: int = 30,
        heartbeat_interval: int = 60,
        workflow_sync_enabled: bool = True,
        platform_adapter: Optional[PlatformAdapter] = None,
        peer_listen_port: int = 0,
        peer_urls: Optional[List[str]] = None,
        nats_url: Optional[str] = None,
        nats_credentials: Optional[str] = None,
    ):
        """
        Initialize the edge agent.

        Args:
            device_id: Unique identifier for this device
            cloud_url: URL of the cloud control plane
            api_key: API key for authentication (or from env RUVON_API_KEY)
            db_path: Path to SQLite database
            encryption_key: Key for encrypting sensitive data (or from env RUVON_ENCRYPTION_KEY)
            config_poll_interval: Seconds between config polls
            sync_interval: Seconds between sync attempts
            heartbeat_interval: Seconds between heartbeats
            peer_listen_port: Port for inbound peer relay server (0 = disabled)
            peer_urls: Known peer device URLs for BFS mesh routing ([] = disabled)
            nats_url: NATS server URL (e.g. "nats://localhost:4222"). When set,
                      activates NATSEdgeTransport for sub-ms command delivery.
                      Also read from RUVON_NATS_URL environment variable.
            nats_credentials: Optional path to NATS credentials file (NKey/JWT).
        """
        self.device_id = device_id
        self.cloud_url = cloud_url.rstrip("/")
        self.api_key = api_key or os.getenv("RUVON_API_KEY", "")
        self.db_path = db_path
        self.encryption_key = encryption_key or os.getenv("RUVON_ENCRYPTION_KEY")
        self.config_poll_interval = config_poll_interval
        self.sync_interval = sync_interval
        self.heartbeat_interval = heartbeat_interval
        self.workflow_sync_enabled = workflow_sync_enabled
        self._platform_adapter: Optional[PlatformAdapter] = platform_adapter
        self._peer_listen_port = peer_listen_port
        self._peer_urls: List[str] = list(peer_urls or [])
        self._nats_url: Optional[str] = nats_url or os.getenv("RUVON_NATS_URL")
        self._nats_credentials: Optional[str] = nats_credentials or os.getenv("RUVON_NATS_CREDENTIALS")

        # Components (initialized in start())
        self.persistence: Optional[SQLitePersistenceProvider] = None
        self.executor: Optional[SyncExecutor] = None
        self.observer: Optional[LoggingObserver] = None
        self.workflow_builder: Optional[WorkflowBuilder] = None
        self.sync_manager: Optional[SyncManager] = None
        self.config_manager: Optional[ConfigManager] = None
        self.workflow_syncer: Optional[EdgeWorkflowSyncer] = None
        self._wasm_resolver = None  # SqliteWasmBinaryResolver, set in start()

        # Transport (initialized in start())
        self._transport = None

        # State
        self._is_running = False
        self._is_online = False
        self._background_tasks: list[asyncio.Task] = []
        # Heartbeat failure counting (4.3)
        self._heartbeat_consecutive_failures: int = 0
        # Custom command handlers registered by application code
        self._custom_command_handlers: dict = {}
        # Mesh peer relay (initialized in start() when peer_urls/peer_listen_port are set)
        self._mesh_router = None

        # RUVON Local Master election state
        self._cloud_offline_secs: float = 0.0   # cumulative offline time since last cloud contact
        self._is_local_master: bool = False      # True when this device has won election
        self._local_master_id: Optional[str] = None  # device_id of current local master
        self._election_threshold: int = 300      # seconds before election triggers (5 min)
        self._agent_start_time: float = 0.0     # set in start() for uptime-based scoring

        # RUVON security — Ed25519 patch signature verification
        # Populated from RUVON_NKEY_PUBLIC_KEY env var in start(); None = verification skipped.
        self._nkey_verifier: Optional[NKeyPatchVerifier] = None

        # RUVON capability gossip
        self._gossip_manager: Optional[CapabilityGossipManager] = None
        self._local_node_tier: NodeTier = NodeTier.TIER_1  # refined in start()

    async def start(self):
        """Start the edge agent."""
        if self._is_running:
            logger.warning("Agent already running")
            return

        logger.info(f"Starting Ruvon Edge Agent: {self.device_id}")

        # Initialize persistence
        self.persistence = SQLitePersistenceProvider(db_path=self.db_path)
        await self.persistence.initialize()

        # Wire WASM binary resolver so WASM steps can read from device_wasm_cache
        from ruvon.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver
        self._wasm_resolver = SqliteWasmBinaryResolver(self.persistence.conn)

        # Auto-bootstrap factory-fresh devices (no pre-configured API key)
        if not self.api_key and self.cloud_url:
            await self.bootstrap()

        # Initialize executor
        self.executor = SyncExecutor()

        # Initialize observer
        self.observer = LoggingObserver()

        # Initialize config manager
        self.config_manager = ConfigManager(
            config_url=self.cloud_url,
            device_id=self.device_id,
            api_key=self.api_key,
            poll_interval_seconds=self.config_poll_interval,
            persistence=self.persistence,
            platform_adapter=self._platform_adapter,
        )
        await self.config_manager.initialize()

        # Initialize sync manager
        self.sync_manager = SyncManager(
            persistence=self.persistence,
            sync_url=self.cloud_url,
            device_id=self.device_id,
            api_key=self.api_key,
            platform_adapter=self._platform_adapter,
        )
        await self.sync_manager.initialize()

        # Initialize workflow builder with empty registry (loaded from config)
        self.workflow_builder = WorkflowBuilder(
            workflow_registry={},
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
        )

        # Initialize workflow syncer (push completed workflows to cloud on sync cycles)
        if self.workflow_sync_enabled:
            self.workflow_syncer = EdgeWorkflowSyncer(
                persistence=self.persistence,
                cloud_url=self.cloud_url,
                device_id=self.device_id,
                api_key=self.api_key,
            )

        # Initialize transport (NATS when RUVON_NATS_URL is set, else HTTP)
        from ruvon_edge.transport import create_transport
        self._transport = create_transport(
            device_id=self.device_id,
            cloud_url=self.cloud_url,
            api_key=self.api_key,
            nats_url=self._nats_url,
            nats_credentials=self._nats_credentials,
        )
        await self._transport.connect()

        # Classify hardware tier and wire NKey verifier
        self._local_node_tier = self._detect_node_tier()
        self._nkey_verifier = NKeyPatchVerifier.from_env()
        if self._nkey_verifier:
            logger.info("[Agent] NKey patch signature verification ENABLED (tier=%s)", self._local_node_tier.value)
        else:
            logger.warning("[Agent] RUVON_NKEY_PUBLIC_KEY not set — WASM patch signatures will NOT be verified")

        # If NATS is active, subscribe to command, config push, and WASM patch channels
        if self._nats_url:
            await self._transport.subscribe_commands(self._handle_cloud_command)
            await self._transport.subscribe_config_push(self._on_config_push)
            await self._transport.subscribe_patch_broadcast(self._on_patch_broadcast)

            # Capability gossip: broadcast this node's vector, receive peer vectors
            self._gossip_manager = CapabilityGossipManager(
                device_id=self.device_id,
                transport=self._transport,
                persistence=self.persistence,
            )
            await self._gossip_manager.start()
            await self._transport.subscribe_capability_gossip(
                self._gossip_manager._on_capability_received
            )

            # Tier 2+ nodes act as build delegates for constrained peers
            if self._local_node_tier >= NodeTier.TIER_2:
                await self._transport.subscribe_build_requests(self._on_build_request)
                logger.info(
                    "[Agent] Build delegation handler registered (tier=%s)",
                    self._local_node_tier.value,
                )

        # Register config change callback to reload workflows
        self.config_manager.on_config_change(self._on_config_change)

        # Check initial connectivity
        self._is_online = await self.sync_manager.check_connectivity()
        logger.info(f"Initial connectivity: {'online' if self._is_online else 'offline'}")

        # Start background tasks
        self._background_tasks.append(
            asyncio.create_task(self._sync_loop())
        )
        self._background_tasks.append(
            asyncio.create_task(self._reconnect_sync_loop())
        )
        self._background_tasks.append(
            asyncio.create_task(self._heartbeat_loop())
        )

        # Start config polling
        await self.config_manager.start_polling()

        # Mesh peer relay — spin up relay server and BFS router if configured
        if self._peer_listen_port > 0 or self._peer_urls:
            from ruvon_edge.peer_relay import MeshRouter
            self._mesh_router = MeshRouter(
                device_id=self.device_id,
                sync_manager=self.sync_manager,
                gossip_manager=self._gossip_manager,
            )

        if self._peer_listen_port > 0:
            from ruvon_edge.peer_relay import PeerRelayServer, create_relay_app
            relay_app = create_relay_app(
                sync_manager=self.sync_manager,
                device_id=self.device_id,
                peer_urls=self._peer_urls,
                is_online_fn=lambda: self._is_online,
                leadership_score_fn=self._compute_leadership_score,
                is_master_fn=lambda: self._is_local_master,
                node_tier_fn=lambda: self._local_node_tier.value,
            )
            relay_server = PeerRelayServer(relay_app, self._peer_listen_port)
            self._background_tasks.append(
                asyncio.create_task(relay_server.start())
            )
            logger.info(
                f"[Mesh] Relay server started on port {self._peer_listen_port}"
            )

        # Register with cloud so other devices can discover this relay via /mesh-peers
        if self._peer_listen_port > 0 and self._is_online and self.cloud_url:
            asyncio.create_task(self._register_relay_server())

        self._agent_start_time = time.monotonic()
        self._is_running = True
        logger.info(f"Ruvon Edge Agent started: {self.device_id}")

    async def bootstrap(
        self,
        device_type: str = "unknown",
        merchant_id: str = "",
        firmware_version: str = "0.0.0",
    ) -> bool:
        """
        Bootstrap a factory-fresh device: check for a stored API key, and if
        absent, register with the cloud and persist the returned key.

        Called automatically by start() when api_key is empty and cloud_url is set.

        Returns True if the device is ready (key present or successfully registered).
        """
        # Ensure persistence is open (may be called before start())
        if self.persistence is None:
            from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
            from pathlib import Path
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.persistence = SQLitePersistenceProvider(db_path=self.db_path)
            await self.persistence.initialize()

        # Check for a stored API key
        try:
            stored = await self.persistence.get_edge_sync_state("api_key")
            # get_edge_sync_state returns a plain str (or None)
            stored_value = stored.value if hasattr(stored, "value") else stored
            if stored_value:
                self.api_key = stored_value
                logger.info(f"bootstrap: loaded stored API key for device {self.device_id}")
                return True
        except Exception as e:
            logger.debug(f"bootstrap: no stored key ({e})")

        # No stored key — register with cloud
        if not self.cloud_url:
            logger.warning("bootstrap: no cloud_url set, cannot auto-register")
            return False

        import httpx as _httpx
        try:
            async with _httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/v1/devices/register",
                    json={
                        "device_id": self.device_id,
                        "device_type": device_type,
                        "merchant_id": merchant_id,
                        "firmware_version": firmware_version,
                    },
                )
            if resp.status_code not in (200, 201):
                logger.error(
                    f"bootstrap: registration failed with status {resp.status_code}"
                )
                return False

            data = resp.json()
            new_api_key = data.get("api_key") or data.get("new_api_key")
            if not new_api_key:
                logger.error("bootstrap: registration response missing api_key field")
                return False

            # Persist the key to SQLite so subsequent starts skip registration
            await self.persistence.set_edge_sync_state("api_key", new_api_key)
            self.api_key = new_api_key
            logger.info(f"bootstrap: registered device {self.device_id}, API key stored")
            return True

        except Exception as e:
            logger.error(f"bootstrap: registration request failed: {e}")
            return False

    async def stop(self):
        """Stop the edge agent."""
        if not self._is_running:
            return

        logger.info(f"Stopping Ruvon Edge Agent: {self.device_id}")

        # Disconnect transport first (before cancelling tasks that may use it)
        if self._transport:
            await self._transport.disconnect()

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._background_tasks.clear()

        # Stop config polling
        if self.config_manager:
            await self.config_manager.stop_polling()
            await self.config_manager.close()

        # Close sync manager
        if self.sync_manager:
            await self.sync_manager.close()

        # Close persistence
        if self.persistence:
            await self.persistence.close()

        self._is_running = False
        logger.info(f"Ruvon Edge Agent stopped: {self.device_id}")

    async def execute_workflow(
        self,
        workflow_type: str,
        data: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute a workflow locally.

        Args:
            workflow_type: Type of workflow to execute
            data: Initial workflow data
            timeout: Optional timeout in seconds

        Returns:
            Workflow result dict
        """
        if not self._is_running:
            raise RuntimeError("Agent not started")

        # Get workflow config from config manager
        workflow_config = self.config_manager.get_workflow_config(workflow_type)
        if not workflow_config:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

        # Generate idempotency key if not provided
        if "idempotency_key" not in data:
            data["idempotency_key"] = f"{self.device_id}:{uuid.uuid4().hex}"

        # Create workflow
        workflow = await self.workflow_builder.create_workflow(
            workflow_type=workflow_type,
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            workflow_builder=self.workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=self.observer,
            initial_data=data,
            owner_id=self.device_id,
            wasm_binary_resolver=self._wasm_resolver,
        )

        # Execute to completion
        try:
            while workflow.status == "ACTIVE":
                result, next_step = await workflow.next_step()

                if workflow.status in ["COMPLETED", "FAILED", "WAITING_HUMAN"]:
                    break

            return {
                "workflow_id": workflow.id,
                "status": workflow.status,
                "state": workflow.state.model_dump() if hasattr(workflow.state, 'model_dump') else workflow.state,
                "result": result if 'result' in dir() else {},
            }

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return {
                "workflow_id": workflow.id,
                "status": "FAILED",
                "error": str(e),
            }

    async def process_payment(
        self,
        amount: float,
        card_token: str,
        merchant_id: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Process a payment transaction.

        This is a convenience method that handles offline fallback
        and Store-and-Forward automatically.

        Args:
            amount: Transaction amount
            card_token: Tokenized card reference
            merchant_id: Merchant identifier
            **kwargs: Additional transaction data

        Returns:
            Payment result dict
        """
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        idempotency_key = f"{merchant_id}:{transaction_id}"

        # Check connectivity
        is_online = await self.sync_manager.check_connectivity()

        if is_online:
            # Online flow - execute payment workflow
            result = await self.execute_workflow(
                workflow_type="PaymentAuthorization",
                data={
                    "transaction_id": transaction_id,
                    "idempotency_key": idempotency_key,
                    "amount": amount,
                    "card_token": card_token,
                    "merchant_id": merchant_id,
                    "terminal_id": self.device_id,
                    "is_online": True,
                    **kwargs,
                }
            )
            return result

        else:
            # Offline flow - check floor limit and queue for sync
            floor_limit = self.config_manager.get_floor_limit()

            if amount > floor_limit:
                return {
                    "transaction_id": transaction_id,
                    "status": "DECLINED",
                    "reason": f"Amount ${amount} exceeds offline floor limit ${floor_limit}",
                    "is_offline": True,
                }

            # Create SAF transaction
            saf_txn = SAFTransaction(
                transaction_id=transaction_id,
                idempotency_key=idempotency_key,
                device_id=self.device_id,
                merchant_id=merchant_id,
                amount=amount,
                currency=kwargs.get("currency", "USD"),
                card_token=card_token,
                card_last_four=kwargs.get("card_last_four", "****"),
                status=TransactionStatus.APPROVED_OFFLINE,
                offline_approved_at=datetime.utcnow(),
            )

            # Queue for sync
            await self.sync_manager.queue_for_sync(saf_txn)

            return {
                "transaction_id": transaction_id,
                "status": "APPROVED_OFFLINE",
                "is_offline": True,
                "requires_sync": True,
                "floor_limit": floor_limit,
            }

    async def get_health(self) -> DeviceHealth:
        """Get current device health status."""
        pending = 0
        if self.sync_manager:
            pending = await self.sync_manager.get_pending_count()

        return DeviceHealth(
            device_id=self.device_id,
            status=DeviceStatus.ONLINE if self._is_online else DeviceStatus.OFFLINE,
            is_online=self._is_online,
            pending_sync=pending,
            last_sync_at=self.sync_manager._last_sync_at if self.sync_manager else None,
            last_config_pull_at=self.config_manager._last_poll_at if self.config_manager else None,
        )

    def _on_config_change(self, config: DeviceConfig):
        """Handle config changes."""
        logger.info(f"Config changed to version {config.version}")

        # Update workflow registry
        if self.workflow_builder and config.workflows:
            self.workflow_builder.workflow_registry = config.workflows
            logger.info(f"Updated workflow registry with {len(config.workflows)} workflows")

        # Update runtime intervals from config (takes effect on next loop iteration)
        new_sync = config.sync_interval_seconds
        new_heartbeat = config.heartbeat_interval_seconds
        if new_sync != self.sync_interval:
            logger.info(f"Sync interval updated: {self.sync_interval}s → {new_sync}s")
            self.sync_interval = new_sync
        if new_heartbeat != self.heartbeat_interval:
            logger.info(f"Heartbeat interval updated: {self.heartbeat_interval}s → {new_heartbeat}s")
            self.heartbeat_interval = new_heartbeat

    async def _sync_loop(self):
        """Background sync loop."""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)

                # Check connectivity
                self._is_online = await self.sync_manager.check_connectivity()

                if self._is_online:
                    # Attempt SAF sync
                    pending = await self.sync_manager.get_pending_count()
                    if pending > 0:
                        logger.info(f"Syncing {pending} pending transactions...")
                        report = await self.sync_manager.sync_all_pending()
                        logger.info(
                            f"Sync complete: {report.synced_count} synced, "
                            f"{report.failed_count} failed"
                        )

                    # Attempt workflow sync (push completed workflows to cloud + purge SQLite)
                    if self.workflow_syncer:
                        try:
                            ws_result = await self.workflow_syncer.sync()
                            if ws_result.get("synced", 0) > 0:
                                logger.info(f"Workflow sync complete: {ws_result}")
                        except Exception as exc:
                            logger.warning(f"Workflow sync error: {exc}")

                    # Refresh peer list from cloud (cached in SQLite for offline use)
                    if self._mesh_router:
                        await self._refresh_mesh_peers()

                    # Reset cloud-offline counter and abdicate if we were local master
                    if self._cloud_offline_secs > 0:
                        self._cloud_offline_secs = 0.0
                        if self._is_local_master:
                            await self._abdicate()

                else:
                    # Offline: attempt mesh peer relay if peers are configured
                    if self._mesh_router and self.sync_manager:
                        pending = await self.sync_manager.get_pending_count()
                        if pending > 0:
                            relay_txns = await self.sync_manager._build_signed_transaction_dicts()
                            if relay_txns:
                                effective_peers = await self._get_effective_peer_urls()
                                logger.info(
                                    f"[Mesh] Offline — probing {len(effective_peers)} peer(s)..."
                                )
                                result = await self._mesh_router.find_relay(
                                    relay_txns, effective_peers
                                )
                                if result and result.accepted_ids:
                                    await self.sync_manager.mark_relayed(result.accepted_ids)
                                    logger.info(
                                        f"[Mesh] Relayed {len(result.accepted_ids)} txns "
                                        f"via {result.relay_path}"
                                    )

                    # Track cumulative offline time; trigger election if threshold crossed
                    self._cloud_offline_secs += self.sync_interval
                    if (
                        self._cloud_offline_secs >= self._election_threshold
                        and self._mesh_router
                        and not self._is_local_master
                        and self._local_master_id is None
                    ):
                        logger.info(
                            f"[RUVON] Cloud offline {self._cloud_offline_secs:.0f}s "
                            f"— triggering election"
                        )
                        asyncio.create_task(self._run_election())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")

    async def _reconnect_sync_loop(self):
        """Fast-polls connectivity while offline; triggers an immediate sync the
        moment the device comes back online, without waiting for _sync_loop's
        full sync_interval to elapse."""
        OFFLINE_POLL_INTERVAL = 5  # seconds between connectivity checks while offline
        while True:
            try:
                if self._is_online:
                    # Already online — nothing to do; _sync_loop handles periodic syncs.
                    # Check again after a short sleep so we catch transitions quickly.
                    await asyncio.sleep(OFFLINE_POLL_INTERVAL)
                    continue

                # Device is offline — poll until we're back
                await asyncio.sleep(OFFLINE_POLL_INTERVAL)
                is_now_online = await self.sync_manager.check_connectivity()
                if not is_now_online:
                    continue

                # Transition: offline → online
                self._is_online = True
                logger.info("Device reconnected — running immediate sync")

                # Abdicate local master role now that cloud is reachable
                if self._is_local_master:
                    await self._abdicate()
                self._cloud_offline_secs = 0.0
                self._local_master_id = None

                if self.sync_manager:
                    pending = await self.sync_manager.get_pending_count()
                    if pending > 0:
                        report = await self.sync_manager.sync_all_pending()
                        logger.info(
                            f"Reconnect SAF sync: {report.synced_count} synced, "
                            f"{report.failed_count} failed"
                        )

                if self.workflow_syncer:
                    try:
                        ws_result = await self.workflow_syncer.sync()
                        if ws_result.get("synced", 0) > 0:
                            logger.info(f"Reconnect workflow sync: {ws_result}")
                    except Exception as exc:
                        logger.warning(f"Reconnect workflow sync error: {exc}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reconnect sync loop error: {e}")

    async def _heartbeat_loop(self):
        """Background heartbeat loop - reports device health to cloud."""
        # Stagger initial heartbeat across fleet to prevent thundering herd.
        # Jitter: uniform 0–50% of heartbeat_interval so a fleet of N devices
        # coming back online simultaneously doesn't all fire at T+interval.
        startup_jitter = random.uniform(0, self.heartbeat_interval * 0.5)
        await asyncio.sleep(startup_jitter)

        while True:
            try:
                await self._send_heartbeat()
                # Per-cycle drift (±10%) prevents re-synchronization after a
                # cloud outage where all devices went silent at the same time.
                drift = random.uniform(
                    self.heartbeat_interval * 0.9,
                    self.heartbeat_interval * 1.1,
                )
                await asyncio.sleep(drift)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
                await asyncio.sleep(self.heartbeat_interval)

    async def _send_heartbeat(self):
        """Send heartbeat with device metrics to cloud control plane."""
        if not self.cloud_url:
            return

        pending_count = await self.sync_manager.get_pending_count() if self.sync_manager else 0

        # Build RUVON vector advisory — cheap (sync, no I/O)
        known_peers = len(await self._get_effective_peer_urls()) if self._mesh_router else 0
        vector_advisory = {
            "relay_score": self._compute_leadership_score() if self._agent_start_time else 0.0,
            "connectivity_quality": 1.0 if self._is_online else 0.0,
            "known_peers": known_peers,
            "is_local_master": self._is_local_master,
        }

        payload = {
            "device_status": "online" if self._is_online else "offline",
            "metrics": {
                "pending_sync_count": pending_count,
                "last_sync_at": (
                    self.sync_manager._last_sync_at.isoformat()
                    if self.sync_manager and self.sync_manager._last_sync_at
                    else None
                ),
                "config_version": (
                    self.config_manager.config.version
                    if self.config_manager and self.config_manager.config
                    else None
                ),
            },
            "vector_advisory": vector_advisory,
        }

        if not self._transport:
            return

        try:
            commands = await self._transport.send_heartbeat(payload)
            self._heartbeat_consecutive_failures = 0
            for cmd in commands:
                await self._handle_cloud_command(cmd)
        except Exception as e:
            self._heartbeat_consecutive_failures += 1
            self._log_heartbeat_failure(str(e))

    async def _on_config_push(self, config_data: Dict[str, Any]) -> None:
        """Handle a server-initiated config push (NATS mode)."""
        try:
            from ruvon_edge.models import DeviceConfig
            new_config = DeviceConfig(**config_data)
            old_config = self.config_manager._current_config
            self.config_manager._current_config = new_config
            logger.info(f"[Config] NATS push received — version {new_config.version}")
            if old_config is None or old_config.version != new_config.version:
                for cb in self.config_manager._on_config_change_callbacks:
                    try:
                        cb(new_config)
                    except Exception as e:
                        logger.error(f"Config change callback error: {e}")
        except Exception as e:
            logger.error(f"[Config] Failed to apply NATS config push: {e}")

    async def _on_patch_broadcast(
        self,
        binary: bytes,
        wasm_hash: str,
        step_name: str,
        signature_b64: str = "",
    ) -> None:
        """Handle a fleet-wide WASM binary patch delivered via ruvon.node.patch.

        Hash integrity has already been verified by NATSEdgeTransport before
        this handler is called.

        Steps:
        1. Ed25519 signature check (when RUVON_NKEY_PUBLIC_KEY is configured).
        2. WASM load-safety gate: if available RAM < _MIN_WASM_LOAD_RAM_MB,
           delegate to a Tier 2 peer via ruvon.mesh.build.request instead of
           attempting a hot-swap that could OOM the device.
        3. Hot-swap the compiled Component into WasmComponentPool.
        """
        try:
            # 1. Signature verification (now properly wired — previously a dead stub)
            if self._nkey_verifier is not None:
                if not self._nkey_verifier.verify(binary, signature_b64):
                    logger.warning(
                        "[Agent:patch] Ed25519 verification failed for "
                        "step=%s hash=%s… — discarding", step_name, wasm_hash[:16]
                    )
                    return

            # 2. WASM load-safety gate: check available RAM before loading into JIT
            try:
                import psutil
                available_mb = psutil.virtual_memory().available / (1024 * 1024)
                if available_mb < _MIN_WASM_LOAD_RAM_MB:
                    logger.warning(
                        "[Agent:patch] Insufficient RAM (%.0f MB available, need %d MB) "
                        "for WASM hot-swap — delegating via ruvon.mesh.build.request",
                        available_mb, _MIN_WASM_LOAD_RAM_MB,
                    )
                    if self._transport and self._nats_url:
                        await self._transport.publish_build_request(
                            wasm_hash,
                            {
                                "step_name": step_name,
                                "reason": "insufficient_ram",
                                "available_ram_mb": round(available_mb, 1),
                            },
                        )
                    return
            except ImportError:
                pass  # psutil unavailable — proceed without gate

            # 3. Hot-swap (in-flight calls using the old component complete normally)
            from ruvon.implementations.execution.component_runtime import _get_wasm_pool
            pool = _get_wasm_pool()
            await pool.swap_module(wasm_hash, binary)
            logger.info(
                "[Agent:patch] Hot-swapped WASM component for step=%s hash=%s…",
                step_name, wasm_hash[:16],
            )
        except Exception as e:
            logger.error("[Agent:patch] Failed to apply WASM patch: %s", e)

    async def _on_build_request(self, data: bytes) -> None:
        """Handle a WASM build delegation request (Tier 2+ nodes only).

        When a Tier 1 node lacks RAM to load a WASM binary, it publishes its
        request here.  This node fetches the binary from the cloud (via the
        normal ConfigManager download path), then re-broadcasts it on
        ruvon.node.patch so the requesting peer (and the whole fleet) gets it.
        """
        try:
            payload = json.loads(data)
        except Exception as e:
            logger.debug("[Agent:build] Malformed build request: %s", e)
            return

        wasm_hash = payload.get("wasm_hash", "")
        step_name = payload.get("step_name", "unknown")
        requester = payload.get("requesting_device_id", "unknown")

        if not wasm_hash:
            return

        logger.info(
            "[Agent:build] Build delegation request from %s for hash=%s… step=%s",
            requester, wasm_hash[:16], step_name,
        )

        if self.config_manager is None:
            return

        # Download and cache binary (idempotent — skips if already cached)
        success = await self.config_manager.handle_sync_wasm_command(
            {"binary_hash": wasm_hash}
        )
        if not success:
            # Already cached — still re-broadcast so requester gets it
            pass

        binary = await self._load_wasm_from_cache(wasm_hash)
        if binary is None:
            logger.warning(
                "[Agent:build] Could not load binary for hash=%s… — cannot relay",
                wasm_hash[:16],
            )
            return

        if self._transport and self._nats_url:
            import base64
            payload_out = json.dumps({
                "wasm_hash": wasm_hash,
                "binary_b64": base64.b64encode(binary).decode(),
                "step_name": step_name,
                "signature_b64": "",  # Signing by build node out-of-scope here
            }).encode()
            try:
                await self._transport._nc.publish("ruvon.node.patch", payload_out)
                logger.info(
                    "[Agent:build] Re-broadcast compiled binary for hash=%s… (%d bytes)",
                    wasm_hash[:16], len(binary),
                )
            except Exception as e:
                logger.error("[Agent:build] Re-broadcast failed: %s", e)

    async def _load_wasm_from_cache(self, wasm_hash: str) -> Optional[bytes]:
        """Read a cached WASM binary from device_wasm_cache. Returns None if absent."""
        if self.persistence is None:
            return None
        try:
            cursor = await self.persistence.conn.execute(
                "SELECT binary_data FROM device_wasm_cache WHERE binary_hash = ?",
                (wasm_hash,),
            )
            row = await cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.debug("[Agent] wasm cache read failed: %s", e)
            return None

    def _detect_node_tier(self) -> NodeTier:
        """Classify this device's NodeTier from live hardware metrics."""
        ram_total_mb = 0.0
        accelerators = []
        try:
            import psutil
            ram_total_mb = psutil.virtual_memory().total / (1024 * 1024)
        except Exception:
            pass
        try:
            from ruvon.utils.platform import detect_accelerators
            accelerators = detect_accelerators()
        except Exception:
            pass
        tier = classify_node_tier(ram_total_mb, accelerators)
        logger.info(
            "[Agent] Hardware tier: %s (RAM=%.0f MB accelerators=%s)",
            tier.value, ram_total_mb, [a if isinstance(a, str) else a.value for a in accelerators],
        )
        return tier

    async def _get_effective_peer_urls(self) -> list:
        """
        Return the current peer URL list for RUVON routing.

        Priority:
          1. Cloud-fetched peer list (cached in edge_sync_state "mesh_peer_urls")
          2. Static peer_urls from constructor config

        The cached list is refreshed every sync cycle when online.
        When offline, the last-known list from SQLite ensures continuity.
        """
        if self.persistence:
            try:
                raw = await self.persistence.get_edge_sync_state("mesh_peer_urls")
                if raw:
                    cached = json.loads(raw)
                    if cached:
                        return cached
            except Exception:
                pass
        return self._peer_urls

    def _log_heartbeat_failure(self, reason: str):
        """Graduated heartbeat failure logging."""
        n = self._heartbeat_consecutive_failures
        if n == 1:
            logger.warning(
                f"Heartbeat failed for device {self.device_id}: {reason}"
            )
        elif n % 10 == 0:
            logger.error(
                f"Device {self.device_id} is invisible to cloud control plane "
                f"({n} consecutive heartbeat failures). Last error: {reason}"
            )

    async def _register_relay_server(self):
        """
        POST relay server URL to cloud so peers can discover this device.

        Idempotent: compares the current host against the last-registered value
        stored in edge_sync_state key "relay_server_host". Re-registers only when
        the host has changed (e.g. DHCP lease renewal assigned a new IP), so the
        cloud always holds a fresh URL.

        Called once at startup (via asyncio.create_task) and then on every online
        sync cycle via _refresh_mesh_peers(), making DHCP IP rotation self-healing
        within one sync interval.
        """
        import httpx
        import socket
        try:
            # Prefer the outbound IP over FQDN — more reliable on LAN when DHCP
            # assigns a new address without updating reverse-DNS.
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))   # doesn't send packets; just resolves route
                host = s.getsockname()[0]
                s.close()
            except Exception:
                host = socket.getfqdn()  # fallback for air-gapped / loopback-only hosts

            # Skip cloud round-trip if the registered host hasn't changed
            if self.persistence:
                cached_host = await self.persistence.get_edge_sync_state("relay_server_host")
                if cached_host == host:
                    return

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/relay-server",
                    json={"host": host, "port": self._peer_listen_port},
                    headers={"X-API-Key": self.api_key},
                )
            if resp.status_code == 200:
                logger.info(
                    f"[RUVON] Relay server registered: {host}:{self._peer_listen_port}"
                )
                # Cache so subsequent calls are no-ops when IP is stable
                if self.persistence:
                    await self.persistence.set_edge_sync_state("relay_server_host", host)
            else:
                logger.warning(
                    f"[RUVON] Relay server registration returned {resp.status_code}"
                )
        except Exception as e:
            logger.debug(f"[RUVON] Relay server registration failed: {e}")

    async def _refresh_mesh_peers(self):
        """
        Fetch active relay peers from cloud and cache to edge_sync_state.

        Also re-checks this device's own relay server URL on every call so that
        DHCP IP changes are self-healing within one sync interval — _register_relay_server()
        is a no-op when the IP is stable (SQLite read only) and re-registers when it changes.
        """
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/mesh-peers",
                    headers={"X-API-Key": self.api_key},
                )
            if resp.status_code == 200:
                peers = resp.json().get("peers", [])
                peer_urls = [p["relay_url"] for p in peers if p.get("relay_url")]
                if self.persistence:
                    await self.persistence.set_edge_sync_state(
                        "mesh_peer_urls", json.dumps(peer_urls)
                    )
                if peer_urls:
                    logger.debug(f"[RUVON] Refreshed mesh peers: {peer_urls}")
        except Exception as e:
            logger.debug(f"[RUVON] Mesh peer refresh failed: {e}")

        # Re-register relay server URL each cycle — detects DHCP IP rotation
        if self._peer_listen_port > 0:
            await self._register_relay_server()

    def _compute_leadership_score(self) -> float:
        """
        Compute RUVON leadership score for Local Master election.

        S_lead = 0.50·P + 0.25·C + 0.25·U

        P = Power:    1.0 if AC/wall power, else battery% / 100 (0.5 if unknown)
        C = CPU:      1.0 - cpu_fraction (0.5 if psutil unavailable)
        U = Uptime:   min(seconds_since_start / 86400, 1.0)

        A device on wall power, low CPU, and running for a full day scores ≈ 1.0.
        A phone at 20% battery with 90% CPU scores ≈ 0.125.
        """
        # P — power source
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is None or battery.power_plugged:
                P = 1.0
            else:
                P = battery.percent / 100.0
        except Exception:
            P = 0.5  # unknown — assume moderate

        # C — available CPU
        try:
            import psutil
            cpu_fraction = psutil.cpu_percent(interval=None) / 100.0
            C = 1.0 - cpu_fraction
        except Exception:
            C = 0.5  # unknown — assume moderate

        # U — uptime stability (time since agent.start(), capped at 1 day)
        uptime_secs = time.monotonic() - self._agent_start_time
        U = min(uptime_secs / 86400.0, 1.0)

        score = round(0.50 * P + 0.25 * C + 0.25 * U, 4)
        return score

    async def _run_election(self) -> None:
        """
        RUVON Local Master election protocol.

        1. Compute S_lead for this device.
        2. Send leadership CLAIM to all known 1-hop peers concurrently.
        3. Wait for responses (1s httpx timeout per peer).
        4. If any peer rejects the claim (they have a higher score): yield to them.
        5. Device-ID-seeded backoff before self-promotion prevents dual-master on
           equal scores (lower device_id wins the tie deterministically).
        6. Persist election outcome to edge_sync_state.
        """
        if self._is_local_master:
            return  # already master — nothing to do

        peers = await self._get_effective_peer_urls()
        if not peers:
            # Island scenario — no peers reachable, self-promote immediately
            await self._promote_to_master(self._compute_leadership_score())
            return

        my_score = self._compute_leadership_score()
        logger.info(
            f"[RUVON] Election initiated — S_lead={my_score:.3f} "
            f"peers={len(peers)}"
        )

        # Device-ID-seeded backoff: 100–500ms (deterministic per device)
        seed = int(hashlib.sha256(self.device_id.encode()).hexdigest()[:8], 16)
        backoff_secs = (100 + (seed % 400)) / 1000.0

        # Send claims concurrently and collect responses
        from ruvon_edge.peer_relay import PeerRelayClient
        client = PeerRelayClient()
        results = await asyncio.gather(
            *[
                client.send_election_claim(url, self.device_id, my_score)
                for url in peers
            ],
            return_exceptions=True,
        )

        # Evaluate responses — any rejection means a peer has a higher score
        beaten = False
        for result in results:
            if isinstance(result, Exception) or result is None:
                continue  # unreachable peer doesn't block election
            if not result.get("accepted", True):
                peer_score = result.get("my_score", 0.0)
                peer_id = result.get("my_device_id", "")
                # Confirm the peer truly outranks us (re-apply tie-break logic)
                if peer_score > my_score or (
                    peer_score == my_score and peer_id < self.device_id
                ):
                    logger.info(
                        f"[RUVON] Yielding to {peer_id} (score={peer_score:.3f})"
                    )
                    self._local_master_id = peer_id
                    beaten = True
                    break

        # Backoff before self-promotion (gives higher-score peers time to claim first)
        await asyncio.sleep(backoff_secs)

        if not beaten:
            await self._promote_to_master(my_score)

    async def _promote_to_master(self, score: float = 0.0) -> None:
        """Claim local master role and persist to edge_sync_state."""
        self._is_local_master = True
        self._local_master_id = self.device_id
        logger.info(
            f"[RUVON] Leadership claimed: device={self.device_id} score={score:.3f}"
        )
        if self.persistence:
            await self.persistence.set_edge_sync_state("i_am_master", "true")
            await self.persistence.set_edge_sync_state("local_master_id", self.device_id)

    async def _abdicate(self) -> None:
        """Relinquish local master role when cloud connectivity is restored."""
        self._is_local_master = False
        self._local_master_id = None
        logger.info("[RUVON] Abdicating — cloud reconnected")
        if self.persistence:
            await self.persistence.set_edge_sync_state("i_am_master", "false")
            await self.persistence.set_edge_sync_state("local_master_id", "")

    def _reload_wasm_resolver(self) -> None:
        """Re-instantiate the WASM resolver against the live SQLite connection.

        aiosqlite.Connection rows are immediately visible after INSERT, so
        re-instantiation is only needed to pick up a fresh conn reference if
        persistence was re-initialized.  Called after a successful sync_wasm
        command to ensure new WASM binaries are available to the next workflow.
        """
        if self.persistence and self.persistence.conn:
            from ruvon.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver
            self._wasm_resolver = SqliteWasmBinaryResolver(self.persistence.conn)

    def register_command_handler(self, command_type: str, handler) -> None:
        """Register an async handler for a cloud command type.

        handler: async def handler(cmd_data: dict) -> None
        """
        self._custom_command_handlers[command_type] = handler
        logger.info(f"Registered custom command handler for: {command_type}")

    async def _handle_cloud_command(self, command: Dict[str, Any]):
        """Handle a command received from cloud via heartbeat response."""
        cmd_type = command.get("command_type", "")
        cmd_data = command.get("command_data", {})
        logger.info(f"Received cloud command: {cmd_type}")

        if cmd_type == "force_sync":
            if self.sync_manager:
                await self.sync_manager.sync_all_pending()
            if self.workflow_syncer:
                result = await self.workflow_syncer.sync()
                logger.info(f"force_sync: workflow sync result: {result}")
        elif cmd_type == "reload_config":
            if self.config_manager:
                await self.config_manager.pull_config()
        elif cmd_type == "update_workflow":
            if self.config_manager:
                success = await self.config_manager.handle_update_workflow_command(
                    payload=cmd_data,
                    workflow_builder=self.workflow_builder,
                )
                logger.info(f"update_workflow command handled: {success}")
        elif cmd_type == "update_model":
            model_name = cmd_data.get("model_name")
            if model_name and self.config_manager:
                logger.info(f"Cloud requested model update: {model_name}")
        elif cmd_type == "sync_wasm":
            if self.config_manager:
                await self.config_manager.handle_sync_wasm_command(cmd_data)
                self._reload_wasm_resolver()
            else:
                logger.warning("sync_wasm command received but config_manager is not set")
        elif cmd_type in self._custom_command_handlers:
            try:
                await self._custom_command_handlers[cmd_type](cmd_data)
            except Exception as exc:
                logger.error(f"Custom handler for {cmd_type} raised: {exc}")
        else:
            logger.warning(f"Unknown cloud command: {cmd_type}")
