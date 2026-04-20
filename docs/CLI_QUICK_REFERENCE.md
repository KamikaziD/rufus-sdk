# Ruvon CLI Quick Reference

One-page command reference for the Ruvon CLI. For detailed documentation, see [CLI_USAGE_GUIDE.md](CLI_USAGE_GUIDE.md).

## Installation

| Deployment target | Install command |
|-------------------|----------------|
| Core SDK + CLI (dev / general use) | `pip install ruvon-sdk` |
| Edge device (POS, ATM, kiosk) | `pip install 'ruvon-edge[edge]'` |
| Cloud REST API server | `pip install 'ruvon-server[server,auth]'` |
| Celery workers | `pip install 'ruvon-server[celery]'` |
| Full server stack | `pip install 'ruvon-server[all]'` |

```bash
# Development (all packages from source)
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/ruvon-edge[edge]"
pip install -e "packages/ruvon-server[server,celery,auth]"

ruvon --help      # Verify installation
```

## Configuration (`ruvon config`)

| Command | Description | Example |
|---------|-------------|---------|
| `show` | Display configuration | `ruvon config show` |
| `path` | Show config file location | `ruvon config path` |
| `set-persistence` | Set database (interactive) | `ruvon config set-persistence` |
| `set-execution` | Set executor (interactive) | `ruvon config set-execution` |
| `set-default` | Set defaults (interactive) | `ruvon config set-default` |
| `reset` | Reset to defaults | `ruvon config reset --yes` |

**Config File:** `~/.ruvon/config.yaml`

## Workflow Management (`ruvon workflow` or top-level)

### List & Search

```bash
ruvon list                              # List all workflows
ruvon list --status ACTIVE              # Filter by status
ruvon list --type OrderProcessing       # Filter by type
ruvon list --limit 100                  # Increase limit
ruvon list --json                       # JSON output
```

### Start & Monitor

```bash
ruvon start MyWorkflow --data '{"user_id": "123"}'    # Start workflow
ruvon start MyWorkflow --data '{}' --interactive     # Interactive mode (prompts at HITL steps)
ruvon interactive run MyWorkflow --config wf.yaml    # Interactive run with config file
ruvon show <id>                                       # Show details
ruvon show <id> --state --logs --metrics              # Show everything
ruvon show <id> --json                                # JSON output
```

### Resume & Retry

```bash
ruvon resume <id> --input '{"approved": true}'  # Resume paused
ruvon retry <id>                                # Retry failed
ruvon retry <id> --from-step Process_Payment    # Retry from step
```

### Logs & Metrics

```bash
ruvon logs <id>                          # View logs
ruvon logs <id> --step Payment           # Filter by step
ruvon logs <id> --level ERROR            # Filter by level
ruvon logs <id> --limit 100              # Limit results
ruvon logs <id> --follow                 # (not yet implemented — shows latest logs only)
ruvon logs <id> --json                   # JSON output

ruvon metrics --workflow-id <id>         # View metrics
ruvon metrics --type OrderProcessing     # By workflow type
ruvon metrics --summary                  # Show summary stats
```

### Cancel

```bash
ruvon cancel <id>                               # Cancel with confirmation
ruvon cancel <id> --reason "Duplicate order"    # With reason
ruvon cancel <id> --force                       # Skip confirmation
```

## Database Management (`ruvon db`)

| Command | Description | Example |
|---------|-------------|---------|
| `init` | Initialize schema | `ruvon db init` |
| `migrate` | Apply migrations | `ruvon db migrate` |
| `migrate --dry-run` | Preview migrations | `ruvon db migrate --dry-run` |
| `status` | Show migration status | `ruvon db status` |
| `stats` | Show database statistics | `ruvon db stats` |
| `validate` | Validate schema | `ruvon db validate` |

**Override database:**
```bash
ruvon db init --db-url sqlite:///path/to/db.sqlite
ruvon db init --db-url postgresql://user:pass@host/db
```

## Zombie Recovery

```bash
ruvon scan-zombies --db postgresql://localhost/ruvon          # Scan (dry-run)
ruvon scan-zombies --db postgresql://localhost/ruvon --fix    # Recover zombies
ruvon scan-zombies --db sqlite:///workflows.db --json        # JSON output
ruvon zombie-daemon --db postgresql://localhost/ruvon         # Continuous daemon
ruvon zombie-daemon --db postgresql://localhost/ruvon --interval 30
```

## Legacy Commands

```bash
ruvon validate config/workflow.yaml         # Validate YAML syntax
ruvon validate config/workflow.yaml --strict --graph  # Full validation + dependency graph
ruvon run config/workflow.yaml -d '{}'      # Run locally (in-memory)
```

## Common Workflows

### Development Setup

```bash
# 1. Configure
ruvon config set-persistence  # Choose SQLite

# 2. Initialize
ruvon db init

# 3. Verify
ruvon db stats

# 4. Test
ruvon run config/my_workflow.yaml -d '{}'
```

### Production Setup

```bash
# 1. Configure
ruvon config set-persistence  # Choose PostgreSQL

# 2. Migrate
ruvon db migrate --dry-run
ruvon db migrate

# 3. Verify
ruvon db status
ruvon db validate
```

### Monitoring

```bash
# Active workflows
ruvon list --status ACTIVE --limit 100

# View logs
ruvon logs <id> --level ERROR --limit 100

# View metrics
ruvon metrics --type OrderProcessing --summary

# Troubleshoot
ruvon show <id> --verbose
```

## Status Values

| Status | Description |
|--------|-------------|
| `ACTIVE` | Currently running |
| `PENDING_ASYNC` | Waiting for async task |
| `PENDING_SUB_WORKFLOW` | Waiting for sub-workflow |
| `PAUSED` | Paused, waiting for resume |
| `WAITING_HUMAN` | Waiting for human input |
| `WAITING_HUMAN_INPUT` | Waiting for user input |
| `WAITING_CHILD_HUMAN_INPUT` | Child workflow waiting |
| `COMPLETED` | Successfully finished |
| `FAILED` | Failed with error |
| `FAILED_ROLLED_BACK` | Failed and rolled back |
| `FAILED_CHILD_WORKFLOW` | Child workflow failed |
| `CANCELLED` | Manually cancelled |

## Log Levels

| Level | Description |
|-------|-------------|
| `DEBUG` | Detailed debugging information |
| `INFO` | General information |
| `WARNING` | Warning messages |
| `ERROR` | Error messages |

## Common Options

| Option | Description | Example |
|--------|-------------|---------|
| `--help` | Show help | `ruvon logs --help` |
| `--json` | JSON output | `ruvon list --json` |
| `--verbose`, `-v` | Verbose output | `ruvon list -v` |
| `--limit` | Limit results | `ruvon list --limit 100` |
| `--status` | Filter by status | `ruvon list --status ACTIVE` |
| `--type` | Filter by type | `ruvon list --type OrderProcessing` |

## Environment Variables

```bash
# Override config file
export RUVON_CONFIG_PATH=/custom/config.yaml

# Override database URL
export RUVON_DB_URL=postgresql://user:pass@localhost/ruvon

# Disable colors (for CI/CD)
export NO_COLOR=1
```

## Configuration File Format

```yaml
version: "1.0"

persistence:
  provider: sqlite  # or postgres, memory
  sqlite:
    db_path: ~/.ruvon/workflows.db
  postgres:
    db_url: postgresql://user:pass@localhost/ruvon
    pool_min_size: 10
    pool_max_size: 50

execution:
  provider: sync  # or thread_pool

observability:
  provider: logging  # or noop

defaults:
  auto_execute: false
  interactive: true
  json_output: false
```

## Troubleshooting

### Configuration Issues

```bash
ruvon config path          # Find config file
ruvon config reset --yes   # Reset if corrupted
```

### Database Issues

```bash
ruvon db init              # Initialize if tables missing
ruvon db status            # Check migration status
ruvon db stats             # Verify tables exist
```

### Workflow Issues

```bash
ruvon show <id> --verbose          # Full workflow details
ruvon logs <id> --level ERROR      # Check for errors
ruvon cancel <id> --force          # Force cancel stuck workflow
```

### CLI Issues

```bash
ruvon --version                    # Check version
ruvon --help                       # Show all commands
pip install -e . --force-reinstall # Reinstall if broken
```

## Tips

1. **Use SQLite for development**, PostgreSQL for production
2. **Always run `db init`** before first workflow
3. **Use `--dry-run`** before applying migrations in production
4. **Export to JSON** for analysis: `ruvon logs <id> --json > logs.json`
5. **Use filters** to narrow down large result sets
6. **Add `--help`** to any command for detailed options

## Getting Help

```bash
ruvon --help               # General help
ruvon config --help        # Config commands
ruvon workflow --help      # Workflow commands
ruvon db --help            # Database commands
ruvon logs --help          # Specific command help
```

**Documentation:**
- [CLI Usage Guide](CLI_USAGE_GUIDE.md) - Complete documentation
- [CLAUDE.md](../CLAUDE.md) - Developer guide
- [README.md](../README.md) - Project overview

**Issues:** https://github.com/your-org/ruvon-sdk/issues

---

**Version:** 0.6.0 | **Last Updated:** 2026-02-25 | **Ruvon SDK:** 0.6.0
