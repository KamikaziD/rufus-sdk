"""
Delta Model Updates - Bandwidth-optimized model distribution.

Implements binary diff/patch for model files to reduce bandwidth consumption
when updating models on edge devices.

Uses bsdiff/bspatch algorithm for efficient binary patching.
"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Callable, Tuple, Dict, Any
import httpx

logger = logging.getLogger(__name__)


class DeltaUpdateManager:
    """
    Manages delta updates for model files.

    Features:
    - Binary diff generation (cloud-side)
    - Binary patch application (edge-side)
    - Automatic fallback to full download
    - Bandwidth usage tracking
    - Hash verification for patches
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initialize delta update manager.

        Args:
            http_client: Optional HTTP client for downloads
        """
        self._http_client = http_client
        self._bandwidth_saved = 0  # Track cumulative bandwidth savings

    async def download_and_apply_delta(
        self,
        delta_url: str,
        current_model_path: str,
        destination_path: str,
        expected_hash: str,
        full_download_url: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Download delta patch and apply to existing model.

        Falls back to full download if:
        - Delta download fails
        - Patch application fails
        - Hash verification fails
        - Current model file doesn't exist

        Args:
            delta_url: URL to download delta patch
            current_model_path: Path to current model file
            destination_path: Path to save updated model
            expected_hash: Expected SHA256 hash of final model
            full_download_url: Optional URL for full model (fallback)
            progress_callback: Optional progress callback(bytes, total)

        Returns:
            Tuple of (success, stats_dict)
            stats_dict includes: bandwidth_used, bandwidth_saved, used_delta
        """
        stats = {
            "bandwidth_used": 0,
            "bandwidth_saved": 0,
            "used_delta": False,
            "fallback_reason": None,
        }

        # Check if current model exists
        if not os.path.exists(current_model_path):
            logger.info("Current model not found, will perform full download")
            if full_download_url:
                return await self._full_download(
                    full_download_url,
                    destination_path,
                    expected_hash,
                    progress_callback,
                    stats
                )
            return False, stats

        try:
            # Download delta patch
            delta_file = tempfile.NamedTemporaryFile(delete=False, suffix=".delta")
            delta_path = delta_file.name
            delta_file.close()

            delta_size = await self._download_file(
                delta_url,
                delta_path,
                progress_callback
            )

            if delta_size == 0:
                logger.warning("Delta download failed, falling back to full download")
                stats["fallback_reason"] = "delta_download_failed"
                if full_download_url:
                    return await self._full_download(
                        full_download_url,
                        destination_path,
                        expected_hash,
                        progress_callback,
                        stats
                    )
                return False, stats

            stats["bandwidth_used"] = delta_size

            # Apply patch
            success = await self._apply_patch(
                current_model_path,
                delta_path,
                destination_path
            )

            # Cleanup delta file
            os.unlink(delta_path)

            if not success:
                logger.warning("Patch application failed, falling back to full download")
                stats["fallback_reason"] = "patch_failed"
                if full_download_url:
                    return await self._full_download(
                        full_download_url,
                        destination_path,
                        expected_hash,
                        progress_callback,
                        stats
                    )
                return False, stats

            # Verify hash
            actual_hash = await self._calculate_file_hash(destination_path)
            if not actual_hash.startswith(expected_hash.replace("sha256:", "")):
                logger.error(
                    f"Patched model hash mismatch: expected {expected_hash}, got {actual_hash}"
                )
                stats["fallback_reason"] = "hash_mismatch"
                if full_download_url:
                    return await self._full_download(
                        full_download_url,
                        destination_path,
                        expected_hash,
                        progress_callback,
                        stats
                    )
                return False, stats

            # Calculate bandwidth savings
            current_size = os.path.getsize(current_model_path)
            stats["bandwidth_saved"] = max(0, current_size - delta_size)
            stats["used_delta"] = True
            self._bandwidth_saved += stats["bandwidth_saved"]

            logger.info(
                f"Delta update successful: {delta_size} bytes downloaded "
                f"(saved {stats['bandwidth_saved']} bytes vs full download)"
            )

            return True, stats

        except Exception as e:
            logger.error(f"Delta update error: {e}")
            stats["fallback_reason"] = f"exception: {str(e)}"
            if full_download_url:
                return await self._full_download(
                    full_download_url,
                    destination_path,
                    expected_hash,
                    progress_callback,
                    stats
                )
            return False, stats

    async def _download_file(
        self,
        url: str,
        destination: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> int:
        """
        Download file from URL.

        Returns:
            Total bytes downloaded (0 if failed)
        """
        if not self._http_client:
            logger.error("HTTP client not initialized")
            return 0

        try:
            async with self._http_client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.error(f"Download failed: HTTP {response.status_code}")
                    return 0

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(destination, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)

                return downloaded

        except Exception as e:
            logger.error(f"Download error: {e}")
            return 0

    async def _full_download(
        self,
        url: str,
        destination: str,
        expected_hash: str,
        progress_callback: Optional[Callable[[int, int], None]],
        stats: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Perform full model download (fallback)."""
        logger.info(f"Performing full download from {url}")

        downloaded = await self._download_file(url, destination, progress_callback)

        if downloaded == 0:
            return False, stats

        stats["bandwidth_used"] = downloaded
        stats["used_delta"] = False

        # Verify hash
        actual_hash = await self._calculate_file_hash(destination)
        if not actual_hash.startswith(expected_hash.replace("sha256:", "")):
            logger.error(f"Model hash mismatch: expected {expected_hash}, got {actual_hash}")
            os.remove(destination)
            return False, stats

        return True, stats

    async def _apply_patch(
        self,
        old_file: str,
        patch_file: str,
        new_file: str
    ) -> bool:
        """
        Apply binary patch to create new file.

        Uses bspatch if available, falls back to Python implementation.

        Args:
            old_file: Path to current model
            patch_file: Path to delta patch
            new_file: Path to output updated model

        Returns:
            True if patch applied successfully
        """
        try:
            # Try using bspatch command (faster, native)
            import subprocess
            result = subprocess.run(
                ["bspatch", old_file, new_file, patch_file],
                capture_output=True,
                timeout=300  # 5 minute timeout
            )
            if result.returncode == 0:
                return True

            logger.warning("bspatch failed, trying Python implementation")

        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("bspatch not available, using Python implementation")

        # Fallback: Python implementation of bspatch
        try:
            import bsdiff4
            with open(old_file, "rb") as old_f:
                old_data = old_f.read()
            with open(patch_file, "rb") as patch_f:
                patch_data = patch_f.read()

            new_data = bsdiff4.patch(old_data, patch_data)

            with open(new_file, "wb") as new_f:
                new_f.write(new_data)

            return True

        except ImportError:
            logger.error("bsdiff4 Python package not available. Install with: pip install bsdiff4")
            return False
        except Exception as e:
            logger.error(f"Patch application failed: {e}")
            return False

    async def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_bandwidth_savings(self) -> int:
        """Get cumulative bandwidth saved by delta updates (bytes)."""
        return self._bandwidth_saved


# Cloud-side utility for generating deltas
def generate_delta_patch(
    old_model_path: str,
    new_model_path: str,
    output_patch_path: str
) -> bool:
    """
    Generate binary delta patch between two model files.

    Cloud-side utility for pre-computing delta patches.

    Args:
        old_model_path: Path to old model version
        new_model_path: Path to new model version
        output_patch_path: Path to save delta patch

    Returns:
        True if patch generated successfully
    """
    try:
        # Try using bsdiff command (faster, native)
        import subprocess
        result = subprocess.run(
            ["bsdiff", old_model_path, new_model_path, output_patch_path],
            capture_output=True,
            timeout=600  # 10 minute timeout for large models
        )
        if result.returncode == 0:
            return True

        logger.warning("bsdiff command failed, trying Python implementation")

    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug(f"bsdiff not available: {e}")

    # Fallback: Python implementation
    try:
        import bsdiff4

        with open(old_model_path, "rb") as old_f:
            old_data = old_f.read()
        with open(new_model_path, "rb") as new_f:
            new_data = new_f.read()

        patch_data = bsdiff4.diff(old_data, new_data)

        with open(output_patch_path, "wb") as patch_f:
            patch_f.write(patch_data)

        return True

    except ImportError:
        logger.error("bsdiff4 not available. Install with: pip install bsdiff4")
        return False
    except Exception as e:
        logger.error(f"Delta generation failed: {e}")
        return False
