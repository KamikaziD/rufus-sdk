# CLI Commands Reference

## Overview

Complete reference for all Rufus CLI commands.

**Installation:**

```bash
pip install -e .
rufus --help
```

---

## Configuration Commands

### `rufus config show`

Display current configuration.

**Syntax:**

```bash
rufus config show [--json]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--json` | flag | Output as JSON |

**Example:**

```bash
rufus config show
rufus config show --json
```

---

### `rufus config path`

Show configuration file location.

**Syntax:**

```bash
rufus config path
```

**Output:** Path to config file (typically `~/.rufus/config.yaml`)

---

### `rufus config set-persistence`

Configure persistence provider (interactive).

**Syntax:**

```bash
rufus config set-persistence
```

**Interactive Prompts:**
1. Select provider (memory, sqlite, postgres, redis)
2. Provider-specific configuration (db path, connection URL, etc.)

**Providers:**

| Provider | Description |
|----------|-------------|
| `memory` | In-memory (testing only, data lost on exit) |
| `sqlite` | SQLite database (development/production) |
| `postgres` | PostgreSQL database (production) |
| `redis` | Redis-based persistence |

---

### `rufus config set-execution`

Configure execution provider (interactive).

**Syntax:**

```bash
rufus config set-execution
```

**Interactive Prompts:**
1. Select provider (sync, thread_pool, celery)

**Providers:**

| Provider | Description |
|----------|-------------|
| `sync` | Synchronous execution (single-threaded) |
| `thread_pool` | Thread-based parallel execution |
| `celery` | Distributed Celery execution |

---

### `rufus config set-default`

Configure default behaviors (interactive).

**Syntax:**

```bash
rufus config set-default
```

**Available Defaults:**
- `auto_execute` - Automatically execute next step
- `interactive` - Use interactive mode
- `json_output` - Output as JSON by default

---

### `rufus config reset`

Reset configuration to defaults.

**Syntax:**

```bash
rufus config reset [--yes]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--yes` | flag | Skip confirmation prompt |

---

## Workflow Commands

### `rufus list`

List workflows with optional filtering.

**Syntax:**

```bash
rufus list [OPTIONS]
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
rufus list
rufus list --status ACTIVE
rufus list --type OrderProcessing --limit 50
rufus list --json
```

---

### `rufus start`

Start a new workflow.

**Syntax:**

```bash
rufus start <workflow-type> [OPTIONS]
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
| `--dry-run` | flag | Validate only, don't execute |

**Examples:**

```bash
rufus start OrderProcessing --data '{"customer_id": "123"}'
rufus start OrderProcessing --data-file order.json
rufus start OrderProcessing --data '{}' --auto
```

---

### `rufus show`

Show detailed workflow information.

**Syntax:**

```bash
rufus show <workflow-id> [OPTIONS]
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
rufus show wf_abc123
rufus show wf_abc123 --state --logs
rufus show wf_abc123 --verbose --json
```

---

### `rufus resume`

Resume a paused workflow.

**Syntax:**

```bash
rufus resume <workflow-id> [OPTIONS]
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
rufus resume wf_abc123 --input '{"approved": true}'
rufus resume wf_abc123 --input-file approval.json --auto
```

---

### `rufus retry`

Retry a failed workflow.

**Syntax:**

```bash
rufus retry <workflow-id> [OPTIONS]
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
rufus retry wf_abc123
rufus retry wf_abc123 --from-step Process_Payment --auto
```

---

### `rufus logs`

View workflow execution logs.

**Syntax:**

```bash
rufus logs <workflow-id> [OPTIONS]
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
| `--limit`, `-n` | int | 100 | Maximum log entries |
| `--follow`, `-f` | flag | - | Follow logs (real-time) |
| `--json` | flag | - | JSON output |

**Log Levels:**

`DEBUG`, `INFO`, `WARNING`, `ERROR`

**Examples:**

```bash
rufus logs wf_abc123
rufus logs wf_abc123 --step Process_Payment
rufus logs wf_abc123 --level ERROR --limit 50
rufus logs wf_abc123 --json
```

---

### `rufus metrics`

View workflow performance metrics.

**Syntax:**

```bash
rufus metrics [OPTIONS]
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
rufus metrics --workflow-id wf_abc123
rufus metrics --type OrderProcessing --summary
rufus metrics --json
```

---

### `rufus cancel`

Cancel a running workflow.

**Syntax:**

```bash
rufus cancel <workflow-id> [OPTIONS]
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
rufus cancel wf_abc123
rufus cancel wf_abc123 --reason "Duplicate order" --force
```

---

## Database Commands

### `rufus db init`

Initialize database schema.

**Syntax:**

```bash
rufus db init [--db-url <url>]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--db-url` | string | Override database URL |

**Examples:**

```bash
rufus db init
rufus db init --db-url sqlite:///workflows.db
rufus db init --db-url postgresql://user:pass@localhost/rufus
```

**Behavior:**
- Creates all required tables
- Applies all migrations
- Idempotent (safe to run multiple times)

---

### `rufus db migrate`

Apply pending database migrations.

**Syntax:**

```bash
rufus db migrate [OPTIONS]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--dry-run` | flag | Preview migrations without applying |
| `--db-url` | string | Override database URL |

**Examples:**

```bash
rufus db migrate
rufus db migrate --dry-run
rufus db migrate --db-url postgresql://user:pass@localhost/rufus
```

---

### `rufus db status`

Show database migration status.

**Syntax:**

```bash
rufus db status [--db-url <url>]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--db-url` | string | Override database URL |

**Example:**

```bash
rufus db status
```

---

### `rufus db stats`

Show database statistics.

**Syntax:**

```bash
rufus db stats [--db-url <url>]
```

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--db-url` | string | Override database URL |

**Example:**

```bash
rufus db stats
```

**Output:**
- Database type and path
- Database size
- Table row counts

---

### `rufus db validate`

Validate database schema.

**Syntax:**

```bash
rufus db validate
```

**Validates:**
- All required tables exist
- Column types match schema
- Indexes exist
- Triggers exist (SQLite)

---

## Zombie Workflow Commands

### `rufus scan-zombies`

Scan for zombie workflows (stale heartbeats).

**Syntax:**

```bash
rufus scan-zombies [OPTIONS]
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
rufus scan-zombies --db postgresql://localhost/rufus
rufus scan-zombies --db sqlite:///workflows.db --fix
rufus scan-zombies --db postgresql://localhost/rufus --threshold 180 --json
```

---

### `rufus zombie-daemon`

Run zombie scanner as continuous daemon.

**Syntax:**

```bash
rufus zombie-daemon [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | string | - | Database URL |
| `--interval` | int | 60 | Scan interval in seconds |
| `--threshold` | int | 120 | Stale threshold in seconds |

**Example:**

```bash
rufus zombie-daemon --db postgresql://localhost/rufus --interval 60
```

---

## Legacy Commands

### `rufus validate`

Validate workflow YAML syntax.

**Syntax:**

```bash
rufus validate <yaml-file>
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `yaml-file` | path | Yes | Path to workflow YAML file |

**Example:**

```bash
rufus validate config/my_workflow.yaml
```

---

### `rufus run`

Run workflow locally (in-memory, synchronous).

**Syntax:**

```bash
rufus run <yaml-file> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `yaml-file` | path | Yes | Path to workflow YAML file |

**Options:**

| Option | Type | Description |
|--------|------|-------------|
| `--data`, `-d` | string | Initial data as JSON string |
| `--registry` | path | Custom registry file path |

**Example:**

```bash
rufus run config/my_workflow.yaml --data '{"user_id": "123"}'
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
| `--version` | Show Rufus version |

**Example:**

```bash
rufus --help
rufus --version
rufus config --help
rufus logs --help
```

---

## Environment Variables

Override CLI behavior with environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `RUFUS_CONFIG_PATH` | Config file location | `~/.rufus/config.yaml` |
| `RUFUS_DB_URL` | Database URL override | From config |
| `NO_COLOR` | Disable colored output | - |

**Example:**

```bash
export RUFUS_CONFIG_PATH=/custom/config.yaml
export RUFUS_DB_URL=postgresql://localhost/rufus
export NO_COLOR=1

rufus list
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
