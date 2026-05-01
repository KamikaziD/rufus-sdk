"""
EchoForgeExtension — ruvon-edge extension for the EchoForge trading engine.

Manages the EchoForge JS worker subprocess and bridges ruvon-edge's
SyncManager, ConfigManager, and NATS transport into it via a local WebSocket
IPC channel on :8767.

Architecture:
  RuvonEdgeAgent
  └── EchoForgeExtension
      ├── start()  → spawn Bun subprocess  →  IPC WS :8767
      ├── _on_phic_config()   → forwards PHIC config to JS workers
      ├── _on_order_intent()  → routes to ruvon-edge SyncManager (SAF)
      ├── _on_telemetry()     → publishes to NATS for PHIC dashboard
      └── _heartbeat_watch()  → restarts subprocess if heartbeat goes silent

Usage (from edge device config / startup code):
    from ruvon_edge.extensions.echoforge import EchoForgeExtension

    ext = EchoForgeExtension(
        agent=agent,
        daemon_path="/path/to/ruvon-echoforge/daemon",
        port=8767,
    )
    await ext.start()
    # ... agent runs ...
    await ext.stop()
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ruvon_edge.agent import RuvonEdgeAgent

logger = logging.getLogger(__name__)

# Seconds without a heartbeat before we consider the subprocess dead
_HEARTBEAT_TIMEOUT_S = 75.0   # >2.5× the 30s heartbeat interval


class EchoForgeExtension:
    """
    Manages the EchoForge JS worker subprocess and IPC bridge.

    Must be started after the agent is fully initialised (sync_manager,
    config_manager, and transport must already exist on the agent).
    """

    def __init__(
        self,
        agent: "RuvonEdgeAgent",
        daemon_path: str,
        port: int = 8767,
    ):
        self.agent       = agent
        self.daemon_path = Path(daemon_path).resolve()
        self.port        = port

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._ws         = None   # websockets.WebSocketClientProtocol
        self._tasks: list[asyncio.Task] = []
        self._last_heartbeat: float = 0.0
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self):
        """Spawn the Bun subprocess and connect the IPC WebSocket."""
        if self._running:
            logger.warning("[EchoForge] Already running")
            return

        logger.info("[EchoForge] Starting daemon from %s on port %d", self.daemon_path, self.port)
        await self._spawn()
        self._running = True

        # Subscribe to PHIC config changes from ConfigManager
        if self.agent.config_manager:
            self.agent.config_manager.on_config_change(self._on_config_change)

        # Optional: subscribe to NATS sentiment feed and bridge to JS workers
        await self._start_sentiment_bridge()

        logger.info("[EchoForge] Extension started")

    async def stop(self):
        """Terminate the subprocess and cancel background tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        logger.info("[EchoForge] Extension stopped")

    async def push_phic_config(self, config: dict):
        """Forward a PHIC config update to the JS workers."""
        await self._ipc_send({"type": "phic_update", "config": config})

    async def hot_swap_model(self, onnx_bytes: bytes):
        """Send new ONNX model bytes to the inference_worker (no restart needed)."""
        msg = {"type": "reload_model", "model_bytes": list(onnx_bytes)}
        await self._ipc_send(msg)

    async def emergency_freeze(self):
        """Set PHIC emergency_freeze=true across all JS workers."""
        await self.push_phic_config({"emergency_freeze": True})

    async def emergency_resume(self):
        """Clear PHIC emergency_freeze."""
        await self.push_phic_config({"emergency_freeze": False})

    # ── Subprocess lifecycle ──────────────────────────────────────────────────

    async def _spawn(self):
        """Start the Bun subprocess and connect IPC WS."""
        env = {
            **os.environ,
            "ECHOFORGE_IPC_PORT": str(self.port),
        }
        # Point the daemon at the ruvon-edge agent's exchange URL if available
        if hasattr(self.agent, "cloud_url") and self.agent.cloud_url:
            # Use the same base URL; exchange adapter reads ECHOFORGE_EXCHANGE_URL
            env.setdefault("ECHOFORGE_EXCHANGE_URL", self.agent.cloud_url)

        self._proc = await asyncio.create_subprocess_exec(
            "bun", "src/runner.js",
            cwd=str(self.daemon_path),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("[EchoForge] Subprocess PID %d", self._proc.pid)

        # Pipe subprocess logs to our logger
        self._tasks.append(asyncio.create_task(self._pipe_logs(self._proc.stdout, logging.DEBUG)))
        self._tasks.append(asyncio.create_task(self._pipe_logs(self._proc.stderr, logging.WARNING)))

        # Wait for the IPC port to be ready (up to 10s)
        for attempt in range(20):
            await asyncio.sleep(0.5)
            try:
                import websockets
                ws = await websockets.connect(f"ws://localhost:{self.port}/ipc")
                self._ws = ws
                self._last_heartbeat = time.monotonic()
                logger.info("[EchoForge] IPC WS connected")
                break
            except Exception:
                if attempt == 19:
                    raise RuntimeError(f"[EchoForge] IPC WS not ready after 10s on port {self.port}")

        self._tasks.append(asyncio.create_task(self._ipc_receive_loop()))
        self._tasks.append(asyncio.create_task(self._heartbeat_watch()))

    async def _restart(self):
        """Restart the subprocess after a crash."""
        logger.warning("[EchoForge] Restarting crashed subprocess")
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass
        for task in [t for t in self._tasks if not t.done()]:
            task.cancel()
        self._tasks.clear()
        self._ws = None
        self._proc = None
        await asyncio.sleep(2.0)  # brief cool-down before restart
        await self._spawn()
        logger.info("[EchoForge] Subprocess restarted")

    # ── IPC receive loop ──────────────────────────────────────────────────────

    async def _ipc_receive_loop(self):
        """Read messages from the JS subprocess and bridge to ruvon-edge."""
        while self._running:
            try:
                if self._ws is None:
                    await asyncio.sleep(1.0)
                    continue

                raw = await self._ws.recv()
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "heartbeat":
                    self._last_heartbeat = time.monotonic()

                elif msg_type == "order_intent":
                    await self._on_order_intent(msg)

                elif msg_type in ("sentinel_alert", "echo_snapshot", "vpin_update",
                                   "correlation_signal", "arb_signal"):
                    await self._on_telemetry(msg)

            except Exception as exc:
                if self._running:
                    logger.warning("[EchoForge] IPC receive error: %s", exc)
                    await asyncio.sleep(1.0)

    async def _heartbeat_watch(self):
        """Restart the subprocess if heartbeats go silent."""
        self._last_heartbeat = time.monotonic()
        while self._running:
            await asyncio.sleep(15.0)
            age = time.monotonic() - self._last_heartbeat
            if age > _HEARTBEAT_TIMEOUT_S:
                logger.error(
                    "[EchoForge] Heartbeat silent for %.0fs — restarting subprocess", age
                )
                await self._restart()
                return  # new _spawn creates a new _heartbeat_watch task

    # ── Outbound helpers ──────────────────────────────────────────────────────

    async def _ipc_send(self, msg: dict):
        if self._ws:
            try:
                await self._ws.send(json.dumps(msg))
            except Exception as exc:
                logger.warning("[EchoForge] IPC send failed: %s", exc)

    # ── Inbound handlers ──────────────────────────────────────────────────────

    async def _on_order_intent(self, msg: dict):
        """Log and publish order intents. The JS daemon handles its own SAF persistence
        via the IndexedDB shim; Python's role is telemetry routing only."""
        logger.info(
            "[EchoForge] Order intent: %s %s qty=%s pattern=%s",
            msg.get("side", "?"), msg.get("symbol", "BTC/USDT"),
            msg.get("qty", "?"), msg.get("pattern_id", "?"),
        )
        # Publish to NATS so the PHIC dashboard can display pending orders
        await self._on_telemetry({**msg, "type": "order_intent"})

    async def _on_telemetry(self, msg: dict):
        """Publish telemetry to NATS for PHIC dashboard via raw NATS client."""
        transport = getattr(self.agent, "_transport", None)
        nc = getattr(transport, "_nc", None)
        if nc is None:
            return
        subject = f"echoforge.{msg.get('type', 'unknown')}"
        try:
            payload = json.dumps(msg).encode()
            await nc.publish(subject, payload)
        except Exception:
            pass  # NATS not connected — telemetry is non-critical, don't propagate

    def _on_config_change(self, config):
        """Called by ConfigManager when cloud pushes a new config. Forward to JS workers."""
        if not self._ws:
            return
        cfg_dict = config.model_dump() if hasattr(config, "model_dump") else dict(config)
        asyncio.create_task(self._ipc_send({"type": "phic_update", "config": cfg_dict}))

    # ── Sentiment bridge (Phase 6d) ───────────────────────────────────────────

    async def _start_sentiment_bridge(self):
        """Subscribe to NATS echoforge.sentiment and forward scores to JS workers.
        Silently a no-op when NATS is not connected — sentiment is non-critical."""
        transport = getattr(self.agent, "_transport", None)
        nc = getattr(transport, "_nc", None)
        if nc is None:
            logger.debug("[EchoForge] No NATS connection — sentiment bridge inactive")
            return
        try:
            await nc.subscribe("echoforge.sentiment", cb=self._on_sentiment)
            logger.info("[EchoForge] Sentiment bridge active (echoforge.sentiment)")
        except Exception as exc:
            logger.warning("[EchoForge] Could not subscribe to sentiment feed: %s", exc)

    async def _on_sentiment(self, msg) -> None:
        """NATS message handler for echoforge.sentiment — forward to JS workers via IPC."""
        try:
            data = json.loads(msg.data)
            score    = float(data.get("score",    0.0))
            momentum = float(data.get("momentum", 0.0))
            await self._ipc_send({
                "type":     "sentiment_update",
                "score":    max(-1.0, min(1.0, score)),
                "momentum": max(-1.0, min(1.0, momentum)),
            })
        except Exception as exc:
            logger.debug("[EchoForge] Sentiment parse error: %s", exc)

    # ── Subprocess log bridge ─────────────────────────────────────────────────

    @staticmethod
    async def _pipe_logs(stream, level: int):
        if not stream:
            return
        async for line in stream:
            text = line.decode(errors="replace").rstrip()
            if text:
                logger.log(level, "[EchoForge:daemon] %s", text)
