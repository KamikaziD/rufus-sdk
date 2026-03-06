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
