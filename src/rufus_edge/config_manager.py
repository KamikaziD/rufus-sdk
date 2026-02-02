"""
ConfigManager - ETag-based configuration polling from cloud.

Handles:
- Periodic config polling with ETag caching
- Hot-reload of workflow definitions
- Fraud rule injection
- Feature flag updates
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import hashlib
import httpx

from rufus_edge.models import DeviceConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages device configuration from cloud control plane.

    Features:
    - ETag-based conditional polling (304 Not Modified)
    - Local caching with persistence
    - Hot-reload callbacks for config changes
    - Fraud rule injection support
    """

    def __init__(
        self,
        config_url: str,
        device_id: str,
        api_key: str,
        poll_interval_seconds: int = 60,
        persistence=None,
    ):
        self.config_url = config_url
        self.device_id = device_id
        self.api_key = api_key
        self.poll_interval_seconds = poll_interval_seconds
        self.persistence = persistence

        self._current_config: Optional[DeviceConfig] = None
        self._current_etag: Optional[str] = None
        self._last_poll_at: Optional[datetime] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._on_config_change_callbacks: list[Callable[[DeviceConfig], None]] = []

    @property
    def config(self) -> Optional[DeviceConfig]:
        """Get the current configuration."""
        return self._current_config

    async def initialize(self):
        """Initialize the config manager."""
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "X-API-Key": self.api_key,
                "X-Device-ID": self.device_id,
            }
        )

        # Load cached config if available
        await self._load_cached_config()

        # Do initial config pull
        await self.pull_config()

        logger.info(f"ConfigManager initialized for device {self.device_id}")

    async def close(self):
        """Close the config manager."""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass

        if self._http_client:
            await self._http_client.aclose()

    def on_config_change(self, callback: Callable[[DeviceConfig], None]):
        """Register a callback for config changes."""
        self._on_config_change_callbacks.append(callback)

    async def start_polling(self):
        """Start background config polling."""
        if self._polling_task and not self._polling_task.done():
            logger.warning("Polling already running")
            return

        self._polling_task = asyncio.create_task(self._polling_loop())
        logger.info(f"Started config polling every {self.poll_interval_seconds}s")

    async def stop_polling(self):
        """Stop background config polling."""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
            logger.info("Stopped config polling")

    async def _polling_loop(self):
        """Background polling loop."""
        while True:
            try:
                await asyncio.sleep(self.poll_interval_seconds)
                await self.pull_config()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Config polling error: {e}")

    async def pull_config(self) -> bool:
        """
        Pull configuration from cloud with ETag support.

        Returns:
            True if config was updated, False if unchanged
        """
        if not self._http_client:
            logger.error("HTTP client not initialized")
            return False

        headers = {}
        if self._current_etag:
            headers["If-None-Match"] = self._current_etag

        try:
            response = await self._http_client.get(
                f"{self.config_url}/api/v1/devices/{self.device_id}/config",
                headers=headers
            )

            self._last_poll_at = datetime.utcnow()

            if response.status_code == 304:
                # Config unchanged
                logger.debug("Config unchanged (304 Not Modified)")
                return False

            if response.status_code == 200:
                # New config available
                new_etag = response.headers.get("ETag")
                config_data = response.json()

                new_config = DeviceConfig(**config_data)
                old_config = self._current_config

                self._current_config = new_config
                self._current_etag = new_etag

                # Cache locally
                await self._cache_config()

                # Notify callbacks
                if old_config is None or old_config.version != new_config.version:
                    logger.info(f"Config updated to version {new_config.version}")
                    for callback in self._on_config_change_callbacks:
                        try:
                            callback(new_config)
                        except Exception as e:
                            logger.error(f"Config change callback error: {e}")

                return True

            else:
                logger.error(f"Config pull failed: HTTP {response.status_code}")
                return False

        except httpx.RequestError as e:
            logger.warning(f"Config pull network error: {e}")
            return False

    async def _load_cached_config(self):
        """Load cached config from local storage."""
        if not self.persistence:
            return

        try:
            # TODO: Implement config caching in persistence
            # cached = await self.persistence.get_cached_config(self.device_id)
            # if cached:
            #     self._current_config = DeviceConfig(**cached["config"])
            #     self._current_etag = cached.get("etag")
            pass
        except Exception as e:
            logger.warning(f"Failed to load cached config: {e}")

    async def _cache_config(self):
        """Cache current config to local storage."""
        if not self.persistence or not self._current_config:
            return

        try:
            # TODO: Implement config caching in persistence
            # await self.persistence.cache_config(
            #     device_id=self.device_id,
            #     config=self._current_config.model_dump(),
            #     etag=self._current_etag
            # )
            pass
        except Exception as e:
            logger.warning(f"Failed to cache config: {e}")

    def get_floor_limit(self) -> float:
        """Get current floor limit for offline approval."""
        if self._current_config:
            return float(self._current_config.floor_limit)
        return 25.00  # Default

    def get_fraud_rules(self) -> list:
        """Get current fraud rules."""
        if self._current_config:
            return self._current_config.fraud_rules
        return []

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled."""
        if self._current_config:
            return self._current_config.features.get(feature, False)
        return False

    def get_workflow_config(self, workflow_type: str) -> Optional[Dict[str, Any]]:
        """Get workflow configuration by type."""
        if self._current_config:
            return self._current_config.workflows.get(workflow_type)
        return None

    def compute_config_hash(self) -> str:
        """Compute hash of current config for change detection."""
        if not self._current_config:
            return ""
        config_str = self._current_config.model_dump_json()
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]
