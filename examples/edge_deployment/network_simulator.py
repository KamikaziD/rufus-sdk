"""
network_simulator.py — Injectable httpx transport that simulates real-world
network conditions (latency, jitter, packet loss) for container-to-container
HTTP calls in edge device emulators.

Usage in edge_device_sim.py:
    from network_simulator import NetworkConditionSimulator
    _net_sim = NetworkConditionSimulator(NETWORK_CONDITION)
    client = _net_sim.make_client(headers={"X-API-Key": api_key}, timeout=15.0)

Profiles (NETWORK_CONDITION env var):
    perfect   — ~0.5ms, no loss (loopback)
    good      — ~2ms, no loss (Docker bridge default)
    lan       — ~5ms, 0.1% loss
    wan       — ~50ms, 1% loss
    degraded  — ~150ms, 5% loss
    flaky     — ~300ms, 20% loss
    offline   — 100% packet loss (SAF stress test)
    auto      — cycles through profiles every 60s

Auto-cycle sequence: good → lan → degraded → flaky → good → offline → good
"""

import asyncio
import itertools
import logging
import random

import httpx

logger = logging.getLogger("net-sim")


class LatencyTransport(httpx.AsyncBaseTransport):
    """httpx transport wrapper that injects latency and packet loss."""

    PROFILES: dict[str, dict] = {
        "perfect":  {"latency_ms": 0.5,  "jitter_ms": 0.2,  "loss_pct":  0.0},
        "good":     {"latency_ms": 2.0,  "jitter_ms": 1.0,  "loss_pct":  0.0},
        "lan":      {"latency_ms": 5.0,  "jitter_ms": 2.0,  "loss_pct":  0.1},
        "wan":      {"latency_ms": 50.0, "jitter_ms": 20.0, "loss_pct":  1.0},
        "degraded": {"latency_ms": 150.0,"jitter_ms": 100.0,"loss_pct":  5.0},
        "flaky":    {"latency_ms": 300.0,"jitter_ms": 200.0,"loss_pct": 20.0},
        "offline":  {"latency_ms": 0.0,  "jitter_ms": 0.0,  "loss_pct":100.0},
    }

    def __init__(self, condition: str = "good") -> None:
        self._real = httpx.AsyncHTTPTransport()
        self._condition = condition

    @property
    def condition(self) -> str:
        return self._condition

    @condition.setter
    def condition(self, value: str) -> None:
        assert value in self.PROFILES, f"Unknown network condition: {value!r}"
        self._condition = value

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        p = self.PROFILES[self._condition]

        # Packet loss
        if p["loss_pct"] > 0.0 and random.random() * 100 < p["loss_pct"]:
            raise httpx.ConnectError(
                f"[NetworkSim] packet loss ({self._condition} — {p['loss_pct']}% loss)"
            )

        # Latency + jitter
        if p["latency_ms"] > 0.0:
            delay = max(0.0, p["latency_ms"] + random.gauss(0, p["jitter_ms"])) / 1000
            await asyncio.sleep(delay)

        return await self._real.handle_async_request(request)

    async def aclose(self) -> None:
        await self._real.aclose()


class NetworkConditionSimulator:
    """
    Wraps a LatencyTransport and exposes a make_client() factory that returns
    httpx.AsyncClient instances sharing the same transport (and thus the same
    current network condition).
    """

    AUTO_CYCLE = ["good", "lan", "degraded", "flaky", "good", "offline", "good"]
    CYCLE_INTERVAL_S = 60

    def __init__(self, condition: str = "good") -> None:
        self._transport = LatencyTransport(condition)
        logger.info(
            "[NetworkSim] initial condition=%s  latency=%.0fms  loss=%.1f%%",
            condition,
            self._transport.PROFILES[condition]["latency_ms"],
            self._transport.PROFILES[condition]["loss_pct"],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def make_client(
        self,
        base_url: str = "",
        headers: dict | None = None,
        timeout: float = 30.0,
    ) -> httpx.AsyncClient:
        """Return an AsyncClient that applies the current network profile."""
        return httpx.AsyncClient(
            transport=self._transport,
            base_url=base_url,
            headers=headers or {},
            timeout=timeout,
        )

    def set_condition(self, name: str) -> None:
        self._transport.condition = name
        p = self._transport.PROFILES[name]
        logger.info(
            "[NetworkSim] → %s  latency=%.0fms  jitter=%.0fms  loss=%.1f%%",
            name, p["latency_ms"], p["jitter_ms"], p["loss_pct"],
        )

    @property
    def current(self) -> str:
        return self._transport.condition

    @property
    def profile(self) -> dict:
        return LatencyTransport.PROFILES[self.current]

    async def auto_cycle(self) -> None:
        """Infinitely cycle through AUTO_CYCLE profiles at CYCLE_INTERVAL_S intervals."""
        for cond in itertools.cycle(self.AUTO_CYCLE):
            self.set_condition(cond)
            await asyncio.sleep(self.CYCLE_INTERVAL_S)
