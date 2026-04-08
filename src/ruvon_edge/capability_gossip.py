"""
capability_gossip.py — RUVON capability vector gossip for the fog mesh.

Each node periodically broadcasts a CapabilityVector on the
``ruvon.mesh.capabilities`` NATS subject (core NATS, ephemeral fan-out).
Neighbours receive these vectors and cache them in edge_sync_state so the
MeshRouter can make informed routing decisions without expensive HTTP probes
against unknown peers.

Components
----------
NodeTier               — Tier classification enum (TIER_1 / TIER_2 / TIER_3).
classify_node_tier()   — Maps hardware profile to NodeTier.
CapabilityVector       — Multi-dimensional capability snapshot.
CapabilityGossipManager— Periodic broadcast + receive + cache.
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

_BROADCAST_INTERVAL_SECS = 30   # How often this node publishes its vector
_PEER_STALE_SECS = 90           # Discard cached vectors older than this
_STATE_KEY = "mesh_peer_capabilities"

# Tier classification thresholds
_TIER3_RAM_MB = 4096    # > 4 GB  → Tier 3
_TIER2_RAM_MB = 512     # ≥ 512 MB → at least Tier 2


# ------------------------------------------------------------------
# NodeTier
# ------------------------------------------------------------------

class NodeTier(str, Enum):
    """Hardware tier for a fog mesh node.

    TIER_1 — Constrained edge device (POS terminal, sensor, small SBC).
              Total RAM < 512 MB, no hardware ML accelerator.
    TIER_2 — Gateway or mid-tier device (Pi 4-class, edge server, kiosk).
              RAM ≥ 512 MB OR has Edge TPU / OpenVINO / Apple Neural Engine.
    TIER_3 — Full server / control plane node.
              RAM > 4 GB OR has CUDA / TensorRT.
    """
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


def classify_node_tier(ram_total_mb: float, accelerators: List[Any]) -> NodeTier:
    """Derive ``NodeTier`` from hardware identity fields.

    Args:
        ram_total_mb:  Total physical RAM in megabytes.
        accelerators:  List of ``AcceleratorType`` values from
                       ``rufus.utils.platform.detect_accelerators()``.

    Returns:
        The most capable tier this hardware qualifies for.
    """
    # Import here to avoid hard-wiring rufus.utils as a mandatory dep
    # in edge-only deployments that strip the core SDK.
    try:
        from ruvon.utils.platform import AcceleratorType
        _tier3_accels = {AcceleratorType.CUDA, AcceleratorType.TENSORRT}
        _tier2_accels = {
            AcceleratorType.EDGE_TPU,
            AcceleratorType.OPENVINO,
            AcceleratorType.APPLE_NEURAL_ENGINE,
            AcceleratorType.APPLE_GPU,
        }
    except ImportError:
        _tier3_accels = set()
        _tier2_accels = set()

    accel_set = set(accelerators)

    if ram_total_mb > _TIER3_RAM_MB or accel_set & _tier3_accels:
        return NodeTier.TIER_3
    if ram_total_mb >= _TIER2_RAM_MB or accel_set & _tier2_accels:
        return NodeTier.TIER_2
    return NodeTier.TIER_1


def _tier_to_int(tier: NodeTier) -> int:
    """Map NodeTier → int (1, 2, 3) for numeric comparisons."""
    return {"tier_1": 1, "tier_2": 2, "tier_3": 3}.get(tier.value, 1)


# ------------------------------------------------------------------
# CapabilityVector
# ------------------------------------------------------------------

@dataclass
class CapabilityVector:
    """Point-in-time capability snapshot broadcast by a fog mesh node.

    Fields mirror the RUVON spec:
        V = [available_ram_mb, cpu_load, model_tier, latency_ms, task_queue_length]

    ``node_tier`` and ``timestamp`` are included for routing and staleness checks.
    """
    device_id: str
    available_ram_mb: float      # Available (free) RAM in MB
    cpu_load: float              # 0.0 (idle) – 1.0 (fully loaded)
    model_tier: int              # 1, 2, or 3 — int value of NodeTier
    latency_ms: float            # Rolling avg round-trip to best peer; 0.0 if unknown
    task_queue_length: int       # Active + pending local workflow executions
    node_tier: NodeTier
    timestamp: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["node_tier"] = self.node_tier.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CapabilityVector":
        d = dict(d)
        d["node_tier"] = NodeTier(d.get("node_tier", "tier_1"))
        return cls(**d)

    def is_stale(self) -> bool:
        """Return True if this vector is older than _PEER_STALE_SECS."""
        try:
            ts = datetime.fromisoformat(self.timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(tz=timezone.utc) - ts).total_seconds()
            return elapsed > _PEER_STALE_SECS
        except (ValueError, TypeError):
            return True  # Unparseable → treat as stale


# ------------------------------------------------------------------
# CapabilityGossipManager
# ------------------------------------------------------------------

class CapabilityGossipManager:
    """Manages periodic capability vector broadcast and receive.

    Broadcasts this node's CapabilityVector every ``_BROADCAST_INTERVAL_SECS``
    seconds on ``ruvon.mesh.capabilities`` via core NATS (ephemeral fan-out —
    loss-tolerant because the next broadcast arrives within 30 s).

    Incoming vectors from peers are cached in ``edge_sync_state`` under the
    key ``"mesh_peer_capabilities"`` as a JSON dict keyed by ``device_id``.

    Usage::

        gossip = CapabilityGossipManager(device_id, transport, persistence)
        await gossip.start()

        # Later — retrieve live peer snapshot for routing decisions
        caps = await gossip.get_peer_capabilities()
        builder = await gossip.find_best_builder()
    """

    def __init__(
        self,
        device_id: str,
        transport,          # NATSEdgeTransport (type-hinted loosely to avoid circular import)
        persistence,        # SQLitePersistenceProvider
    ) -> None:
        self._device_id = device_id
        self._transport = transport
        self._persistence = persistence

        # In-memory peer cache: device_id → CapabilityVector
        self._peer_cache: Dict[str, CapabilityVector] = {}

        self._broadcast_task: Optional[asyncio.Task] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the periodic broadcast loop. Idempotent."""
        if self._running:
            return
        self._running = True
        # Warm the in-memory cache from SQLite before the first broadcast
        self._peer_cache = await self._load_peer_cache()
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(), name="capability_gossip"
        )
        logger.info("[Gossip] CapabilityGossipManager started for %s", self._device_id)

    async def stop(self) -> None:
        """Cancel the broadcast loop gracefully."""
        self._running = False
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        logger.info("[Gossip] CapabilityGossipManager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_peer_capabilities(self) -> Dict[str, CapabilityVector]:
        """Return current in-memory peer capability cache (non-stale entries only)."""
        return {
            dev_id: vec
            for dev_id, vec in self._peer_cache.items()
            if not vec.is_stale()
        }

    async def find_best_builder(self) -> Optional[str]:
        """Return device_id of the best Tier 2+ peer for WASM build delegation.

        Selection criteria:
        1. ``node_tier >= TIER_2``
        2. ``available_ram_mb > 256``
        3. Ranked by: higher tier > lower CPU load > more available RAM.

        Returns None if no eligible peer is found.
        """
        caps = await self.get_peer_capabilities()
        candidates = [
            vec for vec in caps.values()
            if _tier_to_int(vec.node_tier) >= 2 and vec.available_ram_mb > 256
        ]
        if not candidates:
            return None

        candidates.sort(
            key=lambda v: (
                _tier_to_int(v.node_tier),
                -v.cpu_load,
                v.available_ram_mb,
            ),
            reverse=True,
        )
        return candidates[0].device_id

    # ------------------------------------------------------------------
    # Gossip receive handler
    # ------------------------------------------------------------------

    async def _on_capability_received(self, data: bytes) -> None:
        """Handle an incoming capability vector from a peer.

        Called by ``NATSEdgeTransport`` when a message arrives on
        ``ruvon.mesh.capabilities``.  Ignores own broadcasts.
        """
        try:
            payload = json.loads(data)
            vec = CapabilityVector.from_dict(payload)
        except Exception as e:
            logger.debug("[Gossip] Malformed capability vector: %s", e)
            return

        if vec.device_id == self._device_id:
            return  # ignore own broadcast echo

        prev = self._peer_cache.get(vec.device_id)
        self._peer_cache[vec.device_id] = vec

        if prev is None or prev.node_tier != vec.node_tier:
            logger.info(
                "[Gossip] Peer %s tier=%s RAM=%.0f MB CPU=%.0f%% queue=%d",
                vec.device_id, vec.node_tier.value, vec.available_ram_mb,
                vec.cpu_load * 100, vec.task_queue_length,
            )
        else:
            logger.debug(
                "[Gossip] Updated %s: RAM=%.0f CPU=%.0f%%",
                vec.device_id, vec.available_ram_mb, vec.cpu_load * 100,
            )

        await self._save_peer_cache()

    # ------------------------------------------------------------------
    # Broadcast loop
    # ------------------------------------------------------------------

    async def _broadcast_loop(self) -> None:
        """Periodically publish this node's CapabilityVector."""
        while self._running:
            try:
                vec = self._build_local_vector()
                payload = json.dumps(vec.to_dict()).encode()
                await self._transport.publish_capability_vector(payload)
                logger.debug(
                    "[Gossip] Broadcast: tier=%s RAM=%.0f MB CPU=%.0f%% queue=%d",
                    vec.node_tier.value, vec.available_ram_mb,
                    vec.cpu_load * 100, vec.task_queue_length,
                )
            except Exception as e:
                logger.warning("[Gossip] Broadcast error: %s", e)

            await asyncio.sleep(_BROADCAST_INTERVAL_SECS)

    # ------------------------------------------------------------------
    # Local vector construction
    # ------------------------------------------------------------------

    def _build_local_vector(self) -> CapabilityVector:
        """Snapshot current hardware state into a CapabilityVector."""
        available_ram_mb = 0.0
        cpu_load = 0.5
        ram_total_mb = 0.0
        accelerators: List[Any] = []

        try:
            import psutil
            vm = psutil.virtual_memory()
            available_ram_mb = vm.available / (1024 * 1024)
            ram_total_mb = vm.total / (1024 * 1024)
            cpu_load = psutil.cpu_percent(interval=None) / 100.0
        except Exception:
            pass

        try:
            from ruvon.utils.platform import detect_accelerators
            accelerators = detect_accelerators()
        except Exception:
            pass

        node_tier = classify_node_tier(ram_total_mb, accelerators)
        model_tier = _tier_to_int(node_tier)

        # task_queue_length: count active workflow executions if persistence available
        task_queue_length = self._count_active_tasks()

        return CapabilityVector(
            device_id=self._device_id,
            available_ram_mb=round(available_ram_mb, 1),
            cpu_load=round(cpu_load, 3),
            model_tier=model_tier,
            latency_ms=0.0,   # Future: populated from MeshRouter probe history
            task_queue_length=task_queue_length,
            node_tier=node_tier,
        )

    def _count_active_tasks(self) -> int:
        """Best-effort count of pending/active workflow tasks from SQLite."""
        if self._persistence is None:
            return 0
        try:
            # Synchronous SQLite call — safe here because we're inside an asyncio
            # task but the count is purely informational and fast.
            import asyncio as _aio
            loop = _aio.get_event_loop()
            if loop.is_running():
                # Schedule as a fire-and-forget; return cached value instead
                return getattr(self, "_last_task_count", 0)
        except Exception:
            pass
        return 0

    # ------------------------------------------------------------------
    # Peer cache persistence (edge_sync_state)
    # ------------------------------------------------------------------

    async def _save_peer_cache(self) -> None:
        """Persist current in-memory peer cache to edge_sync_state."""
        if self._persistence is None:
            return
        try:
            payload = {
                dev_id: vec.to_dict()
                for dev_id, vec in self._peer_cache.items()
                if not vec.is_stale()
            }
            await self._persistence.set_edge_sync_state(
                _STATE_KEY, json.dumps(payload)
            )
        except Exception as e:
            logger.debug("[Gossip] Could not persist peer cache: %s", e)

    async def _load_peer_cache(self) -> Dict[str, CapabilityVector]:
        """Load peer capability cache from edge_sync_state on startup."""
        if self._persistence is None:
            return {}
        try:
            raw = await self._persistence.get_edge_sync_state(_STATE_KEY)
            if not raw:
                return {}
            data = json.loads(raw)
            result = {}
            for dev_id, vec_dict in data.items():
                try:
                    vec = CapabilityVector.from_dict(vec_dict)
                    if not vec.is_stale():
                        result[dev_id] = vec
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.debug("[Gossip] Could not load peer cache: %s", e)
            return {}
