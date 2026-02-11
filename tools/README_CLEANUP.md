# Database Cleanup Tool

## Overview

The `cleanup_database.py` script removes test data and resets the database to a clean state with default seed data. Useful for cleaning up after load tests or resetting development databases.

## Features

- ✅ **Works with SQLite and PostgreSQL**
- ✅ **Two cleanup modes**: delete-all or load-test-only
- ✅ **Automatic re-seeding** with demo data
- ✅ **Safe operation** with confirmation prompts
- ✅ **Verbose output** for debugging

## Usage

### Basic Usage

```bash
# Clean PostgreSQL and re-seed
python tools/cleanup_database.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"

# Clean SQLite and re-seed
python tools/cleanup_database.py \
  --db-url "sqlite:///workflow.db"
```

### Advanced Options

```bash
# Delete everything without re-seeding
python tools/cleanup_database.py \
  --db-url "postgresql://..." \
  --no-seed

# Delete only load test data (preserve other workflows/devices)
python tools/cleanup_database.py \
  --db-url "postgresql://..." \
  --mode load-test-only

# Skip confirmation prompt
python tools/cleanup_database.py \
  --db-url "postgresql://..." \
  --yes

# Verbose output
python tools/cleanup_database.py \
  --db-url "postgresql://..." \
  --verbose
```

## Cleanup Modes

### `delete-all` (default)

Deletes:
- All workflows from `workflow_executions`
- All edge devices from `edge_devices` (PostgreSQL only)
- All workflow heartbeats from `workflow_heartbeats` (PostgreSQL only, if exists)

Then re-seeds with:
- 4 demo workflows (completed, active, failed, waiting)
- 5 edge devices (POS terminals, ATM, kiosk, mobile reader) - PostgreSQL only

### `load-test-only`

Deletes:
- Only edge devices with `device_id` starting with `load-test-`
- Preserves all other data

Note: Load test workflows cannot be automatically identified, so use `delete-all` mode to remove all workflows.

## What Gets Seeded

After cleanup with re-seeding, your database will contain:

**Workflows (4):**
- Completed task: "Setup development environment"
- Active task: "Review pull request #42"
- Failed task: "Deploy to production"
- Waiting task: "Approve expense report"

**Edge Devices (5, PostgreSQL only):**
- device-001: POS Terminal (Store 001)
- device-002: POS Terminal (Store 002)
- device-003: ATM (Branch 001, offline)
- device-004: Kiosk (Mall 001)
- device-005: Mobile Reader (Field, offline)

## Safety Features

1. **Confirmation prompt** - Asks for confirmation before deleting (use `--yes` to skip)
2. **Clear output** - Shows exactly what will be deleted
3. **Graceful errors** - Continues even if some tables don't exist
4. **Idempotent seeding** - Re-running won't create duplicates (for edge devices)

## Common Workflows

### After Load Testing

```bash
# Clean up all test data and reset to demo state
python tools/cleanup_database.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud" \
  --yes
```

### Reset Development Database

```bash
# Clean SQLite database for fresh start
python tools/cleanup_database.py \
  --db-url "sqlite:///rufus_edge.db" \
  --yes
```

### Quick Load Test Cleanup

```bash
# Remove just the load test devices
python tools/cleanup_database.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud" \
  --mode load-test-only \
  --yes
```

## Database Support

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Delete workflows | ✅ | ✅ |
| Delete edge devices | ➖ (no edge_devices table) | ✅ |
| Delete heartbeats | ➖ (no heartbeats table) | ✅ |
| Re-seed workflows | ✅ | ✅ |
| Re-seed edge devices | ➖ | ✅ |

## Exit Codes

- `0` - Success
- `1` - Error (database connection, cleanup failed, etc.)
- `0` - User cancelled (via confirmation prompt)

## See Also

- `seed_data.py` - Seed database with demo data
- `run_load_test.py` - Run load tests (with automatic seeding)
