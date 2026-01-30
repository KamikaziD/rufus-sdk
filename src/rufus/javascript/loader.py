"""Script loader with caching and TypeScript support."""

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
from threading import Lock

from .types import CompiledScript

logger = logging.getLogger(__name__)


class ScriptLoader:
    """
    Loads and caches JavaScript/TypeScript scripts.

    Features:
    - File loading with path resolution
    - Inline code handling
    - Script caching with cache invalidation
    - TypeScript detection and transpilation
    """

    def __init__(
        self,
        config_dir: Optional[str] = None,
        cache_max_size: int = 100,
        cache_ttl_seconds: int = 300,
    ):
        self._config_dir = Path(config_dir) if config_dir else Path.cwd()
        self._cache_max_size = cache_max_size
        self._cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Tuple[CompiledScript, float]] = {}
        self._cache_lock = Lock()
        self._transpiler: Optional["TypeScriptTranspiler"] = None

    def _get_transpiler(self) -> "TypeScriptTranspiler":
        """Lazy-load TypeScript transpiler."""
        if self._transpiler is None:
            from .typescript import TypeScriptTranspiler
            self._transpiler = TypeScriptTranspiler()
        return self._transpiler

    def _resolve_path(self, script_path: str) -> Path:
        """
        Resolve script path relative to config directory.

        Args:
            script_path: Relative or absolute path to script

        Returns:
            Absolute Path to script
        """
        path = Path(script_path)

        # If absolute, use as-is
        if path.is_absolute():
            return path

        # Try relative to config directory
        config_relative = self._config_dir / path
        if config_relative.exists():
            return config_relative.resolve()

        # Try relative to current working directory
        cwd_relative = Path.cwd() / path
        if cwd_relative.exists():
            return cwd_relative.resolve()

        # Return config-relative path (will fail later with clear error)
        return config_relative

    def _get_cache_key(self, script_path: Optional[str], code: Optional[str]) -> str:
        """Generate cache key for script."""
        if script_path:
            # Use resolved path as key
            resolved = self._resolve_path(script_path)
            return f"file:{resolved}"
        elif code:
            # Use hash of code as key
            code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
            return f"inline:{code_hash}"
        else:
            raise ValueError("Either script_path or code must be provided")

    def _is_cache_valid(self, cached: CompiledScript) -> bool:
        """Check if cached script is still valid."""
        # Check TTL
        if time.time() - cached.compiled_at > self._cache_ttl:
            return False

        # For file-based scripts, check if file was modified
        if cached.original_path and cached.file_mtime is not None:
            try:
                current_mtime = os.path.getmtime(cached.original_path)
                if current_mtime != cached.file_mtime:
                    return False
            except OSError:
                return False

        return True

    def _is_typescript(self, script_path: Optional[str], force_ts: bool) -> bool:
        """Determine if script should be transpiled as TypeScript."""
        if force_ts:
            return True
        if script_path:
            return script_path.lower().endswith(('.ts', '.tsx'))
        return False

    def load(
        self,
        script_path: Optional[str] = None,
        code: Optional[str] = None,
        force_typescript: bool = False,
        tsconfig_path: Optional[str] = None,
    ) -> CompiledScript:
        """
        Load and optionally transpile a script.

        Args:
            script_path: Path to .js or .ts file
            code: Inline JavaScript/TypeScript code
            force_typescript: Force TypeScript transpilation
            tsconfig_path: Path to tsconfig.json

        Returns:
            CompiledScript with source code

        Raises:
            FileNotFoundError: If script file doesn't exist
            ValueError: If neither script_path nor code is provided
        """
        if not script_path and not code:
            raise ValueError("Either 'script_path' or 'code' must be provided")

        cache_key = self._get_cache_key(script_path, code)

        # Check cache
        with self._cache_lock:
            if cache_key in self._cache:
                cached, _ = self._cache[cache_key]
                if self._is_cache_valid(cached):
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached
                else:
                    logger.debug(f"Cache expired for {cache_key}")
                    del self._cache[cache_key]

        # Load source
        if script_path:
            resolved_path = self._resolve_path(script_path)
            if not resolved_path.exists():
                raise FileNotFoundError(f"Script file not found: {resolved_path}")

            source = resolved_path.read_text(encoding='utf-8')
            file_mtime = os.path.getmtime(resolved_path)
            original_path = str(resolved_path)
        else:
            source = code
            file_mtime = None
            original_path = None

        # Determine if TypeScript
        is_ts = self._is_typescript(script_path, force_typescript)

        # Transpile if needed
        transpiled_source = None
        if is_ts:
            transpiler = self._get_transpiler()
            transpiled_source = transpiler.transpile(
                source,
                filename=script_path or "inline.ts",
                tsconfig_path=tsconfig_path,
            )
            final_source = transpiled_source
        else:
            final_source = source

        # Create compiled script
        compiled = CompiledScript(
            source=final_source,
            original_path=original_path,
            is_typescript=is_ts,
            transpiled_source=transpiled_source if is_ts else None,
            compiled_at=time.time(),
            file_mtime=file_mtime,
        )

        # Update cache
        with self._cache_lock:
            # Evict oldest entries if cache is full
            if len(self._cache) >= self._cache_max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]

            self._cache[cache_key] = (compiled, time.time())

        return compiled

    def clear_cache(self) -> None:
        """Clear the script cache."""
        with self._cache_lock:
            self._cache.clear()

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        with self._cache_lock:
            return {
                "size": len(self._cache),
                "max_size": self._cache_max_size,
                "ttl_seconds": self._cache_ttl,
            }
