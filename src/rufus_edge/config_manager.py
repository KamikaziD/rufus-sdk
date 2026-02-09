"""
ConfigManager - ETag-based configuration polling from cloud.

Handles:
- Periodic config polling with ETag caching
- Hot-reload of workflow definitions
- Fraud rule injection
- Feature flag updates
- Policy-based artifact management (via Cloud Policy Engine)
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
import hashlib
import httpx

from rufus_edge.models import DeviceConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Update Instruction Models (matches server-side policy_engine.py)
# ============================================================================

class UpdateInstruction:
    """Artifact update instruction from Cloud Policy Engine."""

    def __init__(
        self,
        needs_update: bool,
        artifact: Optional[str] = None,
        artifact_url: Optional[str] = None,
        artifact_hash: Optional[str] = None,
        policy_id: Optional[str] = None,
        policy_version: Optional[str] = None,
        message: Optional[str] = None,
    ):
        self.needs_update = needs_update
        self.artifact = artifact
        self.artifact_url = artifact_url
        self.artifact_hash = artifact_hash
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.message = message

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UpdateInstruction":
        return cls(
            needs_update=data.get("needs_update", False),
            artifact=data.get("artifact"),
            artifact_url=data.get("artifact_url"),
            artifact_hash=data.get("artifact_hash"),
            policy_id=data.get("policy_id"),
            policy_version=data.get("policy_version"),
            message=data.get("message"),
        )


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
        """Load cached config from local storage via SQLite tasks table."""
        if not self.persistence:
            return

        try:
            async with self.persistence.conn.execute(
                """
                SELECT task_data FROM tasks
                WHERE step_name = 'CONFIG_CACHE'
                  AND execution_id = ?
                  AND status = 'COMPLETED'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (self.device_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                cached = self.persistence._deserialize_json(row[0])
                if cached and "config" in cached:
                    self._current_config = DeviceConfig(**cached["config"])
                    self._current_etag = cached.get("etag")
                    logger.info("Loaded cached config from local storage")
        except Exception as e:
            logger.warning(f"Failed to load cached config: {e}")

    async def _cache_config(self):
        """Cache current config to local storage via SQLite tasks table."""
        if not self.persistence or not self._current_config:
            return

        try:
            cache_data = self.persistence._serialize_json({
                "config": self._current_config.model_dump(mode="json"),
                "etag": self._current_etag,
                "cached_at": datetime.utcnow().isoformat(),
            })

            # Upsert: delete old cache, insert new
            await self.persistence.conn.execute(
                """
                DELETE FROM tasks
                WHERE step_name = 'CONFIG_CACHE' AND execution_id = ?
                """,
                (self.device_id,)
            )
            await self.persistence.conn.execute(
                """
                INSERT INTO tasks (
                    task_id, execution_id, step_name, step_index,
                    status, task_data
                ) VALUES (?, ?, 'CONFIG_CACHE', 0, 'COMPLETED', ?)
                """,
                (
                    self.persistence._generate_uuid(),
                    self.device_id,
                    cache_data,
                )
            )
            await self.persistence.conn.commit()
            logger.debug("Cached config to local storage")
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

    # ─────────────────────────────────────────────────────────────────────────
    # Model Management
    # ─────────────────────────────────────────────────────────────────────────

    def get_model_config(self, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get model configuration by name.

        Model config from cloud includes:
        - version: Model version string
        - url: Download URL for model file
        - hash: SHA256 hash for integrity verification
        - runtime: Inference runtime (tflite, onnx)
        - size_kb: Model file size for download progress
        """
        if self._current_config and self._current_config.models:
            return self._current_config.models.get(model_name)
        return None

    def get_all_model_configs(self) -> Dict[str, Any]:
        """Get all model configurations."""
        if self._current_config and self._current_config.models:
            return self._current_config.models
        return {}

    def is_model_update_available(self, model_name: str, current_version: str) -> bool:
        """
        Check if a model update is available.

        Args:
            model_name: Name of the model
            current_version: Currently installed version

        Returns:
            True if a newer version is available in config
        """
        model_config = self.get_model_config(model_name)
        if not model_config:
            return False

        config_version = model_config.get("version", "0.0.0")
        return self._version_compare(config_version, current_version) > 0

    def _version_compare(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.

        Returns:
            -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
        """
        try:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]

            # Pad shorter version with zeros
            max_len = max(len(parts1), len(parts2))
            parts1.extend([0] * (max_len - len(parts1)))
            parts2.extend([0] * (max_len - len(parts2)))

            for p1, p2 in zip(parts1, parts2):
                if p1 < p2:
                    return -1
                if p1 > p2:
                    return 1
            return 0
        except (ValueError, AttributeError):
            # Fall back to string comparison
            if v1 < v2:
                return -1
            if v1 > v2:
                return 1
            return 0

    async def download_model(
        self,
        model_name: str,
        destination_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Download a model file from cloud.

        Args:
            model_name: Name of the model in config
            destination_path: Local path to save the model
            progress_callback: Optional callback(bytes_downloaded, total_bytes)

        Returns:
            True if download successful and hash verified
        """
        model_config = self.get_model_config(model_name)
        if not model_config:
            logger.error(f"Model {model_name} not found in config")
            return False

        url = model_config.get("url")
        expected_hash = model_config.get("hash")

        if not url:
            logger.error(f"No download URL for model {model_name}")
            return False

        if not self._http_client:
            logger.error("HTTP client not initialized")
            return False

        try:
            import os
            from pathlib import Path

            # Ensure directory exists
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)

            logger.info(f"Downloading model {model_name} from {url}")

            # Stream download for large files
            async with self._http_client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.error(f"Model download failed: HTTP {response.status_code}")
                    return False

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                hasher = hashlib.sha256()

                with open(destination_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)

            # Verify hash if provided
            if expected_hash:
                actual_hash = hasher.hexdigest()
                # Support both full hash and prefix matching
                if not actual_hash.startswith(expected_hash.replace("sha256:", "")):
                    logger.error(
                        f"Model hash mismatch: expected {expected_hash}, got {actual_hash}"
                    )
                    os.remove(destination_path)
                    return False

            logger.info(f"Model {model_name} downloaded successfully to {destination_path}")
            return True

        except Exception as e:
            logger.error(f"Model download error: {e}")
            return False

    async def sync_models(
        self,
        models_dir: str,
        inference_executor=None
    ) -> Dict[str, bool]:
        """
        Sync all models from config to local storage.

        Downloads new models and updates existing ones if newer versions available.

        Args:
            models_dir: Directory to store model files
            inference_executor: Optional InferenceExecutor to reload models

        Returns:
            Dict mapping model_name to success status
        """
        import os
        from pathlib import Path

        results = {}
        model_configs = self.get_all_model_configs()

        for model_name, config in model_configs.items():
            version = config.get("version", "1.0.0")
            runtime = config.get("runtime", "tflite")
            extension = ".tflite" if runtime == "tflite" else ".onnx"

            # Determine local path
            local_path = os.path.join(models_dir, f"{model_name}_v{version}{extension}")
            version_file = os.path.join(models_dir, f"{model_name}.version")

            # Check if already have this version
            current_version = None
            if os.path.exists(version_file):
                with open(version_file, "r") as f:
                    current_version = f.read().strip()

            if current_version == version and os.path.exists(local_path):
                logger.debug(f"Model {model_name} v{version} already up to date")
                results[model_name] = True
                continue

            # Download new version
            success = await self.download_model(model_name, local_path)
            results[model_name] = success

            if success:
                # Update version file
                Path(version_file).parent.mkdir(parents=True, exist_ok=True)
                with open(version_file, "w") as f:
                    f.write(version)

                # Reload model in executor if provided
                if inference_executor:
                    try:
                        provider = inference_executor.get_provider(runtime)
                        if provider and provider.is_model_loaded(model_name):
                            await provider.unload_model(model_name)
                            await provider.load_model(
                                model_path=local_path,
                                model_name=model_name,
                                model_version=version
                            )
                            logger.info(f"Reloaded model {model_name} v{version}")
                    except Exception as e:
                        logger.error(f"Failed to reload model {model_name}: {e}")

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Policy Engine Integration - Artifact Update Checking
    # ─────────────────────────────────────────────────────────────────────────

    async def check_for_artifact_update(
        self,
        current_artifact: Optional[str] = None,
        current_hash: Optional[str] = None,
    ) -> UpdateInstruction:
        """
        Check Cloud Policy Engine for artifact updates.

        This is the edge-side component of the "Hardware Handshake":
        1. Device sends its Hardware Identity
        2. Cloud evaluates active Policies
        3. Cloud returns appropriate artifact instruction

        Args:
            current_artifact: Currently running artifact filename
            current_hash: Hash of current artifact for verification

        Returns:
            UpdateInstruction with details about any available update
        """
        if not self._http_client:
            logger.error("HTTP client not initialized")
            return UpdateInstruction(needs_update=False, message="HTTP client not initialized")

        try:
            # Build hardware identity
            hw_identity = await self._get_hardware_identity()
            hw_identity["current_artifact"] = current_artifact
            hw_identity["current_hash"] = current_hash

            # Call update-check endpoint
            response = await self._http_client.post(
                f"{self.config_url}/api/v1/update-check",
                json=hw_identity,
            )

            if response.status_code == 200:
                data = response.json()
                instruction = UpdateInstruction.from_dict(data)

                if instruction.needs_update:
                    logger.info(
                        f"Artifact update available: {instruction.artifact} "
                        f"(policy: {instruction.policy_version})"
                    )
                else:
                    logger.debug(f"No update needed: {instruction.message}")

                return instruction

            else:
                logger.error(f"Update check failed: HTTP {response.status_code}")
                return UpdateInstruction(
                    needs_update=False,
                    message=f"HTTP {response.status_code}"
                )

        except httpx.RequestError as e:
            logger.warning(f"Update check network error: {e}")
            return UpdateInstruction(needs_update=False, message=str(e))

    async def _get_hardware_identity(self) -> Dict[str, Any]:
        """
        Get hardware identity for Policy Engine check-in.

        Uses InferenceFactory if available for full hardware detection.
        """
        try:
            from rufus.implementations.inference.factory import InferenceFactory
            factory = InferenceFactory()
            identity = factory.get_hardware_identity(self.device_id)
            return identity.to_dict()
        except ImportError:
            # Fallback to basic detection
            pass

        try:
            from rufus.utils.platform import get_platform_info
            info = get_platform_info()
            return {
                "device_id": self.device_id,
                "hw": "APPLE_SILICON" if info.is_apple_silicon else "CPU",
                "platform": info.system,
                "arch": info.machine,
                "accelerators": [a.value for a in info.accelerators],
                "supports_neural_engine": info.is_apple_silicon,
            }
        except ImportError:
            pass

        # Minimal fallback
        import platform
        return {
            "device_id": self.device_id,
            "hw": "CPU",
            "platform": platform.system(),
            "arch": platform.machine(),
            "accelerators": ["cpu"],
        }

    async def download_artifact(
        self,
        instruction: UpdateInstruction,
        destination_dir: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Optional[str]:
        """
        Download artifact based on Policy Engine instruction.

        Args:
            instruction: UpdateInstruction from check_for_artifact_update
            destination_dir: Directory to save the artifact
            progress_callback: Optional callback(bytes_downloaded, total_bytes)

        Returns:
            Path to downloaded artifact, or None if failed
        """
        if not instruction.needs_update or not instruction.artifact_url:
            logger.warning("No artifact URL in update instruction")
            return None

        if not self._http_client:
            logger.error("HTTP client not initialized")
            return None

        try:
            import os
            from pathlib import Path

            # Ensure directory exists
            Path(destination_dir).mkdir(parents=True, exist_ok=True)

            destination_path = os.path.join(destination_dir, instruction.artifact)

            logger.info(f"Downloading artifact {instruction.artifact}")

            # Stream download
            async with self._http_client.stream("GET", instruction.artifact_url) as response:
                if response.status_code != 200:
                    logger.error(f"Artifact download failed: HTTP {response.status_code}")
                    return None

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                hasher = hashlib.sha256()

                with open(destination_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)

            # Verify hash if provided
            if instruction.artifact_hash:
                actual_hash = hasher.hexdigest()
                expected = instruction.artifact_hash.replace("sha256:", "")
                if not actual_hash.startswith(expected[:min(len(expected), 16)]):
                    logger.error(
                        f"Artifact hash mismatch: expected {expected}, got {actual_hash}"
                    )
                    os.remove(destination_path)
                    return None

            logger.info(f"Artifact downloaded successfully: {destination_path}")

            # Report download status to cloud
            await self._report_update_status("downloading")

            return destination_path

        except Exception as e:
            logger.error(f"Artifact download error: {e}")
            await self._report_update_status("failed", str(e))
            return None

    async def _report_update_status(
        self,
        status: str,
        error_message: Optional[str] = None
    ):
        """Report artifact update status to Cloud Policy Engine."""
        if not self._http_client:
            return

        try:
            await self._http_client.post(
                f"{self.config_url}/api/v1/devices/{self.device_id}/update-status",
                params={"status": status},
                json={"error_message": error_message} if error_message else None,
            )
        except Exception as e:
            logger.warning(f"Failed to report update status: {e}")
