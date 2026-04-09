"""
NATSBridge — server-side NATS JetStream bridge for the Ruvon control plane.

Connects to NATS on server startup and mirrors all device communication
that previously required HTTP polling:

  devices.*.heartbeat     → device_service.process_heartbeat()
  devices.*.config.req    → device_service.get_active_config() + reply
  devices.*.sync          → device_service.process_saf_sync() + reply
  devices.*.workflows     → persistence.sync_workflows()

Commands issued via send_command() are published to the JetStream workqueue
and held durably until the device ACKs — eliminating the 60s polling gap.

Config pushes via push_config() publish to CONFIG_UPDATES (last-per-subject),
so a device that was offline for days still gets the latest config on reconnect.

Activated by setting RUVON_NATS_URL in the environment.
The server falls back gracefully (no-op) when NATS is not configured.
"""
import asyncio
import logging
import json
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# JetStream stream definitions
_STREAMS = [
    {
        "name": "DEVICE_HEARTBEATS",
        "subjects": ["devices.*.heartbeat"],
        "retention": "limits",
        "max_age": 3600,  # 1 hour
    },
    {
        "name": "DEVICE_COMMANDS",
        "subjects": ["devices.*.commands"],
        "retention": "workqueue",   # messages deleted on ACK
        "max_age": 86400 * 7,       # 7 days — hold commands for offline devices
    },
    {
        "name": "CONFIG_UPDATES",
        "subjects": ["devices.*.config"],
        "retention": "limits",
        "max_msgs_per_subject": 1,   # last-per-subject — device gets latest config on reconnect
    },
    {
        "name": "DEVICE_WF_SYNC",
        "subjects": ["devices.*.workflows"],
        "retention": "limits",
        "max_age": 86400,            # 24 hours
    },
    {
        "name": "WORKFLOW_EVENTS",
        "subjects": ["workflow.events.>"],
        "retention": "limits",
        "max_age": 86400,
    },
]


class NATSBridge:
    """
    Server-side NATS bridge. Wired into FastAPI lifespan in main.py.

    All business logic delegates to device_service and persistence —
    no duplication of HTTP endpoint logic.
    """

    def __init__(
        self,
        nats_url: str,
        device_service,        # DeviceService instance
        persistence,           # PersistenceProvider instance
        nats_credentials: Optional[str] = None,
    ):
        self.nats_url = nats_url
        self.device_service = device_service
        self.persistence = persistence
        self.nats_credentials = nats_credentials

        self._nc = None
        self._js = None
        self._subscriptions: list = []
        self._running = False

    async def start(self) -> None:
        """Connect to NATS, provision streams, and subscribe to device subjects."""
        try:
            import nats
        except ImportError:
            logger.warning("[NATSBridge] nats-py not installed — NATS bridge disabled")
            return

        try:
            connect_kwargs: Dict[str, Any] = {
                "servers": [self.nats_url],
                "error_cb": self._on_error,
            }
            if self.nats_credentials:
                connect_kwargs["credentials"] = self.nats_credentials

            self._nc = await nats.connect(**connect_kwargs)
            self._js = self._nc.jetstream()
            logger.info(f"[NATSBridge] Connected to {self.nats_url}")

            # Provision JetStream streams (idempotent)
            await self._provision_streams()

            # Subscribe to device subjects
            await self._subscribe_all()

            self._running = True
            logger.info("[NATSBridge] Server-side NATS bridge active")

        except Exception as e:
            logger.error(f"[NATSBridge] Failed to start: {e}")

    async def stop(self) -> None:
        """Drain subscriptions and close NATS connection."""
        self._running = False
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        if self._nc:
            try:
                await self._nc.drain()
            except Exception:
                pass
        logger.info("[NATSBridge] Stopped")

    # ------------------------------------------------------------------
    # Stream provisioning
    # ------------------------------------------------------------------

    async def _provision_streams(self) -> None:
        """Create JetStream streams idempotently (update if exists)."""
        for stream_cfg in _STREAMS:
            try:
                from nats.js.api import StreamConfig
                cfg = StreamConfig(
                    name=stream_cfg["name"],
                    subjects=stream_cfg["subjects"],
                    retention=stream_cfg.get("retention", "limits"),
                    max_age=stream_cfg.get("max_age", 0),
                    max_msgs_per_subject=stream_cfg.get("max_msgs_per_subject", -1),
                )
                try:
                    await self._js.add_stream(cfg)
                    logger.debug(f"[NATSBridge] Created stream {stream_cfg['name']}")
                except Exception:
                    # Stream already exists — update config
                    await self._js.update_stream(cfg)
                    logger.debug(f"[NATSBridge] Updated stream {stream_cfg['name']}")
            except Exception as e:
                logger.warning(f"[NATSBridge] Stream {stream_cfg['name']} provision failed: {e}")

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def _subscribe_all(self) -> None:
        """Subscribe to wildcard subjects for all device operations."""
        from ruvon.utils.serialization import unpack_message, pack_message

        # Heartbeat
        sub_hb = await self._nc.subscribe("devices.*.heartbeat", cb=self._handle_heartbeat)
        self._subscriptions.append(sub_hb)

        # Config request (request/reply)
        sub_cfg = await self._nc.subscribe("devices.*.config.req", cb=self._handle_config_req)
        self._subscriptions.append(sub_cfg)

        # SAF sync (request/reply)
        sub_sync = await self._nc.subscribe("devices.*.sync", cb=self._handle_saf_sync)
        self._subscriptions.append(sub_sync)

        # Workflow sync (fire-and-store)
        sub_wf = await self._nc.subscribe("devices.*.workflows", cb=self._handle_workflow_sync)
        self._subscriptions.append(sub_wf)

        logger.info("[NATSBridge] Subscribed to devices.* subjects")

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_heartbeat(self, msg) -> None:
        """Forward heartbeat to device_service.process_heartbeat()."""
        try:
            from ruvon.utils.serialization import unpack_message
            data = unpack_message(msg.data)
            device_id = self._extract_device_id(msg.subject, "devices", "heartbeat")
            if device_id and self.device_service:
                status = data.get("device_status", "online") if isinstance(data, dict) else "online"
                metrics = data.get("metrics") if isinstance(data, dict) else None
                await self.device_service.process_heartbeat(device_id, status, metrics)
        except Exception as e:
            logger.error(f"[NATSBridge] Heartbeat handler error: {e}")

    async def _handle_config_req(self, msg) -> None:
        """Serve config request via request/reply."""
        try:
            from ruvon.utils.serialization import unpack_message, pack_message
            data = unpack_message(msg.data)
            device_id = self._extract_device_id(msg.subject, "devices", "config.req")

            if not device_id or not self.device_service:
                await msg.respond(pack_message({"not_modified": False, "config": None}))
                return

            etag = data.get("if_none_match", "")
            config_dict, new_etag = await self.device_service.get_active_config(device_id, etag)

            if config_dict is None:
                response = {"not_modified": True, "config": None, "etag": etag}
            else:
                response = {"not_modified": False, "config": config_dict, "etag": new_etag}

            await msg.respond(pack_message(response))
        except Exception as e:
            logger.error(f"[NATSBridge] Config req handler error: {e}")
            try:
                from ruvon.utils.serialization import pack_message
                await msg.respond(pack_message({"error": str(e)}))
            except Exception:
                pass

    async def _handle_saf_sync(self, msg) -> None:
        """Process SAF sync batch via request/reply."""
        try:
            from ruvon.utils.serialization import unpack_message, pack_message
            data = unpack_message(msg.data)
            device_id = self._extract_device_id(msg.subject, "devices", "sync")

            if not device_id or not self.device_service:
                await msg.respond(pack_message({"accepted": [], "rejected": []}))
                return

            result = await self.device_service.process_saf_sync(device_id, data)
            await msg.respond(pack_message(result))
        except Exception as e:
            logger.error(f"[NATSBridge] SAF sync handler error: {e}")
            try:
                from ruvon.utils.serialization import pack_message
                await msg.respond(pack_message({"error": str(e)}))
            except Exception:
                pass

    async def _handle_workflow_sync(self, msg) -> None:
        """Store workflow sync batch via persistence provider."""
        try:
            from ruvon.utils.serialization import unpack_message
            data = unpack_message(msg.data)
            if self.persistence and hasattr(self.persistence, "save_edge_workflow_batch"):
                await self.persistence.save_edge_workflow_batch(data)
        except Exception as e:
            logger.error(f"[NATSBridge] Workflow sync handler error: {e}")

    # ------------------------------------------------------------------
    # Outbound: commands + config push
    # ------------------------------------------------------------------

    async def send_command(self, device_id: str, command: Dict[str, Any]) -> bool:
        """
        Publish a command to the device's JetStream workqueue.

        The command is held durably until the device ACKs — eliminating the
        60s HTTP polling gap for command delivery.
        """
        if not self._running or not self._js:
            return False

        subject = f"devices.{device_id}.commands"
        try:
            from ruvon.utils.serialization import pack_message
            data = pack_message(command)
            await self._js.publish(subject, data)
            logger.debug(f"[NATSBridge] Command published to {subject}")
            return True
        except Exception as e:
            logger.error(f"[NATSBridge] send_command failed: {e}")
            return False

    async def push_config(self, device_id: str, config: Dict[str, Any], etag: str) -> bool:
        """
        Push config to device via CONFIG_UPDATES stream (last-per-subject).

        The device receives the latest config even after extended offline periods.
        """
        if not self._running or not self._js:
            return False

        subject = f"devices.{device_id}.config"
        try:
            from ruvon.utils.serialization import pack_message
            data = pack_message(config)
            await self._js.publish(subject, data)
            logger.info(f"[NATSBridge] Config pushed to device {device_id}")
            return True
        except Exception as e:
            logger.error(f"[NATSBridge] push_config failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_device_id(subject: str, prefix: str, suffix: str) -> Optional[str]:
        """Extract device_id from subject like 'devices.{device_id}.heartbeat'."""
        try:
            parts = subject.split(".")
            # subject = prefix.device_id.suffix
            # find device_id between prefix and suffix parts
            prefix_parts = prefix.split(".")
            suffix_parts = suffix.split(".")
            n_prefix = len(prefix_parts)
            n_suffix = len(suffix_parts)
            device_id_parts = parts[n_prefix: len(parts) - n_suffix]
            return ".".join(device_id_parts) if device_id_parts else None
        except Exception:
            return None

    async def _on_error(self, e) -> None:
        logger.error(f"[NATSBridge] NATS error: {e}")


# ---------------------------------------------------------------------------
# Module-level singleton (accessed from main.py lifespan)
# ---------------------------------------------------------------------------

_bridge_instance: Optional[NATSBridge] = None


def get_nats_bridge() -> Optional[NATSBridge]:
    return _bridge_instance


def set_nats_bridge(bridge: NATSBridge) -> None:
    global _bridge_instance
    _bridge_instance = bridge
