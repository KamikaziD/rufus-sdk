# Rufus CLI Quick Reference

One-page command reference for the Rufus CLI. For detailed documentation, see [CLI_USAGE_GUIDE.md](CLI_USAGE_GUIDE.md).

## Installation

```bash
pip install -e .  # Development mode
rufus --help      # Verify installation
```

## Configuration (`rufus config`)

| Command | Description | Example |
|---------|-------------|---------|
| `show` | Display configuration | `rufus config show` |
| `path` | Show config file location | `rufus config path` |
| `set-persistence` | Set database (interactive) | `rufus config set-persistence` |
| `set-execution` | Set executor (interactive) | `rufus config set-execution` |
| `set-default` | Set defaults (interactive) | `rufus config set-default` |
| `reset` | Reset to defaults | `rufus config reset --yes` |

**Config File:** `~/.rufus/config.yaml`

## Workflow Management (`rufus workflow` or top-level)

### List & Search

```bash
rufus list                              # List all workflows
rufus list --status ACTIVE              # Filter by status
rufus list --type OrderProcessing       # Filter by type
rufus list --limit 100                  # Increase limit
rufus list --json                       # JSON output
```

### Start & Monitor

```bash
rufus start MyWorkflow --data '{"user_id": "123"}'    # Start workflow
rufus show <id>                                       # Show details
rufus show <id> --state --logs --metrics              # Show everything
rufus show <id> --json                                # JSON output
```

### Resume & Retry

```bash
rufus resume <id> --input '{"approved": true}'  # Resume paused
rufus retry <id>                                # Retry failed
rufus retry <id> --from-step Process_Payment    # Retry from step
```

### Logs & Metrics

```bash
rufus logs <id>                          # View logs
rufus logs <id> --step Payment           # Filter by step
rufus logs <id> --level ERROR            # Filter by level
rufus logs <id> --limit 100              # Limit results
rufus logs <id> --json                   # JSON output

rufus metrics --workflow-id <id>         # View metrics
rufus metrics --type OrderProcessing     # By workflow type
rufus metrics --summary                  # Show summary stats
```

### Cancel

```bash
rufus cancel <id>                               # Cancel with confirmation
rufus cancel <id> --reason "Duplicate order"    # With reason
rufus cancel <id> --force                       # Skip confirmation
```

## Database Management (`rufus db`)

| Command | Description | Example |
|---------|-------------|---------|
| `init` | Initialize schema | `rufus db init` |
| `migrate` | Apply migrations | `rufus db migrate` |
| `migrate --dry-run` | Preview migrations | `rufus db migrate --dry-run` |
| `status` | Show migration status | `rufus db status` |
| `stats` | Show database statistics | `rufus db stats` |
| `validate` | Validate schema | `rufus db validate` |

**Override database:**
```bash
rufus db init --db-url sqlite:///path/to/db.sqlite
rufus db init --db-url postgresql://user:pass@host/db
```

## Legacy Commands

```bash
rufus validate config/workflow.yaml         # Validate YAML syntax
rufus run config/workflow.yaml -d '{}'      # Run locally (in-memory)
```

## Common Workflows

### Development Setup

```bash
# 1. Configure
rufus config set-persistence  # Choose SQLite

# 2. Initialize
rufus db init

# 3. Verify
rufus db stats

# 4. Test
rufus run config/my_workflow.yaml -d '{}'
```

### Production Setup

```bash
# 1. Configure
rufus config set-persistence  # Choose PostgreSQL

# 2. Migrate
rufus db migrate --dry-run
rufus db migrate

# 3. Verify
rufus db status
rufus db validate
```

### Monitoring

```bash
# Active workflows
rufus list --status ACTIVE --limit 100

# View logs
rufus logs <id> --level ERROR --limit 100

# View metrics
rufus metrics --type OrderProcessing --summary

# Troubleshoot
rufus show <id> --verbose
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
| `--help` | Show help | `rufus logs --help` |
| `--json` | JSON output | `rufus list --json` |
| `--verbose`, `-v` | Verbose output | `rufus list -v` |
| `--limit` | Limit results | `rufus list --limit 100` |
| `--status` | Filter by status | `rufus list --status ACTIVE` |
| `--type` | Filter by type | `rufus list --type OrderProcessing` |

## Environment Variables

```bash
# Override config file
export RUFUS_CONFIG_PATH=/custom/config.yaml

# Override database URL
export RUFUS_DB_URL=postgresql://user:pass@localhost/rufus

# Disable colors (for CI/CD)
export NO_COLOR=1
```

## Configuration File Format

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

## Troubleshooting

### Configuration Issues

```bash
rufus config path          # Find config file
rufus config reset --yes   # Reset if corrupted
```

### Database Issues

```bash
rufus db init              # Initialize if tables missing
rufus db status            # Check migration status
rufus db stats             # Verify tables exist
```

### Workflow Issues

```bash
rufus show <id> --verbose          # Full workflow details
rufus logs <id> --level ERROR      # Check for errors
rufus cancel <id> --force          # Force cancel stuck workflow
```

### CLI Issues

```bash
rufus --version                    # Check version
rufus --help                       # Show all commands
pip install -e . --force-reinstall # Reinstall if broken
```

## Tips

1. **Use SQLite for development**, PostgreSQL for production
2. **Always run `db init`** before first workflow
3. **Use `--dry-run`** before applying migrations in production
4. **Export to JSON** for analysis: `rufus logs <id> --json > logs.json`
5. **Use filters** to narrow down large result sets
6. **Add `--help`** to any command for detailed options

## Getting Help

```bash
rufus --help               # General help
rufus config --help        # Config commands
rufus workflow --help      # Workflow commands
rufus db --help            # Database commands
rufus logs --help          # Specific command help
```

**Documentation:**
- [CLI Usage Guide](CLI_USAGE_GUIDE.md) - Complete documentation
- [CLAUDE.md](../CLAUDE.md) - Developer guide
- [README.md](../README.md) - Project overview

**Issues:** https://github.com/your-org/rufus-sdk/issues

---

**Version:** 1.0 | **Last Updated:** 2026-01-24 | **Rufus CLI:** 0.1.0+
