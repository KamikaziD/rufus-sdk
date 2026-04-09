"""Build script: compile apply_config.wasm from config_applier.wasm_main().

This script is NOT a Ruvon step function — it is a one-time build tool
invoked via the CLI or CI pipeline:

    python -m ruvon_edge.sidecar.build_wasm

or via the CLI command (once registered):

    ruvon sidecar build-wasm

Requirements:
    pip install wasmtime           # Python bindings for the Wasmtime runtime
    # For full compilation, also need py2wasm or wasi-sdk on PATH

What this script does:
1.  Reads the wasm_main() function from config_applier.py
2.  Serialises the module via py2wasm (Python → WASM via CPython WASI build)
3.  Writes the compiled binary to  src/ruvon_edge/sidecar/wasm/apply_config.wasm
4.  Optionally runs wizer to pre-initialise the module (faster cold-start)

The compiled binary reads a JSON proposal from stdin and writes the result
to stdout — a pure WASI I/O module with no filesystem or network access
outside its sandboxed tmp directory.

WASM module contract (stdin → stdout):
    Input:  {"key": "fraud_threshold", "value": 0.85, "approved": true}
    Output: {"outcome": "hot_swapped:fraud_threshold=0.85", "method": "hot_swap"}
    Error:  {"outcome": "error:<message>"}

The binary is committed to the repo (~50KB after wizer pre-init) so devices
receive it via the standard ETag config push without needing build tooling.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

_WASM_OUT = Path(__file__).parent / "wasm" / "apply_config.wasm"
_WASM_HASH = Path(__file__).parent / "wasm" / "apply_config.sha256"


def compute_source_hash() -> str:
    """Return the SHA-256 of config_applier.py (used for staleness detection)."""
    src = Path(__file__).parent / "config_applier.py"
    return hashlib.sha256(src.read_bytes()).hexdigest()


def is_up_to_date() -> bool:
    """Return True if the compiled WASM binary matches the current source."""
    if not _WASM_OUT.exists() or not _WASM_HASH.exists():
        return False
    return _WASM_HASH.read_text().strip() == compute_source_hash()


def build(force: bool = False) -> Path:
    """Compile apply_config.wasm.

    Args:
        force: Rebuild even if the binary is current.

    Returns:
        Path to the compiled WASM binary.

    Raises:
        RuntimeError: If required toolchain (py2wasm / wasi-sdk) is not found.
    """
    if not force and is_up_to_date():
        print(f"[build_wasm] Binary is up to date: {_WASM_OUT}")
        return _WASM_OUT

    _WASM_OUT.parent.mkdir(parents=True, exist_ok=True)

    # Strategy 1: Use py2wasm (Python → WASM)
    try:
        _build_with_py2wasm()
        _write_hash()
        print(f"[build_wasm] Compiled (py2wasm): {_WASM_OUT}")
        return _WASM_OUT
    except FileNotFoundError:
        pass

    # Strategy 2: Use a pre-built CPython WASI distribution
    try:
        _build_with_wasi_sdk()
        _write_hash()
        print(f"[build_wasm] Compiled (wasi-sdk): {_WASM_OUT}")
        return _WASM_OUT
    except FileNotFoundError:
        pass

    raise RuntimeError(
        "WASM compilation requires py2wasm or wasi-sdk on PATH.\n"
        "  Install:  pip install py2wasm\n"
        "  Or:       brew install wasi-sdk  (macOS)\n"
        "            apt install wasi-sdk   (Debian/Ubuntu)\n"
        "\n"
        "The Python fallback (type: STANDARD) in deployment_monitor.yaml is\n"
        "fully functional without this binary."
    )


def _build_with_py2wasm() -> None:
    """Compile using py2wasm (Python → WASM via Nuitka/WASI-SDK).

    py2wasm requires Python 3.11+.  If the current interpreter is 3.10, we
    look for a python3.11 binary on PATH and invoke py2wasm through it.
    """
    import sys

    entry = Path(__file__).parent / "config_applier.py"
    py2wasm_cmd = ["py2wasm", str(entry), "-o", str(_WASM_OUT)]

    # py2wasm 2.6+ requires Python 3.11+; fall back to explicit python3.11
    if sys.version_info < (3, 11):
        import shutil
        py311 = shutil.which("python3.11")
        if py311 is None:
            raise FileNotFoundError("py2wasm requires Python 3.11+; python3.11 not found on PATH")
        py2wasm_cmd = [py311, "-m", "py2wasm", str(entry), "-o", str(_WASM_OUT)]

    subprocess.run(
        py2wasm_cmd,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_with_wasi_sdk() -> None:
    """Compile via a wasi-sdk clang toolchain (requires C extension build)."""
    # This path is used when py2wasm is unavailable; requires the WASI SDK
    # installed at /opt/wasi-sdk or $WASI_SDK_PATH
    wasi_sdk = Path(
        __import__("os").environ.get("WASI_SDK_PATH", "/opt/wasi-sdk")
    )
    if not wasi_sdk.exists():
        raise FileNotFoundError(f"WASI SDK not found at {wasi_sdk}")
    raise FileNotFoundError("wasi-sdk path requires manual C extension setup")


def _write_hash() -> None:
    _WASM_HASH.write_text(compute_source_hash())


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Compile apply_config.wasm")
    parser.add_argument("--force", action="store_true", help="Force full rebuild")
    args = parser.parse_args()
    try:
        out = build(force=args.force)
        print(f"WASM binary: {out}")
        print(f"Size: {out.stat().st_size:,} bytes")
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
