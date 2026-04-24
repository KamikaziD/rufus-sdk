"""
NATSEdgeTransport — sub-millisecond edge-to-cloud transport via NATS JetStream.

Activated when RUFUS_NATS_URL is set. Falls back gracefully to HTTP if the
NATS server is unreachable at connect() time (logged as warning).

Subject hierarchy:
  devices.{device_id}.heartbeat     → publish  (DEVICE_HEARTBEATS stream)
  devices.{device_id}.commands      → subscribe (DEVICE_COMMANDS workqueue)
  devices.{device_id}.sync          → request/reply (SAF sync)
  devices.{device_id}.config.req    → request/reply (config fetch)
  devices.{device_id}.config        → subscribe (CONFIG_UPDATES last-per-subject)
  devices.{device_id}.workflows     → publish  (DEVICE_WF_SYNC stream)

Commands use a durable push consumer — JetStream holds unacked commands
while the device is offline and replays them on reconnect.

Config stream uses max_msgs_per_subject=1 so the device always gets the
latest config even after days offline.
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# JetStream stream names
_STREAM_HEARTBEATS = "DEVICE_HEARTBEATS"
_STREAM_COMMANDS   = "DEVICE_COMMANDS"
_STREAM_CONFIG     = "CONFIG_UPDATES"
_STREAM_WF_SYNC    = "DEVICE_WF_SYNC"

# Request/reply timeout
_REQUEST_TIMEOUT = 10.0


class NATSEdgeTransport:
    """NATS JetStream transport for edge devices."""

    def __init__(
        self,
        device_id: str,
        nats_url: str,
        api_key: str = "",
        nats_credentials: Optional[str] = None,
    ):
        self.device_id = device_id
        self.nats_url = nats_url
        self.api_key = api_key
        self.nats_credentials = nats_credentials

        self._nc = None    # nats.Client
        self._js = None    # JetStreamContext
        self._connected = False
        self._subscriptions: list = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to NATS and initialise JetStream context."""
        try:
            import nats

            connect_kwargs: Dict[str, Any] = {
                "servers": [self.nats_url],
                "reconnected_cb": self._on_reconnect,
                "error_cb": self._on_error,
                "closed_cb": self._on_closed,
                "max_reconnect_attempts": -1,  # reconnect forever
            }
            if self.nats_credentials:
                connect_kwargs["credentials"] = self.nats_credentials

            self._nc = await nats.connect(**connect_kwargs)
            self._js = self._nc.jetstream()
            self._connected = True
            logger.info(f"[NATSTransport] Connected to {self.nats_url} — NATS Edge transport active")

        except ImportError:
            logger.warning("[NATSTransport] nats-py not installed — falling back to HTTP. "
                           "Install with: pip install nats-py")
            self._connected = False
        except Exception as e:
            logger.warning(f"[NATSTransport] Connect failed ({e}) — falling back to HTTP")
            self._connected = False

    async def disconnect(self) -> None:
        """Drain and close NATS connection."""
        if self._nc and self._connected:
            try:
                await self._nc.drain()
            except Exception:
                pass
            self._connected = False
            logger.info("[NATSTransport] Disconnected")

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def check_connectivity(self) -> bool:
        """Return True if NATS connection is live."""
        return self._connected and self._nc is not None and not self._nc.is_closed

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Publish heartbeat to JetStream. Commands arrive via subscribe_commands(),
        so this always returns [].
        """
        if not self._connected:
            return []

        subject = f"devices.{self.device_id}.heartbeat"
        try:
            from rufus.utils.serialization import pack_message, _USING_PROTO
            if _USING_PROTO:
                try:
                    from rufus.proto.gen import HeartbeatMsg
                    msg = HeartbeatMsg(
                        device_id=payload.get("device_id", self.device_id),
                        device_status=payload.get("device_status", "online"),
                        pending_sync_count=payload.get("metrics", {}).get("pending_sync_count", 0),
                        last_sync_at=payload.get("metrics", {}).get("last_sync_at") or "",
                        config_version=payload.get("metrics", {}).get("config_version") or "",
                        sent_at=payload.get("sent_at", ""),
                    )
                    data = pack_message(payload, msg)
                except ImportError:
                    data = pack_message(payload)
            else:
                data = pack_message(payload)

            await self._js.publish(subject, data)
        except Exception as e:
            logger.warning(f"[NATSTransport] Heartbeat publish failed: {e}")

        # Commands arrive via push consumer — no return value needed
        return []

    # ------------------------------------------------------------------
    # Command subscription
    # ------------------------------------------------------------------

    async def subscribe_commands(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Subscribe to cloud commands via durable JetStream push consumer.

        Commands persist in JetStream until ACK'd, so the device receives
        queued commands on reconnect even after extended offline periods.
        """
        if not self._connected:
            return

        subject = f"devices.{self.device_id}.commands"
        consumer_name = f"rufus-edge-{self.device_id}"

        try:
            sub = await self._js.subscribe(
                subject,
                durable=consumer_name,
                cb=self._make_command_handler(callback),
                manual_ack=True,
            )
            self._subscriptions.append(sub)
            logger.info(f"[NATSTransport] Subscribed to commands on {subject}")
        except Exception as e:
            logger.error(f"[NATSTransport] Command subscription failed: {e}")

    def _make_command_handler(self, callback):
        from rufus.utils.serialization import unpack_message

        async def _handler(msg):
            try:
                data = unpack_message(msg.data)
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
                await msg.ack()
            except Exception as e:
                logger.error(f"[NATSTransport] Command handler error: {e}")
                await msg.nak()

        return _handler

    # ------------------------------------------------------------------
    # SAF sync
    # ------------------------------------------------------------------

    async def sync_transactions(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send SAF transaction batch via NATS request/reply.
        """
        if not self._connected:
            return {"error": "NATS not connected"}

        subject = f"devices.{self.device_id}.sync"
        try:
            from rufus.utils.serialization import pack_message, unpack_message, _USING_PROTO
            if _USING_PROTO:
                try:
                    from rufus.proto.gen import SyncBatch, EncryptedTransaction
                    txns = []
                    for t in batch.get("transactions", []):
                        txns.append(EncryptedTransaction(
                            transaction_id=t.get("transaction_id", ""),
                            encrypted_blob=t.get("encrypted_blob", ""),
                            encryption_key_id=t.get("encryption_key_id", ""),
                            merchant_id=t.get("merchant_id", ""),
                            amount_cents=t.get("amount_cents", 0),
                            currency=t.get("currency", "USD"),
                            card_token=t.get("card_token", ""),
                            card_last_four=t.get("card_last_four", ""),
                            workflow_id=t.get("workflow_id", ""),
                            hmac=t.get("hmac", ""),
                        ))
                    proto_msg = SyncBatch(
                        transactions=txns,
                        device_sequence=batch.get("device_sequence", 0),
                        device_timestamp=batch.get("device_timestamp", ""),
                        device_id=self.device_id,
                    )
                    data = pack_message(batch, proto_msg)
                except ImportError:
                    data = pack_message(batch)
            else:
                data = pack_message(batch)

            reply = await self._nc.request(subject, data, timeout=_REQUEST_TIMEOUT)
            return unpack_message(reply.data)
        except Exception as e:
            logger.warning(f"[NATSTransport] sync_transactions failed: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    async def pull_config(self, etag: Optional[str]) -> Dict[str, Any]:
        """
        Fetch device config via NATS request/reply.
        """
        if not self._connected:
            return {"not_modified": False, "config": None, "etag": etag,
                    "error": "NATS not connected"}

        subject = f"devices.{self.device_id}.config.req"
        try:
            from rufus.utils.serialization import pack_message, unpack_message
            req_payload = {"device_id": self.device_id, "if_none_match": etag or ""}
            data = pack_message(req_payload)

            reply = await self._nc.request(subject, data, timeout=_REQUEST_TIMEOUT)
            result = unpack_message(reply.data)

            # Normalise to standard pull_config response shape
            if isinstance(result, dict):
                if "not_modified" not in result:
                    result["not_modified"] = False
            return result
        except Exception as e:
            logger.warning(f"[NATSTransport] pull_config failed: {e}")
            return {"not_modified": False, "config": None, "etag": etag, "error": str(e)}

    async def subscribe_config_push(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Subscribe to server-initiated config pushes via CONFIG_UPDATES stream.

        The server publishes to devices.{id}.config with max_msgs_per_subject=1
        so the device always receives the latest config on reconnect.
        """
        if not self._connected:
            return

        subject = f"devices.{self.device_id}.config"
        consumer_name = f"rufus-config-{self.device_id}"
        from rufus.utils.serialization import unpack_message

        async def _handler(msg):
            try:
                config_data = unpack_message(msg.data)
                if asyncio.iscoroutinefunction(callback):
                    await callback(config_data)
                else:
                    callback(config_data)
                await msg.ack()
            except Exception as e:
                logger.error(f"[NATSTransport] Config push handler error: {e}")

        try:
            sub = await self._js.subscribe(
                subject,
                durable=consumer_name,
                cb=_handler,
                manual_ack=True,
            )
            self._subscriptions.append(sub)
            logger.info(f"[NATSTransport] Subscribed to config push on {subject}")
        except Exception as e:
            logger.error(f"[NATSTransport] Config push subscription failed: {e}")

    # ------------------------------------------------------------------
    # Fleet WASM patch broadcast
    # ------------------------------------------------------------------

    async def subscribe_patch_broadcast(
        self,
        handler: Callable[[bytes, str, str], Any],
    ) -> None:
        """Subscribe to ruvon.node.patch for fleet-wide WASM binary delivery.

        Every node in the fleet subscribes to the same subject.  The AI
        publisher broadcasts a compiled .wasm binary; all nodes simultaneously
        shadow-verify and cache it so the next workflow step using that hash
        gets the updated component without a restart.

        Message JSON payload::

            {
                "wasm_hash": "<sha256hex>",
                "binary_b64": "<base64-encoded .wasm bytes>",
                "step_name": "<step identifier this patch targets>"
            }

        The handler signature is::

            async def on_patch(binary: bytes, wasm_hash: str, step_name: str) -> None

        Hash integrity is verified before the handler is called.  A mismatch
        is logged and the message is nack-ed so the broker can redeliver or
        route to a dead-letter subject.

        Args:
            handler: Coroutine (or sync) callable invoked with
                     ``(binary, wasm_hash, step_name)`` after integrity check.
        """
        if not self._connected:
            return

        import base64
        import hashlib

        subject = "ruvon.node.patch"
        # Unique cursor per device — each node tracks its own replay position.
        consumer_name = f"rufus-patch-{self.device_id}"

        async def _handler(msg):
            try:
                payload = json.loads(msg.data)
                wasm_hash = payload.get("wasm_hash", "")
                binary_b64 = payload.get("binary_b64", "")
                step_name = payload.get("step_name", "unknown")

                binary = base64.b64decode(binary_b64)
                actual_hash = hashlib.sha256(binary).hexdigest()

                if actual_hash != wasm_hash:
                    logger.error(
                        "[NATSTransport:patch] Hash mismatch for step=%s: "
                        "expected=%s actual=%s — discarding",
                        step_name, wasm_hash[:16], actual_hash[:16],
                    )
                    await msg.nak()
                    return

                signature_b64 = payload.get("signature_b64", "")

                if asyncio.iscoroutinefunction(handler):
                    await handler(binary, wasm_hash, step_name, signature_b64)
                else:
                    handler(binary, wasm_hash, step_name, signature_b64)

                await msg.ack()
                logger.info(
                    "[NATSTransport:patch] Applied WASM patch for step=%s hash=%s…",
                    step_name, wasm_hash[:16],
                )
            except Exception as e:
                logger.error("[NATSTransport:patch] Patch handler error: %s", e)

        try:
            sub = await self._js.subscribe(
                subject,
                durable=consumer_name,
                cb=_handler,
                manual_ack=True,
            )
            self._subscriptions.append(sub)
            logger.info(
                "[NATSTransport] Subscribed to patch broadcast on %s (consumer=%s)",
                subject, consumer_name,
            )
        except Exception as e:
            logger.error("[NATSTransport] Patch broadcast subscription failed: %s", e)

    # ------------------------------------------------------------------
    # Capability gossip (ruvon.mesh.capabilities)
    # ------------------------------------------------------------------

    async def publish_capability_vector(self, payload: bytes) -> None:
        """Publish a serialised CapabilityVector to ``ruvon.mesh.capabilities``.

        Uses core NATS publish (NOT JetStream) for ephemeral fan-out.  Loss is
        acceptable — the next broadcast arrives within 30 s.

        Args:
            payload: JSON-encoded CapabilityVector bytes.
        """
        if not self._connected:
            return
        try:
            await self._nc.publish("ruvon.mesh.capabilities", payload)
        except Exception as e:
            logger.debug("[NATSTransport] capability vector publish failed: %s", e)

    async def subscribe_capability_gossip(
        self,
        handler: "Callable[[bytes], Any]",
    ) -> None:
        """Subscribe to ``ruvon.mesh.capabilities`` for peer capability vectors.

        Non-durable core NATS subscribe (ephemeral).  Incoming messages are
        passed raw (bytes) to ``handler``.

        Args:
            handler: Async or sync callable accepting ``bytes``.
        """
        if not self._connected:
            return

        async def _handler(msg):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg.data)
                else:
                    handler(msg.data)
            except Exception as e:
                logger.debug("[NATSTransport] capability gossip handler error: %s", e)

        try:
            sub = await self._nc.subscribe("ruvon.mesh.capabilities", cb=_handler)
            self._subscriptions.append(sub)
            logger.info("[NATSTransport] Subscribed to capability gossip on ruvon.mesh.capabilities")
        except Exception as e:
            logger.error("[NATSTransport] Capability gossip subscription failed: %s", e)

    # ------------------------------------------------------------------
    # EchoForge aliveness gossip (ruvon.echoforge.aliveness)
    # ------------------------------------------------------------------

    async def publish_echo_aliveness(self, payload: bytes) -> None:
        """Publish a serialised ``SharedEcho`` to ``ruvon.echoforge.aliveness``.

        Uses core NATS publish (NOT JetStream) for ephemeral fan-out.
        Loss is acceptable — the next broadcast arrives within 20 s.

        Args:
            payload: JSON-encoded SharedEcho bytes (including signature_b64).
        """
        if not self._connected:
            return
        try:
            await self._nc.publish("ruvon.echoforge.aliveness", payload)
        except Exception as e:
            logger.debug("[NATSTransport] echo aliveness publish failed: %s", e)

    async def subscribe_echo_aliveness(
        self,
        handler: "Callable[[bytes], Any]",
    ) -> None:
        """Subscribe to ``ruvon.echoforge.aliveness`` for peer SharedEcho gossip.

        Non-durable core NATS subscribe (ephemeral).  Incoming messages are
        passed raw (bytes) to ``handler``.

        Args:
            handler: Async or sync callable accepting ``bytes``.
        """
        if not self._connected:
            return

        async def _handler(msg):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg.data)
                else:
                    handler(msg.data)
            except Exception as e:
                logger.debug("[NATSTransport] echo aliveness handler error: %s", e)

        try:
            sub = await self._nc.subscribe("ruvon.echoforge.aliveness", cb=_handler)
            self._subscriptions.append(sub)
            logger.info("[NATSTransport] Subscribed to echo aliveness on ruvon.echoforge.aliveness")
        except Exception as e:
            logger.error("[NATSTransport] Echo aliveness subscription failed: %s", e)

    # ------------------------------------------------------------------
    # EchoForge sentinel alerts (ruvon.echoforge.sentinel)
    # ------------------------------------------------------------------

    async def publish_sentinel_alert(self, payload: bytes) -> None:
        """Publish a serialised ``SentinelAlert`` to ``ruvon.echoforge.sentinel``.

        Uses JetStream for durability — sentinel alerts must not be lost since
        they may trigger circuit-breaker actions on all fleet nodes.

        Args:
            payload: JSON-encoded SentinelAlert bytes.
        """
        if not self._connected:
            return
        try:
            await self._js.publish("ruvon.echoforge.sentinel", payload)
        except Exception as e:
            logger.warning("[NATSTransport] sentinel alert publish failed: %s", e)

    async def subscribe_sentinel_alerts(
        self,
        handler: "Callable[[bytes], Any]",
    ) -> None:
        """Subscribe to ``ruvon.echoforge.sentinel`` for fleet-wide sentinel alerts.

        Durable JetStream consumer — alerts persist until ACK'd so nodes
        receive queued alerts after reconnect.

        Args:
            handler: Async or sync callable accepting raw ``bytes`` payload.
        """
        if not self._connected:
            return

        consumer_name = f"rufus-sentinel-{self.device_id}"

        async def _handler(msg):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg.data)
                else:
                    handler(msg.data)
                await msg.ack()
            except Exception as e:
                logger.error("[NATSTransport] Sentinel alert handler error: %s", e)
                await msg.nak()

        try:
            sub = await self._js.subscribe(
                "ruvon.echoforge.sentinel",
                durable=consumer_name,
                cb=_handler,
                manual_ack=True,
            )
            self._subscriptions.append(sub)
            logger.info(
                "[NATSTransport] Subscribed to sentinel alerts (consumer=%s)",
                consumer_name,
            )
        except Exception as e:
            logger.error("[NATSTransport] Sentinel alert subscription failed: %s", e)

    # ------------------------------------------------------------------
    # WASM build delegation (ruvon.mesh.build.request)
    # ------------------------------------------------------------------

    async def publish_build_request(self, wasm_hash: str, build_spec: dict) -> None:
        """Publish a WASM build delegation request to ``ruvon.mesh.build.request``.

        Uses JetStream for durability — the request must not be lost since Tier 1
        nodes are unable to proceed without a compiled binary.

        Args:
            wasm_hash:  SHA-256 hex digest of the target WASM binary.
            build_spec: Context dict, e.g. ``{"step_name": ..., "reason": ...,
                        "available_ram_mb": ...}``.
        """
        if not self._connected:
            return
        import json as _json
        payload = _json.dumps({
            "requesting_device_id": self.device_id,
            "wasm_hash": wasm_hash,
            **build_spec,
        }).encode()
        try:
            await self._js.publish("ruvon.mesh.build.request", payload)
            logger.info(
                "[NATSTransport] Build delegation request published for hash=%s…",
                wasm_hash[:16],
            )
        except Exception as e:
            logger.warning("[NATSTransport] Build request publish failed: %s", e)

    async def subscribe_build_requests(
        self,
        handler: "Callable[[bytes], Any]",
    ) -> None:
        """Subscribe to ``ruvon.mesh.build.request`` (Tier 2+ nodes only).

        Durable JetStream consumer so requests survive transient disconnects.
        Messages are ACKed after the handler returns without raising.

        Args:
            handler: Async or sync callable accepting raw ``bytes`` payload.
        """
        if not self._connected:
            return

        consumer_name = f"rufus-build-worker-{self.device_id}"

        async def _handler(msg):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg.data)
                else:
                    handler(msg.data)
                await msg.ack()
            except Exception as e:
                logger.error("[NATSTransport] Build request handler error: %s", e)
                await msg.nak()

        try:
            sub = await self._js.subscribe(
                "ruvon.mesh.build.request",
                durable=consumer_name,
                cb=_handler,
                manual_ack=True,
            )
            self._subscriptions.append(sub)
            logger.info(
                "[NATSTransport] Subscribed to build requests (consumer=%s)",
                consumer_name,
            )
        except Exception as e:
            logger.error("[NATSTransport] Build request subscription failed: %s", e)

    # ------------------------------------------------------------------
    # Workflow sync
    # ------------------------------------------------------------------

    async def sync_workflows(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish completed workflow batch to DEVICE_WF_SYNC stream.
        """
        if not self._connected:
            return {"error": "NATS not connected"}

        subject = f"devices.{self.device_id}.workflows"
        try:
            from rufus.utils.serialization import pack_message
            data = pack_message(batch)
            ack = await self._js.publish(subject, data)
            return {"accepted_workflow_ids": batch.get("workflows", []),
                    "seq": ack.seq}
        except Exception as e:
            logger.warning(f"[NATSTransport] sync_workflows failed: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # NATS callbacks
    # ------------------------------------------------------------------

    async def _on_reconnect(self):
        logger.info("[NATSTransport] Reconnected to NATS — JetStream replay will deliver queued messages")

    async def _on_error(self, e):
        logger.error(f"[NATSTransport] NATS error: {e}")

    async def _on_closed(self):
        logger.warning("[NATSTransport] NATS connection closed")
        self._connected = False
