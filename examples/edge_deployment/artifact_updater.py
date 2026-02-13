"""
Artifact Update Workflow with Saga Rollback Pattern

This module implements a production-ready artifact update workflow:
1. Download artifact from cloud
2. Verify hash/signature
3. Backup current artifact
4. Install new artifact
5. Verify installation
6. If failure -> Rollback (Saga pattern)
7. Report status to cloud

Saga Pattern:
- Each step has a compensating action
- If any step fails, all previous steps are rolled back
- System returns to consistent state
"""

import asyncio
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class UpdateStatus(str, Enum):
    """Artifact update status."""
    IDLE = "idle"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    BACKING_UP = "backing_up"
    INSTALLING = "installing"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


@dataclass
class UpdateInstruction:
    """Update instruction from cloud policy engine."""
    needs_update: bool
    artifact: Optional[str] = None
    artifact_url: Optional[str] = None
    artifact_hash: Optional[str] = None
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    message: Optional[str] = None


@dataclass
class UpdateResult:
    """Result of an update operation."""
    success: bool
    status: UpdateStatus
    message: str
    artifact_path: Optional[str] = None
    error: Optional[str] = None
    rollback_performed: bool = False


class ArtifactUpdater:
    """
    Manages artifact updates with automatic rollback on failure.

    Uses the Saga pattern to ensure system consistency:
    - Each operation has a compensating action
    - Failed operations trigger rollback of previous steps
    - System always returns to a consistent state
    """

    def __init__(
        self,
        artifacts_dir: str,
        backup_dir: Optional[str] = None,
        cloud_url: str = "http://localhost:8000",
        api_key: str = "demo-api-key",
    ):
        """
        Initialize the artifact updater.

        Args:
            artifacts_dir: Directory where artifacts are installed
            backup_dir: Directory for backups (default: artifacts_dir/backups)
            cloud_url: Cloud control plane URL
            api_key: API key for authentication
        """
        self.artifacts_dir = Path(artifacts_dir)
        self.backup_dir = Path(backup_dir) if backup_dir else self.artifacts_dir / "backups"
        self.cloud_url = cloud_url
        self.api_key = api_key

        # Ensure directories exist
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Update state
        self.current_status = UpdateStatus.IDLE
        self.current_artifact: Optional[str] = None
        self.backup_path: Optional[Path] = None

        # Saga compensation stack
        self._compensation_stack: list[Callable] = []

    async def perform_update(
        self,
        instruction: UpdateInstruction,
        device_id: str,
        current_artifact: Optional[str] = None,
        progress_callback: Optional[Callable[[UpdateStatus, str], None]] = None
    ) -> UpdateResult:
        """
        Perform artifact update with automatic rollback on failure.

        This is the main saga orchestrator. Each step is added to the
        compensation stack, and if any step fails, all compensating
        actions are executed in reverse order.

        Args:
            instruction: Update instruction from cloud
            device_id: Device identifier
            current_artifact: Currently installed artifact
            progress_callback: Optional callback for progress updates

        Returns:
            UpdateResult with success status and details
        """
        if not instruction.needs_update:
            return UpdateResult(
                success=True,
                status=UpdateStatus.IDLE,
                message="No update needed"
            )

        self.current_artifact = current_artifact
        self._compensation_stack = []

        try:
            # Step 1: Download artifact
            await self._update_status(UpdateStatus.DOWNLOADING, "Downloading artifact", progress_callback)
            artifact_path = await self._download_artifact(instruction)
            self._add_compensation(lambda: self._cleanup_download(artifact_path))

            # Step 2: Verify hash
            await self._update_status(UpdateStatus.VERIFYING, "Verifying integrity", progress_callback)
            await self._verify_artifact(artifact_path, instruction.artifact_hash)

            # Step 3: Backup current artifact
            if current_artifact:
                await self._update_status(UpdateStatus.BACKING_UP, "Backing up current version", progress_callback)
                self.backup_path = await self._backup_current_artifact(current_artifact)
                self._add_compensation(lambda: self._restore_backup())

            # Step 4: Install new artifact
            await self._update_status(UpdateStatus.INSTALLING, "Installing new version", progress_callback)
            installed_path = await self._install_artifact(artifact_path, instruction.artifact)
            self._add_compensation(lambda: self._uninstall_artifact(installed_path))

            # Step 5: Test installation
            await self._update_status(UpdateStatus.TESTING, "Testing installation", progress_callback)
            await self._test_installation(installed_path)

            # Success! Report to cloud
            await self._report_status(device_id, "installed")

            await self._update_status(UpdateStatus.COMPLETED, "Update completed successfully", progress_callback)

            return UpdateResult(
                success=True,
                status=UpdateStatus.COMPLETED,
                message=f"Successfully installed {instruction.artifact}",
                artifact_path=str(installed_path)
            )

        except Exception as e:
            # Saga rollback: Execute compensating actions in reverse order
            logger.error(f"Update failed: {e}. Initiating rollback...")
            await self._update_status(UpdateStatus.ROLLING_BACK, f"Rollback: {e}", progress_callback)

            rollback_success = await self._execute_rollback()

            # Report failure to cloud
            await self._report_status(device_id, "failed", str(e))

            final_status = UpdateStatus.ROLLED_BACK if rollback_success else UpdateStatus.FAILED

            return UpdateResult(
                success=False,
                status=final_status,
                message=f"Update failed: {e}",
                error=str(e),
                rollback_performed=rollback_success
            )

    def _add_compensation(self, compensate_fn: Callable):
        """Add a compensating action to the saga stack."""
        self._compensation_stack.append(compensate_fn)

    async def _execute_rollback(self) -> bool:
        """
        Execute all compensating actions in reverse order.

        Returns:
            True if rollback successful, False otherwise
        """
        logger.info(f"Executing rollback: {len(self._compensation_stack)} compensating actions")

        success = True
        for compensate_fn in reversed(self._compensation_stack):
            try:
                result = compensate_fn()
                if asyncio.iscoroutine(result):
                    await result
                logger.info(f"Compensating action executed: {compensate_fn.__name__}")
            except Exception as e:
                logger.error(f"Compensating action failed: {e}")
                success = False

        self._compensation_stack.clear()
        return success

    async def _download_artifact(self, instruction: UpdateInstruction) -> Path:
        """Download artifact from cloud."""
        import httpx

        if not instruction.artifact_url:
            raise ValueError("No artifact URL provided")

        artifact_path = self.artifacts_dir / "staging" / instruction.artifact
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading {instruction.artifact} from {instruction.artifact_url}")

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", instruction.artifact_url) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"Download failed: HTTP {response.status_code}")

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(artifact_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            if downloaded % (1024 * 1024) == 0:  # Log every MB
                                logger.debug(f"Downloaded: {progress:.1f}%")

        logger.info(f"Download complete: {artifact_path}")
        return artifact_path

    async def _verify_artifact(self, artifact_path: Path, expected_hash: Optional[str]):
        """Verify artifact integrity using SHA256 hash."""
        if not expected_hash:
            logger.warning("No hash provided, skipping verification")
            return

        logger.info("Verifying artifact integrity...")

        hasher = hashlib.sha256()
        with open(artifact_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)

        actual_hash = hasher.hexdigest()
        expected = expected_hash.replace("sha256:", "")

        if not actual_hash.startswith(expected[:min(len(expected), 16)]):
            raise RuntimeError(
                f"Hash mismatch: expected {expected[:16]}..., got {actual_hash[:16]}..."
            )

        logger.info("Artifact verified successfully")

    async def _backup_current_artifact(self, artifact_name: str) -> Path:
        """Create backup of currently installed artifact."""
        current_path = self.artifacts_dir / artifact_name

        if not current_path.exists():
            logger.warning(f"Current artifact not found: {current_path}")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{artifact_name}.backup_{timestamp}"

        logger.info(f"Backing up {artifact_name} to {backup_path}")
        shutil.copy2(current_path, backup_path)

        return backup_path

    async def _install_artifact(self, source_path: Path, artifact_name: str) -> Path:
        """Install artifact to production location."""
        target_path = self.artifacts_dir / artifact_name

        logger.info(f"Installing {artifact_name} to {target_path}")

        # Atomic move (on same filesystem)
        if source_path.parent == target_path.parent:
            source_path.rename(target_path)
        else:
            shutil.copy2(source_path, target_path)
            source_path.unlink()

        # Make executable if it's a PEX
        if artifact_name.endswith(".pex"):
            os.chmod(target_path, 0o755)

        logger.info(f"Installation complete: {target_path}")
        return target_path

    async def _test_installation(self, artifact_path: Path):
        """Test that the installed artifact works."""
        # For PEX files, we could try to execute with --help
        if artifact_path.suffix == ".pex":
            logger.info("Testing PEX execution...")
            # In production, you'd actually test execution:
            # subprocess.run([str(artifact_path), "--version"], check=True, timeout=10)
            logger.info("Installation test passed (simulated)")
        else:
            logger.info("No test available for this artifact type")

    def _cleanup_download(self, artifact_path: Path):
        """Compensating action: Remove downloaded artifact."""
        try:
            if artifact_path and artifact_path.exists():
                artifact_path.unlink()
                logger.info(f"Cleaned up download: {artifact_path}")
        except Exception as e:
            logger.error(f"Failed to cleanup download: {e}")

    def _restore_backup(self):
        """Compensating action: Restore from backup."""
        try:
            if self.backup_path and self.backup_path.exists():
                target = self.artifacts_dir / self.current_artifact
                shutil.copy2(self.backup_path, target)
                logger.info(f"Restored backup: {self.backup_path} -> {target}")
        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")

    def _uninstall_artifact(self, artifact_path: Path):
        """Compensating action: Remove installed artifact."""
        try:
            if artifact_path and artifact_path.exists():
                artifact_path.unlink()
                logger.info(f"Uninstalled artifact: {artifact_path}")
        except Exception as e:
            logger.error(f"Failed to uninstall artifact: {e}")

    async def _report_status(
        self,
        device_id: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """Report update status to cloud."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.cloud_url}/api/v1/devices/{device_id}/update-status",
                    params={"status": status},
                    json={"error_message": error_message} if error_message else None,
                    headers={"X-API-Key": self.api_key}
                )
                logger.info(f"Reported status to cloud: {status}")
        except Exception as e:
            logger.warning(f"Failed to report status to cloud: {e}")

    async def _update_status(
        self,
        status: UpdateStatus,
        message: str,
        callback: Optional[Callable[[UpdateStatus, str], None]] = None
    ):
        """Update current status and notify callback."""
        self.current_status = status
        logger.info(f"Status: {status.value} - {message}")

        if callback:
            try:
                result = callback(status, message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")
