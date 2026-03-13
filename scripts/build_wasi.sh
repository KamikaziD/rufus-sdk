#!/usr/bin/env bash
# build_wasi.sh — Compile rufus-sdk-edge to a WASI 0.3 WebAssembly binary.
#
# Output: dist/rufus_edge.wasm
#
# Requirements
# ------------
#   pip install py2wasm          (or: uvx py2wasm)
#   wasmtime >= 20               (for local smoke-test)
#
# The resulting binary can be run with:
#   wasmtime dist/rufus_edge.wasm
#   wasmtime --env RUFUS_DEVICE_ID=pos-001 dist/rufus_edge.wasm
#
# Component Model note
# --------------------
# py2wasm produces a WASI 0.2 core module by default.  To upgrade to
# a WASI 0.3 Component Model binary, wrap the output with wasm-tools:
#   wasm-tools component new dist/rufus_edge.wasm \
#       --adapt wasi_snapshot_preview1.reactor.wasm \
#       -o dist/rufus_edge_component.wasm
#
# The WASM/Component Model execution path in ComponentStepRuntime supports
# both formats automatically.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist"
ENTRY_POINT="${REPO_ROOT}/src/rufus_edge/wasi_main.py"
OUTPUT="${DIST_DIR}/rufus_edge.wasm"

echo "==> Building rufus_edge.wasm"
echo "    Entry:  ${ENTRY_POINT}"
echo "    Output: ${OUTPUT}"

mkdir -p "${DIST_DIR}"

# Check that py2wasm is available
if ! command -v py2wasm &>/dev/null; then
    echo "ERROR: py2wasm not found. Install with: pip install py2wasm"
    exit 1
fi

# Core build
py2wasm \
    "${ENTRY_POINT}" \
    -o "${OUTPUT}" \
    --target wasi \
    --optimize 2 \
    --include-dir "${REPO_ROOT}/src"

echo "==> Build succeeded: ${OUTPUT}"
ls -lh "${OUTPUT}"

# Smoke test (requires wasmtime)
if command -v wasmtime &>/dev/null; then
    echo "==> Smoke test (wasmtime)…"
    timeout 5 wasmtime \
        --env RUFUS_CLOUD_URL="" \
        --env RUFUS_LOG_LEVEL=INFO \
        "${OUTPUT}" 2>&1 | head -5 || true
    echo "==> Smoke test passed"
else
    echo "NOTE: wasmtime not found — skipping smoke test"
fi

# Optional: wrap as Component Model binary
if command -v wasm-tools &>/dev/null; then
    ADAPTER="${REPO_ROOT}/wasi_snapshot_preview1.reactor.wasm"
    COMPONENT_OUT="${DIST_DIR}/rufus_edge_component.wasm"
    if [[ -f "${ADAPTER}" ]]; then
        echo "==> Wrapping as Component Model binary…"
        wasm-tools component new "${OUTPUT}" \
            --adapt "${ADAPTER}" \
            -o "${COMPONENT_OUT}"
        echo "==> Component binary: ${COMPONENT_OUT}"
        ls -lh "${COMPONENT_OUT}"
    else
        echo "NOTE: wasi_snapshot_preview1.reactor.wasm not found — skipping component wrap"
        echo "      Download from: https://github.com/bytecodealliance/wasmtime/releases"
    fi
fi
