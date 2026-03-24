"""
EdgeTransport — protocol interface for edge-to-cloud communication.

Implementations:
  HTTPEdgeTransport — standard HTTP polling (always available)
  NATSEdgeTransport — sub-millisecond pub/sub (when RUFUS_NATS_URL is set)

All methods are async. The transport is created once in RufusEdgeAgent.start()
and torn down in stop().
"""
from typing import Any, Callable, Dict, List, Optional
from typing_extensions import Protocol, runtime_checkable


@runtime_checkable
class EdgeTransport(Protocol):
    """
    Protocol for edge-to-cloud transport abstraction.

    Implementations must be safe to use as async context managers at the
    agent level: connect() on start, disconnect() on stop.
    """

    async def connect(self) -> None:
        """Establish connection (idempotent)."""
        ...

    async def disconnect(self) -> None:
        """Tear down connection gracefully."""
        ...

    async def check_connectivity(self) -> bool:
        """Return True if the cloud endpoint is reachable."""
        ...

    async def send_heartbeat(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Send heartbeat payload to cloud.

        HTTP mode: POSTs to /api/v1/devices/{id}/heartbeat, returns the
        'commands' list from the response body.

        NATS mode: publishes to devices.{id}.heartbeat JetStream subject,
        returns [] — commands arrive via subscribe_commands() push instead.
        """
        ...

    async def subscribe_commands(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Subscribe to cloud-push commands (NATS mode only).

        callback: async def handler(command: dict) -> None

        HTTP mode: no-op (commands returned in send_heartbeat response).
        NATS mode: creates durable push consumer on DEVICE_COMMANDS workqueue;
        callback is invoked for each command; message is ACK'd after callback.
        """
        ...

    async def sync_transactions(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload a SAF transaction batch to cloud.

        Returns the parsed response body dict.
        """
        ...

    async def pull_config(self, etag: Optional[str]) -> Dict[str, Any]:
        """
        Fetch device config from cloud with ETag conditional GET.

        Returns dict with keys:
          not_modified: bool
          config: dict | None
          etag: str | None
        """
        ...

    async def subscribe_config_push(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Subscribe to server-initiated config updates (NATS mode only).

        HTTP mode: no-op (config arrives via pull_config polling).
        NATS mode: subscribes to CONFIG_UPDATES last-per-subject stream;
        callback receives the new config dict on push.
        """
        ...

    async def sync_workflows(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Push completed edge workflow executions to cloud.

        Returns the parsed response body dict.
        """
        ...
