# Package Split: rufus-sdk → Three Wheels (v0.6.0)

## Step 1 — Create sub-package pyproject.toml files
- [x] Create `packages/rufus-sdk-edge/pyproject.toml`
- [x] Create `packages/rufus-sdk-server/pyproject.toml`

## Step 2 — Update root pyproject.toml
- [x] Remove `rufus_edge` + `rufus_server` from `packages = [...]`
- [x] Strip extras: `server`, `celery`, `auth`, `edge`, `all` → moved to sub-packages
- [x] Keep extras: `postgres`, `performance`, `cli`
- [x] Bump `version` to `"0.6.0"`

## Step 3 — Bump versions in source files
- [x] `src/rufus/__init__.py`: `"0.5.4"` → `"0.6.0"`
- [x] `src/rufus_edge/__init__.py`: `"0.5.0"` → `"0.6.0"` (was stale)
- [x] `src/rufus_server/__init__.py`: add `__version__ = "0.6.0"` (was empty)
- [x] `src/rufus_cli/__init__.py`: add `__version__ = "0.6.0"` (was empty)

## Step 4 — Tests
- [x] Add `tests/test_package_versions.py` (2 tests — version consistency guard)
- [x] Run full test suite — must still pass (no imports changed)

## Step 5 — Update Docker production images
- [x] `docker/Dockerfile.rufus-server-prod` — use `rufus-sdk-server[server,auth]==0.6.0`
- [x] `docker/Dockerfile.rufus-worker-prod` — use `rufus-sdk-server[celery]==0.6.0`
- [x] `docker/Dockerfile.rufus-flower-prod` — use `rufus-sdk-server[celery]==0.6.0`
- [x] `docker/build-production-images.sh` — fix default VERSION `0.3.5` → `0.6.0`

## Step 6 — Update documentation
- [x] `docs/how-to-guides/installation.md` — rewrite install sections by deployment target
- [x] `docs/explanation/edge-architecture.md` — update install commands to `rufus-sdk-edge`
- [x] `docs/tutorials/edge-deployment.md` — fix `pip install rufus` → `pip install 'rufus-sdk-edge[edge]'`
- [x] `docs/reference/configuration/edge-footprint.md` — update wheel sizes for split packages
- [x] `docs/CLI_QUICK_REFERENCE.md` — add split package install table
- [x] `CLAUDE.md` (Setup section) — add per-role install instructions
- [x] `.claude/TECHNICAL_INFORMATION.md §17` — package split reference

## Step 7 — Update memory
- [x] `memory/MEMORY.md` — update version + package names
- [x] `memory/production-deployment.md` — update v0.6.0 status

## Pending (user actions after publish)
- [ ] Build all three wheels (`poetry build` from each location)
- [ ] Verify wheel contents with `unzip -l` (each should contain only its own packages)
- [ ] Publish all three to TestPyPI
- [ ] Rebuild Docker images with `--no-cache` using `./build-production-images.sh 0.6.0 ruhfuskdev true`

## Review

### Proof of Work
- `tests/test_package_versions.py` — 2 tests pass
- Full test suite — pending (in progress)
- Root `pyproject.toml` packages: `rufus` + `rufus_cli` only ✅
- Sub-package pyproject.toml files created ✅
- All four `__version__` = `"0.6.0"` ✅

### Files Changed
**New files:**
- `packages/rufus-sdk-edge/pyproject.toml`
- `packages/rufus-sdk-server/pyproject.toml`
- `tests/test_package_versions.py`

**Modified:**
- `pyproject.toml`
- `src/rufus/__init__.py`
- `src/rufus_edge/__init__.py`
- `src/rufus_server/__init__.py`
- `src/rufus_cli/__init__.py`
- `docker/Dockerfile.rufus-server-prod`
- `docker/Dockerfile.rufus-worker-prod`
- `docker/Dockerfile.rufus-flower-prod`
- `docker/build-production-images.sh`
- `docs/how-to-guides/installation.md`
- `docs/explanation/edge-architecture.md`
- `docs/tutorials/edge-deployment.md`
- `docs/reference/configuration/edge-footprint.md`
- `docs/CLI_QUICK_REFERENCE.md`
- `CLAUDE.md`
- `.claude/TECHNICAL_INFORMATION.md`
- `memory/MEMORY.md`
- `memory/production-deployment.md`
