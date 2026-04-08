"""
peer_relay.py — RUVON mesh peer relay for offline SAF routing.

Implements Vector-Optimised Networking (RUVON): instead of returning the
first online peer found via BFS, every candidate within 3 hops is scored
using a weighted vector formula:

    S(Vc) = 0.50·C + 0.15·(1/H) + 0.25·U + 0.10·P

Where:
    C = Connectivity quality  (1.0 online, 0.5 degraded, 0.0 offline)
    H = Hop distance          (1, 2, or 3 — inverted so closer is higher)
    U = Uptime/stability      (historical success rate, 0.0–1.0)
    P = Capacity              (1 - relay_load/max, 0.0–1.0)

All candidates are collected, scored, sorted descending, and attempted
in order. A per-peer circuit breaker (stored in edge_sync_state key
"relay_peer_stats") skips peers with ≥3 consecutive failures.

Components:
    PeerStatus        — probe response (extended with vector dimensions)
    RelayResult       — outcome of a successful relay attempt
    PeerRelayClient   — httpx client: probe, get_peers, relay_saf, send_election_claim
    MeshRouter        — RUVON scored routing (replaces greedy BFS)
    create_relay_app  — FastAPI relay server (status, relay SAF, election endpoint)
    PeerRelayServer   — wraps the app in an asyncio background task
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)

# RUVON scoring weights
_WC = 0.50   # Connectivity
_WH = 0.15   # Hop distance (applied as 1/H)
_WU = 0.25   # Uptime/stability
_WP = 0.10   # Capacity

# Circuit breaker thresholds
_CB_THRESHOLD = 3        # consecutive failures before circuit opens
_CB_HALF_OPEN_SECS = 120 # seconds after last_fail before a half-open probe is allowed


@dataclass
class PeerStatus:
    """Response from /peer/status — extended with RUVON vector dimensions."""
    online: bool
    can_relay: bool
    device_id: str
    peer_urls: List[str] = field(default_factory=list)
    # Vector scoring dimensions (Phase 2)
    connectivity_quality: float = 1.0   # 1.0 fully online, 0.5 degraded
    relay_load: int = 0                 # current active relay sessions
    relay_load_max: int = 10            # relay capacity ceiling
    relay_success_rate: float = 1.0    # self-reported historical success rate
    # Tier classification (populated from capability gossip when available)
    node_tier: Optional[str] = None     # "tier_1" / "tier_2" / "tier_3"


@dataclass
class RelayResult:
    accepted_ids: List[str]
    rejected_ids: List[str]
    relay_url: str
    relay_path: List[str] = field(default_factory=list)
    vector_score: float = 0.0           # RUVON score of the winning relay peer


class PeerRelayClient:
    """HTTP client for peer-to-peer relay operations."""

    async def probe(self, peer_url: str) -> Optional[PeerStatus]:
        """GET /peer/status — 2s timeout. Returns None on any error."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{peer_url}/peer/status")
            if resp.status_code == 200:
                data = resp.json()
                return PeerStatus(
                    online=data.get("online", False),
                    can_relay=data.get("can_relay", False),
                    device_id=data.get("device_id", ""),
                    peer_urls=data.get("peer_urls", []),
                    connectivity_quality=float(data.get("connectivity_quality", 1.0)),
                    relay_load=int(data.get("relay_load", 0)),
                    relay_load_max=int(data.get("relay_load_max", 10)),
                    relay_success_rate=float(data.get("relay_success_rate", 1.0)),
                    node_tier=data.get("node_tier"),
                )
        except Exception as e:
            logger.debug(f"[Mesh] Probe failed for {peer_url}: {e}")
        return None

    async def get_peers(self, peer_url: str) -> List[str]:
        """GET /peer/peers — returns peer URL list for BFS expansion."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{peer_url}/peer/peers")
            if resp.status_code == 200:
                return resp.json().get("peer_urls", [])
        except Exception as e:
            logger.debug(f"[Mesh] get_peers failed for {peer_url}: {e}")
        return []

    async def relay_saf(
        self,
        peer_url: str,
        transactions: List[dict],
        source_device_id: str,
        hop_count: int = 1,
    ) -> Optional[RelayResult]:
        """POST /peer/relay/saf — forward signed SAF transactions to a relay peer."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{peer_url}/peer/relay/saf",
                    json={"transactions": transactions, "hop_count": hop_count},
                    headers={"X-Relay-Source": source_device_id},
                )
            if resp.status_code == 200:
                data = resp.json()
                return RelayResult(
                    accepted_ids=[
                        t.get("transaction_id", "")
                        for t in data.get("accepted", [])
                    ],
                    rejected_ids=[
                        t.get("transaction_id", "")
                        for t in data.get("rejected", [])
                    ],
                    relay_url=peer_url,
                    relay_path=[peer_url],
                )
        except Exception as e:
            logger.debug(f"[Mesh] relay_saf failed for {peer_url}: {e}")
        return None

    async def send_election_claim(
        self,
        peer_url: str,
        device_id: str,
        leader_score: float,
    ) -> Optional[dict]:
        """
        POST /peer/election/claim — send leadership claim to a peer.

        Returns the peer's response dict, or None on error.
        Response: {"accepted": bool, "my_score": float, "my_device_id": str}
        """
        import httpx
        from datetime import datetime as _dt
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.post(
                    f"{peer_url}/peer/election/claim",
                    json={
                        "device_id": device_id,
                        "leader_score": leader_score,
                        "timestamp": _dt.utcnow().isoformat(),
                    },
                )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"[Mesh] Election claim to {peer_url} failed: {e}")
        return None


class MeshRouter:
    """
    RUVON scored routing — replaces greedy BFS first-match.

    All relay candidates within 3 hops are probed, scored by the RUVON
    vector formula, then attempted in descending score order. A circuit
    breaker (≥3 consecutive failures) skips persistently unreliable peers.
    """

    def __init__(self, device_id: str, sync_manager, gossip_manager=None):
        self._device_id = device_id
        self._sync_manager = sync_manager
        self._client = PeerRelayClient()
        # Optional CapabilityGossipManager — when present its cached peer data
        # supplements the RUVON P-dimension for peers with no local relay history.
        self._gossip_manager = gossip_manager

    # ------------------------------------------------------------------
    # Per-peer failure tracking (stored in edge_sync_state)
    # ------------------------------------------------------------------

    async def _load_peer_stats(self) -> dict:
        """
        Load per-peer stats from edge_sync_state key "relay_peer_stats".
        Returns a dict keyed by peer URL:
          { "http://pos-002:9001": {"failures": 2, "successes": 8, "last_fail": "..."} }
        """
        persistence = getattr(self._sync_manager, "persistence", None)
        if persistence is None:
            return {}
        try:
            raw = await persistence.get_edge_sync_state("relay_peer_stats")
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"[Mesh] Could not load peer stats: {e}")
        return {}

    async def _save_peer_stats(self, stats: dict) -> None:
        """Persist updated per-peer stats back to edge_sync_state."""
        persistence = getattr(self._sync_manager, "persistence", None)
        if persistence is None:
            return
        try:
            await persistence.set_edge_sync_state(
                "relay_peer_stats", json.dumps(stats)
            )
        except Exception as e:
            logger.debug(f"[Mesh] Could not save peer stats: {e}")

    def _is_circuit_open(self, peer_url: str, stats: dict) -> bool:
        """
        Three-state circuit breaker:

        CLOSED  — failures < threshold → allow all probes
        OPEN    — failures ≥ threshold AND last_fail within half-open window → skip
        HALF-OPEN — failures ≥ threshold BUT last_fail > _CB_HALF_OPEN_SECS ago
                    → allow one probe to test recovery

        A successful half-open probe resets failures (→ CLOSED).
        A failed half-open probe updates last_fail, restarting the cooldown.
        """
        entry = stats.get(peer_url, {})
        if entry.get("failures", 0) < _CB_THRESHOLD:
            return False  # CLOSED

        last_fail_iso = entry.get("last_fail")
        if not last_fail_iso:
            return True   # OPEN (no timestamp — be conservative)

        try:
            last_fail = datetime.fromisoformat(last_fail_iso).replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            elapsed = (now - last_fail).total_seconds()
            if elapsed >= _CB_HALF_OPEN_SECS:
                logger.debug(
                    f"[Mesh] Half-open probe allowed for {peer_url} "
                    f"(last_fail {elapsed:.0f}s ago)"
                )
                return False  # HALF-OPEN — allow one test probe
        except ValueError:
            pass

        return True  # OPEN

    def _record_success(self, peer_url: str, stats: dict) -> None:
        entry = stats.setdefault(peer_url, {"failures": 0, "successes": 0, "last_fail": None})
        entry["failures"] = 0   # reset consecutive counter on success (HALF-OPEN → CLOSED)
        entry["successes"] = entry.get("successes", 0) + 1

    def _record_failure(self, peer_url: str, stats: dict) -> None:
        entry = stats.setdefault(peer_url, {"failures": 0, "successes": 0, "last_fail": None})
        entry["failures"] = entry.get("failures", 0) + 1
        # Updating last_fail restarts the half-open cooldown so a persistently
        # dead peer doesn't spam the mesh with probes every 2 minutes.
        entry["last_fail"] = datetime.now(tz=timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # RUVON vector scoring
    # ------------------------------------------------------------------

    def _score_candidate(
        self,
        status: PeerStatus,
        hop: int,
        peer_url: str,
        peer_stats: dict,
    ) -> float:
        """
        S(Vc) = wc·C + wh·(1/H) + wu·U + wp·P

        C = connectivity_quality  (from /peer/status)
        H = hop distance
        U = historical success rate from local peer_stats (or self-reported fallback)
        P = available capacity = 1 - relay_load/relay_load_max
        """
        C = status.connectivity_quality if status.online else 0.0
        H = max(hop, 1)
        # Prefer locally-tracked stats over self-reported (harder to spoof)
        entry = peer_stats.get(peer_url, {})
        total = entry.get("successes", 0) + entry.get("failures", 0)
        if total > 0:
            U = entry["successes"] / total
        else:
            U = status.relay_success_rate  # fall back to peer self-report
        load_max = max(status.relay_load_max, 1)
        P = 1.0 - min(status.relay_load / load_max, 1.0)

        # Supplement P with gossip-reported capacity when no local relay history
        # exists.  Gossip data is more accurate than self-reported relay_load for
        # peers this node has never actually relayed through.
        if total == 0 and self._gossip_manager is not None:
            peer_caps = self._gossip_manager._peer_cache.get(status.device_id)
            if peer_caps is not None and not peer_caps.is_stale():
                # Blend CPU slack and RAM headroom (both 0.0–1.0) into P
                cpu_slack = max(0.0, 1.0 - peer_caps.cpu_load)
                ram_headroom = min(peer_caps.available_ram_mb / 1024.0, 1.0)
                P = (cpu_slack + ram_headroom) / 2.0

        score = _WC * C + _WH * (1.0 / H) + _WU * U + _WP * P
        logger.debug(
            f"[RUVON] {peer_url} hop={hop} C={C:.2f} U={U:.2f} P={P:.2f} → score={score:.3f}"
        )
        return score

    # ------------------------------------------------------------------
    # Main routing entry point
    # ------------------------------------------------------------------

    async def find_relay(
        self,
        transactions: List[dict],
        known_peers: List[str],
        max_depth: int = 3,
    ) -> Optional[RelayResult]:
        """
        RUVON scored relay selection.

        1. BFS-probes all peers within max_depth hops.
        2. Skips circuit-broken peers (≥3 consecutive failures).
        3. Scores each live candidate with the RUVON formula.
        4. Attempts relays in descending score order.
        5. Records success/failure in edge_sync_state for future cycles.

        Returns RelayResult if a relay was found and transactions forwarded,
        None otherwise (caller keeps transactions in SAF queue).
        """
        peer_stats = await self._load_peer_stats()

        # Phase 1: collect all reachable candidates with their scores
        # ----------------------------------------------------------------
        # candidates: list of (score, hop, peer_url, status)
        candidates: list = []
        visited: set = set()
        frontier: List[str] = list(known_peers)

        for depth in range(1, max_depth + 1):
            next_frontier: List[str] = []

            for peer_url in frontier:
                if peer_url in visited:
                    continue
                visited.add(peer_url)

                # Circuit breaker: skip persistently failing peers
                if self._is_circuit_open(peer_url, peer_stats):
                    logger.debug(f"[Mesh] Circuit open — skipping {peer_url}")
                    continue

                status = await self._client.probe(peer_url)
                if status is None:
                    self._record_failure(peer_url, peer_stats)
                    continue

                if status.can_relay:
                    score = self._score_candidate(status, depth, peer_url, peer_stats)
                    candidates.append((score, depth, peer_url, status))

                # Expand BFS: use peer_urls from status if available, else probe /peer/peers
                peer_peers = status.peer_urls or await self._client.get_peers(peer_url)
                for pp in peer_peers:
                    if pp not in visited:
                        next_frontier.append(pp)

            frontier = next_frontier
            if not frontier:
                break

        if not candidates:
            await self._save_peer_stats(peer_stats)
            return None

        # Phase 2: sort descending by score, attempt in order
        # ----------------------------------------------------------------
        candidates.sort(key=lambda t: t[0], reverse=True)

        for score, depth, peer_url, status in candidates:
            logger.info(
                f"[RUVON] Attempting relay via {peer_url} "
                f"(hop={depth} score={score:.3f})"
            )
            result = await self._client.relay_saf(
                peer_url, transactions, self._device_id, hop_count=depth
            )
            if result:
                result.vector_score = score
                self._record_success(peer_url, peer_stats)
                await self._save_peer_stats(peer_stats)
                logger.info(
                    f"[RUVON] Relay succeeded via {peer_url} "
                    f"score={score:.3f} accepted={len(result.accepted_ids)}"
                )
                return result
            else:
                self._record_failure(peer_url, peer_stats)

        await self._save_peer_stats(peer_stats)
        return None


def create_relay_app(
    sync_manager,
    device_id: str,
    peer_urls: List[str],
    is_online_fn: Callable[[], bool],
    leadership_score_fn: Optional[Callable[[], float]] = None,
    is_master_fn: Optional[Callable[[], bool]] = None,
    node_tier_fn: Optional[Callable[[], Optional[str]]] = None,
):
    """
    Create the FastAPI app for the peer relay server.

    Endpoints:
        GET  /peer/status           → { online, can_relay, device_id, peer_urls,
                                        connectivity_quality, relay_load,
                                        relay_load_max, relay_success_rate,
                                        leader_score, is_local_master }
        GET  /peer/peers            → { peer_urls }
        POST /peer/relay/saf        → accept and forward SAF from a peer
        POST /peer/election/claim   → RUVON leadership claim contest
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Rufus Peer Relay", docs_url=None, redoc_url=None)

    # Track active relay sessions for relay_load reporting
    _relay_load = {"active": 0}

    @app.get("/peer/status")
    async def peer_status():
        online = is_online_fn()
        # connectivity_quality: 1.0 fully online, 0.0 offline
        # (future: 0.5 for degraded/cellular link via transport quality)
        connectivity_quality = 1.0 if online else 0.0
        return {
            "online": online,
            "can_relay": online,
            "device_id": device_id,
            "peer_urls": peer_urls,
            "connectivity_quality": connectivity_quality,
            "relay_load": _relay_load["active"],
            "relay_load_max": 10,
            "relay_success_rate": 1.0,  # self-reported; remotes use local stats
            "leader_score": leadership_score_fn() if leadership_score_fn else 0.0,
            "is_local_master": is_master_fn() if is_master_fn else False,
            "node_tier": node_tier_fn() if node_tier_fn else None,
        }

    @app.get("/peer/peers")
    async def peer_peers():
        return {"peer_urls": peer_urls}

    @app.post("/peer/relay/saf")
    async def relay_saf(request: Request):
        from datetime import datetime as _dt
        source = request.headers.get("X-Relay-Source", "unknown")
        body = await request.json()
        transactions = body.get("transactions", [])
        hop_count = body.get("hop_count", 1)

        if not transactions:
            return JSONResponse({"accepted": [], "rejected": []})

        logger.info(
            f"[Mesh] Inbound relay from {source}: {len(transactions)} txn(s)"
        )

        _relay_load["active"] += 1
        relay_metadata = {
            "relay_device_id": device_id,
            "hop_count": hop_count,
            "relayed_at": _dt.utcnow().isoformat(),
        }

        try:
            result = await sync_manager.sync_batch_direct(transactions, relay_metadata=relay_metadata)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"[Mesh] Relay sync_batch_direct failed: {e}")
            return JSONResponse(
                {
                    "accepted": [],
                    "rejected": [
                        {"transaction_id": t.get("transaction_id", ""), "reason": str(e)}
                        for t in transactions
                    ],
                },
                status_code=500,
            )
        finally:
            _relay_load["active"] = max(0, _relay_load["active"] - 1)

    @app.post("/peer/election/claim")
    async def election_claim(request: Request):
        """
        RUVON leadership claim contest.

        Accepts a claim from a peer and responds with acceptance or rejection
        based on this device's own leadership score.

        Accept  → incoming score > my score  (or equal score, lower device_id wins)
        Reject  → my score > incoming score  (send back my score so peer can yield)
        """
        body = await request.json()
        incoming_device_id = body.get("device_id", "")
        incoming_score = float(body.get("leader_score", 0.0))

        my_score = leadership_score_fn() if leadership_score_fn else 0.0

        # Deterministic tie-break: lexicographically lower device_id wins
        # (ensures two equal-score devices always elect the same one)
        incoming_wins = incoming_score > my_score or (
            incoming_score == my_score and incoming_device_id < device_id
        )

        if incoming_wins:
            logger.info(
                f"[RUVON] Accepted claim from {incoming_device_id} "
                f"(score={incoming_score:.3f} beats mine={my_score:.3f})"
            )
        else:
            logger.info(
                f"[RUVON] Rejected claim from {incoming_device_id} "
                f"(my score={my_score:.3f} beats {incoming_score:.3f})"
            )

        return JSONResponse({
            "accepted": incoming_wins,
            "my_score": my_score,
            "my_device_id": device_id,
        })

    return app


class PeerRelayServer:
    """Background asyncio task that runs the relay FastAPI app on a local port."""

    def __init__(self, app, port: int):
        self._app = app
        self._port = port
        self._server = None

    async def start(self):
        import uvicorn
        config = uvicorn.Config(
            self._app,
            host="0.0.0.0",
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        logger.info(f"[Mesh] Peer relay server listening on port {self._port}")
        await self._server.serve()

    async def stop(self):
        if self._server:
            self._server.should_exit = True
