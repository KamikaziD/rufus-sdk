# Rufus CLI Usage Guide

Complete guide to using the Rufus command-line interface for workflow orchestration, database management, and monitoring.

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

The Rufus CLI provides a comprehensive command-line interface for managing workflows, databases, and monitoring your Rufus workflow orchestration system. It features:

- **21 commands** across 4 categories
- **Beautiful terminal output** with color-coded tables
- **Interactive configuration** wizards
- **Multi-database support** (SQLite, PostgreSQL)
- **Advanced monitoring** (logs, metrics, cancellation)

### Command Structure

```
rufus <command> [subcommand] [options] [arguments]
```

**Command Groups:**
- `rufus config` - Configuration management
- `rufus workflow` - Workflow operations
- `rufus db` - Database management

**Top-level Aliases:**
- `rufus list`, `rufus start`, `rufus show`, etc. (shortcuts to workflow commands)

---

## Installation

### Requirements
- Python 3.9+
- pip or poetry

### Install from Source

```bash
# Clone repository
git clone https://github.com/your-org/rufus-sdk.git
cd rufus-sdk

# Install with pip
pip install -e .

# Or with poetry
poetry install

# Verify installation
rufus --help
```

### Install from PyPI (when published)

```bash
pip install rufus-sdk
```

---

## Quick Start

### 1. Configure Persistence

```bash
# Interactive configuration
rufus config set-persistence

# Choose SQLite for development
# Select: 2 (sqlite)
# Path: ./workflows.db

# Verify configuration
rufus config show
```

### 2. Initialize Database

```bash
# Create database schema
rufus db init

# Verify database
rufus db stats
```

### 3. Start a Workflow

```bash
# Start a workflow (requires workflow definition)
rufus start MyWorkflow --data '{"user_id": "123"}'

# List all workflows
rufus list

# View workflow details
rufus show <workflow-id>
```

---

## Configuration Commands

Manage persistent CLI configuration stored at `~/.rufus/config.yaml`.

### `rufus config show`

Display current configuration.

```bash
rufus config show

# Output as JSON
rufus config show --json
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

### `rufus config path`

Show configuration file location.

```bash
rufus config path

# Output:
# ~/.rufus/config.yaml
```

### `rufus config set-persistence`

Configure persistence provider (interactive).

```bash
rufus config set-persistence
```

**Interactive Prompts:**
```
Available persistence providers:
  1. memory - In-memory (testing only)
  2. sqlite - SQLite database (development/production)
  3. postgres - PostgreSQL database (production)

Select provider (1-3): 2

Database path [~/.rufus/workflows.db]: ./workflows.db

✅ Persistence provider set to: sqlite
ℹ️  Database path: ./workflows.db
```

**Providers:**
- **memory** - In-memory storage (data lost on restart)
- **sqlite** - SQLite file-based database
- **postgres** - PostgreSQL database (requires connection URL)

### `rufus config set-execution`

Configure execution provider (interactive).

```bash
rufus config set-execution
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

### `rufus config set-default`

Configure default behaviors (interactive).

```bash
rufus config set-default
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

### `rufus config reset`

Reset configuration to defaults.

```bash
# With confirmation
rufus config reset

# Skip confirmation
rufus config reset --yes
```

---

## Workflow Management

Manage workflow lifecycle: list, start, monitor, resume, retry.

### `rufus list`

List workflows with optional filtering.

```bash
# List all workflows (default: 20)
rufus list

# Filter by status
rufus list --status ACTIVE
rufus list --status COMPLETED
rufus list --status FAILED

# Filter by workflow type
rufus list --type OrderProcessing

# Increase limit
rufus list --limit 100

# Verbose output (more details)
rufus list --verbose

# JSON output
rufus list --json

# Combine filters
rufus list --status ACTIVE --type OrderProcessing --limit 50
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

### `rufus start`

Start a new workflow.

```bash
# Start workflow with inline JSON data
rufus start OrderProcessing --data '{"customer_id": "123", "amount": 99.99}'

# Start workflow from JSON file
rufus start OrderProcessing --data-file order.json

# Specify workflow config file
rufus start OrderProcessing --config config/order_workflow.yaml --data '{}'

# Auto-execute all steps (non-interactive)
rufus start OrderProcessing --data '{}' --auto

# Dry run (validate only, don't execute)
rufus start OrderProcessing --data '{}' --dry-run
```

**Example Output:**
```
✅ Workflow started successfully

Workflow ID: wf_abc123def456
Status: ACTIVE
Current Step: Validate_Order

Next steps:
  • View details: rufus show wf_abc123def456
  • Resume: rufus resume wf_abc123def456
```

**Data Format:**
- Must be valid JSON
- Keys match workflow's initial state model
- Use `--data-file` for complex data

### `rufus show`

Show detailed workflow information.

```bash
# Basic workflow info
rufus show <workflow-id>

# Include full state
rufus show <workflow-id> --state

# Include execution logs
rufus show <workflow-id> --logs

# Include metrics
rufus show <workflow-id> --metrics

# Show everything
rufus show <workflow-id> --verbose

# JSON output
rufus show <workflow-id> --json
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

### `rufus resume`

Resume a paused workflow.

```bash
# Resume workflow (interactive prompts for input if needed)
rufus resume <workflow-id>

# Provide input as JSON
rufus resume <workflow-id> --input '{"approved": true}'

# Provide input from file
rufus resume <workflow-id> --input-file approval.json

# Auto-execute remaining steps
rufus resume <workflow-id> --auto
```

**Note:** Resume/retry are partially implemented. Full workflow reconstruction coming in future release.

### `rufus retry`

Retry a failed workflow.

```bash
# Retry from beginning
rufus retry <workflow-id>

# Retry from specific step
rufus retry <workflow-id> --from-step Process_Payment

# Auto-execute remaining steps
rufus retry <workflow-id> --auto
```

---

## Database Management

Initialize, migrate, and monitor your Rufus database.

### `rufus db init`

Initialize database schema.

```bash
# Initialize using configured database
rufus db init

# Initialize specific database
rufus db init --db-url sqlite:///path/to/db.sqlite
rufus db init --db-url postgresql://user:pass@localhost/rufus
```

**What it does:**
- Creates all required tables (workflow_executions, tasks, logs, metrics, etc.)
- Creates indexes for performance
- Sets up triggers for automatic timestamps
- Enables foreign key constraints (SQLite)
- Enables WAL mode (SQLite)

**SQLite Schema:**
- 6 tables: workflow_executions, tasks, compensation_log, audit_log, execution_logs, metrics
- 7 indexes for query performance
- 2 triggers for timestamp management

**PostgreSQL Schema:**
- Same tables with PostgreSQL-specific optimizations
- Managed via migration system

### `rufus db migrate`

Apply pending database migrations.

```bash
# Apply all pending migrations
rufus db migrate

# Dry run (show pending migrations without applying)
rufus db migrate --dry-run

# Use specific database
rufus db migrate --db-url postgresql://user:pass@localhost/rufus
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

### `rufus db status`

Show database migration status.

```bash
# Show migration status for configured database
rufus db status

# Show status for specific database
rufus db status --db-url sqlite:///workflows.db
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

### `rufus db stats`

Show database statistics.

```bash
# Show statistics for configured database
rufus db stats

# Show stats for specific database
rufus db stats --db-url sqlite:///workflows.db
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

### `rufus db validate`

Validate database schema against definition.

```bash
# Validate schema
rufus db validate
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

### `rufus logs`

View workflow execution logs.

```bash
# View logs for a workflow
rufus logs <workflow-id>

# Filter by step
rufus logs <workflow-id> --step Process_Payment

# Filter by log level
rufus logs <workflow-id> --level ERROR
rufus logs <workflow-id> --level WARNING

# Limit number of logs
rufus logs <workflow-id> --limit 100
rufus logs <workflow-id> -n 100

# Follow logs (real-time, coming soon)
rufus logs <workflow-id> --follow
rufus logs <workflow-id> -f

# JSON output
rufus logs <workflow-id> --json
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

### `rufus metrics`

View workflow performance metrics.

```bash
# View metrics for specific workflow
rufus metrics --workflow-id <id>
rufus metrics -w <id>

# View metrics by workflow type
rufus metrics --type OrderProcessing

# Show summary statistics
rufus metrics --workflow-id <id> --summary

# Limit results
rufus metrics --limit 100

# JSON output
rufus metrics --json

# Combine filters
rufus metrics --type OrderProcessing --summary --limit 50
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

### `rufus cancel`

Cancel a running workflow.

```bash
# Cancel workflow (with confirmation)
rufus cancel <workflow-id>

# Cancel with reason
rufus cancel <workflow-id> --reason "Duplicate order detected"

# Force cancel (skip compensation/rollback)
rufus cancel <workflow-id> --force
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

### `rufus validate`

Validate workflow YAML syntax.

```bash
# Validate workflow file
rufus validate config/my_workflow.yaml

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

### `rufus run`

Run workflow locally (in-memory, synchronous).

```bash
# Run workflow with initial data
rufus run config/my_workflow.yaml --data '{"user_id": "123"}'

# Short form
rufus run config/my_workflow.yaml -d '{}'
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
rufus config set-persistence  # Choose SQLite
rufus db init

# 2. Validate workflow definition
rufus validate config/my_workflow.yaml

# 3. Test locally (in-memory)
rufus run config/my_workflow.yaml --data '{}'

# 4. Start with persistence
rufus start MyWorkflow --data '{}'

# 5. Monitor
rufus list --status ACTIVE
rufus logs <workflow-id>

# 6. View results
rufus show <workflow-id> --state
```

### Production Workflow

```bash
# 1. Setup PostgreSQL
rufus config set-persistence  # Choose PostgreSQL
# Enter connection URL: postgresql://user:pass@prod-db:5432/rufus

# 2. Initialize/migrate database
rufus db init
rufus db migrate

# 3. Verify setup
rufus db status
rufus db stats

# 4. Start workflows (via API or CLI)
rufus start OrderProcessing --data @order.json

# 5. Monitor production
rufus list --status ACTIVE --limit 100
rufus metrics --type OrderProcessing --summary

# 6. Troubleshoot issues
rufus logs <workflow-id> --level ERROR
rufus show <workflow-id> --verbose

# 7. Cancel if needed
rufus cancel <workflow-id> --reason "Customer cancelled order"
```

### Testing Workflow

```bash
# Use in-memory for unit tests
rufus config set-persistence  # Choose memory

# Validate workflow definitions
rufus validate config/*.yaml

# Run tests with in-memory execution
rufus run config/test_workflow.yaml --data @test_data.json

# Check results (data lost after process ends)
```

### Migration Workflow

```bash
# From old CLI to new CLI

# 1. Check existing setup
rufus config show

# 2. Backup database (if using SQLite)
cp ~/.rufus/workflows.db ~/.rufus/workflows.db.backup

# 3. Run migrations (if needed)
rufus db migrate --dry-run  # Check first
rufus db migrate            # Apply

# 4. Verify schema
rufus db validate
rufus db stats

# 5. Test with existing workflows
rufus list
rufus show <existing-workflow-id>
```

---

## Troubleshooting

### Configuration Issues

**Problem:** Configuration not persisting
```bash
# Check config file location
rufus config path

# Check file exists and is writable
ls -la ~/.rufus/config.yaml

# Reset if corrupted
rufus config reset --yes
```

**Problem:** Database connection errors
```bash
# Verify database URL
rufus config show

# Test connection
rufus db stats

# Reinitialize if needed
rufus db init --db-url sqlite:///new_path.db
```

### Database Issues

**Problem:** "Table not found" errors
```bash
# Initialize database
rufus db init

# Verify tables exist
rufus db stats

# Check migration status
rufus db status
```

**Problem:** Migration failures
```bash
# Check pending migrations
rufus db migrate --dry-run

# Verify schema
rufus db validate

# Check database permissions
# (PostgreSQL) GRANT ALL ON DATABASE rufus TO user;
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
rufus validate config/workflow.yaml

# Check initial data format
echo '{"valid": "json"}' | jq .

# Try dry run
rufus start MyWorkflow --data '{}' --dry-run

# Check logs
rufus logs <workflow-id> --level ERROR
```

**Problem:** Workflow stuck/not progressing
```bash
# Check status
rufus show <workflow-id>

# View logs for errors
rufus logs <workflow-id> --level ERROR

# Check if waiting for input
rufus show <workflow-id> --state

# Resume if paused
rufus resume <workflow-id> --input '{}'

# Cancel if needed
rufus cancel <workflow-id> --reason "Debugging"
```

**Problem:** Cannot view logs/metrics
```bash
# Verify workflow exists
rufus show <workflow-id>

# Check database has logs table
rufus db stats

# Reinitialize database if needed
rufus db init
```

### CLI Issues

**Problem:** Command not found
```bash
# Verify installation
which rufus
rufus --version

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
rufus list --json

# Check terminal supports colors
echo $TERM
```

### Getting Help

**View help for any command:**
```bash
rufus --help
rufus config --help
rufus workflow --help
rufus logs --help
```

**Check version:**
```bash
rufus --version
```

**Report issues:**
- GitHub: https://github.com/your-org/rufus-sdk/issues
- Include output of: `rufus config show` and `rufus db status`

---

## Tips and Best Practices

### Configuration

1. **Use SQLite for development**, PostgreSQL for production
2. **Store config in version control** (without sensitive data)
3. **Use environment variables** for production secrets
4. **Back up SQLite databases** regularly

### Workflows

1. **Always validate** workflow definitions before deploying
2. **Test with `rufus run`** before using persistence
3. **Use meaningful workflow IDs** in logs
4. **Add comprehensive logging** in step functions
5. **Monitor metrics** for performance tracking

### Database

1. **Initialize database** before first workflow
2. **Run migrations** in maintenance windows
3. **Monitor database size** with `rufus db stats`
4. **Validate schema** after upgrades
5. **Back up before migrations** (production)

### Monitoring

1. **Use filters** to find specific logs/metrics
2. **Export to JSON** for analysis: `rufus logs <id> --json > logs.json`
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
- `rufus config show` - Show configuration
- `rufus config path` - Show config file path
- `rufus config set-persistence` - Set persistence provider
- `rufus config set-execution` - Set execution provider
- `rufus config set-default` - Set default behaviors
- `rufus config reset` - Reset to defaults

**Workflows:**
- `rufus list` - List workflows
- `rufus start` - Start workflow
- `rufus show` - Show workflow details
- `rufus resume` - Resume paused workflow
- `rufus retry` - Retry failed workflow
- `rufus logs` - View execution logs
- `rufus metrics` - View performance metrics
- `rufus cancel` - Cancel running workflow

**Database:**
- `rufus db init` - Initialize schema
- `rufus db migrate` - Apply migrations
- `rufus db status` - Show migration status
- `rufus db stats` - Show database statistics
- `rufus db validate` - Validate schema

**Legacy:**
- `rufus validate` - Validate workflow YAML
- `rufus run` - Run workflow locally

### Environment Variables

```bash
# Override config file location
export RUFUS_CONFIG_PATH=/custom/path/config.yaml

# Override database URL
export RUFUS_DB_URL=postgresql://user:pass@localhost/rufus

# Disable colors (for CI/CD)
export NO_COLOR=1
```

### Configuration File Format

```yaml
version: "1.0"

persistence:
  provider: sqlite  # or postgres, memory, redis
  sqlite:
    db_path: ~/.rufus/workflows.db
  postgres:
    db_url: postgresql://user:pass@localhost/rufus
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
**Rufus CLI Version:** 0.1.0+
