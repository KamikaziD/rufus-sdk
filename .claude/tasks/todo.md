# WASM/Browser/WASI Edge Agent — Component Model + Dual Target

**Branch:** `claude/plan-session-EBu8w`
**Spec:** `.claude/tasks/spec.md`

## Phase 1 — Platform I/O Abstraction (shared foundation)

- [ ] Create `src/rufus_edge/platform/base.py` — `PlatformAdapter` Protocol + `HttpResponse` + `NullSystemMetrics`
- [ ] Create `src/rufus_edge/platform/native.py` — `NativePlatformAdapter` (wraps `httpx`, `psutil`)
- [ ] Create `src/rufus_edge/platform/pyodide.py` — `PyodidePlatformAdapter` (`js.fetch`, stub metrics, `wa-sqlite` note)
- [ ] Create `src/rufus_edge/platform/wasi.py` — `WasiPlatformAdapter` (wasi:http shim, stub metrics)
- [ ] Create `src/rufus_edge/platform/__init__.py` — `detect_platform()` auto-selector
- [ ] Refactor `SyncManager`: accept `adapter: PlatformAdapter = None`; replace `httpx` calls with adapter
- [ ] Refactor `ConfigManager`: accept `adapter: PlatformAdapter = None`; replace `httpx` calls with adapter
- [ ] Guard `subprocess.run` calls in `src/rufus/utils/platform.py` behind `sys.platform != 'wasm32'`
- [ ] Update `RufusEdgeAgent.__init__` to accept optional `platform_adapter` and pass it down

## Phase 2 — Component Model WASM Executor

- [ ] Create `src/rufus/wasm_component/step.wit` — WIT interface (`rufus:step@0.1.0` world)
- [ ] Create `src/rufus/wasm_component/__init__.py`
- [ ] Create `src/rufus/implementations/execution/component_runtime.py` — `ComponentStepRuntime`
  - `_is_component(binary)` — detect CM magic bytes vs core module
  - `_run_component()` — native: `wasmtime.component`; browser: `js.WebAssembly`
  - `_run_legacy_wasi()` — delegates to existing `WasmRuntime._execute_wasi()`
  - Keep `WasmRuntime` unchanged (backward compat)
- [ ] Update `workflow.py` WASM step dispatch to use `ComponentStepRuntime` by default

## Phase 3 — Browser Target (Pyodide + JSPI)

- [ ] Create `scripts/browser_loader.js` — Pyodide bootstrap, wa-sqlite init, edge agent start
- [ ] Implement `PyodideSQLiteProvider` shim (thin adapter over wa-sqlite JS API) — note in `pyodide.py`
- [ ] Document Pyodide constraints in `TECHNICAL_INFORMATION.md` (new §20)
- [ ] Add `browser` extra to `packages/rufus-sdk-edge/pyproject.toml` (no psutil, no websockets, no httpx)

## Phase 4 — WASI 0.3 Native Target

- [ ] Create `src/rufus_edge/wasi_main.py` — WASI entrypoint (no asyncio.run; use wasi event loop)
- [ ] Create `scripts/build_wasi.sh` — py2wasm build script with WASI target
- [ ] Add `wasi` extra to `packages/rufus-sdk-edge/pyproject.toml` (zero extra deps)
- [ ] Add `native` extra for wasmtime Component Model on native Python

## Phase 5 — Tests

- [ ] `tests/edge/test_platform_adapters.py` — unit tests for all 3 adapters (mock HTTP)
- [ ] `tests/edge/test_component_runtime.py` — unit tests for `ComponentStepRuntime` (mock binary)
- [ ] Regression: run `pytest tests/` and ensure existing tests pass

## Phase 6 — Commit & Push

- [ ] Stage and commit all changes with descriptive message
- [ ] Push to `claude/plan-session-EBu8w`

---

# v0.7.4 Release — Version Bump, Wheels, Docker Images, Docs ✅

## Release Checklist

### Step 1 — Version Bump (12 locations) ✅
- [x] `pyproject.toml` → 0.7.4
- [x] `packages/rufus-sdk-edge/pyproject.toml` → 0.7.4
- [x] `packages/rufus-sdk-server/pyproject.toml` → 0.7.4
- [x] `src/rufus/__init__.py` → 0.7.4
- [x] `src/rufus_cli/__init__.py` → 0.7.4
- [x] `src/rufus_server/__init__.py` → 0.7.4
- [x] `src/rufus_edge/__init__.py` → 0.7.4
- [x] `docker/Dockerfile.rufus-server-prod` → 0.7.4
- [x] `docker/Dockerfile.rufus-worker-prod` → 0.7.4
- [x] `docker/Dockerfile.rufus-flower-prod` → 0.7.4
- [x] `docker/build-production-images.sh` default → 0.7.4
- [x] `packages/rufus-dashboard/package.json` → 0.7.4

### Step 2 — Build 3 Python Wheels ✅
- [x] `dist/rufus_sdk-0.7.4-py3-none-any.whl`
- [x] `packages/rufus-sdk-edge/dist/rufus_sdk_edge-0.7.4-py3-none-any.whl`
- [x] `packages/rufus-sdk-server/dist/rufus_sdk_server-0.7.4-py3-none-any.whl`

### Step 3 — Upload Wheels to TestPyPI ✅
- [x] All 3 wheels uploaded; confirmed indexed:
  - https://test.pypi.org/project/rufus-sdk/0.7.4/
  - https://test.pypi.org/project/rufus-sdk-edge/0.7.4/
  - https://test.pypi.org/project/rufus-sdk-server/0.7.4/

### Step 4 — Build & Push 4 Docker Images ✅
- [x] `ruhfuskdev/rufus-server:0.7.4` + `:latest` — multi-arch (amd64+arm64) ✓
- [x] `ruhfuskdev/rufus-worker:0.7.4` + `:latest` — multi-arch ✓
- [x] `ruhfuskdev/rufus-flower:0.7.4` + `:latest` — multi-arch ✓
- [x] `ruhfuskdev/rufus-dashboard:0.7.4` + `:latest` — multi-arch, Next.js 14.2.21, 17 routes built ✓
- **Note:** Encountered TestPyPI CDN propagation delay on arm64 builder (3 retries needed)
  — Fixed by confirming all 3 packages indexed via API + pruning Docker buildx cache before final retry

### Step 5 — Documentation Updates ✅
- [x] `README.md`: all 0.5.4 → 0.7.4 (Docker image tags, pip install lines)
- [x] `TECHNICAL_INFORMATION.md §16`: added `workflow_definitions` + `server_commands` rows (Workers group now 4 tables; total 35 cloud tables)
- [x] `TECHNICAL_INFORMATION.md §17`: NEW Live Workflow Updates section (architecture, DDL, hot-reload, poller, API, edge agent, dashboard)
- [x] `TECHNICAL_INFORMATION.md §18/19`: renumbered Edge Footprint + Package Split
- [x] `memory/MEMORY.md`: version 0.7.4, Docker image tags, outstanding tasks updated

### Step 6 — Git Commit + Tag ✅
- [x] Commit `e87f7e88`: "feat: v0.7.4 — Live Workflow Updates + Dashboard DAG Editor"
- [x] Tag `v0.7.4` (annotated)

---

# Fix Server Crash + automate_start Feature ✅

## Part 1 — Server Crash Fix ✅
- [x] `rufus_test/docker-compose.test-async.yml`: added 2 bind-mounts (`workflow_definition_service.py`, `server_command_service.py`) + 2 touch entries in startup command

## Part 2 — `automate_start: true` Feature ✅
- [x] `src/rufus/workflow.py`: added `automate_start: bool = False` param to `__init__`; stored as `self.automate_start`
- [x] `src/rufus/builder.py`: parse `automate_start` from workflow config YAML; pass to `Workflow()` constructor
- [x] `src/rufus/engine.py`: after `on_workflow_started`, call `await new_workflow.next_step(user_input={})` if `automate_start` is set

## Review

### Lessons Learned
- **TestPyPI CDN propagation**: All 3 packages must be confirmed indexed via API before Docker build — check each individually, not just one. CDN can show different versions for different packages even when uploaded together.
- **Docker buildx cache prune**: Required before retry when arm64 builder hits stale CDN; `docker buildx prune --builder rufus-builder --force` clears intermediate layers.
- **12 version locations** (not 10 as previously noted): build script default + dashboard package.json were missing from the old checklist.
