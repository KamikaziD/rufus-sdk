"""
echoforge_gossip.py — EchoForge aliveness gossip for the fog mesh.

Extends the RUVON capability gossip layer with a second gossip channel for
trading pattern aliveness scores.  Each node periodically broadcasts a
``SharedEcho`` on the ``ruvon.echoforge.aliveness`` NATS subject (core NATS,
ephemeral fan-out — same pattern as capability_gossip.py).

Privacy guarantee: only ``pattern_id``, ``net_aliveness``, ``regime_tag``,
and ``decay_rate`` are gossiped.  No trade history, balances, order IDs, API
keys, or PII ever leave the local node.

Security: outbound ``SharedEcho`` messages are signed with ``NKeyPatchSigner``
when ``RUFUS_NKEY_PRIVATE_KEY`` is configured.  Inbound messages are verified
with ``NKeyPatchVerifier`` when ``RUFUS_NKEY_PUBLIC_KEY`` is configured.
Messages that fail verification are discarded silently.

Components
----------
RegimeTag               — Volatility/toxicity regime enum.
SharedEcho              — Privacy-safe pattern aliveness snapshot.
EchoForgeGossipManager  — Periodic broadcast + receive + in-memory cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

_BROADCAST_INTERVAL_SECS = 20   # How often this node publishes its echoes
_ECHO_STALE_SECS = 60           # Discard cached echoes older than this
_STATE_KEY = "echoforge_peer_echoes"
_NATS_SUBJECT = "ruvon.echoforge.aliveness"


# ------------------------------------------------------------------
# RegimeTag
# ------------------------------------------------------------------

class RegimeTag(str, Enum):
    """Volatility/toxicity regime classification for a trading pattern.

    LOW_VOL  — Quiet market; wider spreads, slower decay.
    HIGH_VOL — Active market; tighter spreads, faster execution.
    TOXIC    — Adverse selection detected (high VPIN); pattern paused.
    UNKNOWN  — Regime not yet classified (startup / insufficient data).
    """
    LOW_VOL  = "LowVol"
    HIGH_VOL = "HighVol"
    TOXIC    = "Toxic"
    UNKNOWN  = "Unknown"


# ------------------------------------------------------------------
# SharedEcho
# ------------------------------------------------------------------

@dataclass
class SharedEcho:
    """Privacy-safe pattern aliveness snapshot gossiped across the PFN.

    Only aggregated, non-identifiable fields are included.  The full
    ``MarketEcho`` (with trade history, delta predictions, etc.) stays
    local on each node.

    Fields
    ------
    pattern_id   : Deterministic hash of the pattern definition (not a trade ID).
    net_aliveness: Bayesian reinforcement score 0.0–1.0. Higher = more alive.
    regime_tag   : Current volatility/toxicity classification.
    decay_rate   : Bayesian α parameter — how fast this echo adapts (0.0–1.0).
    node_id      : Sender identifier (device_id of the originating node).
    timestamp    : ISO-8601 UTC emission time.
    """
    pattern_id:    str
    net_aliveness: float
    regime_tag:    RegimeTag
    decay_rate:    float
    node_id:       str
    timestamp:     str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["regime_tag"] = self.regime_tag.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SharedEcho":
        d = dict(d)
        d["regime_tag"] = RegimeTag(d.get("regime_tag", RegimeTag.UNKNOWN.value))
        return cls(**d)

    def is_stale(self) -> bool:
        """Return True if this echo is older than ``_ECHO_STALE_SECS``."""
        try:
            ts = datetime.fromisoformat(self.timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (datetime.now(tz=timezone.utc) - ts).total_seconds() > _ECHO_STALE_SECS
        except (ValueError, TypeError):
            return True


# ------------------------------------------------------------------
# EchoForgeGossipManager
# ------------------------------------------------------------------

class EchoForgeGossipManager:
    """Manages periodic SharedEcho broadcast and receive for the EchoForge PFN.

    Broadcasts each locally active echo every ``_BROADCAST_INTERVAL_SECS``
    seconds on ``ruvon.echoforge.aliveness`` via core NATS (ephemeral fan-out).

    Incoming echoes from peers are cached in memory (and optionally persisted
    to ``edge_sync_state``) keyed by ``(node_id, pattern_id)``.

    Usage::

        gossip = EchoForgeGossipManager(
            node_id=device_id,
            transport=nats_transport,
            persistence=sqlite_persistence,   # optional
        )
        await gossip.start()

        # Register active echoes from the local decay engine
        gossip.set_local_echoes([echo1, echo2, ...])

        # Retrieve live peer snapshots for quorum consensus
        peer_echoes = await gossip.get_peer_echoes()
        regime = await gossip.quorum_regime()
    """

    def __init__(
        self,
        node_id: str,
        transport,          # NATSEdgeTransport (loose type to avoid circular import)
        persistence=None,   # SQLitePersistenceProvider (optional)
        signer=None,        # NKeyPatchSigner (optional)
        verifier=None,      # NKeyPatchVerifier (optional)
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._persistence = persistence
        self._signer = signer
        self._verifier = verifier

        # Local echoes this node produces (set by the decay engine)
        self._local_echoes: List[SharedEcho] = []

        # Peer cache: (node_id, pattern_id) → SharedEcho
        self._peer_cache: Dict[tuple, SharedEcho] = {}

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
        self._peer_cache = await self._load_peer_cache()
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(), name="echoforge_gossip"
        )
        logger.info("[EchoForge] EchoForgeGossipManager started for %s", self._node_id)

    async def stop(self) -> None:
        """Cancel the broadcast loop gracefully."""
        self._running = False
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        logger.info("[EchoForge] EchoForgeGossipManager stopped")

    # ------------------------------------------------------------------
    # Local echo registration
    # ------------------------------------------------------------------

    def set_local_echoes(self, echoes: List[SharedEcho]) -> None:
        """Replace the set of echoes this node broadcasts.

        Called by the local decay engine whenever aliveness scores are updated.
        Only echoes with ``node_id == self._node_id`` are accepted.
        """
        self._local_echoes = [
            e for e in echoes if e.node_id == self._node_id
        ]

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    async def get_peer_echoes(self) -> Dict[tuple, SharedEcho]:
        """Return non-stale peer echoes keyed by ``(node_id, pattern_id)``."""
        return {
            key: echo
            for key, echo in self._peer_cache.items()
            if not echo.is_stale()
        }

    async def quorum_regime(self, min_nodes: int = 2) -> Optional[RegimeTag]:
        """Return the majority ``RegimeTag`` across all live peers.

        Uses simple majority vote weighted by ``net_aliveness``.
        Returns ``None`` if fewer than ``min_nodes`` are reachable.
        """
        peers = await self.get_peer_echoes()
        if not peers:
            return None

        node_ids = {echo.node_id for echo in peers.values()}
        if len(node_ids) < min_nodes:
            return None

        # Weighted vote: each echo contributes its net_aliveness to its regime
        weights: Dict[RegimeTag, float] = {}
        for echo in peers.values():
            weights[echo.regime_tag] = (
                weights.get(echo.regime_tag, 0.0) + echo.net_aliveness
            )

        return max(weights, key=lambda r: weights[r])

    async def get_aliveness_for_pattern(self, pattern_id: str) -> float:
        """Return the average peer aliveness for a given pattern_id.

        Returns 0.0 if no peers are reporting on this pattern.
        """
        peers = await self.get_peer_echoes()
        scores = [
            echo.net_aliveness
            for (_, pid), echo in peers.items()
            if pid == pattern_id and not echo.is_stale()
        ]
        return sum(scores) / len(scores) if scores else 0.0

    # ------------------------------------------------------------------
    # Incoming gossip handler
    # ------------------------------------------------------------------

    async def _on_echo_received(self, data: bytes) -> None:
        """Handle an incoming SharedEcho from a peer.

        Called by ``NATSEdgeTransport`` when a message arrives on
        ``ruvon.echoforge.aliveness``.  Ignores own broadcasts.
        Verifies Ed25519 signature when verifier is configured.
        """
        try:
            payload = json.loads(data)
        except Exception as e:
            logger.debug("[EchoForge] Malformed gossip payload: %s", e)
            return

        # Signature verification (when configured)
        sig_b64 = payload.pop("signature_b64", "")
        if self._verifier is not None:
            raw = json.dumps(payload, sort_keys=True).encode()
            if not self._verifier.verify(raw, sig_b64):
                logger.debug("[EchoForge] Rejected echo: bad signature from node=%s",
                             payload.get("node_id", "?"))
                return

        try:
            echo = SharedEcho.from_dict(payload)
        except Exception as e:
            logger.debug("[EchoForge] Could not deserialise SharedEcho: %s", e)
            return

        if echo.node_id == self._node_id:
            return  # ignore own echo

        key = (echo.node_id, echo.pattern_id)
        prev = self._peer_cache.get(key)
        self._peer_cache[key] = echo

        if prev is None:
            logger.info(
                "[EchoForge] New peer echo — node=%s pattern=%s aliveness=%.3f regime=%s",
                echo.node_id, echo.pattern_id, echo.net_aliveness, echo.regime_tag.value,
            )
        else:
            logger.debug(
                "[EchoForge] Updated echo — node=%s pattern=%s aliveness=%.3f",
                echo.node_id, echo.pattern_id, echo.net_aliveness,
            )

        await self._save_peer_cache()

    # ------------------------------------------------------------------
    # Broadcast loop
    # ------------------------------------------------------------------

    async def _broadcast_loop(self) -> None:
        """Periodically publish all local SharedEchoes."""
        while self._running:
            try:
                for echo in list(self._local_echoes):
                    payload = echo.to_dict()

                    # Sign the payload (deterministic key order)
                    if self._signer is not None:
                        raw = json.dumps(payload, sort_keys=True).encode()
                        payload["signature_b64"] = self._signer.sign(raw)
                    else:
                        payload["signature_b64"] = ""

                    await self._transport.publish_echo_aliveness(
                        json.dumps(payload).encode()
                    )
                    logger.debug(
                        "[EchoForge] Broadcast echo pattern=%s aliveness=%.3f regime=%s",
                        echo.pattern_id, echo.net_aliveness, echo.regime_tag.value,
                    )
            except Exception as e:
                logger.warning("[EchoForge] Broadcast error: %s", e)

            await asyncio.sleep(_BROADCAST_INTERVAL_SECS)

    # ------------------------------------------------------------------
    # Peer cache persistence
    # ------------------------------------------------------------------

    async def _save_peer_cache(self) -> None:
        if self._persistence is None:
            return
        try:
            payload = {
                f"{node_id}:{pid}": echo.to_dict()
                for (node_id, pid), echo in self._peer_cache.items()
                if not echo.is_stale()
            }
            await self._persistence.set_edge_sync_state(
                _STATE_KEY, json.dumps(payload)
            )
        except Exception as e:
            logger.debug("[EchoForge] Could not persist peer cache: %s", e)

    async def _load_peer_cache(self) -> Dict[tuple, SharedEcho]:
        if self._persistence is None:
            return {}
        try:
            raw = await self._persistence.get_edge_sync_state(_STATE_KEY)
            if not raw:
                return {}
            data = json.loads(raw)
            result = {}
            for composite_key, echo_dict in data.items():
                try:
                    echo = SharedEcho.from_dict(echo_dict)
                    if not echo.is_stale():
                        result[(echo.node_id, echo.pattern_id)] = echo
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.debug("[EchoForge] Could not load peer cache: %s", e)
            return {}
