# Changelog

All notable changes to Rufus SDK are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
