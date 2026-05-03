# Spec: WASM/Browser/WASI Deployment for ruvon-edge

**Date:** 2026-03-12
**Scope:** `ruvon-edge` (edge agent only; cloud control plane unchanged)
**Targets:** Browser (Pyodide + JSPI) + Native WASI 0.3 (parallel)
**WASM Steps:** Migrate to Component Model (replace stdin/stdout + wasmtime)

---

## 1. Current State

| Component | Current Impl | WASM Problem |
|-----------|-------------|-------------|
| HTTP client | `httpx.AsyncClient` | OS sockets; unavailable in browser/WASI |
| System metrics | `psutil` (optional dep) | No `/proc` in browser/WASI |
| Subprocess | `subprocess.run` in `platform.py` | Sandboxed in WASM |
| WASM step exec | `wasmtime` (stdin/stdout JSON) | `wasmtime` Python pkg not portable |
| SQLite | `aiosqlite` | Works on WASI; needs `wa-sqlite` in browser |
| Event loop | `asyncio` | Works via JSPI in Pyodide; native in WASI |
| Crypto | `hmac`, `hashlib` | Pure Python; portable |

---

## 2. Target Architecture

```
                    ┌──────────────────────────────────────────┐
                    │          RuvonEdgeAgent                  │
                    │  (unchanged public API)                  │
                    └──────────────┬───────────────────────────┘
                                   │ uses
                    ┌──────────────▼───────────────────────────┐
                    │         PlatformAdapter (Protocol)        │
                    │  http_fetch / system_metrics / wasm_exec  │
                    └─────┬───────────────┬────────────────────┘
                          │               │
           ┌──────────────▼──┐   ┌────────▼─────────────┐
           │ NativeAdapter   │   │  WasiAdapter          │
           │ (httpx+psutil)  │   │  (wasi:http+stubs)    │
           └─────────────────┘   └──────────────────────┘
                                         │
                    ┌────────────────────▼───────────────────┐
                    │ PyodideAdapter                         │
                    │ (js.fetch + wa-sqlite + no psutil)     │
                    └────────────────────────────────────────┘

WASM Step Execution (Component Model):
  ┌───────────────────────────────────────────────┐
  │  ComponentStepRuntime (replaces WasmRuntime)  │
  │  - Resolves component bytes via BinaryResolver │
  │  - Invokes typed WIT interface (not stdin/out) │
  │  - native: wasmtime.component Python bindings │
  │  - browser: js.WebAssembly + cm-js polyfill    │
  │  - wasi host: wasi:component                   │
  └───────────────────────────────────────────────┘
```

---

## 3. New File Map

```
src/ruvon_edge/
  platform/
    __init__.py            # exports detect_platform(), get_adapter()
    base.py                # PlatformAdapter Protocol + NullSystemMetrics
    native.py              # NativePlatformAdapter (httpx, psutil)
    wasi.py                # WasiPlatformAdapter (wasi:http, stubs)
    pyodide.py             # PyodidePlatformAdapter (js.fetch, wa-sqlite)

src/ruvon/implementations/execution/
  component_runtime.py     # ComponentStepRuntime (replaces WasmRuntime for CM)

src/ruvon/wasm_component/
  step.wit                 # WIT interface definition for workflow steps
  __init__.py

scripts/
  build_wasi.sh            # py2wasm build for WASI target
  browser_loader.js        # Pyodide bootstrap + wa-sqlite init

packages/ruvon-edge/pyproject.toml  # new extras: browser, wasi
```

---

## 4. WIT Interface (Component Model Contract)

```wit
// src/ruvon/wasm_component/step.wit
package ruvon:step@0.1.0;

interface step-types {
  type state-json = string;   // JSON-encoded state dict
  type result-json = string;  // JSON-encoded result dict

  record step-error {
    code: u32,
    message: string,
  }
}

world step-component {
  use step-types.{state-json, result-json, step-error};

  export execute: func(
    state: state-json,
    step-name: string,
  ) -> result<result-json, step-error>;
}
```

This replaces the stdin/stdout contract:
- **Before:** module reads stdin → writes stdout → exit 0
- **After:** host calls `execute(state_json, step_name) → result_json`

The old `WasmRuntime` (stdin/stdout) stays for **backward compatibility** but is deprecated.
`ComponentStepRuntime` detects which interface a component exposes and dispatches accordingly
(CM-first, stdout-fallback).

---

## 5. PlatformAdapter Protocol

```python
# src/ruvon_edge/platform/base.py

class HttpResponse(Protocol):
    status_code: int
    def json(self) -> dict: ...
    def text(self) -> str: ...

class PlatformAdapter(Protocol):
    async def http_get(self, url: str, headers: dict, timeout: float) -> HttpResponse: ...
    async def http_post(self, url: str, json: dict, headers: dict, timeout: float) -> HttpResponse: ...
    def system_metrics(self) -> dict: ...          # cpu%, mem%, disk%  (or empty dict)
    def is_wasm_capable(self) -> bool: ...         # can run component steps inline?
```

`SyncManager` and `ConfigManager` are refactored to accept an optional
`adapter: PlatformAdapter = None` (defaults to `NativePlatformAdapter()`).

---

## 6. Browser (Pyodide + JSPI) Plan

**How it works:**
1. `browser_loader.js` loads Pyodide into a Web Worker
2. Installs `wa-sqlite` (SQLite compiled to WASM, exposed via JS API)
3. Imports `ruvon_edge` Python package via `pyodide.loadPackage`
4. Calls `await pyodide.runPythonAsync(...)` to start `RuvonEdgeAgent`
5. Asyncio runs on browser event loop via JSPI

**Key constraints:**
- `psutil` → stub returning empty metrics dict
- `websockets` → not needed (use browser native WebSocket via `js.WebSocket`)
- `aiosqlite` → replaced by `wa-sqlite` JS bridge in `PyodideSQLiteProvider`
- `httpx` → replaced by `PyodideHttpAdapter` wrapping `js.fetch`
- `numpy` → available in Pyodide (keep dep)

---

## 7. WASI 0.3 Plan

**How it works:**
1. CPython + ruvon_edge compiled to `wasm32-wasi` using `py2wasm` or `wasi-python`
2. `wasi:http/outgoing-handler` for HTTP (via `wasi-http` Python binding)
3. `wasi:filesystem` for SQLite file I/O (`aiosqlite` works unchanged)
4. `wasi:clocks` for datetime (Python stdlib uses this automatically)

**Key constraints:**
- `psutil` → stub (no `/proc` in WASI sandbox)
- `subprocess` → gate behind `sys.platform != 'wasm32'` in `platform.py`
- `numpy` → conditional import (skip if unavailable)

**Build script** (`scripts/build_wasi.sh`):
```bash
py2wasm src/ruvon_edge/wasi_main.py -o dist/ruvon_edge.wasm
```

---

## 8. Component Model WASM Steps — Migration Path

| Step | Before (stdin/stdout) | After (Component Model) |
|------|-----------------------|------------------------|
| Input | `json.dumps(state)` → module stdin | Host calls `execute(state_json, step_name)` |
| Output | `stdout.read()` → `json.loads()` | Return value from `execute()` |
| Runtime | `wasmtime` Python pkg | `wasmtime.component` (native) / `js.WebAssembly` (browser) |
| Error | exit code != 0 | `result<_, step-error>` variant |
| Binary format | Module (core WASM) | Component (WASM Component Model) |
| Hash check | SHA-256 on bytes | SHA-256 on bytes (unchanged) |

**`ComponentStepRuntime` dispatch logic:**
```python
async def execute(self, config, state_data):
    binary = await self._resolver.resolve(config.wasm_hash)
    if _is_component(binary):           # magic bytes: \0asm + version = 0xd
        return await self._run_component(binary, config, state_data)
    else:                               # legacy core module
        return await self._run_legacy_wasi(binary, config, state_data)
```

---

## 9. Backward Compatibility Rules

1. `WasmRuntime` (stdin/stdout) stays in `wasm_runtime.py` — not deleted
2. `WasmBinaryResolver` protocol unchanged — both resolvers continue to work
3. `device_wasm_cache` SQLite table stores either binary format
4. `sync_wasm` cloud command still works
5. Existing `wasmtime` optional dep stays for native fallback; moved to `native` extra

---

## 10. Dependency Changes (pyproject.toml)

```toml
[project.optional-dependencies]
# Existing (unchanged for compatibility)
edge    = ["websockets>=12.0", "psutil>=5.9", "numpy>=1.24"]
# New extras
browser = ["numpy>=1.24"]
wasi    = []
native  = ["websockets>=12.0", "psutil>=5.9", "numpy>=1.24", "wasmtime>=20.0"]
all     = ["websockets>=12.0", "psutil>=5.9", "numpy>=1.24", "wasmtime>=20.0"]
```

---

## 11. Non-Goals (out of scope)

- Cloud control plane changes
- Celery workers as WASM components
- Debug UI port
- CI/CD pipeline changes
- Full E2E browser integration tests
