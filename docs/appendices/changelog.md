# Changelog

All notable changes to Rufus SDK are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0rc1] — 2026-03-14

### Breaking Changes
- **`WorkflowBuilder.__init__()` — 4 params only**: `workflow_registry`, `expression_evaluator_cls`, `template_engine_cls`, `config_dir`. Removed `persistence_provider`, `execution_provider`, `observer` from constructor — these now go to `create_workflow()`.
- **`Workflow.next_step()` replaces `execute_next_step()`**: rename all call sites.
- **`WorkflowObserver` is now an ABC** (was `Protocol`): partial implementations fail at instantiation rather than silently at runtime.
- **`workflow_observer=` param name** in `create_workflow()` (was `observer=`).

### Added
- **CLI fixed**: `workflow_cmd.py`, `interactive.py`, `main.py` fully migrated to `WorkflowBuilder.create_workflow()` — `rufus start`, `rufus retry --auto`, `rufus interactive run` all functional.
- **`automate_start` attribute** on `Workflow` — `WorkflowEngine.start_workflow()` respects it; mock tests updated.
- **5 new `WorkflowObserver` lifecycle events**: `on_workflow_paused`, `on_workflow_resumed`, `on_compensation_started`, `on_compensation_completed`, `on_child_workflow_started`.
- **`OtelObserver`** — OpenTelemetry parent/child spans; graceful no-op when `opentelemetry-sdk` absent; install via `pip install 'rufus-sdk[otel]'`.
- **`ExecutionContext` dataclass** — `trace_id`, `workflow_id`, `step_name`, `attempt`, `actor_id`; additive param on `dispatch_async_task` / `dispatch_parallel_tasks`.
- **Ed25519 server-side verification** — `DeviceService.sync_transactions()` verifies `X-Payload-Signature` for devices with a registered public key; falls back to HMAC-only for unregistered devices.
- **WASM Component Model + Browser/WASI targets** — `PlatformAdapter` Protocol with Native/Pyodide/WASI implementations; `ComponentStepRuntime`; `WIT` interface; `PyodideSQLiteProvider`; `bootstrap_wasi()`.
- **Browser demo** (`examples/browser_demo/`) — 3 demo workflows running Pyodide + Transformers.js (WebGPU); summariser model updated to `Qwen2.5-0.5B-Instruct` (q4).
- **`annotated-types>=0.7.0`** — bumped from `>=0.5` to fix `annotated_types.Not` in Pydantic v2 advanced validators.

### Fixed
- `test_start_workflow_success` — mock `Workflow` now sets `automate_start = False`.
- `test_validate_policy_passes_valid_data`, `test_persist_policy_inserts_and_syncs` — resolved by `annotated-types` bump.

---

## [Unreleased] — v1.0 Roadmap Sprints

### Sprint 1 — Provider Interface Contract Freeze

#### Added
- **Domain DTOs** (`src/rufus/providers/dtos.py`) — `WorkflowRecord`, `TaskRecord`, `AuditLogRecord`, `MetricRecord`, `SyncStateRecord` typed dataclasses (slots=True) replacing `Dict[str,Any]` in new code
- **Typed exceptions** — `PersistenceError`, `WorkflowNotFoundError`, `DuplicateIdempotencyKeyError`, `TaskNotFoundError` in `persistence.py`
- **`CompatibilityMixin`** — moves `_sync` suffix methods out of abstract interface; `PersistenceProvider` now has ~16 abstract methods (was 24)
- **5 edge sync abstract methods** on `PersistenceProvider`: `get_pending_sync_workflows`, `get_audit_logs_for_workflows`, `delete_synced_workflows`, `get_edge_sync_state(key) -> Optional[str]`, `set_edge_sync_state`
- **`ExecutionContext` dataclass** (`execution.py`) — `trace_id`, `workflow_id`, `step_name`, `attempt`, `actor_id`; added to `dispatch_async_task` / `dispatch_parallel_tasks`
- **`WorkflowObserver` → ABC** (was `Protocol`): partial implementations now fail at instantiation; all methods have default async no-op bodies
- **5 new observer lifecycle events**: `on_workflow_paused`, `on_workflow_resumed`, `on_compensation_started`, `on_compensation_completed`, `on_child_workflow_started`
- **`duration_ms: Optional[float] = None`** on `on_step_executed()` (backward-compatible default)
- **Provider compliance test suites** (`tests/providers/`) — `base_persistence_compliance.py`, `base_execution_compliance.py`, `base_observer_compliance.py`, SQLite/InMemory compliance tests, observer ordering tests

### Sprint 2 — Offline Resilience

#### Added
- **Monotonic sequence counter** — `device_sequence` SQLite table; `SyncManager._next_sequence()` uses `BEGIN IMMEDIATE` for atomic increment; replaces hardcoded `"device_sequence": 0` in SAF payloads
- **Process-safe sync lock** — `sync_lock` SQLite table with stale-lock detection (>5 min); replaces in-memory `_sync_in_progress` flag (broken in multi-process)
- **`mark_rejected(transaction_ids)`** on `SyncManager` — sets tasks to `FAILED` after cloud rejection; ends infinite retry cycle
- **Audit log pagination** — `get_audit_logs_for_workflows(limit_per_workflow=50)`; 5 MB hard cap in `workflow_sync.py` (drops audit logs when exceeded, syncs workflow records only)
- **Tests**: `tests/edge/test_sequence_counter.py`, `test_sync_lock.py`, `test_sync_conflict_resolution.py`, `test_audit_pagination.py`

### Sprint 3 — Observability

#### Added
- **Step timing** (`workflow.py`) — `time.monotonic()` wrap around sync step execution; `duration_ms` passed to `observer.on_step_executed()` and `persistence.record_metric()`
- **Structured JSON logging** (`logging.py`) — `StructuredLogFormatter`; all `LoggingObserver` methods use `logger.info("event.name", extra={...})` pattern for Fluent Bit / syslog aggregators
- **`OtelObserver`** (`src/rufus/implementations/observability/otel.py`) — parent span per workflow, child span per step; graceful no-op if `opentelemetry-sdk` not installed; add `pip install 'rufus-sdk[otel]'`
- **`EventPublisherObserver`** updates — `duration_ms` in `step.executed` stream event; 5 new lifecycle events; saga events to `rufus:saga_events` stream
- **Tests**: `tests/providers/test_otel_observer.py`, `test_logging_observer.py`, `tests/sdk/test_step_timing.py`

### Sprint 4 — Security Hardening

#### Added
- **Ed25519 payload signing** — `SyncManager._sync_batch()` signs `json.dumps(payload, sort_keys=True)` and adds `X-Payload-Signature` header (base64-encoded); `_ed25519_private_key` field on `SyncManager`
- **API key rotation** — `DeviceService.rotate_api_key(device_id, current_api_key)` endpoint `POST /api/v1/devices/{device_id}/rotate-key`; `api_key_rotated_at` column added to `edge_devices` via Alembic migration `f1a2b3c4d5e6`
- **Graduated heartbeat failure logging** — `RufusEdgeAgent`: warning on 1st consecutive failure, error on every 10th; counter resets on success
- **Device bootstrap** — `RufusEdgeAgent.bootstrap(device_type, merchant_id, firmware_version) -> bool`; reads stored API key from `edge_sync_state`; auto-registers with cloud if absent; `start()` calls `bootstrap()` when `api_key` is empty
- **Alembic migration** `f1a2b3c4d5e6` — adds `last_device_sequence INTEGER DEFAULT 0` and `api_key_rotated_at TIMESTAMP` to `edge_devices`
- **Tests**: `tests/edge/test_payload_signing.py`, `test_api_key_rotation.py`, `test_device_bootstrap.py`

### Known Test Environment Notes
- `annotated_types.Not` `AttributeError` in `tests/test_server_endpoints.py` and `tests/integration/test_webhook_integration.py` — pre-existing pydantic/fastapi version mismatch in dev venv; tests are guarded with `pytestmark = pytest.mark.skipif(not _FASTAPI_AVAILABLE, ...)`
- `AsyncWorkflowStep` IS a subclass of `WorkflowStep` (inherits from it); `is_sync_step` in `workflow.py` is determined by `not isinstance(step, (AsyncWorkflowStep, HttpWorkflowStep, ...))` — not by `isinstance(step, WorkflowStep)`
- `get_edge_sync_state(key)` returns `Optional[str]` (plain string), not `Optional[SyncStateRecord]`; access the returned value directly, not via `.value`
- Direct `Workflow()` instantiation requires all 6 providers; in tests use `MagicMock()` for `workflow_builder` and pass `SimpleExpressionEvaluator` / `Jinja2TemplateEngine` as classes

---

## [0.8.0] - 2026-03-12

### Added
- **Platform I/O abstraction** — `PlatformAdapter` protocol with three concrete implementations:
  `NativePlatformAdapter` (standard CPython), `PyodidePlatformAdapter` (browser/JSPI),
  and `WasiPlatformAdapter` (WASI 0.3). Step functions call `platform.read_stdin()` /
  `platform.write_stdout()` and remain target-agnostic.
- **Component Model WASM executor** — `ComponentStepRuntime` drives the
  `wasmtime` Component Model API; `step.wit` defines the canonical
  `run-step(input: string) -> string` interface shared by all WASM step components.
- **Browser target** — `PyodidePlatformAdapter` + JSPI async bridge; `wa-sqlite`
  replaces native SQLite in browser context; `browser_loader.js` bootstraps the
  Pyodide runtime and mounts the Rufus wheel.
- **WASI 0.3 native target** — `wasi_main.py` entry-point reads workflow state from
  stdin and writes result JSON to stdout; `build_wasi.sh` compiles the edge agent to
  a portable WASI component using `componentize-py`.
- **`WorkflowBuilder` `wasm_binary_resolver` param** — callers can inject a custom
  resolver (e.g. `SqliteWasmBinaryResolver`, `HttpWasmBinaryResolver`) so the builder
  fetches `.wasm` binaries at workflow creation time without tight coupling to storage.
- **TECHNICAL_INFORMATION.md §20** — full reference for Component Model contract,
  WIT interface, browser bootstrapping, WASI build pipeline, and cross-target testing.

---

## [Unreleased]

### Added
- **WASM step type** — Execute pre-compiled WebAssembly binaries as workflow steps via the WASI stdin/stdout interface. Any language that compiles to WASM (Rust, C, Go) can implement step logic with full sandbox isolation. Requires `pip install wasmtime`.
  - `WasmConfig` + `WasmWorkflowStep` models in `rufus.models`
  - `WasmRuntime` helper with `DiskWasmBinaryResolver` (cloud) and `SqliteWasmBinaryResolver` (edge)
  - Builder parses `type: "WASM"` steps from workflow YAML
  - `Workflow` accepts optional `wasm_runtime=` parameter
- **WASM component registry** — Cloud control plane APIs for binary lifecycle management:
  - `POST /api/v1/admin/wasm-components` — upload `.wasm` binary (computes SHA-256, stores to disk)
  - `GET /api/v1/wasm-components/{hash}/download` — stream binary to edge devices
  - `GET /api/v1/wasm-components` — list registered components
  - `GET /api/v1/wasm-components/{hash}` — fetch component metadata
- **WASM edge distribution** — new `SYNC_WASM` command type (LOW priority, heartbeat). `ConfigManager.handle_sync_wasm_command()` downloads, verifies SHA-256, and caches to `device_wasm_cache`. Startup prefetch scans workflow YAMLs for missing WASM hashes.
- **New DB tables**: `wasm_components` (cloud, Alembic migration `e1f2a3b4c5d6`) and `device_wasm_cache` (edge SQLite, `CREATE TABLE IF NOT EXISTS`).

---

## [0.7.9] - 2026-03-09

### Added
- **Edge Workflow Sync** — `EdgeWorkflowSyncer` pushes completed edge workflows + audit logs
  to cloud PostgreSQL in batches of 100 (oldest-first); purges local SQLite rows after
  cloud ack; idempotent `ON CONFLICT DO NOTHING` on server side
- **Immediate reconnect sync** — new `_reconnect_sync_loop` polls connectivity every 5 s while
  offline; triggers SAF + workflow sync within 5 s of reconnect (no 60 s wait)
- **`force_sync` command now includes workflow sync** — dashboard Force Sync button pushes
  both SAF transactions and completed workflows

### Fixed
- **Dashboard timezone display** — all timestamps now parsed as UTC via `parseUtcDate()` in
  `utils.ts`; affects Audit Log, Workflow Detail, and Admin pages
- **Synced edge workflow detail 404** — `get_workflow_status` falls back to raw DB row when
  edge step modules are not installed on the cloud server
- **SQLite `workflow_audit_log` FK + CASCADE** — audit rows cascade-delete when parent
  workflow is purged; explicit pre-delete ensures backwards compatibility with older DBs

---

## [0.7.8] - 2026-03-09

### Added
- **Edge telemetry loop** — `edge_device_sim.py` now runs a continuous `EdgeTelemetry`
  workflow loop (default 30 s interval) instead of an idle `sleep(999_999)`.
  Graceful shutdown on SIGTERM/SIGINT via `_shutdown_event`.
- **`telemetry_steps.py`** — 4-step workflow (collect → analyse → sync → finalise):
  - `collect_telemetry`: CPU/memory/disk/network via `psutil`; random fallback when unavailable
  - `analyse_metrics`: threshold alerts (HIGH_CPU >80%, HIGH_MEM >90%, LOW_DISK >95%)
  - `sync_telemetry`: probes `/health`; tracks SAF queue depth when offline
  - `finalise_cycle`: queries SQLite row counts; projects DB growth in MB/day
- **`edge_admin_tool.py`** — interactive host-side CLI for edge fleet management:
  list devices, show config, list/edit/push workflow definitions, broadcast `update_workflow`
- **`docker-compose.test-async.yml`**: `telemetry_steps.py` bind-mount, `TELEMETRY_INTERVAL`
  env var, `touch` command override to bust `.pyc` cache on start

### Fixed
- **Audit log population** — `postgres.py save_workflow()` now writes an audit row on every
  workflow lifecycle event; `log_audit_event()` column names corrected
  (`old_state→old_status`, `new_state→new_status`, `metadata→details`)
- **SQLite audit** — `sqlite.py save_workflow()` writes audit rows using SQLite schema column
  names (`audit_id`, `user_id`, `old_state`, `new_state`)
- **`POST /api/v1/audit/query`** — redirected from dead `command_audit_log` table to
  `workflow_audit_log`; returns normalized `{log_id, timestamp, event_type, entity_type,
  entity_id, actor}` shape
- **Edge sim `sdk_version`** — bumped from `"0.7.5"` to `"0.7.7"` in device registration payload

---

## [0.7.7] - 2026-03-09

### Fixed
- **Edge SQLite config cache**: migrate `_cache_config` / `_load_cached_config` from `tasks`
  table (FK violation) to dedicated `device_config_cache` table
- **Edge SQLite workflow cache**: migrate `handle_update_workflow_command` /
  `load_local_workflow_definitions` from `tasks` table to new `edge_workflow_cache` table;
  persisted workflow definitions now survive device restarts
- **Dashboard**: `sendDeviceCommand` API call now sends `{ type, data }` matching server model
  (was sending `{ command_type, payload }` which server silently ignored)
- **Server**: `webhook_registrations.events` cast to JSONB before `@>` containment operator
  (was failing with `operator does not exist: text @> jsonb` on every webhook dispatch)
- **Server**: added UNIQUE constraint on `rate_limit_tracking(identifier, resource, window_start)`
  required by `ON CONFLICT` upsert (was silently failing on every API request)
- **Edge simulator**: persist API key to `{DB_PATH}.apikey` so config endpoint authenticates
  across container restarts
- **Dashboard**: CommandSender replaced free-text command form with structured dropdown +
  per-command dynamic fields (force_sync, reload_config, update_workflow, update_model)

---

## [0.7.6] - 2026-03-08

### Added
- **`POST /api/v1/devices/commands/broadcast`** — new endpoint broadcasts a command to all registered edge devices; primary use is pushing `update_workflow` commands from the Admin dashboard
- **`DeviceBroadcastRequest`** Pydantic model in `api_models.py`
- **`update_workflow` command handler** in `RufusEdgeAgent._handle_cloud_command()` — edge agents now process workflow-push commands received via heartbeat response
- **`ruhfuskdev/rufus-edge-dev:0.7.6`** Docker image — minimal edge device emulator for docker-compose testing
- **`examples/edge_deployment/edge_device_sim.py`** — clean self-contained edge device simulator script
- **`docker/Dockerfile.rufus-edge-dev`** — Dockerfile for the edge device emulator image
- **`rufus-edge-sim` service** in `rufus_test/docker-compose.test-async.yml` — automatically registers with the cloud control plane and receives workflow pushes

### Fixed
- **Edge agent heartbeat payload field mismatch** — `RufusEdgeAgent._send_heartbeat()` was sending `"status"` but the server's `DeviceHeartbeatRequest` model requires `"device_status"`; caused silent 422 errors dropping all heartbeat responses (and pending commands)
- **`run_edge_macbook.py`** — removed broken imports (`artifact_updater`, `command_handler`, `InferenceFactory`) and rewrote to use `RufusEdgeAgent` with proper device registration

---

## [0.7.5] - 2026-03-06

### Added
- **`automate_start` workflow flag** — new optional YAML/Python boolean; when `true`, the engine calls `next_step()` immediately after `create_workflow()` with no manual resumption required
  - YAML: `automate_start: true` in workflow definition
  - `Workflow(..., automate_start=True)` constructor parameter
  - `builder.py` reads the flag from YAML and passes it to `Workflow`
- **`HardwareIdentity.id` field** — unique device identifier added to `HardwareIdentity` dataclass in `implementations/inference/factory.py`
- **Dashboard how-to guide** (`docs/how-to-guides/dashboard.md`) — complete operational reference covering deployment, Keycloak OIDC setup, 5 role types, 13-page UI walkthrough, live definition updates, and troubleshooting

### Fixed
- Test docker-compose (`rufus_test/docker-compose.test-async.yml`) — image tags updated to v0.7.5; bind-mount `alembic/versions/` directory so migration `c1d2e3f4a5b6` (workflow_definitions + server_commands) is visible when running on older base images

---

## [0.6.0] - 2026-02-27

### Added
- **Package split** — `rufus-sdk` (9.3 MB monolithic) divided into three targeted distribution wheels published to TestPyPI:
  - `rufus-sdk` — core engine (`rufus/`) + CLI (`rufus_cli/`); ~185 KB wheel
  - `rufus-sdk-edge` — edge agent (`rufus_edge/`) only; ~250 KB wheel — edge devices no longer pull 9+ MB of cloud control plane code
  - `rufus-sdk-server` — cloud control plane (`rufus_server/`) only; ~9.5 MB wheel
- **Sub-package `pyproject.toml` files** — `packages/rufus-sdk-edge/pyproject.toml` and `packages/rufus-sdk-server/pyproject.toml` (hatchling build backend with `force-include` for out-of-tree source)
- **`tests/test_package_versions.py`** — version drift guard; asserts all four `__version__` strings are equal across `rufus`, `rufus_edge`, `rufus_server`, `rufus_cli`
- **`__version__`** added to `rufus_server/__init__.py` and `rufus_cli/__init__.py` (previously empty)

### Changed
- **Root `pyproject.toml`** — packages trimmed to `[rufus, rufus_cli]`; extras `server`, `celery`, `auth`, `edge`, `all` moved to their respective sub-packages; optional deps slimmed accordingly
- **`rufus_edge.__version__`** corrected from stale `"0.5.0"` to `"0.6.0"`
- **Docker production images** updated to two-step install pattern: Step 1 installs `rufus-sdk` + `rufus-sdk-server` (no extras) from TestPyPI; Step 2 installs actual optional deps (fastapi, celery, etc.) from PyPI to avoid broken TestPyPI stubs
- **`docker/build-production-images.sh`** default `VERSION` updated from `0.3.5` → `0.6.0`
- **Docs** — `installation.md`, `edge-architecture.md`, `edge-deployment.md`, `edge-footprint.md`, `CLI_QUICK_REFERENCE.md`, `CLAUDE.md` updated for three-package install model

### Fixed
- `rufus_edge.__version__` was `"0.5.0"` (stale since v0.3.x); now correctly `"0.6.0"`

---

## [0.5.3] - 2026-02-25

### Added
- **PARALLEL `batch_size` field** — sequential chunking of large `iterate_over` lists; supported by `SyncExecutor` and `ThreadPoolExecutorProvider`. Set `batch_size: 0` (default) to disable batching.
- **PARALLEL `allow_partial_success` field** — when `true`, the parallel step succeeds even if some tasks fail; failed errors are logged but do not raise.
- **CRON_SCHEDULE polling engine** — `tasks.poll_scheduled_workflows` (Celery Beat) now queries the `scheduled_workflows` DB table and triggers due workflows; `CeleryExecutionProvider.register_scheduled_workflow` inserts schedule rows into the DB.
- **Admin auth on 8 server endpoints** — `POST/PUT/POST /api/v1/admin/commands/versions/...`, `DELETE /api/v1/webhooks/{id}`, and 4 `/api/v1/admin/rate-limits` routes now enforce `require_admin` (role `"admin"` required); `auth/dependencies.py` exports `require_admin`.
- **WebSocket device authentication** — `GET /api/v1/devices/{device_id}/ws` now validates `?api_key=` query parameter against the `edge_devices` table before accepting the connection.
- **New test files** — `test_fire_and_forget.py`, `test_cron_schedule.py`, `test_expression_evaluator.py`, `test_template_engine.py`, `test_thread_pool_executor.py` (32 tests total).

### Changed
- **Step type `CRON_SCHEDULER` renamed to `CRON_SCHEDULE`** — aligns YAML key with `CronScheduleWorkflowStep` class name; update any existing YAML files.
- **CLI `celery` executor** — `NotImplementedError` replaced with `ValueError` and a helpful message.
- **CLI `redis` persistence** — dead import removed; raises `ValueError` with clear message.

### Removed
- **JavaScript step type removed** — `JavaScriptConfig`, `JavaScriptWorkflowStep`, and the `JAVASCRIPT` builder branch have been deleted. Will return in v0.6 once the runtime is ready. Remove `type: JAVASCRIPT` steps from any existing workflows.

### Fixed
- `initial_state_model:` → `initial_state_model_path:` throughout all documentation YAML examples.
- `PREFER_OLD` → `PREFER_EXISTING` in all docs (correct enum value).
- `context.loop_state.current_item` → `context.loop_item` and `context.loop_state.current_iteration` → `context.loop_index` in all docs.
- `step-context.md` rewritten to reflect actual Pydantic `BaseModel` with correct field names.
- All 6 `MergeStrategy` enum values documented (`SHALLOW`, `DEEP`, `REPLACE`, `APPEND`, `OVERWRITE_EXISTING`, `PRESERVE_EXISTING`).
- `AI_INFERENCE` step type added to `step-types.md` documentation.
- `description` common step field added to `yaml-schema.md`.
- `input_model` (YAML) vs `input_schema` (Python) clarification added.
- `saga_enabled` top-level workflow field documented in `yaml-schema.md`.

---

## [0.5.2] - 2026-02-24

### Added
- **PolicyRollout workflow** — durable policy creation with saga compensation: `Validate_Policy` → `Persist_Policy` (compensatable: DELETE + in-memory cache eviction) → `Finalize_Policy_Rollout`; endpoint at `POST /api/v1/policies/rollout`
- `src/rufus_server/steps/policy_rollout_steps.py` — step functions + `PolicyRolloutState` model + `init_services()` injection
- `config/policy_rollout_workflow.yaml` — YAML definition registered in `workflow_registry.yaml`

### Fixed
- **`TECHNICAL_INFORMATION.md §4`** — LOOP YAML examples corrected from deprecated `loop_config: items/condition` syntax to actual fields: `mode:`, `iterate_over:`, `item_var_name:`, `while_condition:`, `loop_body:`
- **`docs/reference/configuration/yaml-schema.md`** — PARALLEL section now documents dynamic fan-out fields (`iterate_over`, `task_function`, `item_var_name`) with examples
- **`docs/explanation/parallel-execution.md`** — added "Pattern 4: Dynamic Fan-Out" section with YAML + Python examples and a static-vs-dynamic comparison table
- **`docs/explanation/self-hosting.md`** — corrected ConfigRollout step names (were wrong); added LOOP/WHILE monitoring step explanation; added PolicyRollout description

### Added (boundary comments)
- `policy_engine.py` — block comment on `PolicyEvaluator` documenting which methods stay as direct calls vs. go through workflows
- `device_service.py` — block comment on `DeviceService` documenting direct vs. workflow-orchestrated methods

---

## [0.5.1] - 2026-02-24

### Documentation
- **README.md** — full rewrite with new positioning: self-hosting insight, 3-role architecture diagram (Device Runtime / Cloud Worker / Control Plane), Docker Compose quick-start using published images, horizontal edge framing (robotics, MedTech, drones, industrial IoT alongside fintech)
- **`docs/explanation/self-hosting.md`** — new file explaining how Rufus orchestrates itself; covers the three-role model, what self-hosting means for reliability and architecture, and the recursive pattern in practice
- **`docs/explanation/architecture.md`** — added "Three Roles, One Runtime" section with ASCII diagram and self-hosting prose
- **`docs/reference/configuration/database-schema.md`** — complete rewrite documenting all 33 cloud tables (by group) and 10 edge tables; added schema governance table, extending-schema instructions, and cascade behavior reference
- **`docs/reference/configuration/configuration.md`** — added `RUFUS_ENCRYPTION_KEY` (marked required) and `RUFUS_CUSTOM_ROUTERS` with usage examples
- **`docs/appendices/changelog.md`** — added v0.4.0, v0.4.1, v0.4.2, v0.5.0 entries (were missing entirely)
- **`docs/appendices/migration-notes.md`** — added v0.4.0/0.4.1/0.4.2/v0.5.0 upgrade guides and updated compatibility matrix to include all versions from 0.4.x onward
- **`docs/appendices/roadmap.md`** — updated timeline (v0.5.0 current), moved v0.4.x features to completed, added new roadmap items (OpenTelemetry, GPU inference step type, mTLS, HSM)
- **`docs/advanced/extending-rufus.md`** — added "Extending the Database Schema" section (custom tables via shared `metadata`) and "Custom API Routes (RUFUS_CUSTOM_ROUTERS)" section
- **`docs/advanced/security.md`** — added "Fintech & PCI-DSS Patterns" section: `RUFUS_ENCRYPTION_KEY` setup/rotation, card tokenization, transaction signing, device authentication, offline floor limit pattern, PCI audit trail query
- **`docs/tutorials/edge-deployment.md`** — fixed broken code: `SyncExecutor()` → `SyncExecutionProvider()`
- **`docs/index.md`** — updated to v0.5.0, new self-hosting intro paragraph, added self-hosting link
- **`docs/README.md`** — removed stale `v0.9.0` version claim
- **`docs/FEATURES_AND_CAPABILITIES.md`** — removed `Pre-release v0.9.0`; updated to Stable v0.5.0 with v0.4.x/v0.5.0 version history
- **`docs/OUTSTANDING_FEATURES.md`** — removed pre-release framing; updated current release to v0.5.0 stable

---

## [0.5.0] - 2026-02-24

### Changed
- Database schema consolidation: `src/rufus/db_schema/database.py` is now the single source of truth for all **33 PostgreSQL tables** (previously only ~7 were Alembic-managed)
- `docker/init-db.sql` stripped to PostgreSQL extensions only (`uuid-ossp`, `pg_trgm`); all schema creation and seed data migrated to Alembic

### Added
- 27 previously-unmanaged tables now under Alembic management:
  - Core workflow: `tasks`, `compensation_log`, `scheduled_workflows`
  - Edge device: `worker_nodes`, expanded `device_commands` (+13 columns: `command_id`, retry fields, batch/broadcast links)
  - Commands & broadcasting: `command_broadcasts`, `command_batches`, `command_templates`, `command_schedules`, `schedule_executions`
  - Audit: `command_audit_log`, `audit_retention_policies`
  - Authorization / RBAC: `authorization_roles`, `role_assignments`, `authorization_policies`, `command_approvals`, `approval_responses`
  - Versioning: `command_versions`, `command_changelog`
  - Webhooks & rate limiting: `webhook_registrations`, `webhook_deliveries`, `rate_limit_rules`, `rate_limit_tracking`
  - Edge config & SAF: `device_configs`, `saf_transactions`, `device_assignments`, `policies`
- 3 new edge-specific SQLite tables: `saf_pending_transactions`, `device_config_cache`, `edge_sync_state`
- `src/rufus/db_schema/edge_database.py` — edge SQLite schema constants and documentation
- Helper functions: `get_core_tables()`, `get_cloud_only_tables()`, `get_edge_device_tables()`
- Alembic migration `a1b2c3d4e5f6` — creates all missing tables, TSVECTOR column, seed data (roles, policies, rate limits, command versions)
- `TECHNICAL_INFORMATION.md` §16: schema reference and table inventory
- Docker Hub images (linux/amd64 + linux/arm64): `ruhfuskdev/rufus-server:0.5.0`, `ruhfuskdev/rufus-worker:0.5.0`, `ruhfuskdev/rufus-flower:0.5.0`

---

## [0.4.2] - 2026-02-23

### Added
- 25 endpoint tests covering all major API routes
- OpenAPI `responses=` annotations on key route decorators

### Fixed
- `_get_workflow_or_404` helper added; fixed bare `get_workflow()` calls in `get_workflow_status` and `next_workflow_step`
- Exception-to-status mapping: `ValueError`→400, `WorkflowFailedException`→422, `SagaWorkflowException`→409
- `rate_limit_check` crash when Redis client is `None` in test environments

---

## [0.4.1] - 2026-02-23

### Added
- OpenAPI tags on all 86 route decorators across 14 tag groups:
  Health, Workflows, Devices, Commands, Policies, Webhooks, Broadcasts,
  Batch Operations, Scheduling, Configuration, Audit, Authorization,
  Rate Limiting, Monitoring
- Grouped, navigable Swagger UI at `/docs`

### Changed
- API version bumped to `0.4.0` in FastAPI constructor

---

## [0.4.0] - 2026-02-23

### Added
- `RUFUS_CUSTOM_ROUTERS` environment variable: comma-separated dotted paths to FastAPI `APIRouter` objects, mounted on server startup without modifying core server code

---

## [0.3.0] - 2026-02-13

### Added
- **Debug UI** - Complete port from Confucius with visual workflow inspection
  - Real-time workflow status dashboard
  - Step execution timeline view
  - State inspection and history
  - Audit log viewer
  - Accessible at `http://localhost:8000/debug` when running Rufus Server
- **Feature Parity Analysis** - Comprehensive comparison with Confucius (80% parity achieved)
- **Docker/Kubernetes Deployment** - Complete distributed Celery worker deployment
  - Docker Compose orchestration for multi-container setup
  - Kubernetes manifests and Helm charts
  - Production-ready distributed execution
  - Health checks and monitoring
- Database seeding script for testing and demos (`tools/seed_data.py`)
- Automatic seed data check in load tests
- Database cleanup tool (`tools/cleanup_db.py`)

### Fixed
- Pydantic protected namespace warnings
- PostgreSQL compatibility for `current_step` field (converted to string)
- Missing dependencies in `pyproject.toml`
- Package name correction from `rufus-edge` to `rufus`
- Load testing for 500+ concurrent devices
- Device cleanup and registration in load tests

### Changed
- Improved error messages with full exception tracebacks (`exc_info=True`)
- Enhanced HTTP client recreation after device registration
- Updated pip install syntax to PEP 508 format

### Documentation
- Comprehensive `docker/README.md` with deployment guides
- Installation decision tree in `QUICKSTART.md`
- Migration systems documentation in `CLAUDE.md`
- Load test prerequisites and setup guides

---

## [0.1.2] - 2026-01-15

### Fixed
- Suppress Pydantic protected namespace warning for `AIInferenceConfig`
- Convert `current_step` to string for PostgreSQL compatibility

---

## [0.1.1] - 2026-01-15

### Fixed
- Add missing dependencies to `pyproject.toml`
- Correct package name from `rufus-edge` to `rufus`

---

## [0.1.0] - 2026-01-12

**First official release of Rufus SDK**

### Added

#### Core SDK Features
- **Workflow orchestration engine** with 8 step types
  - STANDARD - Synchronous step execution
  - ASYNC - Asynchronous task dispatch
  - DECISION - Conditional branching
  - PARALLEL - Concurrent task execution
  - LOOP - Iteration over collections
  - HTTP - Polyglot workflows (call external services)
  - FIRE_AND_FORGET - Non-blocking async execution
  - CRON_SCHEDULER - Scheduled recurring execution
- **Saga pattern** with compensation/rollback support
- **Sub-workflows** with hierarchical status propagation
- **Human-in-the-loop** workflows with pause/resume
- **Dynamic step injection** based on runtime conditions
- **Type-safe state models** using Pydantic
- **Provider-based architecture** for pluggable integrations

#### Persistence Providers
- **SQLite** - Embedded database for development/testing
  - In-memory mode for fast tests
  - WAL mode for better concurrency
  - Foreign key enforcement
- **PostgreSQL** - Production-ready persistence
  - JSONB for flexible state storage
  - Row-level locking (FOR UPDATE SKIP LOCKED)
  - Audit logging with event tracking
  - Connection pooling (configurable min/max)
- **Redis** - High-performance caching and task queues
- **In-Memory** - Testing and development

#### Execution Providers
- **SyncExecutionProvider** - Single-process synchronous execution
- **ThreadPoolExecutionProvider** - Multi-threaded parallel execution
- **CeleryExecutionProvider** - Distributed async task execution
- **PostgresExecutor** - PostgreSQL-backed task queue

#### Database Management
- **Alembic** - Schema migration system
  - Auto-generate migrations from SQLAlchemy models
  - PostgreSQL and SQLite support
  - Incremental migration support
  - Rollback capability
- **SQLAlchemy Core** - Schema definition (migrations only)
- **Raw SQL** - Runtime queries (zero overhead)

#### CLI Tool (21 commands)
- **Workflow Management**
  - `rufus list` - List workflows with filtering
  - `rufus show` - Show workflow details
  - `rufus start` - Start new workflow
  - `rufus resume` - Resume paused workflow
  - `rufus retry` - Retry failed workflow
  - `rufus cancel` - Cancel running workflow
  - `rufus logs` - View execution logs
  - `rufus metrics` - View performance metrics
- **Configuration**
  - `rufus config show` - Show current configuration
  - `rufus config set-persistence` - Configure database
  - `rufus config set-execution` - Configure executor
  - `rufus config set-default` - Set defaults
  - `rufus config reset` - Reset to defaults
  - `rufus config path` - Show config file location
- **Database**
  - `rufus db init` - Initialize schema
  - `rufus db migrate` - Apply migrations
  - `rufus db status` - Migration status
  - `rufus db stats` - Database statistics
  - `rufus db validate` - Validate schema
- **Zombie Recovery**
  - `rufus scan-zombies` - Scan for zombie workflows
  - `rufus zombie-daemon` - Run scanner as daemon

#### Reliability Features
- **Zombie workflow recovery** with heartbeat monitoring
  - `HeartbeatManager` for worker health tracking
  - `ZombieScanner` for stale workflow detection
  - Automatic marking of crashed workflows
  - CLI and daemon modes
- **Workflow versioning** with definition snapshots
  - Snapshot YAML definitions at creation time
  - Running workflows immune to YAML changes
  - Optional explicit version tracking
- **Idempotent operations** with unique constraint handling
- **Graceful error handling** with compensation support

#### Performance Optimizations (Phase 1)
- **uvloop** - 2-4x faster async I/O (automatically enabled)
- **orjson** - 3-5x faster JSON serialization
- **Connection pooling** - Optimized PostgreSQL pool (min=10, max=50)
- **Import caching** - 162x speedup for repeated step function imports
- Benchmark results: 703,633 workflows/sec (simplified), 5.5µs p50 latency

#### Edge Deployment (Rufus Edge)
- **Offline-first architecture** with SQLite
- **Store-and-Forward (SAF)** for payment transactions
- **Cloud control plane** (Rufus Server) with FastAPI
  - Device registry API
  - Config server with ETag-based updates
  - Transaction sync API
- **Edge agent** for device management
  - SyncManager for SAF operations
  - ConfigManager for hot configuration
  - Heartbeat monitoring

#### Documentation
- Comprehensive user guides and tutorials
- API reference documentation
- Architecture explanations
- Quickstart guide
- YAML configuration guide
- CLI usage guide
- How-to guides for common patterns

#### Examples
- **Quickstart** - Simple workflow example (working)
- **SQLite Task Manager** - Task workflow with SQLite backend
- **Loan Application** - Complex multi-step approval workflow
- **FastAPI Integration** - Web service integration
- **Flask Integration** - Alternative web framework
- **JavaScript/Polyglot** - HTTP steps calling external services
- **Edge Deployment** - POS/ATM fintech workflows

#### Testing Infrastructure
- **TestHarness** - Simplified workflow testing
- **Comprehensive test suite** - 125 test files
- **Load testing** - Performance benchmarks (500+ concurrent devices)
- **CI/CD integration** - GitHub Actions ready

### Changed
- Extracted from monolithic "Confucius" prototype
- Modular SDK architecture (31,112 lines, 125 files vs 4,637 lines, 22 files)
- Provider pattern for all external dependencies
- Unified `Workflow` class (replacing `WorkflowEngine`)
- Improved sub-workflow status propagation
- Enhanced parallel execution with conflict detection

### Breaking Changes
None (first release)

---

## Release Notes

### Version 0.3.0 Highlights

**Debug UI Launch** - Visual workflow inspection and monitoring is now available. Access the Debug UI at `http://localhost:8000/debug` when running Rufus Server to view real-time workflow status, step execution timelines, state history, and audit logs.

**Production Deployment** - Complete Docker and Kubernetes deployment templates with distributed Celery worker support. Deploy multi-container setups with health checks and monitoring out of the box.

**Feature Parity** - Achieved 80% feature parity with Confucius, preserving all critical features while adding production-grade capabilities.

### Version 0.1.0 Highlights

**First Official Release** - Rufus SDK is production-capable for most workloads. Core workflow orchestration, 8 step types, multiple persistence and execution providers, comprehensive CLI, and reliability features are stable and tested.

**Fintech-Ready** - Offline-first architecture with Store-and-Forward, edge device management, and PCI-DSS ready features make Rufus suitable for payment terminal deployments.

**Performance Optimized** - Phase 1 optimizations deliver 50-100% throughput improvement and 30-40% latency reduction for I/O-bound workflows.

**Developer-Friendly** - Type-safe state models, TestHarness for easy testing, comprehensive documentation, and working examples make Rufus accessible to new users.

---

## Upgrade Guides

### Upgrading to 0.3.0 from 0.1.x

**No breaking changes.** This is a feature release with full backward compatibility.

**New Features:**
- Debug UI available at `/debug` endpoint
- Database seeding with `tools/seed_data.py`
- Database cleanup with `tools/cleanup_db.py`
- Docker/Kubernetes deployment templates

**Optional Actions:**
- Review `docker/README.md` for deployment options
- Try the Debug UI for workflow monitoring
- Use seed data for testing: `python tools/seed_data.py`

### Upgrading to 0.1.2 from 0.1.1

**No breaking changes.** Bug fix release.

**Fixes:**
- Pydantic warnings suppressed
- PostgreSQL compatibility improved

### Upgrading to 0.1.1 from 0.1.0

**No breaking changes.** Bug fix release.

**Fixes:**
- Missing dependencies added
- Package name corrected

---

## GitHub Releases

For full release notes, changelogs, and downloadable assets, see:
- [GitHub Releases](https://github.com/your-org/rufus-sdk/releases)

---

## Deprecation Notices

None currently.

---

## Security Advisories

No security issues reported to date.

---

**Note:** Pre-1.0 versions (0.x) may include minor API changes. See `migration-notes.md` for version-to-version upgrade guides.

**Last Updated:** 2026-02-24
