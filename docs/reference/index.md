# Rufus SDK Reference Documentation

Complete API and configuration reference for Rufus workflow engine.

---

## API Reference

Core Python API documentation.

### [WorkflowBuilder](api/workflow-builder.md)

Load workflow definitions and create workflow instances.

**Key Methods:**
- `create_workflow()` - Create new workflow
- `load_workflow()` - Load existing workflow
- `get_workflow_config()` - Get workflow configuration

### [Workflow](api/workflow.md)

Main workflow orchestration class.

**Key Methods:**
- `execute_next_step()` - Execute next step
- `enable_saga_mode()` - Enable Saga pattern
- `cancel()` - Cancel workflow
- `jump_to_step()` - Jump to specific step

**Key Properties:**
- `status` - Current workflow status
- `state` - Workflow state (Pydantic model)
- `current_step` - Current executing step

### [Providers](api/providers.md)

Provider interfaces for persistence, execution, and observability.

**Interfaces:**
- `PersistenceProvider` - Database abstraction
- `ExecutionProvider` - Task execution abstraction
- `WorkflowObserver` - Observability hooks
- `ExpressionEvaluator` - Expression evaluation
- `TemplateEngine` - Template rendering

**Implementations:**
- PostgreSQL, SQLite, Redis, In-Memory (persistence)
- Sync, Thread Pool, Celery (execution)
- Logging, No-op (observability)

### [StepContext](api/step-context.md)

Context object passed to step functions.

**Fields:**
- `workflow_id` - Workflow identifier
- `step_name` - Current step name
- `previous_step_result` - Previous step result
- `loop_state` - Loop iteration state
- `parent_workflow_id` - Parent workflow (if sub-workflow)
- `metadata` - Additional metadata

### [Directives](api/directives.md)

Control flow exceptions for workflow orchestration.

**Directives:**
- `WorkflowJumpDirective` - Jump to specific step
- `WorkflowPauseDirective` - Pause workflow
- `StartSubWorkflowDirective` - Launch sub-workflow
- `SagaWorkflowException` - Trigger compensation

---

## Configuration Reference

YAML, CLI, and environment variable configuration.

### [YAML Schema](configuration/yaml-schema.md)

Complete YAML workflow definition specification.

**Schemas:**
- Workflow Registry
- Workflow Definition
- Step Configuration
- Dynamic Injection
- Routes (DECISION steps)
- HTTP Steps
- PARALLEL Steps
- LOOP Steps

### [Step Types](configuration/step-types.md)

All 9 step execution types with configuration options.

**Types:**
- `STANDARD` - Synchronous execution
- `ASYNC` - Asynchronous task queue
- `DECISION` - Conditional branching
- `PARALLEL` - Concurrent execution
- `HTTP` - External API calls
- `LOOP` - Iteration (ITERATE/WHILE)
- `FIRE_AND_FORGET` - Background workflows
- `CRON_SCHEDULE` - Recurring workflows
- `HUMAN_IN_LOOP` - Human approval

### [CLI Commands](configuration/cli-commands.md)

Complete command-line interface reference.

**Command Groups:**
- `rufus config` - Configuration management
- `rufus workflow` - Workflow operations
- `rufus db` - Database management
- `rufus scan-zombies` - Zombie workflow detection

**Top-Level Commands:**
- `list`, `start`, `show`, `resume`, `retry`
- `logs`, `metrics`, `cancel`
- `validate`, `run` (legacy)

### [Database Schema](configuration/database-schema.md)

Complete database schema documentation.

**Core Tables:**
- `workflow_executions` - Main workflow state
- `workflow_heartbeats` - Zombie detection
- `workflow_audit_log` - Audit trail
- `workflow_execution_logs` - Debug logs
- `workflow_metrics` - Performance metrics
- `tasks` - Async task queue
- `compensation_log` - Saga rollback

**Edge Tables:**
- `edge_devices` - Device registry
- `device_commands` - Cloud-to-device commands

### [Configuration](configuration/configuration.md)

Environment variables and configuration files.

**Configuration Sources:**
- Environment variables (`DATABASE_URL`, `RUFUS_*`, etc.)
- CLI config file (`~/.rufus/config.yaml`)
- Workflow registry (`config/workflow_registry.yaml`)
- Provider configurations

---

## Quick Reference Tables

### Workflow Statuses

| Status | Description |
|--------|-------------|
| `ACTIVE` | Currently running |
| `PENDING_ASYNC` | Waiting for async task |
| `PENDING_SUB_WORKFLOW` | Waiting for sub-workflow |
| `PAUSED` | Paused for input |
| `WAITING_HUMAN` | Waiting for human input |
| `WAITING_HUMAN_INPUT` | Waiting for user input |
| `WAITING_CHILD_HUMAN_INPUT` | Child workflow waiting |
| `COMPLETED` | Successfully finished |
| `FAILED` | Failed with error |
| `FAILED_ROLLED_BACK` | Failed and rolled back (Saga) |
| `FAILED_CHILD_WORKFLOW` | Child workflow failed |
| `FAILED_WORKER_CRASH` | Worker crashed (zombie) |
| `CANCELLED` | Manually cancelled |

### Step Types Summary

| Type | Execution | Pauses | Compensation | Use Case |
|------|-----------|--------|--------------|----------|
| `STANDARD` | Sync | No | Yes | Fast operations |
| `ASYNC` | Async | Yes | Yes | Long tasks |
| `DECISION` | Sync | No | No | Branching |
| `PARALLEL` | Concurrent | Yes | No | Scatter-gather |
| `HTTP` | Sync/Async | Optional | No | API calls |
| `LOOP` | Iterative | No | No | Batch processing |
| `FIRE_AND_FORGET` | Async | No | No | Background jobs |
| `CRON_SCHEDULE` | Scheduled | No | No | Recurring workflows |
| `HUMAN_IN_LOOP` | Manual | Yes | No | Approvals |

### Provider Implementations

| Provider | PostgreSQL | SQLite | Redis | Memory |
|----------|-----------|--------|-------|--------|
| **Persistence** | ✅ | ✅ | ✅ | ✅ |
| **Execution** | ✅ (PostgresExecutor) | - | ✅ (via Celery) | - |
| **LISTEN/NOTIFY** | ✅ | ❌ | ✅ | - |
| **Production-Ready** | ✅ | ✅ (low concurrency) | ✅ | ❌ |

---

## Navigation

**Tutorials:**
- [Getting Started](../tutorials/getting-started.md)

**How-To Guides:**
- [Write Step Functions](../how-to-guides/write-step-functions.md)
- [Control Flow](../how-to-guides/control-flow.md)
- [Saga Pattern](../how-to-guides/saga-pattern.md)

**Developer Docs:**
- [CLAUDE.md](../../CLAUDE.md) - Complete developer guide

---

## Document Organization

This reference documentation follows the **information-oriented** principle:

- **Dry, factual tone** - No tutorials or explanations
- **Lookup tables** - Structured for quick reference
- **Complete specifications** - All parameters and options
- **Type annotations** - Precise type information
- **Minimal examples** - Code examples are concise and precise

For learning-oriented content, see [Tutorials](../tutorials/).

For task-oriented content, see [How-To Guides](../how-to-guides/).

---

**Last Updated:** 2026-02-13
