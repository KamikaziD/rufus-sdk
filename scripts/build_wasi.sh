#!/usr/bin/env bash
# build_wasi.sh — Build ruvon-edge as a WASI 0.3 component.
#
# Prerequisites:
#   pip install py2wasm          # Nuitka-based CPython → wasm32-wasi compiler
#   pip install ruvon-edge[wasi]
#
# Usage:
#   bash scripts/build_wasi.sh [--output dist/ruvon_edge.wasm]
#
# Output:
#   dist/ruvon_edge.wasm   (~15 MB before brotli compression)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENTRY_POINT="${REPO_ROOT}/src/ruvon_edge/wasi_main.py"
OUTPUT_DIR="${REPO_ROOT}/dist"
OUTPUT_FILE="${OUTPUT_DIR}/ruvon_edge.wasm"

# Allow override via CLI argument
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_FILE="$2"
      OUTPUT_DIR="$(dirname "${OUTPUT_FILE}")"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p "${OUTPUT_DIR}"

echo "==> Building WASI component from ${ENTRY_POINT}"
echo "    Output: ${OUTPUT_FILE}"

# py2wasm compiles CPython + application to a self-contained .wasm binary
# targeting wasm32-wasi.  The --wasi flag enables WASI 0.3 preview.
#
# --nofollow-import-to=psutil: psutil uses native extensions; exclude it.
# --nofollow-import-to=httpx:  httpx uses OS sockets; exclude it.
# WasiPlatformAdapter uses urllib / wasi:http instead.

py2wasm "${ENTRY_POINT}" \
  --output "${OUTPUT_FILE}" \
  --wasi \
  --nofollow-import-to=psutil \
  --nofollow-import-to=httpx \
  --nofollow-import-to=websockets \
  --nofollow-import-to=wasmtime \
  --include-package=rufus \
  --include-package=ruvon_edge

echo "==> Build complete: ${OUTPUT_FILE}"
echo "    Size: $(du -sh "${OUTPUT_FILE}" | cut -f1)"

# Phase 2: Pre-initialize with Wizer (cold-start killer)
# Target: <5ms boot time instead of 300ms-2s
# Install: cargo install wizer --all-features
if command -v wizer &>/dev/null; then
    SNAPSHOT_OUT="${OUTPUT_DIR}/ruvon_edge_snapshotted.wasm"
    echo "==> Snapshotting Python runtime with Wizer..."
    wizer \
        --allow-wasi \
        --dir=. \
        --init-func=rufus_pre_init \
        -o "${SNAPSHOT_OUT}" \
        "${OUTPUT_FILE}"
    echo "==> Snapshot complete: ${SNAPSHOT_OUT}"
    ls -lh "${SNAPSHOT_OUT}"
else
    echo "NOTE: Wizer not found — skipping snapshot (install: cargo install wizer --all-features)"
    echo "      Without snapshot, cold-start is 300ms-2s instead of <5ms"
fi

# Optional: validate with wasmtime
if command -v wasmtime &>/dev/null; then
  echo "==> Validating with wasmtime..."
  wasmtime compile "${OUTPUT_FILE}" -o /dev/null
  echo "    Validation passed."
else
  echo "    (wasmtime not found; skipping validation)"
fi

echo ""
echo "Deploy the component:"
echo "  wasmtime run --env RUVON_DEVICE_ID=pos-001 \\"
echo "               --env RUVON_CLOUD_URL=https://control.example.com \\"
echo "               --env RUVON_API_KEY=your-key \\"
echo "               ${OUTPUT_FILE}"
