# Ruvon CLI Usage Guide

Complete guide to using the Ruvon command-line interface for workflow orchestration, database management, and monitoring.

## Table of Contents

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Configuration Commands](#configuration-commands)
5. [Workflow Management](#workflow-management)
6. [Database Management](#database-management)
7. [Advanced Monitoring](#advanced-monitoring)
8. [Legacy Commands](#legacy-commands)
9. [Common Workflows](#common-workflows)
10. [Troubleshooting](#troubleshooting)

---

## Introduction

The Ruvon CLI provides a comprehensive command-line interface for managing workflows, databases, and monitoring your Ruvon workflow orchestration system. It features:

- **21 commands** across 4 categories
- **Beautiful terminal output** with color-coded tables
- **Interactive configuration** wizards
- **Multi-database support** (SQLite, PostgreSQL)
- **Advanced monitoring** (logs, metrics, cancellation)

### Command Structure

```
ruvon <command> [subcommand] [options] [arguments]
```

**Command Groups:**
- `ruvon config` - Configuration management
- `ruvon workflow` - Workflow operations
- `ruvon db` - Database management

**Top-level Aliases:**
- `ruvon list`, `ruvon start`, `ruvon show`, etc. (shortcuts to workflow commands)

---

## Installation

### Requirements
- Python 3.9+
- pip or poetry

### Install from Source

```bash
# Clone repository
git clone https://github.com/your-org/ruvon-sdk.git
cd ruvon-sdk

# Install with pip
pip install -e .

# Or with poetry
poetry install

# Verify installation
ruvon --help
```

### Install from PyPI (when published)

```bash
pip install ruvon-sdk
```

---

## Quick Start

### 1. Configure Persistence

```bash
# Interactive configuration
ruvon config set-persistence

# Choose SQLite for development
# Select: 2 (sqlite)
# Path: ./workflows.db

# Verify configuration
ruvon config show
```

### 2. Initialize Database

```bash
# Create database schema
ruvon db init

# Verify database
ruvon db stats
```

### 3. Start a Workflow

```bash
# Start a workflow (requires workflow definition)
ruvon start MyWorkflow --data '{"user_id": "123"}'

# List all workflows
ruvon list

# View workflow details
ruvon show <workflow-id>
```

---

## Configuration Commands

Manage persistent CLI configuration stored at `~/.ruvon/config.yaml`.

### `ruvon config show`

Display current configuration.

```bash
ruvon config show

# Output as JSON
ruvon config show --json
```

**Example Output:**
```json
{
  "version": "1.0",
  "persistence": {
    "provider": "sqlite",
    "sqlite": {
      "db_path": "./workflows.db"
    }
  },
  "execution": {
    "provider": "sync"
  }
}
```

### `ruvon config path`

Show configuration file location.

```bash
ruvon config path

# Output:
# ~/.ruvon/config.yaml
```

### `ruvon config set-persistence`

Configure persistence provider (interactive).

```bash
ruvon config set-persistence
```

**Interactive Prompts:**
```
Available persistence providers:
  1. memory - In-memory (testing only)
  2. sqlite - SQLite database (development/production)
  3. postgres - PostgreSQL database (production)

Select provider (1-3): 2

Database path [~/.ruvon/workflows.db]: ./workflows.db

✅ Persistence provider set to: sqlite
ℹ️  Database path: ./workflows.db
```

**Providers:**
- **memory** - In-memory storage (data lost on restart)
- **sqlite** - SQLite file-based database
- **postgres** - PostgreSQL database (requires connection URL)

### `ruvon config set-execution`

Configure execution provider (interactive).

```bash
ruvon config set-execution
```

**Interactive Prompts:**
```
Available execution providers:
  1. sync - Synchronous execution (simple, single-threaded)
  2. thread_pool - Thread-based parallel execution

Select provider (1-2): 1

✅ Execution provider set to: sync
```

**Providers:**
- **sync** - Synchronous, single-threaded execution
- **thread_pool** - Thread-based parallel execution
- **celery** - Distributed execution (requires Celery setup)

### `ruvon config set-default`

Configure default behaviors (interactive).

```bash
ruvon config set-default
```

**Interactive Prompts:**
```
Available defaults:
  1. auto_execute - Automatically execute next step
  2. interactive - Use interactive mode
  3. json_output - Output as JSON by default

Select default to configure (1-3): 2
Enable interactive? [y/N]: y

✅ Default 'interactive' set to: True
```

### `ruvon config reset`

Reset configuration to defaults.

```bash
# With confirmation
ruvon config reset

# Skip confirmation
ruvon config reset --yes
```

---

## Workflow Management

Manage workflow lifecycle: list, start, monitor, resume, retry.

### `ruvon list`

List workflows with optional filtering.

```bash
# List all workflows (default: 20)
ruvon list

# Filter by status
ruvon list --status ACTIVE
ruvon list --status COMPLETED
ruvon list --status FAILED

# Filter by workflow type
ruvon list --type OrderProcessing

# Increase limit
ruvon list --limit 100

# Verbose output (more details)
ruvon list --verbose

# JSON output
ruvon list --json

# Combine filters
ruvon list --status ACTIVE --type OrderProcessing --limit 50
```

**Example Output:**
```
╭─ Workflows ─────────────────────────────────────────────────────────╮
│ Workflow ID  │ Type              │ Status  │ Current Step      │ ... │
├──────────────┼───────────────────┼─────────┼───────────────────┼─────┤
│ wf_abc123    │ OrderProcessing   │ ACTIVE  │ Process_Payment   │ ... │
│ wf_def456    │ OrderProcessing   │ PAUSED  │ Approval_Step     │ ... │
│ wf_ghi789    │ DataPipeline      │ COMPLETED│ Finalize         │ ... │
╰──────────────┴───────────────────┴─────────┴───────────────────┴─────╯
```

**Status Values:**
- **ACTIVE** - Currently running
- **PENDING_ASYNC** - Waiting for async task
- **PENDING_SUB_WORKFLOW** - Waiting for sub-workflow
- **PAUSED** - Paused, waiting for resume
- **WAITING_HUMAN** - Waiting for human input
- **WAITING_HUMAN_INPUT** - Waiting for user input
- **WAITING_CHILD_HUMAN_INPUT** - Child workflow waiting for input
- **COMPLETED** - Successfully finished
- **FAILED** - Failed with error
- **FAILED_ROLLED_BACK** - Failed and rolled back (Saga)
- **FAILED_CHILD_WORKFLOW** - Child workflow failed
- **CANCELLED** - Manually cancelled

### `ruvon start`

Start a new workflow.

```bash
# Start workflow with inline JSON data
ruvon start OrderProcessing --data '{"customer_id": "123", "amount": 99.99}'

# Start workflow from JSON file
ruvon start OrderProcessing --data-file order.json

# Specify workflow config file
ruvon start OrderProcessing --config config/order_workflow.yaml --data '{}'

# Auto-execute all steps (non-interactive)
ruvon start OrderProcessing --data '{}' --auto

# Dry run (validate only, don't execute)
ruvon start OrderProcessing --data '{}' --dry-run
```

**Example Output:**
```
✅ Workflow started successfully

Workflow ID: wf_abc123def456
Status: ACTIVE
Current Step: Validate_Order

Next steps:
  • View details: ruvon show wf_abc123def456
  • Resume: ruvon resume wf_abc123def456
```

**Data Format:**
- Must be valid JSON
- Keys match workflow's initial state model
- Use `--data-file` for complex data

### `ruvon show`

Show detailed workflow information.

```bash
# Basic workflow info
ruvon show <workflow-id>

# Include full state
ruvon show <workflow-id> --state

# Include execution logs
ruvon show <workflow-id> --logs

# Include metrics
ruvon show <workflow-id> --metrics

# Show everything
ruvon show <workflow-id> --verbose

# JSON output
ruvon show <workflow-id> --json
```

**Example Output:**
```
╭─ Workflow Details: wf_abc123 ────────────────────────────────────╮
│                                                                   │
│ Workflow ID:    wf_abc123def456                                   │
│ Type:           OrderProcessing                                   │
│ Status:         ACTIVE                                            │
│ Current Step:   Process_Payment (step 2/5)                        │
│ Created:        2026-01-24 10:30:15                               │
│ Updated:        2026-01-24 10:31:42                               │
│                                                                   │
│ State Summary:                                                    │
│   customer_id: "123"                                              │
│   order_total: 99.99                                              │
│   status: "processing"                                            │
│                                                                   │
╰───────────────────────────────────────────────────────────────────╯
```

### `ruvon resume`

Resume a paused workflow.

```bash
# Resume workflow (interactive prompts for input if needed)
ruvon resume <workflow-id>

# Provide input as JSON
ruvon resume <workflow-id> --input '{"approved": true}'

# Provide input from file
ruvon resume <workflow-id> --input-file approval.json

# Auto-execute remaining steps
ruvon resume <workflow-id> --auto
```

**Note:** Resume/retry are partially implemented. Full workflow reconstruction coming in future release.

### `ruvon retry`

Retry a failed workflow.

```bash
# Retry from beginning
ruvon retry <workflow-id>

# Retry from specific step
ruvon retry <workflow-id> --from-step Process_Payment

# Auto-execute remaining steps
ruvon retry <workflow-id> --auto
```

---

## Database Management

Initialize, migrate, and monitor your Ruvon database.

### `ruvon db init`

Initialize database schema by applying all migrations.

```bash
# Initialize using configured database
ruvon db init

# Initialize specific database
ruvon db init --db-url sqlite:///path/to/db.sqlite
ruvon db init --db-url postgresql://user:pass@localhost/ruvon
```

**How It Works:**
- Uses **migration files** as single source of truth (`migrations/*.sql`)
- Creates `schema_migrations` table to track applied versions
- Applies all pending migrations in order
- Idempotent - safe to run multiple times

**What it creates:**
- All required tables (workflow_executions, tasks, logs, metrics, heartbeats, etc.)
- Performance indexes for query optimization
- Triggers for automatic timestamps
- Foreign key constraints (enforced)
- WAL mode enabled (SQLite only)

**Tables Created:**
- `workflow_executions` - Core workflow state and metadata
- `workflow_heartbeats` - Worker health tracking for zombie detection
- `tasks` - Distributed task queue
- `compensation_log` - Saga pattern rollback actions
- `workflow_audit_log` - Complete audit trail
- `workflow_execution_logs` - Debug and monitoring logs
- `workflow_metrics` - Performance analytics
- `schema_migrations` - Migration version tracking

**SQLite Auto-Init:**
For development convenience, SQLite databases automatically initialize on first use:
```python
# Schema automatically created via migrations
persistence = SQLitePersistenceProvider(db_path="workflows.db", auto_init=True)
await persistence.initialize()  # Creates schema if missing
```

**Note:** Both `ruvon db init` and SQLite auto-init use the same migration files, ensuring schema consistency.

### `ruvon db migrate`

Apply pending database migrations.

```bash
# Apply all pending migrations
ruvon db migrate

# Dry run (show pending migrations without applying)
ruvon db migrate --dry-run

# Use specific database
ruvon db migrate --db-url postgresql://user:pass@localhost/ruvon
```

**Example Output:**
```
ℹ️  Using database from config
Applying pending migrations...

▶ Applying migration 001: initial_schema
  ✓ Successfully applied migration 001

▶ Applying migration 002: add_metrics_table
  ✓ Successfully applied migration 002

✅ Migrations applied successfully
```

### `ruvon db status`

Show database migration status.

```bash
# Show migration status for configured database
ruvon db status

# Show status for specific database
ruvon db status --db-url sqlite:///workflows.db
```

**Example Output:**
```
Database Migration Status

Database type: SQLite

Applied migrations: 2
  ✓ 001
  ✓ 002

Pending migrations: 0
  Database is up to date
```

### `ruvon db stats`

Show database statistics.

```bash
# Show statistics for configured database
ruvon db stats

# Show stats for specific database
ruvon db stats --db-url sqlite:///workflows.db
```

**Example Output:**
```
Database Statistics

Type: SQLite
Path: /tmp/workflows.db
Size: 94,208 bytes (92.00 KB)

Table Statistics:
  workflow_executions: 15 rows
  workflow_execution_logs: 143 rows
  workflow_metrics: 87 rows

✅ Stats retrieved successfully
```

### `ruvon db validate`

Validate database schema against definition.

```bash
# Validate schema
ruvon db validate
```

**What it validates:**
- Schema matches `migrations/schema.yaml` definition
- All tables present
- All columns present with correct types
- Indexes exist
- Triggers exist (SQLite)

---

## Advanced Monitoring

View logs, metrics, and manage running workflows.

### `ruvon logs`

View workflow execution logs.

```bash
# View logs for a workflow
ruvon logs <workflow-id>

# Filter by step
ruvon logs <workflow-id> --step Process_Payment

# Filter by log level
ruvon logs <workflow-id> --level ERROR
ruvon logs <workflow-id> --level WARNING

# Limit number of logs
ruvon logs <workflow-id> --limit 100
ruvon logs <workflow-id> -n 100

# Follow logs (real-time, coming soon)
ruvon logs <workflow-id> --follow
ruvon logs <workflow-id> -f

# JSON output
ruvon logs <workflow-id> --json
```

**Example Output:**
```
╭─ Workflow Logs: wf_abc123 ───────────────────────────────────────╮
│ Time     │ Level   │ Step              │ Message                 │
├──────────┼─────────┼───────────────────┼─────────────────────────┤
│ 10:30:15 │ INFO    │ Validate_Order    │ Order validation...     │
│ 10:30:16 │ INFO    │ Validate_Order    │ Validation successful   │
│ 10:30:17 │ WARNING │ Process_Payment   │ Retry attempt 1/3       │
│ 10:30:20 │ INFO    │ Process_Payment   │ Payment processed       │
╰──────────┴─────────┴───────────────────┴─────────────────────────╯

Showing 4 log entries
```

**Log Levels:**
- **DEBUG** - Detailed debugging information
- **INFO** - General information (default)
- **WARNING** - Warning messages
- **ERROR** - Error messages

### `ruvon metrics`

View workflow performance metrics.

```bash
# View metrics for specific workflow
ruvon metrics --workflow-id <id>
ruvon metrics -w <id>

# View metrics by workflow type
ruvon metrics --type OrderProcessing

# Show summary statistics
ruvon metrics --workflow-id <id> --summary

# Limit results
ruvon metrics --limit 100

# JSON output
ruvon metrics --json

# Combine filters
ruvon metrics --type OrderProcessing --summary --limit 50
```

**Example Output:**
```
╭─ Workflow Metrics: OrderProcessing ──────────────────────────────╮
│ Time     │ Workflow    │ Step            │ Metric       │ Value │
├──────────┼─────────────┼─────────────────┼──────────────┼───────┤
│ 10:30:15 │ wf_abc123.. │ Validate_Order  │ duration_ms  │ 45.30 │
│ 10:30:17 │ wf_abc123.. │ Process_Payment │ duration_ms  │ 1250  │
│ 10:30:20 │ wf_abc123.. │ Send_Email      │ duration_ms  │ 320.5 │
╰──────────┴─────────────┴─────────────────┴──────────────┴───────╯

Showing 3 metrics

Summary:
  Total metrics: 3
  Unique steps: 3
```

**Common Metrics:**
- **duration_ms** - Step execution time in milliseconds
- **retry_count** - Number of retries
- **memory_mb** - Memory usage in megabytes
- **custom metrics** - Application-defined metrics

### `ruvon cancel`

Cancel a running workflow.

```bash
# Cancel workflow (with confirmation)
ruvon cancel <workflow-id>

# Cancel with reason
ruvon cancel <workflow-id> --reason "Duplicate order detected"

# Force cancel (skip compensation/rollback)
ruvon cancel <workflow-id> --force
```

**Example Interactive Session:**
```
🛑 Cancelling workflow: wf_abc123def456

Cancel workflow wf_abc123def456?
Current status: ACTIVE
This action may trigger compensation if saga mode is enabled.
[y/N]: y

✅ Workflow cancelled successfully
Previous status: ACTIVE
New status: CANCELLED
```

**Behavior:**
- **Validates state:** Cannot cancel already-completed workflows
- **Interactive confirmation:** Prompts for confirmation (unless `--force`)
- **Saga awareness:** Warns if saga mode enabled
- **Audit logging:** Logs cancellation with reason
- **Status update:** Sets status to CANCELLED

---

## Legacy Commands

Preserved commands from original CLI for backward compatibility.

### `ruvon validate`

Validate workflow YAML syntax.

```bash
# Validate workflow file
ruvon validate config/my_workflow.yaml

# Validates:
# - YAML syntax
# - Required fields (workflow_type, steps)
# - Step structure
# - Basic schema
```

**Example Output:**
```
✅ Successfully validated config/my_workflow.yaml (syntax and basic structure passed)
```

### `ruvon run`

Run workflow locally (in-memory, synchronous).

```bash
# Run workflow with initial data
ruvon run config/my_workflow.yaml --data '{"user_id": "123"}'

# Short form
ruvon run config/my_workflow.yaml -d '{}'
```

**What it does:**
- Uses in-memory persistence (data not saved)
- Synchronous execution (single-threaded)
- Auto-executes all steps
- Good for testing and development

**Example Output:**
```
Running workflow from config/my_workflow.yaml with initial data: {"user_id": "123"}

Workflow ID: temp_abc123
Initial Status: ACTIVE
Initial State: {"user_id": "123"}

--- Current Step: Validate_Input (ACTIVE) ---
Current State: {"user_id": "123", "validated": true}
Step Result: {"validated": true}

--- Workflow Finished (COMPLETED) ---
Final State: {"user_id": "123", "validated": true, "result": "success"}

✅ Successfully completed workflow temp_abc123
```

---

## Common Workflows

### Development Workflow

```bash
# 1. Setup
ruvon config set-persistence  # Choose SQLite
ruvon db init

# 2. Validate workflow definition
ruvon validate config/my_workflow.yaml

# 3. Test locally (in-memory)
ruvon run config/my_workflow.yaml --data '{}'

# 4. Start with persistence
ruvon start MyWorkflow --data '{}'

# 5. Monitor
ruvon list --status ACTIVE
ruvon logs <workflow-id>

# 6. View results
ruvon show <workflow-id> --state
```

### Production Workflow

```bash
# 1. Setup PostgreSQL
ruvon config set-persistence  # Choose PostgreSQL
# Enter connection URL: postgresql://user:pass@prod-db:5432/ruvon

# 2. Initialize/migrate database
ruvon db init
ruvon db migrate

# 3. Verify setup
ruvon db status
ruvon db stats

# 4. Start workflows (via API or CLI)
ruvon start OrderProcessing --data @order.json

# 5. Monitor production
ruvon list --status ACTIVE --limit 100
ruvon metrics --type OrderProcessing --summary

# 6. Troubleshoot issues
ruvon logs <workflow-id> --level ERROR
ruvon show <workflow-id> --verbose

# 7. Cancel if needed
ruvon cancel <workflow-id> --reason "Customer cancelled order"
```

### Testing Workflow

```bash
# Use in-memory for unit tests
ruvon config set-persistence  # Choose memory

# Validate workflow definitions
ruvon validate config/*.yaml

# Run tests with in-memory execution
ruvon run config/test_workflow.yaml --data @test_data.json

# Check results (data lost after process ends)
```

### Migration Workflow

```bash
# From old CLI to new CLI

# 1. Check existing setup
ruvon config show

# 2. Backup database (if using SQLite)
cp ~/.ruvon/workflows.db ~/.ruvon/workflows.db.backup

# 3. Run migrations (if needed)
ruvon db migrate --dry-run  # Check first
ruvon db migrate            # Apply

# 4. Verify schema
ruvon db validate
ruvon db stats

# 5. Test with existing workflows
ruvon list
ruvon show <existing-workflow-id>
```

---

## Troubleshooting

### Configuration Issues

**Problem:** Configuration not persisting
```bash
# Check config file location
ruvon config path

# Check file exists and is writable
ls -la ~/.ruvon/config.yaml

# Reset if corrupted
ruvon config reset --yes
```

**Problem:** Database connection errors
```bash
# Verify database URL
ruvon config show

# Test connection
ruvon db stats

# Reinitialize if needed
ruvon db init --db-url sqlite:///new_path.db
```

### Database Issues

**Problem:** "Table not found" errors
```bash
# Initialize database
ruvon db init

# Verify tables exist
ruvon db stats

# Check migration status
ruvon db status
```

**Problem:** Migration failures
```bash
# Check pending migrations
ruvon db migrate --dry-run

# Verify schema
ruvon db validate

# Check database permissions
# (PostgreSQL) GRANT ALL ON DATABASE ruvon TO user;
```

**Problem:** SQLite database locked
```bash
# Close other connections
# Increase timeout in config

# Check WAL mode enabled
sqlite3 workflows.db "PRAGMA journal_mode;"
# Should return: wal
```

### Workflow Issues

**Problem:** Workflow not starting
```bash
# Validate workflow definition
ruvon validate config/workflow.yaml

# Check initial data format
echo '{"valid": "json"}' | jq .

# Try dry run
ruvon start MyWorkflow --data '{}' --dry-run

# Check logs
ruvon logs <workflow-id> --level ERROR
```

**Problem:** Workflow stuck/not progressing
```bash
# Check status
ruvon show <workflow-id>

# View logs for errors
ruvon logs <workflow-id> --level ERROR

# Check if waiting for input
ruvon show <workflow-id> --state

# Resume if paused
ruvon resume <workflow-id> --input '{}'

# Cancel if needed
ruvon cancel <workflow-id> --reason "Debugging"
```

**Problem:** Cannot view logs/metrics
```bash
# Verify workflow exists
ruvon show <workflow-id>

# Check database has logs table
ruvon db stats

# Reinitialize database if needed
ruvon db init
```

### CLI Issues

**Problem:** Command not found
```bash
# Verify installation
which ruvon
ruvon --version

# Reinstall
pip install -e . --force-reinstall
```

**Problem:** Import errors
```bash
# Check Python version
python --version  # Should be 3.9+

# Check dependencies
pip install typer>=0.21 rich>=14.0

# Reinstall package
pip install -e .
```

**Problem:** Formatting issues (garbled output)
```bash
# Update rich library
pip install --upgrade rich

# Use JSON output as fallback
ruvon list --json

# Check terminal supports colors
echo $TERM
```

### Getting Help

**View help for any command:**
```bash
ruvon --help
ruvon config --help
ruvon workflow --help
ruvon logs --help
```

**Check version:**
```bash
ruvon --version
```

**Report issues:**
- GitHub: https://github.com/your-org/ruvon-sdk/issues
- Include output of: `ruvon config show` and `ruvon db status`

---

## Tips and Best Practices

### Configuration

1. **Use SQLite for development**, PostgreSQL for production
2. **Store config in version control** (without sensitive data)
3. **Use environment variables** for production secrets
4. **Back up SQLite databases** regularly

### Workflows

1. **Always validate** workflow definitions before deploying
2. **Test with `ruvon run`** before using persistence
3. **Use meaningful workflow IDs** in logs
4. **Add comprehensive logging** in step functions
5. **Monitor metrics** for performance tracking

### Database

1. **Initialize database** before first workflow
2. **Run migrations** in maintenance windows
3. **Monitor database size** with `ruvon db stats`
4. **Validate schema** after upgrades
5. **Back up before migrations** (production)

### Monitoring

1. **Use filters** to find specific logs/metrics
2. **Export to JSON** for analysis: `ruvon logs <id> --json > logs.json`
3. **Set up alerts** based on ERROR logs
4. **Track metrics** over time for trends
5. **Cancel stuck workflows** promptly

### Performance

1. **Limit query results** with `--limit` for large datasets
2. **Use indexes** (already configured in schema)
3. **Clean up old workflows** periodically
4. **Monitor database size** and optimize as needed
5. **Use async execution** (thread_pool/celery) for high throughput

---

## Appendix

### All Commands Reference

**Configuration:**
- `ruvon config show` - Show configuration
- `ruvon config path` - Show config file path
- `ruvon config set-persistence` - Set persistence provider
- `ruvon config set-execution` - Set execution provider
- `ruvon config set-default` - Set default behaviors
- `ruvon config reset` - Reset to defaults

**Workflows:**
- `ruvon list` - List workflows
- `ruvon start` - Start workflow
- `ruvon show` - Show workflow details
- `ruvon resume` - Resume paused workflow
- `ruvon retry` - Retry failed workflow
- `ruvon logs` - View execution logs
- `ruvon metrics` - View performance metrics
- `ruvon cancel` - Cancel running workflow

**Database:**
- `ruvon db init` - Initialize schema
- `ruvon db migrate` - Apply migrations
- `ruvon db status` - Show migration status
- `ruvon db stats` - Show database statistics
- `ruvon db validate` - Validate schema

**Legacy:**
- `ruvon validate` - Validate workflow YAML
- `ruvon run` - Run workflow locally

### Environment Variables

```bash
# Override config file location
export RUVON_CONFIG_PATH=/custom/path/config.yaml

# Override database URL
export RUVON_DB_URL=postgresql://user:pass@localhost/ruvon

# Disable colors (for CI/CD)
export NO_COLOR=1
```

### Configuration File Format

```yaml
version: "1.0"

persistence:
  provider: sqlite  # or postgres, memory, redis
  sqlite:
    db_path: ~/.ruvon/workflows.db
  postgres:
    db_url: postgresql://user:pass@localhost/ruvon
    pool_min_size: 10
    pool_max_size: 50

execution:
  provider: sync  # or thread_pool, celery

observability:
  provider: logging  # or noop

defaults:
  auto_execute: false
  interactive: true
  json_output: false
```

---

**Last Updated:** 2026-01-24
**Version:** 1.0
**Ruvon CLI Version:** 0.1.0+
