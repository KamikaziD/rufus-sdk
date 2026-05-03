"""
HTTPEdgeTransport — pure extraction of existing HTTP logic from agent.py,
sync_manager.py, config_manager.py, and workflow_sync.py.

Zero behavior change — this class is a direct refactor of the code that
was previously inlined. The agent delegates to this transport when
RUVON_NATS_URL is not set.
"""
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HTTPEdgeTransport:
    """HTTP polling transport — always-on fallback, no additional deps."""

    def __init__(
        self,
        device_id: str,
        cloud_url: str,
        api_key: str,
    ):
        self.device_id = device_id
        self.cloud_url = cloud_url.rstrip("/")
        self.api_key = api_key

    async def connect(self) -> None:
        """HTTP is connectionless — no-op."""

    async def disconnect(self) -> None:
        """HTTP is connectionless — no-op."""

    async def check_connectivity(self) -> bool:
        """Ping cloud health endpoint."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.cloud_url}/health",
                    headers=self._headers(),
                )
            return resp.status_code < 500
        except Exception:
            return False

    async def send_heartbeat(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """POST heartbeat, return commands list from response."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/heartbeat",
                    json=payload,
                    headers=self._headers(),
                )
            if response.status_code == 200:
                return response.json().get("commands", [])
            logger.warning(f"[HTTPTransport] Heartbeat status {response.status_code}")
            return []
        except Exception as e:
            logger.warning(f"[HTTPTransport] Heartbeat error: {e}")
            return []

    async def subscribe_commands(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """HTTP mode: commands come back in heartbeat response — no subscription needed."""

    async def sync_transactions(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """POST SAF transaction batch to cloud sync endpoint."""
        import json as _json
        import httpx

        payload_bytes = _json.dumps(batch, sort_keys=True).encode("utf-8")
        headers = self._headers()
        headers["X-Device-ID"] = self.device_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/sync",
                    content=payload_bytes,
                    headers={**headers, "Content-Type": "application/json"},
                )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def pull_config(self, etag: Optional[str]) -> Dict[str, Any]:
        """GET device config with conditional ETag."""
        import httpx

        headers = self._headers()
        if etag:
            headers["If-None-Match"] = etag

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/config",
                    headers=headers,
                )
            if resp.status_code == 304:
                return {"not_modified": True, "config": None, "etag": etag}
            if resp.status_code == 200:
                new_etag = resp.headers.get("ETag") or resp.headers.get("etag")
                return {"not_modified": False, "config": resp.json(), "etag": new_etag}
            return {"not_modified": False, "config": None, "etag": etag,
                    "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"not_modified": False, "config": None, "etag": etag, "error": str(e)}

    async def subscribe_config_push(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """HTTP mode: config updates arrive via pull_config polling — no subscription needed."""

    async def sync_workflows(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """POST completed workflow batch to cloud."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/sync/workflows",
                    json=batch,
                    headers=self._headers(),
                )
            if resp.status_code in (200, 201):
                return resp.json()
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def _headers(self) -> Dict[str, str]:
        h = {}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h
