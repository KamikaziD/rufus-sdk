"""TypeScript transpilation using esbuild."""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Flag to track if esbuild is available
_ESBUILD_AVAILABLE: Optional[bool] = None


def is_esbuild_available() -> bool:
    """Check if esbuild is available."""
    global _ESBUILD_AVAILABLE
    if _ESBUILD_AVAILABLE is None:
        try:
            result = subprocess.run(
                ["esbuild", "--version"],
                capture_output=True,
                timeout=5,
            )
            _ESBUILD_AVAILABLE = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _ESBUILD_AVAILABLE = False
    return _ESBUILD_AVAILABLE


class TypeScriptTranspiler:
    """
    Transpiles TypeScript to JavaScript using esbuild.

    esbuild is chosen for:
    - Speed: 10-100x faster than tsc
    - Simplicity: Single binary, no Node.js required
    - Future: Supports bundling for npm packages
    """

    def __init__(self, tsconfig_path: Optional[str] = None):
        self._default_tsconfig = tsconfig_path
        self._verify_esbuild()

    def _verify_esbuild(self) -> None:
        """Verify esbuild is installed."""
        if not is_esbuild_available():
            raise RuntimeError(
                "esbuild not found. TypeScript support requires esbuild. "
                "Install with: pip install esbuild (or npm install -g esbuild)"
            )

    def transpile(
        self,
        source: str,
        filename: str = "script.ts",
        tsconfig_path: Optional[str] = None,
    ) -> str:
        """
        Transpile TypeScript source to JavaScript.

        Args:
            source: TypeScript source code
            filename: Original filename (for error messages)
            tsconfig_path: Path to tsconfig.json (optional)

        Returns:
            Transpiled JavaScript code

        Raises:
            RuntimeError: If transpilation fails
        """
        # Build esbuild command
        cmd = [
            "esbuild",
            "--bundle=false",       # Don't bundle imports
            "--format=iife",        # Wrap in IIFE for isolation
            "--target=es2020",      # Target ES2020 (V8 compatible)
            "--platform=neutral",   # No Node.js builtins
            "--loader=ts",          # Input is TypeScript
        ]

        # Add tsconfig if provided
        config_path = tsconfig_path or self._default_tsconfig
        if config_path:
            cmd.append(f"--tsconfig={config_path}")

        try:
            # Run esbuild with source on stdin
            result = subprocess.run(
                cmd,
                input=source.encode('utf-8'),
                capture_output=True,
                timeout=30,
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8', errors='replace')
                raise RuntimeError(f"TypeScript transpilation failed: {error_msg}")

            return result.stdout.decode('utf-8')

        except subprocess.TimeoutExpired:
            raise RuntimeError("TypeScript transpilation timed out")
        except FileNotFoundError:
            raise RuntimeError("esbuild not found in PATH")

    def transpile_file(
        self,
        file_path: Path,
        tsconfig_path: Optional[str] = None,
    ) -> str:
        """
        Transpile TypeScript file to JavaScript.

        Args:
            file_path: Path to .ts file
            tsconfig_path: Path to tsconfig.json (optional)

        Returns:
            Transpiled JavaScript code
        """
        source = file_path.read_text(encoding='utf-8')
        return self.transpile(source, filename=file_path.name, tsconfig_path=tsconfig_path)

    def check_syntax(self, source: str, filename: str = "script.ts") -> Optional[str]:
        """
        Check TypeScript syntax without transpiling.

        Args:
            source: TypeScript source code
            filename: Filename for error messages

        Returns:
            None if valid, error message if invalid
        """
        try:
            # Use esbuild to check syntax (it will fail fast on errors)
            self.transpile(source, filename)
            return None
        except RuntimeError as e:
            return str(e)


class FallbackTranspiler:
    """
    Fallback transpiler when esbuild is not available.

    This is a very basic implementation that strips TypeScript
    type annotations. It's not recommended for production use.
    """

    def transpile(self, source: str, filename: str = "script.ts", **kwargs) -> str:
        """
        Basic TypeScript to JavaScript conversion.

        This strips common type annotations but doesn't handle
        all TypeScript features. Use esbuild for proper support.
        """
        import re

        logger.warning(
            "Using fallback TypeScript transpiler. "
            "Install esbuild for proper TypeScript support."
        )

        result = source

        # Remove interface declarations
        result = re.sub(
            r'interface\s+\w+\s*\{[^}]*\}',
            '',
            result,
            flags=re.MULTILINE | re.DOTALL
        )

        # Remove type declarations
        result = re.sub(
            r'type\s+\w+\s*=\s*[^;]+;',
            '',
            result,
            flags=re.MULTILINE
        )

        # Remove type annotations from variables
        result = re.sub(
            r'(const|let|var)\s+(\w+)\s*:\s*[^=]+\s*=',
            r'\1 \2 =',
            result
        )

        # Remove function return type annotations
        result = re.sub(
            r'\)\s*:\s*[\w<>\[\]|&\s]+\s*\{',
            ') {',
            result
        )

        # Remove parameter type annotations
        result = re.sub(
            r'(\w+)\s*:\s*[\w<>\[\]|&]+\s*([,)])',
            r'\1\2',
            result
        )

        # Remove 'as' type assertions
        result = re.sub(
            r'\s+as\s+[\w<>\[\]|&]+',
            '',
            result
        )

        # Remove angle bracket type assertions
        result = re.sub(
            r'<[\w<>\[\]|&\s]+>(\w+)',
            r'\1',
            result
        )

        return result


def get_transpiler(tsconfig_path: Optional[str] = None) -> "TypeScriptTranspiler":
    """
    Get the best available TypeScript transpiler.

    Returns esbuild-based transpiler if available,
    otherwise falls back to basic regex-based transpiler.
    """
    if is_esbuild_available():
        return TypeScriptTranspiler(tsconfig_path)
    else:
        logger.warning(
            "esbuild not available. Using fallback transpiler. "
            "Some TypeScript features may not work correctly."
        )
        return FallbackTranspiler()
