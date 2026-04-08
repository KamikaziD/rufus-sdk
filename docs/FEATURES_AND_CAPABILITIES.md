# Ruvon Features & Capabilities

**Last Updated:** 2026-02-27
**Version:** 0.6.0 (Stable)

This document provides a comprehensive catalog of all Ruvon SDK features, their implementation status, stability, and links to documentation and examples.

---

## Feature Matrix

### Step Types

| Feature | Status | Stability | Example Location | Documentation |
|---------|--------|-----------|------------------|---------------|
| **STANDARD** | ✅ Implemented | **Stable** | `examples/quickstart/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#standard-steps) |
| **ASYNC** | ✅ Implemented | **Stable** | `examples/loan_application/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#async-steps) |
| **PARALLEL** | ✅ Implemented | **Stable** | `examples/loan_application/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#parallel-execution) |
| **DECISION** | ✅ Implemented | **Stable** | `examples/loan_application/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#decision-steps) |
| **LOOP** | ✅ Implemented | **Beta** | See usage guide | [USAGE_GUIDE.md](../USAGE_GUIDE.md#loop-steps) |
| **HTTP** | ✅ Implemented | **Stable** | `examples/quickstart/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#http-steps) |
| **FIRE_AND_FORGET** | ✅ Implemented | **Beta** | See usage guide | [USAGE_GUIDE.md](../USAGE_GUIDE.md#fire-and-forget) |
| **CRON_SCHEDULE** | ✅ Implemented | **Beta** | See usage guide | [USAGE_GUIDE.md](../USAGE_GUIDE.md#cron-schedule) |

**Legend:**
- ✅ **Stable** - Production-ready, fully tested, API stable
- ✅ **Beta** - Functional, API may change in minor updates
- 🚧 **Alpha** - Experimental, API unstable
- 📋 **Planned** - Not yet implemented

---

### Control Flow Mechanisms

| Feature | Status | Stability | Example | Documentation |
|---------|--------|-----------|---------|---------------|
| **Automate Next** | ✅ Implemented | **Stable** | `examples/quickstart/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#automate-next) |
| **Conditional Branching** | ✅ Implemented | **Stable** | `examples/loan_application/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#conditional-branching) |
| **Human-in-the-Loop** | ✅ Implemented | **Stable** | `examples/sqlite_task_manager/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#human-in-loop) |
| **Sub-Workflows** | ✅ Implemented | **Stable** | `examples/loan_application/` | [USAGE_GUIDE.md](../USAGE_GUIDE.md#sub-workflows) |
| **Dynamic Injection** | ✅ Implemented | **Experimental** | See advanced guide | [CLAUDE.md](../CLAUDE.md#dynamic-injection-caution) |
| **Declarative Routes** | ✅ Implemented | **Beta** | `examples/loan_application/` | [YAML_GUIDE.md](../YAML_GUIDE.md#routes) |
| **Step Dependencies** | ✅ Implemented | **Stable** | All examples | [YAML_GUIDE.md](../YAML_GUIDE.md#dependencies) |
| **Workflow Jumps** | ✅ Implemented | **Stable** | See usage guide | [USAGE_GUIDE.md](../USAGE_GUIDE.md#workflow-jumps) |

---

### Persistence Providers

| Provider | Status | Best Use Case | Performance | Example |
|----------|--------|---------------|-------------|---------|
| **SQLite** | ✅ **Stable** | Development, Testing, Low-concurrency (<50 workflows/sec) | ~9K ops/sec | `examples/sqlite_task_manager/` |
| **PostgreSQL** | ✅ **Stable** | Production, High-concurrency (>100 workflows/sec) | ~15K ops/sec | See deployment guide |
| **Redis** | ✅ **Beta** | Caching, Specific use-cases | ~20K ops/sec | See advanced guide |
| **In-Memory** | ✅ **Stable** | Testing only (no persistence) | ~50K ops/sec | `tests/sdk/` |

**Features by Provider:**

| Feature | SQLite | PostgreSQL | Redis | In-Memory |
|---------|--------|------------|-------|-----------|
| Persistence | ✅ File/Memory | ✅ Database | ✅ Redis | ❌ Ephemeral |
| Concurrency | ⚠️ Limited (1 writer) | ✅ High | ✅ High | ✅ High |
| ACID Transactions | ✅ Yes | ✅ Yes | ⚠️ Limited | ❌ N/A |
| Auto-initialization | ✅ Yes | ❌ No (use `ruvon db init`) | ❌ No | ✅ Yes |
| LISTEN/NOTIFY | ❌ No | ✅ Yes | ✅ Pub/Sub | ❌ No |
| Setup Complexity | ✅ Zero | ⚠️ Medium | ⚠️ Medium | ✅ Zero |

---

### Execution Providers

| Provider | Status | Best Use Case | Concurrency Model | Example |
|----------|--------|---------------|-------------------|---------|
| **Sync** | ✅ **Stable** | Simple workflows, Testing | Single-threaded | `examples/quickstart/` |
| **Thread Pool** | ✅ **Stable** | Local concurrency, CPU-bound tasks | Multi-threaded (local) | See usage guide |
| **Celery** | ✅ **Stable** | Distributed execution, Long-running tasks | Distributed workers | See deployment guide |
| **PostgreSQL Executor** | ✅ **Beta** | PostgreSQL-based task queue | Database-backed queue | See advanced guide |

**Features by Executor:**

| Feature | Sync | Thread Pool | Celery | PostgreSQL Executor |
|---------|------|-------------|--------|---------------------|
| Parallel Steps | ⚠️ Sequential | ✅ Parallel (local) | ✅ Parallel (distributed) | ✅ Parallel (DB-backed) |
| Async Steps | ⚠️ Blocking | ✅ Non-blocking | ✅ Non-blocking | ✅ Non-blocking |
| Scalability | ❌ Single process | ⚠️ Limited (threads) | ✅ Unlimited (workers) | ✅ High |
| Setup Complexity | ✅ Zero | ✅ Zero | ⚠️ Medium (Redis+Celery) | ⚠️ Medium (PostgreSQL) |
| Best For | Testing, simple | Local workflows | Production, distributed | PostgreSQL-only stacks |

---

### Advanced Features

| Feature | Status | Stability | Use Case | Documentation |
|---------|--------|-----------|----------|---------------|
| **Saga Pattern** | ✅ Implemented | **Stable** | Distributed transactions, Rollback | [USAGE_GUIDE.md](../USAGE_GUIDE.md#saga-pattern) |
| **Zombie Recovery** | ✅ Implemented | **Stable** | Detect crashed workers, Auto-recovery | [CLAUDE.md](../CLAUDE.md#zombie-workflow-recovery) |
| **Workflow Versioning** | ✅ Implemented | **Stable** | Protect running workflows from YAML changes | [CLAUDE.md](../CLAUDE.md#workflow-versioning) |
| **Heartbeat Management** | ✅ Implemented | **Stable** | Worker health monitoring | [CLAUDE.md](../CLAUDE.md#zombie-workflow-recovery) |
| **Performance Optimizations** | ✅ Implemented | **Stable** | uvloop, orjson, connection pooling | [CLAUDE.md](../CLAUDE.md#performance-optimizations-phase-1) |
| **Auto-initialization (SQLite)** | ✅ Implemented | **Stable** | Zero-setup database schema | [CLAUDE.md](../CLAUDE.md#sqlite-persistence-provider) |
| **Migration System** | ✅ Implemented | **Stable** | Database schema versioning | [CLAUDE.md](../CLAUDE.md#database-schema-management) |
| **Polyglot Workflows (HTTP)** | ✅ Implemented | **Stable** | Call services in any language | [USAGE_GUIDE.md](../USAGE_GUIDE.md#polyglot-workflows) |

---

### CLI Commands

**Status:** All commands ✅ **Stable** and production-ready

#### Configuration Commands (6 commands)
| Command | Purpose | Example |
|---------|---------|---------|
| `ruvon config show` | Show current configuration | `ruvon config show` |
| `ruvon config set-persistence` | Set database provider | `ruvon config set-persistence` |
| `ruvon config set-execution` | Set execution provider | `ruvon config set-execution` |
| `ruvon config set-default` | Set default behaviors | `ruvon config set-default` |
| `ruvon config reset` | Reset to defaults | `ruvon config reset` |
| `ruvon config path` | Show config file location | `ruvon config path` |

#### Workflow Management Commands (8 commands)
| Command | Purpose | Example |
|---------|---------|---------|
| `ruvon list` | List workflows | `ruvon list --status ACTIVE --limit 50` |
| `ruvon start` | Start workflow | `ruvon start OrderProcessing -d '{"customer_id": "123"}'` |
| `ruvon show` | Show workflow details | `ruvon show <workflow-id> --state --logs` |
| `ruvon resume` | Resume paused workflow | `ruvon resume <workflow-id> --input '{"approved": true}'` |
| `ruvon retry` | Retry failed workflow | `ruvon retry <workflow-id> --from-step Payment` |
| `ruvon cancel` | Cancel workflow | `ruvon cancel <workflow-id> --reason "Duplicate"` |
| `ruvon logs` | View workflow logs | `ruvon logs <workflow-id> --level ERROR` |
| `ruvon metrics` | View performance metrics | `ruvon metrics --summary` |

#### Database Management Commands (5 commands)
| Command | Purpose | Example |
|---------|---------|---------|
| `ruvon db init` | Initialize database schema | `ruvon db init` |
| `ruvon db migrate` | Apply pending migrations | `ruvon db migrate --dry-run` |
| `ruvon db status` | Check migration status | `ruvon db status` |
| `ruvon db stats` | Show database statistics | `ruvon db stats` |
| `ruvon db validate` | Validate schema integrity | `ruvon db validate` |

#### Monitoring & Recovery Commands (2 commands)
| Command | Purpose | Example |
|---------|---------|---------|
| `ruvon scan-zombies` | Find zombie workflows | `ruvon scan-zombies --fix --threshold 120` |
| `ruvon zombie-daemon` | Run zombie recovery daemon | `ruvon zombie-daemon --interval 60` |

#### Validation & Testing Commands (2 commands)
| Command | Purpose | Example |
|---------|---------|---------|
| `ruvon validate` | Validate workflow YAML | `ruvon validate workflow.yaml --strict` |
| `ruvon run` | Run workflow locally (testing) | `ruvon run workflow.yaml -d '{}'` |

**Total:** 21 commands across 5 categories

---

### Observability & Monitoring

| Feature | Status | Stability | Integration | Documentation |
|---------|--------|-----------|-------------|---------------|
| **Logging Observer** | ✅ Implemented | **Stable** | Console logging | [USAGE_GUIDE.md](../USAGE_GUIDE.md#observability) |
| **CLI Metrics** | ✅ Implemented | **Stable** | `ruvon metrics` command | [CLI_REFERENCE.md](CLI_REFERENCE.md#metrics) |
| **Audit Logging (PostgreSQL)** | ✅ Implemented | **Stable** | Database audit table | See advanced guide |
| **Workflow Heartbeats** | ✅ Implemented | **Stable** | Worker health monitoring | [CLAUDE.md](../CLAUDE.md#heartbeat-manager) |
| **NoOp Observer** | ✅ Implemented | **Stable** | Silent mode for testing | `tests/sdk/` |
| **OpenTelemetry** | 📋 Planned | N/A | Distributed tracing | See roadmap |
| **Prometheus Metrics** | 📋 Planned | N/A | Metrics export | See roadmap |
| **Grafana Dashboards** | 📋 Planned | N/A | Visualization | See roadmap |

---

### Developer Experience

| Feature | Status | Stability | Benefit |
|---------|--------|-----------|---------|
| **Type Hints** | ✅ Implemented | **Stable** | IDE autocomplete, type checking |
| **Pydantic Validation** | ✅ Implemented | **Stable** | Runtime validation, clear errors |
| **TestHarness** | ✅ Implemented | **Stable** | Easy workflow testing |
| **YAML Schema** | ✅ Implemented | **Stable** | IDE autocomplete in YAML files |
| **JSON Schema Validation** | ✅ Implemented | **Stable** | Pre-flight validation (`ruvon validate --strict`) |
| **Error Messages** | ✅ Implemented | **Beta** | Clear, actionable errors (being improved) |
| **Package Auto-discovery** | ✅ Implemented | **Stable** | Automatic `ruvon-*` package loading |
| **Cookiecutter Template** | ✅ Implemented | **Beta** | Project scaffolding |

---

### Ecosystem & Integrations

| Package/Integration | Status | Purpose | Repository |
|---------------------|--------|---------|------------|
| **ruvon-slack** | ✅ **Beta** | Slack notifications & workflows | `/ruvon-slack/` |
| **FastAPI Integration** | ✅ **Example** | REST API wrapper | `examples/fastapi_api/` |
| **Flask Integration** | ✅ **Example** | REST API wrapper | `examples/flask_api/` |
| **JavaScript/HTTP Steps** | ✅ **Example** | Polyglot workflows | `examples/javascript_steps/` |
| **Cookiecutter Template** | ✅ **Beta** | Package template | `/cookiecutter-ruvon-package/` |
| **ruvon-stripe** | 🚧 **In Progress** | Stripe payment workflows | TBD |
| **ruvon-aws** | 📋 **Planned** | AWS service integrations | TBD |
| **ruvon-gcp** | 📋 **Planned** | GCP service integrations | TBD |

---

## Feature Details

### 1. Step Types

#### STANDARD Steps
**Status:** ✅ **Stable**
**Use Case:** Synchronous, fast operations (<1 second)

**Example:**
```yaml
- name: "Validate_Input"
  type: "STANDARD"
  function: "steps.validate_input"
  automate_next: true
```

**Best Practices:**
- Use for validation, simple calculations, state updates
- Keep execution time under 1 second
- No I/O operations (use ASYNC instead)

**Limitations:**
- Blocks workflow execution
- Not suitable for long-running tasks

---

#### ASYNC Steps
**Status:** ✅ **Stable**
**Use Case:** Long-running, I/O-bound operations

**Example:**
```yaml
- name: "Send_Email"
  type: "ASYNC"
  function: "notifications.send_email"
```

**Best Practices:**
- Use for API calls, database queries, file operations
- Configure execution provider (Celery for distributed)
- Implement idempotency

**Limitations:**
- Requires execution provider (Celery, Thread Pool)
- Adds latency for task dispatch

---

#### PARALLEL Steps
**Status:** ✅ **Stable**
**Use Case:** Execute multiple tasks concurrently

**Example:**
```yaml
- name: "Risk_Assessment"
  type: "PARALLEL"
  tasks:
    - name: "Credit_Check"
      function: "checks.credit"
    - name: "Fraud_Detection"
      function: "checks.fraud"
  merge_strategy: "SHALLOW"
  merge_conflict_behavior: "PREFER_NEW"
  allow_partial_success: true
```

**Features:**
- Merge strategies: `SHALLOW`, `DEEP`, `REPLACE`, `APPEND`, `OVERWRITE_EXISTING`, `PRESERVE_EXISTING`
  - `SHALLOW` — merge top-level keys; existing keys are overwritten
  - `DEEP` — recursive merge for nested dicts
  - `REPLACE` — entire state replaced by result
  - `APPEND` — result items appended to list; falls back to SHALLOW for non-lists
  - `OVERWRITE_EXISTING` — existing keys overwritten, new keys added
  - `PRESERVE_EXISTING` — only new keys added; existing keys kept
- Conflict resolution: `PREFER_NEW`, `PREFER_EXISTING`, `RAISE_ERROR`
- Partial success handling (`allow_partial_success: true`)

**Best Practices:**
- Use for independent operations
- Handle merge conflicts explicitly
- Consider timeout settings

---

### 2. Control Flow

#### Human-in-the-Loop
**Status:** ✅ **Stable**

**Example:**
```python
from ruvon.models import WorkflowPauseDirective

def approval_step(state, context):
    raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

**Resume:**
```bash
ruvon resume <workflow-id> --input '{"approved": true}'
```

---

### 3. Advanced Patterns

#### Saga Pattern (Compensation)
**Status:** ✅ **Stable**

**Example:**
```yaml
- name: "Charge_Payment"
  function: "payments.charge"
  compensate_function: "payments.refund"  # Called on failure
```

**Enable:**
```python
workflow.enable_saga_mode()
```

**Behavior:**
- On failure, compensation functions execute in reverse order
- Workflow status becomes `FAILED_ROLLED_BACK`
- All compensations logged

---

## Known Limitations

### Current Limitations

1. **SQLite Concurrency**
   - Single writer at a time
   - Recommended for <50 concurrent workflows
   - **Workaround:** Use PostgreSQL for higher concurrency

2. **No GUI**
   - CLI and SDK only
   - **Workaround:** Web UI planned for future release

3. **Limited Real-time Monitoring**
   - Basic metrics via CLI
   - **Workaround:** OpenTelemetry integration planned

4. **No Visual Workflow Designer**
   - YAML editing only
   - **Workaround:** Use IDE with YAML schema validation

5. **Manual Deployment**
   - No auto-deployment tools
   - **Workaround:** Docker/K8s templates available

### Addressing in v1.0

- Enhanced SQLite concurrency guidance
- Web UI (separate project)
- Deployment templates
- Enhanced monitoring integrations

---

## Version History

### v0.6.0 (Current — Stable)
- ✅ **Package split** — monolithic `ruvon-sdk` (9.3 MB) split into three targeted wheels
  - `ruvon-sdk` (core + CLI, ~185 KB wheel) — `ruvon` + `ruvon_cli`
  - `ruvon-edge` (~250 KB wheel) — `ruvon_edge` only; edge devices no longer pull cloud code
  - `ruvon-server` (~9.5 MB wheel) — `ruvon_server` only
- ✅ Docker Hub: `ruhfuskdev/ruvon-server:0.6.0`, `ruhfuskdev/ruvon-worker:0.6.0`, `ruhfuskdev/ruvon-flower:0.6.0`
- ✅ `ruvon_edge.__version__` corrected from stale `"0.5.0"` to `"0.6.0"`; `ruvon_server` + `ruvon_cli` now expose `__version__`
- ✅ `tests/test_package_versions.py` — version drift guard across all four packages

### v0.5.3
- ✅ PARALLEL `batch_size` + `allow_partial_success` fields
- ✅ CRON_SCHEDULE polling engine (Celery Beat)
- ✅ Admin auth enforced on 8 server endpoints; WebSocket device API key auth
- ✅ 32 new tests (FaF, CRON, ExpressionEvaluator, TemplateEngine, ThreadPool)

### v0.5.0
- ✅ 33-table PostgreSQL schema under Alembic management
- ✅ 10-table SQLite edge schema (auto-created)
- ✅ Database schema consolidation (`database.py` as single source of truth)
- ✅ Edge-specific tables: `saf_pending_transactions`, `device_config_cache`, `edge_sync_state`

### v0.4.2
- ✅ 25 endpoint tests covering all major API routes
- ✅ Error handling: 404/422/409 responses
- ✅ `_get_workflow_or_404` helper; proper exception-to-status mapping
- ✅ `rate_limit_check` crash fix for test environments

### v0.4.1
- ✅ OpenAPI tags on all 86 route decorators (14 tag groups)
- ✅ Grouped Swagger UI at `/docs`

### v0.4.0
- ✅ `RUVON_CUSTOM_ROUTERS` environment variable for user-defined API extensions

### v0.3.0
- ✅ Core SDK complete
- ✅ 21 CLI commands
- ✅ SQLite auto-initialization
- ✅ Zombie recovery
- ✅ Workflow versioning
- ✅ Performance optimizations (uvloop, orjson, connection pooling, import caching)

### v1.0.0 (Planned)
- OpenTelemetry integration
- Prometheus metrics endpoint
- GPU inference step type
- mTLS device authentication
- HSM integration for PCI-DSS

---

## Feature Request Process

To request a new feature:

1. **Check Roadmap:** See [OUTSTANDING_FEATURES.md](../OUTSTANDING_FEATURES.md)
2. **GitHub Discussion:** Post in Discussions → Ideas
3. **Use Case:** Describe your use case clearly
4. **Priority:** Community votes determine priority

---

**For detailed usage of any feature, see:**
- [USAGE_GUIDE.md](../USAGE_GUIDE.md) - Common patterns
- [CLAUDE.md](../CLAUDE.md) - Advanced features
- [YAML_GUIDE.md](../YAML_GUIDE.md) - YAML reference
- [CLI_REFERENCE.md](CLI_REFERENCE.md) - CLI commands

---

**Last Updated:** 2026-02-24
**Maintained By:** Ruvon SDK Team
