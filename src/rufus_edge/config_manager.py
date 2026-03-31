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

from rufus_edge.models import DeviceConfig
from rufus_edge.platform.base import PlatformAdapter

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
        adapter: Optional[PlatformAdapter] = None,
        platform_adapter: Optional[PlatformAdapter] = None,
    ):
        self.config_url = config_url
        self.device_id = device_id
        self.api_key = api_key
        self.poll_interval_seconds = poll_interval_seconds
        self.persistence = persistence

        self._current_config: Optional[DeviceConfig] = None
        self._current_etag: Optional[str] = None
        self._last_poll_at: Optional[datetime] = None
        self._adapter: Optional[PlatformAdapter] = platform_adapter or adapter
        self._polling_task: Optional[asyncio.Task] = None
        self._on_config_change_callbacks: list[Callable[[DeviceConfig], None]] = []

    @property
    def config(self) -> Optional[DeviceConfig]:
        """Get the current configuration."""
        return self._current_config

    async def initialize(self):
        """Initialize the config manager."""
        if self._adapter is None:
            from rufus_edge.platform import detect_platform
            self._adapter = detect_platform(
                default_headers={
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

        if self._adapter is not None and hasattr(self._adapter, "aclose"):
            await self._adapter.aclose()

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
        if not self._adapter:
            logger.error("Platform adapter not initialized")
            return False

        req_headers: Dict[str, str] = {
            "X-API-Key": self.api_key,
            "X-Device-ID": self.device_id,
        }
        if self._current_etag:
            req_headers["If-None-Match"] = self._current_etag

        try:
            response = await self._adapter.http_get(
                f"{self.config_url}/api/v1/devices/{self.device_id}/config",
                headers=req_headers,
            )

            self._last_poll_at = datetime.utcnow()

            if response.status_code == 304:
                # Config unchanged
                logger.debug("Config unchanged (304 Not Modified)")
                return False

            if response.status_code == 200:
                # New config available
                new_etag = response.headers.get("ETag") or response.headers.get("etag")
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

        except Exception as e:
            logger.warning(f"Config pull network error: {e}")
            return False

    async def _load_cached_config(self):
        """Load cached config from local storage via device_config_cache table."""
        if not self.persistence:
            return

        try:
            async with self.persistence.conn.execute(
                "SELECT config_data, etag FROM device_config_cache WHERE device_id = ?",
                (self.device_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                cached = self.persistence._deserialize_json(row[0])
                self._current_config = DeviceConfig(**cached)
                self._current_etag = row[1]
                logger.info("Loaded cached config from local storage")
        except Exception as e:
            logger.warning(f"Failed to load cached config: {e}")

    async def _cache_config(self):
        """Cache current config to local storage via device_config_cache table."""
        if not self.persistence or not self._current_config:
            return

        try:
            await self.persistence.conn.execute(
                """
                INSERT INTO device_config_cache
                    (device_id, config_version, config_data, etag, cached_at, last_poll_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id) DO UPDATE SET
                    config_version = excluded.config_version,
                    config_data    = excluded.config_data,
                    etag           = excluded.etag,
                    cached_at      = excluded.cached_at,
                    last_poll_at   = excluded.last_poll_at
                """,
                (
                    self.device_id,
                    self._current_config.version,
                    self.persistence._serialize_json(
                        self._current_config.model_dump(mode="json")
                    ),
                    self._current_etag,
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

    def get_offline_mode(self) -> bool:
        """Check if offline mode is enabled (default: True)."""
        if self._current_config:
            return self._current_config.features.get("offline_mode", True)
        return True

    def get_sync_interval(self) -> int:
        """Get sync interval in seconds from config."""
        if self._current_config:
            return self._current_config.sync_interval_seconds
        return 30

    def get_heartbeat_interval(self) -> int:
        """Get heartbeat interval in seconds from config."""
        if self._current_config:
            return self._current_config.heartbeat_interval_seconds
        return 60

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
        current_model_path: Optional[str] = None,
        use_delta: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Download a model file from cloud with delta update support.

        If a current model exists and delta URL is provided in config,
        attempts delta update first with automatic fallback to full download.

        Args:
            model_name: Name of the model in config
            destination_path: Local path to save the model
            current_model_path: Optional path to current model (for delta updates)
            use_delta: Whether to attempt delta updates (default: True)
            progress_callback: Optional callback(bytes_downloaded, total_bytes)

        Returns:
            True if download successful and hash verified
        """
        model_config = self.get_model_config(model_name)
        if not model_config:
            logger.error(f"Model {model_name} not found in config")
            return False

        url = model_config.get("url")
        delta_url = model_config.get("delta_url")  # Optional delta patch URL
        expected_hash = model_config.get("hash")

        if not url:
            logger.error(f"No download URL for model {model_name}")
            return False

        if not self._adapter:
            logger.error("Platform adapter not initialized")
            return False

        try:
            import os
            from pathlib import Path

            # Ensure directory exists
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)

            # Try delta update if available
            if (use_delta and delta_url and current_model_path
                and os.path.exists(current_model_path)):

                from rufus_edge.delta_updates import DeltaUpdateManager

                delta_manager = DeltaUpdateManager(http_client=self._adapter)
                success, stats = await delta_manager.download_and_apply_delta(
                    delta_url=delta_url,
                    current_model_path=current_model_path,
                    destination_path=destination_path,
                    expected_hash=expected_hash,
                    full_download_url=url,  # Fallback
                    progress_callback=progress_callback
                )

                if success:
                    if stats["used_delta"]:
                        logger.info(
                            f"Model {model_name} updated via delta: "
                            f"saved {stats['bandwidth_saved']} bytes"
                        )
                    else:
                        logger.info(
                            f"Model {model_name} downloaded (delta fallback: "
                            f"{stats.get('fallback_reason', 'unknown')})"
                        )
                    return True

                # Delta manager handles fallback automatically
                # If we get here, both delta and fallback failed
                logger.error(f"Model download failed for {model_name}")
                return False

            # Standard full download
            logger.info(f"Downloading model {model_name} from {url}")

            response = await self._adapter.http_get(
                url,
                headers={
                    "X-API-Key": self.api_key,
                    "X-Device-ID": self.device_id,
                },
            )
            if response.status_code != 200:
                logger.error(f"Model download failed: HTTP {response.status_code}")
                return False

            content = response.content
            hasher = hashlib.sha256()
            hasher.update(content)
            if progress_callback:
                progress_callback(len(content), len(content))

            with open(destination_path, "wb") as f:
                f.write(content)

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
        if not self._adapter:
            logger.error("Platform adapter not initialized")
            return UpdateInstruction(needs_update=False, message="Platform adapter not initialized")

        try:
            import json as _json
            # Build hardware identity
            hw_identity = await self._get_hardware_identity()
            hw_identity["current_artifact"] = current_artifact
            hw_identity["current_hash"] = current_hash

            # Call update-check endpoint
            response = await self._adapter.http_post(
                f"{self.config_url}/api/v1/update-check",
                body=_json.dumps(hw_identity).encode("utf-8"),
                headers={
                    "X-API-Key": self.api_key,
                    "X-Device-ID": self.device_id,
                },
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

        except Exception as e:
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

        if not self._adapter:
            logger.error("Platform adapter not initialized")
            return None

        try:
            import os
            from pathlib import Path

            # Ensure directory exists
            Path(destination_dir).mkdir(parents=True, exist_ok=True)

            destination_path = os.path.join(destination_dir, instruction.artifact)

            logger.info(f"Downloading artifact {instruction.artifact}")

            response = await self._adapter.http_get(
                instruction.artifact_url,
                headers={
                    "X-API-Key": self.api_key,
                    "X-Device-ID": self.device_id,
                },
            )
            if response.status_code != 200:
                logger.error(f"Artifact download failed: HTTP {response.status_code}")
                return None

            content = response.content
            hasher = hashlib.sha256()
            hasher.update(content)
            if progress_callback:
                progress_callback(len(content), len(content))

            with open(destination_path, "wb") as f:
                f.write(content)

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
        if not self._adapter:
            return

        try:
            import json as _json
            body_data: Dict[str, Any] = {"status": status}
            if error_message:
                body_data["error_message"] = error_message
            await self._adapter.http_post(
                f"{self.config_url}/api/v1/devices/{self.device_id}/update-status",
                body=_json.dumps(body_data).encode("utf-8"),
                headers={
                    "X-API-Key": self.api_key,
                    "X-Device-ID": self.device_id,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to report update status: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Device Command: update_workflow
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_update_workflow_command(
        self,
        payload: Dict[str, Any],
        workflow_builder=None,
    ) -> bool:
        """
        Handle an `update_workflow` device command delivered via the
        device_commands polling mechanism.

        The payload must contain:
            workflow_type  (str)  — e.g. "PaymentAuthorization"
            yaml_content   (str)  — full YAML string
            version        (int)  — for logging; optional

        Steps:
        1. Persist the YAML to local SQLite under a dedicated config-cache key.
        2. If a WorkflowBuilder instance is passed, call
           reload_workflow_type() to invalidate its caches immediately.
        3. New workflow starts use the updated YAML; running workflows are
           unaffected (their definition_snapshot is already frozen).

        Returns True on success, False on error.
        """
        workflow_type = payload.get("workflow_type")
        yaml_content = payload.get("yaml_content")
        version = payload.get("version", "?")

        if not workflow_type or not yaml_content:
            logger.error(
                "update_workflow command missing workflow_type or yaml_content"
            )
            return False

        # Persist to local SQLite so the YAML survives a device restart
        if self.persistence:
            try:
                await self.persistence.conn.execute(
                    """
                    INSERT INTO edge_workflow_cache (workflow_type, yaml_content, version, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(workflow_type) DO UPDATE SET
                        yaml_content = excluded.yaml_content,
                        version      = excluded.version,
                        updated_at   = excluded.updated_at
                    """,
                    (workflow_type, yaml_content, str(version))
                )
                await self.persistence.conn.commit()
                logger.info(
                    f"Persisted workflow definition '{workflow_type}' "
                    f"v{version} to local SQLite"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to persist workflow definition locally: {e}"
                )

        # Hot-reload the in-process WorkflowBuilder cache
        if workflow_builder is not None:
            try:
                workflow_builder.reload_workflow_type(workflow_type, yaml_content)
                logger.info(
                    f"Hot-reloaded edge workflow '{workflow_type}' v{version}"
                )
            except Exception as e:
                logger.error(
                    f"Edge hot-reload failed for '{workflow_type}': {e}"
                )
                return False

        return True

    async def load_local_workflow_definitions(self, workflow_builder=None) -> int:
        """
        On device startup, load any previously persisted workflow definitions
        from SQLite and inject them into the WorkflowBuilder.

        Returns the number of definitions loaded.
        """
        if not self.persistence or not workflow_builder:
            return 0

        loaded = 0
        try:
            async with self.persistence.conn.execute(
                "SELECT workflow_type, yaml_content, version FROM edge_workflow_cache"
            ) as cursor:
                rows = await cursor.fetchall()

            for workflow_type, yaml_content, version in rows:
                try:
                    workflow_builder.reload_workflow_type(workflow_type, yaml_content)
                    loaded += 1
                    logger.info(
                        f"Loaded local workflow definition '{workflow_type}' v{version}"
                    )
                    # Prefetch any WASM binaries referenced by this workflow
                    if self.persistence and self._adapter:
                        await self._prefetch_missing_wasm_binaries(yaml_content)
                except Exception as e:
                    logger.warning(
                        f"Failed to load cached definition '{workflow_type}': {e}"
                    )

        except Exception as e:
            logger.warning(f"Failed to load local workflow definitions: {e}")

        return loaded

    async def handle_sync_wasm_command(self, payload: dict) -> bool:
        """Handle a sync_wasm command from the cloud.

        Downloads a WASM binary identified by binary_hash and caches it in
        the device_wasm_cache SQLite table. Idempotent — silently skips if
        the hash is already cached.

        Args:
            payload: Command data dict containing:
                binary_hash (str): SHA-256 hex digest of the .wasm binary.

        Returns:
            True if the binary was newly cached; False if already present or on error.
        """
        import hashlib

        binary_hash = payload.get("binary_hash")
        if not binary_hash:
            logger.error("sync_wasm: missing binary_hash in command payload")
            return False

        if not self.persistence:
            logger.error("sync_wasm: persistence not available")
            return False

        if not self._adapter:
            logger.error("sync_wasm: Platform adapter not initialized")
            return False

        # Idempotency check
        try:
            cursor = await self.persistence.conn.execute(
                "SELECT 1 FROM device_wasm_cache WHERE binary_hash = ?",
                (binary_hash,),
            )
            row = await cursor.fetchone()
            if row:
                logger.info(f"sync_wasm: binary already cached: {binary_hash[:16]}…")
                return False
        except Exception as e:
            logger.warning(f"sync_wasm: cache lookup failed: {e}")

        # Download binary from cloud
        download_url = f"{self.config_url}/api/v1/wasm-components/{binary_hash}/download"
        logger.info(f"sync_wasm: downloading {binary_hash[:16]}… from {download_url}")
        try:
            response = await self._adapter.http_get(
                download_url,
                headers={
                    "X-API-Key": self.api_key,
                    "X-Device-ID": self.device_id,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            binary_data = response.content
        except Exception as e:
            logger.error(f"sync_wasm: download failed for {binary_hash[:16]}…: {e}")
            return False

        # Verify integrity
        actual_hash = hashlib.sha256(binary_data).hexdigest()
        if actual_hash != binary_hash:
            logger.error(
                f"sync_wasm: hash mismatch for downloaded binary "
                f"(expected {binary_hash[:16]}…, got {actual_hash[:16]}…)"
            )
            return False

        # Persist to SQLite cache
        try:
            from datetime import datetime
            now = datetime.utcnow().isoformat()
            await self.persistence.conn.execute(
                "INSERT OR REPLACE INTO device_wasm_cache (binary_hash, binary_data, last_accessed) "
                "VALUES (?, ?, ?)",
                (binary_hash, binary_data, now),
            )
            await self.persistence.conn.commit()
            logger.info(
                f"sync_wasm: cached {len(binary_data):,} bytes for {binary_hash[:16]}…"
            )
            return True
        except Exception as e:
            logger.error(f"sync_wasm: failed to write to device_wasm_cache: {e}")
            return False

    async def _prefetch_missing_wasm_binaries(self, yaml_content: str) -> None:
        """Scan a workflow YAML for WASM steps and prefetch any uncached binaries.

        Called from load_local_workflow_definitions() for each cached workflow.
        Missing binaries are fetched in the background so they are ready when
        the workflow runs.

        Args:
            yaml_content: Raw YAML string of the workflow definition.
        """
        import yaml as _yaml
        import asyncio

        try:
            config = _yaml.safe_load(yaml_content)
        except Exception as e:
            logger.debug(f"_prefetch_missing_wasm_binaries: YAML parse error: {e}")
            return

        steps = config.get("steps", []) if isinstance(config, dict) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") != "WASM":
                continue
            wasm_config = step.get("wasm_config", {})
            binary_hash = wasm_config.get("wasm_hash")
            if not binary_hash:
                continue

            # Check cache
            try:
                cursor = await self.persistence.conn.execute(
                    "SELECT 1 FROM device_wasm_cache WHERE binary_hash = ?",
                    (binary_hash,),
                )
                row = await cursor.fetchone()
                if row:
                    continue  # Already cached
            except Exception:
                continue

            logger.info(
                f"WASM binary not cached for step '{step.get('name')}' "
                f"(hash={binary_hash[:16]}…) — scheduling background fetch"
            )
            asyncio.ensure_future(
                self.handle_sync_wasm_command({"binary_hash": binary_hash})
            )
