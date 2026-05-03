# CLI Commands Reference

## Overview

Complete reference for all Ruvon CLI commands.

**Installation:**

```bash
pip install -e .
ruvon --help
```

---

## Configuration Commands

### `ruvon config show`

Display current configuration.

**Syntax:**

```bash
ruvon config show [--json]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--json` | flag | Output as JSON |

**Example:**

```bash
ruvon config show
ruvon config show --json
```

---

### `ruvon config path`

Show configuration file location.

**Syntax:**

```bash
ruvon config path
```

**Output:** Path to config file (typically `~/.ruvon/config.yaml`)

---

### `ruvon config set-persistence`

Configure persistence provider (interactive).

**Syntax:**

```bash
ruvon config set-persistence
```

**Interactive Prompts:**
1. Select provider (memory, sqlite, postgres)
2. Provider-specific configuration (db path, connection URL, etc.)

**Providers:**

| Provider | Description |
|----------|-------------|
| `memory` | In-memory (testing only, data lost on exit) |
| `sqlite` | SQLite database (development/production) |
| `postgres` | PostgreSQL database (production) |

> **Note:** `redis` is listed in the config schema but is not available in the CLI (raises an error). Use `memory`, `sqlite`, or `postgres`.

---

### `ruvon config set-execution`

Configure execution provider (interactive).

**Syntax:**

```bash
ruvon config set-execution
```

**Interactive Prompts:**
1. Select provider (sync, thread_pool, celery)

**Providers:**

| Provider | Description |
|----------|-------------|
| `sync` | Synchronous execution (single-threaded) |
| `thread_pool` | Thread-based parallel execution |

> **Note:** `celery` is not supported in the CLI (requires ruvon-server and a running broker). Use `sync` or `thread_pool` for local execution.

---

### `ruvon config set-default`

Configure default behaviors (interactive).

**Syntax:**

```bash
ruvon config set-default
```

**Available Defaults:**
- `auto_execute` - Automatically execute next step
- `interactive` - Use interactive mode
- `json_output` - Output as JSON by default

---

### `ruvon config reset`

Reset configuration to defaults.

**Syntax:**

```bash
ruvon config reset [--yes]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--yes` | flag | Skip confirmation prompt |

---

## Workflow Commands

### `ruvon list`

List workflows with optional filtering.

**Syntax:**

```bash
ruvon list [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--status` | string | - | Filter by workflow status |
| `--type` | string | - | Filter by workflow type |
| `--limit` | int | 20 | Maximum results |
| `--verbose`, `-v` | flag | - | Verbose output |
| `--json` | flag | - | JSON output |

**Status Values:**

`ACTIVE`, `PENDING_ASYNC`, `PENDING_SUB_WORKFLOW`, `PAUSED`, `WAITING_HUMAN`, `WAITING_HUMAN_INPUT`, `WAITING_CHILD_HUMAN_INPUT`, `COMPLETED`, `FAILED`, `FAILED_ROLLED_BACK`, `FAILED_CHILD_WORKFLOW`, `CANCELLED`, `FAILED_WORKER_CRASH`

**Examples:**

```bash
ruvon list
ruvon list --status ACTIVE
ruvon list --type OrderProcessing --limit 50
ruvon list --json
```

---

### `ruvon start`

Start a new workflow.

**Syntax:**

```bash
ruvon start <workflow-type> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-type` | string | Yes | Workflow type from registry |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--data`, `-d` | string | Initial data as JSON string |
| `--data-file` | path | Path to JSON file with initial data |
| `--config` | path | Path to workflow YAML file |
| `--auto` | flag | Auto-execute all steps |
| `--interactive`, `-i` | flag | Interactive mode (prompt at HITL steps) |
| `--dry-run` | flag | Validate only, don't execute |

**Examples:**

```bash
ruvon start OrderProcessing --data '{"customer_id": "123"}'
ruvon start OrderProcessing --data-file order.json
ruvon start OrderProcessing --data '{}' --auto
```

---

### `ruvon show`

Show detailed workflow information.

**Syntax:**

```bash
ruvon show <workflow-id> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-id` | UUID | Yes | Workflow identifier |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--state` | flag | Include full state |
| `--logs` | flag | Include execution logs |
| `--metrics` | flag | Include performance metrics |
| `--verbose`, `-v` | flag | Include everything |
| `--json` | flag | JSON output |

**Examples:**

```bash
ruvon show wf_abc123
ruvon show wf_abc123 --state --logs
ruvon show wf_abc123 --verbose --json
```

---

### `ruvon resume`

Resume a paused workflow.

**Syntax:**

```bash
ruvon resume <workflow-id> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-id` | UUID | Yes | Workflow identifier |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--input` | string | Input data as JSON string |
| `--input-file` | path | Path to JSON file with input data |
| `--auto` | flag | Auto-execute remaining steps |

**Examples:**

```bash
ruvon resume wf_abc123 --input '{"approved": true}'
ruvon resume wf_abc123 --input-file approval.json --auto
```

---

### `ruvon retry`

Retry a failed workflow.

**Syntax:**

```bash
ruvon retry <workflow-id> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-id` | UUID | Yes | Workflow identifier |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--from-step` | string | Retry from specific step name |
| `--auto` | flag | Auto-execute remaining steps |

**Examples:**

```bash
ruvon retry wf_abc123
ruvon retry wf_abc123 --from-step Process_Payment --auto
```

---

### `ruvon logs`

View workflow execution logs.

**Syntax:**

```bash
ruvon logs <workflow-id> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-id` | UUID | Yes | Workflow identifier |

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--step` | string | - | Filter by step name |
| `--level` | string | - | Filter by log level |
| `--limit`, `-n` | int | 50 | Maximum log entries |
| `--follow`, `-f` | flag | - | Follow logs *(not yet implemented — shows latest logs only)* |
| `--json` | flag | - | JSON output |

**Log Levels:**

`DEBUG`, `INFO`, `WARNING`, `ERROR`

**Examples:**

```bash
ruvon logs wf_abc123
ruvon logs wf_abc123 --step Process_Payment
ruvon logs wf_abc123 --level ERROR --limit 50
ruvon logs wf_abc123 --json
```

---

### `ruvon metrics`

View workflow performance metrics.

**Syntax:**

```bash
ruvon metrics [OPTIONS]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--workflow-id`, `-w` | UUID | Filter by workflow ID |
| `--type` | string | Filter by workflow type |
| `--summary` | flag | Show summary statistics |
| `--limit` | int | Maximum metric entries |
| `--json` | flag | JSON output |

**Examples:**

```bash
ruvon metrics --workflow-id wf_abc123
ruvon metrics --type OrderProcessing --summary
ruvon metrics --json
```

---

### `ruvon cancel`

Cancel a running workflow.

**Syntax:**

```bash
ruvon cancel <workflow-id> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-id` | UUID | Yes | Workflow identifier |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--reason` | string | Cancellation reason |
| `--force` | flag | Skip confirmation |

**Examples:**

```bash
ruvon cancel wf_abc123
ruvon cancel wf_abc123 --reason "Duplicate order" --force
```

---

### `ruvon interactive run`

Run a workflow interactively, pausing at each Human-in-the-Loop step to collect user input via terminal prompts.

**Syntax:**

```bash
ruvon interactive run <workflow-type> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `workflow-type` | string | Yes | Workflow type from registry |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--data`, `-d` | string | Initial workflow data as JSON string |
| `--data-file` | path | Initial workflow data from JSON file |
| `--config` | path | Workflow YAML config file |

**Examples:**

```bash
ruvon interactive run OrderProcessing --config workflows/order.yaml
ruvon interactive run Approval --data '{"request_id": "123"}'
```

**Behavior:**
- Auto-executes STANDARD steps without prompting
- Pauses at `WAITING_HUMAN` steps and collects field-by-field input
- Displays step names, status, and progress as the workflow advances

---

## Database Commands

### `ruvon db init`

Initialize database schema.

**Syntax:**

```bash
ruvon db init [--db-url <url>]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--db-url` | string | Override database URL |

**Examples:**

```bash
ruvon db init
ruvon db init --db-url sqlite:///workflows.db
ruvon db init --db-url postgresql://user:pass@localhost/ruvon
```

**Behavior:**
- Creates all required tables
- Applies all migrations
- Idempotent (safe to run multiple times)

---

### `ruvon db migrate`

Apply pending database migrations.

**Syntax:**

```bash
ruvon db migrate [OPTIONS]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--dry-run` | flag | Preview migrations without applying |
| `--db-url` | string | Override database URL |

**Examples:**

```bash
ruvon db migrate
ruvon db migrate --dry-run
ruvon db migrate --db-url postgresql://user:pass@localhost/ruvon
```

---

### `ruvon db status`

Show database migration status.

**Syntax:**

```bash
ruvon db status [--db-url <url>]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--db-url` | string | Override database URL |

**Example:**

```bash
ruvon db status
```

---

### `ruvon db stats`

Show database statistics.

**Syntax:**

```bash
ruvon db stats [--db-url <url>]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--db-url` | string | Override database URL |

**Example:**

```bash
ruvon db stats
```

**Output:**
- Database type and path
- Database size
- Table row counts

---

### `ruvon db validate`

Validate database schema.

**Syntax:**

```bash
ruvon db validate
```

**Validates:**
- All required tables exist
- Column types match schema
- Indexes exist
- Triggers exist (SQLite)

---

## Zombie Workflow Commands

### `ruvon scan-zombies`

Scan for zombie workflows (stale heartbeats).

**Syntax:**

```bash
ruvon scan-zombies [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | string | - | Database URL |
| `--fix` | flag | - | Recover zombie workflows |
| `--threshold` | int | 120 | Stale threshold in seconds |
| `--json` | flag | - | JSON output |

**Examples:**

```bash
ruvon scan-zombies --db postgresql://localhost/ruvon
ruvon scan-zombies --db sqlite:///workflows.db --fix
ruvon scan-zombies --db postgresql://localhost/ruvon --threshold 180 --json
```

---

### `ruvon zombie-daemon`

Run zombie scanner as continuous daemon.

**Syntax:**

```bash
ruvon zombie-daemon [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | string | - | Database URL |
| `--interval` | int | 60 | Scan interval in seconds |
| `--threshold` | int | 120 | Stale threshold in seconds |

**Example:**

```bash
ruvon zombie-daemon --db postgresql://localhost/ruvon --interval 60
```

---

## Legacy Commands

### `ruvon validate`

Validate workflow YAML syntax and structure.

**Syntax:**

```bash
ruvon validate <yaml-file> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `yaml-file` | path | Yes | Path to workflow YAML file |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--strict` | flag | Also validate function imports and state model |
| `--json` | flag | Output results as JSON |
| `--graph` | flag | Generate step dependency graph |
| `--graph-format` | string | Graph format: `mermaid` (default), `dot`, or `text` |

**Examples:**

```bash
ruvon validate config/my_workflow.yaml
ruvon validate config/my_workflow.yaml --strict
ruvon validate config/my_workflow.yaml --graph
ruvon validate config/my_workflow.yaml --graph --graph-format dot
ruvon validate config/my_workflow.yaml --json
```

---

### `ruvon run`

Run workflow locally (in-memory, synchronous).

**Syntax:**

```bash
ruvon run <yaml-file> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `yaml-file` | path | Yes | Path to workflow YAML file |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--data`, `-d` | string | Initial data as JSON string |

**Example:**

```bash
ruvon run config/my_workflow.yaml --data '{"user_id": "123"}'
```

**Behavior:**
- Uses in-memory persistence
- Synchronous execution
- Auto-executes all steps
- Data not saved to database

---

## Global Options

Available for all commands:

| Option | Description |
|--------|-------------|
| `--help` | Show command help |
| `--version` | Show Ruvon version |

**Example:**

```bash
ruvon --help
ruvon --version
ruvon config --help
ruvon logs --help
```

---

## Environment Variables

Override CLI behavior with environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `RUVON_CONFIG_PATH` | Config file location | `~/.ruvon/config.yaml` |
| `RUVON_DB_URL` | Database URL override | From config |
| `NO_COLOR` | Disable colored output | - |

**Example:**

```bash
export RUVON_CONFIG_PATH=/custom/config.yaml
export RUVON_DB_URL=postgresql://localhost/ruvon
export NO_COLOR=1

ruvon list
```

---

## Exit Codes

| Code | Description |
|------|-------------|
| `0` | Success |
| `1` | General error |
| `2` | Invalid arguments |
| `3` | Database error |
| `4` | Workflow not found |

---

## See Also

- [YAML Schema](yaml-schema.md)
- [Database Schema](database-schema.md)
- [Configuration](configuration.md)
