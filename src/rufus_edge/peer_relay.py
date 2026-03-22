"""
peer_relay.py — Mesh peer relay for offline SAF routing.

Provides BFS-based multi-hop SAF routing through peer devices.
When the device is offline, it searches up to 3 hops deep through
known peers to find one that has cloud connectivity, then forwards
SAF transactions through that relay device.

Components:
    PeerRelayServer   — lightweight FastAPI app accepting inbound relay requests
    PeerRelayClient   — httpx client for probing peers and forwarding SAF
    MeshRouter        — BFS routing to find the nearest online peer
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class PeerStatus:
    online: bool
    can_relay: bool
    device_id: str
    peer_urls: List[str] = field(default_factory=list)


@dataclass
class RelayResult:
    accepted_ids: List[str]
    rejected_ids: List[str]
    relay_url: str
    relay_path: List[str] = field(default_factory=list)


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
    ) -> Optional[RelayResult]:
        """POST /peer/relay/saf — forward signed SAF transactions to a relay peer."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{peer_url}/peer/relay/saf",
                    json={"transactions": transactions},
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


class MeshRouter:
    """BFS routing to find the nearest online relay peer (max 3 hops)."""

    def __init__(self, device_id: str, sync_manager):
        self._device_id = device_id
        self._sync_manager = sync_manager
        self._client = PeerRelayClient()

    async def find_relay(
        self,
        transactions: List[dict],
        known_peers: List[str],
        max_depth: int = 3,
    ) -> Optional[RelayResult]:
        """
        BFS through peer graph up to max_depth hops.

        Returns RelayResult if a relay was found and transactions forwarded,
        None otherwise (no regression — caller keeps transactions in SAF queue).
        """
        visited: set = set()
        frontier: List[str] = list(known_peers)
        hop_path: List[str] = []

        for depth in range(1, max_depth + 1):
            next_frontier: List[str] = []

            for peer_url in frontier:
                if peer_url in visited:
                    continue
                visited.add(peer_url)

                status = await self._client.probe(peer_url)
                if status is None:
                    continue

                if status.online and status.can_relay:
                    logger.info(
                        f"[Mesh] Found online relay at {peer_url} ({depth} hop(s))"
                    )
                    result = await self._client.relay_saf(
                        peer_url, transactions, self._device_id
                    )
                    if result:
                        result.relay_path = [*hop_path, peer_url]
                        return result

                # Expand BFS: use peer_urls from status if available, else probe /peer/peers
                peer_peers = status.peer_urls or await self._client.get_peers(peer_url)
                for pp in peer_peers:
                    if pp not in visited:
                        next_frontier.append(pp)

            frontier = next_frontier
            hop_path = frontier[:]  # track path for reporting
            if not frontier:
                break

        return None


def create_relay_app(
    sync_manager,
    device_id: str,
    peer_urls: List[str],
    is_online_fn: Callable[[], bool],
):
    """
    Create the FastAPI app for the peer relay server.

    Endpoints:
        GET  /peer/status      → { online, can_relay, device_id, peer_urls }
        GET  /peer/peers       → { peer_urls }
        POST /peer/relay/saf   → accept and forward SAF from a peer
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Rufus Peer Relay", docs_url=None, redoc_url=None)

    @app.get("/peer/status")
    async def peer_status():
        online = is_online_fn()
        return {
            "online": online,
            "can_relay": online,
            "device_id": device_id,
            "peer_urls": peer_urls,
        }

    @app.get("/peer/peers")
    async def peer_peers():
        return {"peer_urls": peer_urls}

    @app.post("/peer/relay/saf")
    async def relay_saf(request: Request):
        source = request.headers.get("X-Relay-Source", "unknown")
        body = await request.json()
        transactions = body.get("transactions", [])

        if not transactions:
            return JSONResponse({"accepted": [], "rejected": []})

        logger.info(
            f"[Mesh] Inbound relay from {source}: {len(transactions)} txn(s)"
        )

        try:
            result = await sync_manager.sync_batch_direct(transactions)
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
