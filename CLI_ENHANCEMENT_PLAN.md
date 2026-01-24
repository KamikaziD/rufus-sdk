# Rufus CLI Enhancement Plan

## Executive Summary

This plan outlines enhancements to the Rufus CLI to transform it from a basic validation/execution tool into a comprehensive workflow management interface. The goal is to provide developers with full workflow lifecycle management capabilities while maintaining simplicity and practical utility.

---

## Current State

### Existing Commands ✅

**`rufus validate <workflow.yaml>`**
- Validates YAML syntax and basic structure
- Checks for required fields (workflow_type, steps)
- Attempts to build steps from config
- Status: ✅ Working

**`rufus run <workflow.yaml> --data '{...}'`**
- Runs workflow locally with in-memory persistence
- Uses synchronous execution
- Auto-advances through all steps (no human input support)
- Status: ✅ Working, but limited

### Limitations

1. **No persistence options** - Only in-memory, data lost after execution
2. **No workflow management** - Can't list, resume, retry existing workflows
3. **No HITL support** - Can't pause for human input or resume paused workflows
4. **No database integration** - Can't use PostgreSQL or SQLite
5. **No migration tools** - Database schema management manual
6. **No workflow inspection** - Can't view workflow state, logs, or metrics
7. **Limited error recovery** - Can't retry failed workflows or rewind steps

---

## Proposed Enhancements

### Phase 1: Core Workflow Management 🎯 (High Priority)

#### 1.1 Persistence Configuration

Add global configuration for persistence providers:

```bash
# Configure persistence provider (persists in ~/.rufus/config.yaml)
rufus config set persistence sqlite --db-path workflows.db
rufus config set persistence postgres --db-url postgresql://localhost/rufus
rufus config set persistence memory  # Default

# View current configuration
rufus config show

# Reset to defaults
rufus config reset
```

**Files affected:**
- New: `src/rufus_cli/config.py` - Config management
- New: `~/.rufus/config.yaml` - User config file
- Modified: `src/rufus_cli/main.py` - Load config for all commands

**Benefits:**
- ✅ Reusable persistence across CLI sessions
- ✅ No need to specify --db-url on every command
- ✅ Easy switching between dev/prod databases

---

#### 1.2 Workflow Lifecycle Commands

**`rufus list [OPTIONS]`** - List workflows

```bash
# List all workflows
rufus list

# Filter by status
rufus list --status ACTIVE
rufus list --status COMPLETED
rufus list --status FAILED

# Filter by workflow type
rufus list --type OrderProcessing

# Limit results
rufus list --limit 20

# Show detailed view
rufus list --verbose

# Output as JSON
rufus list --json
```

**Output (table format):**
```
WORKFLOW ID          TYPE              STATUS    CURRENT STEP       CREATED          UPDATED
wf_abc123           OrderProcessing    ACTIVE    Process_Payment    2h ago           5m ago
wf_def456           TaskApproval       PAUSED    Request_Approval   1d ago           1d ago
wf_ghi789           OrderProcessing    COMPLETED -                  3d ago           3d ago
```

---

**`rufus start <workflow-type> [OPTIONS]`** - Start a new workflow

```bash
# Start workflow with initial data
rufus start OrderProcessing --data '{"order_id": "123", "amount": 99.99}'

# Load data from file
rufus start OrderProcessing --data-file order.json

# Use specific workflow YAML
rufus start OrderProcessing --config workflows/order.yaml

# Dry run (validate without executing)
rufus start OrderProcessing --data '{}' --dry-run

# Auto-execute all steps (current behavior)
rufus start OrderProcessing --data '{}' --auto

# Interactive mode (prompt for HITL steps)
rufus start OrderProcessing --data '{}' --interactive
```

**Output:**
```
✅ Started workflow: OrderProcessing
   Workflow ID: wf_abc123
   Status: ACTIVE
   Current Step: Validate_Order

   Run 'rufus show wf_abc123' to view details
   Run 'rufus resume wf_abc123' to continue execution
```

---

**`rufus show <workflow-id> [OPTIONS]`** - Show workflow details

```bash
# Show workflow overview
rufus show wf_abc123

# Show full state
rufus show wf_abc123 --state

# Show execution logs
rufus show wf_abc123 --logs

# Show metrics
rufus show wf_abc123 --metrics

# Show all details
rufus show wf_abc123 --verbose

# Output as JSON
rufus show wf_abc123 --json
```

**Output (overview):**
```
Workflow: wf_abc123
Type: OrderProcessing
Status: ACTIVE
Current Step: Process_Payment (step 2/5)
Created: 2024-01-24 10:30:00
Updated: 2024-01-24 10:32:15

State:
  order_id: "123"
  amount: 99.99
  validated: true
  payment_status: "pending"

Steps:
  ✅ Validate_Order (completed)
  ⏳ Process_Payment (in progress)
  ⏸  Ship_Order (pending)
  ⏸  Send_Confirmation (pending)
  ⏸  Complete_Order (pending)
```

---

**`rufus resume <workflow-id> [OPTIONS]`** - Resume paused workflow

```bash
# Resume workflow (execute next step)
rufus resume wf_abc123

# Resume with user input (for HITL steps)
rufus resume wf_abc123 --input '{"approved": true, "comments": "Looks good"}'

# Resume from file
rufus resume wf_abc123 --input-file approval.json

# Auto-execute remaining steps
rufus resume wf_abc123 --auto

# Interactive mode
rufus resume wf_abc123 --interactive
```

**Output:**
```
⏯  Resuming workflow: wf_abc123

Executing: Process_Payment
  Result: {"payment_id": "pay_xyz", "status": "completed"}

Status: ACTIVE
Current Step: Ship_Order

Run 'rufus resume wf_abc123' to continue
```

---

**`rufus retry <workflow-id> [OPTIONS]`** - Retry failed workflow

```bash
# Retry from current step
rufus retry wf_abc123

# Retry from specific step
rufus retry wf_abc123 --from-step Process_Payment

# Retry with modified state
rufus retry wf_abc123 --state '{"amount": 89.99}'

# Retry and auto-execute
rufus retry wf_abc123 --auto
```

**Output:**
```
🔄 Retrying workflow: wf_abc123
   Previous status: FAILED
   Retry from step: Process_Payment

   Status: ACTIVE
   Current Step: Process_Payment

   Run 'rufus show wf_abc123' to monitor progress
```

---

**`rufus rewind <workflow-id> --to-step <step-name>`** - Rewind workflow

```bash
# Rewind to specific step (for debugging/corrections)
rufus rewind wf_abc123 --to-step Validate_Order

# Rewind and modify state
rufus rewind wf_abc123 --to-step Validate_Order --state '{"amount": 79.99}'

# Dry run (show what would happen)
rufus rewind wf_abc123 --to-step Validate_Order --dry-run
```

**Output:**
```
⏪ Rewinding workflow: wf_abc123
   Current step: Ship_Order (step 3/5)
   Rewinding to: Validate_Order (step 1/5)

   ⚠️  WARNING: This will reset all progress after Validate_Order

   Steps to be reset:
     - Process_Payment
     - Ship_Order

   Continue? [y/N]: y

   ✅ Workflow rewound successfully
   Status: ACTIVE
   Current Step: Validate_Order
```

---

**`rufus cancel <workflow-id> [OPTIONS]`** - Cancel workflow

```bash
# Cancel active workflow
rufus cancel wf_abc123

# Cancel with reason
rufus cancel wf_abc123 --reason "Customer requested cancellation"

# Force cancel (skip compensation)
rufus cancel wf_abc123 --force
```

---

**`rufus delete <workflow-id> [OPTIONS]`** - Delete workflow

```bash
# Delete workflow (preserves audit logs)
rufus delete wf_abc123

# Delete including all logs
rufus delete wf_abc123 --purge

# Confirm deletion
rufus delete wf_abc123 --yes
```

---

### Phase 2: Database Management 🗄️ (Medium Priority)

#### 2.1 Database Migration Commands

**`rufus db init [OPTIONS]`** - Initialize database

```bash
# Initialize database (creates tables)
rufus db init

# Specify database explicitly
rufus db init --db-url postgresql://localhost/rufus
rufus db init --db-path workflows.db

# Use config from ~/.rufus/config.yaml
rufus db init  # Uses configured persistence provider
```

**Output:**
```
🗄️  Initializing database...
   Database: PostgreSQL (postgresql://localhost/rufus)

   Creating tables:
     ✅ workflow_executions
     ✅ tasks
     ✅ compensation_log
     ✅ workflow_audit_log
     ✅ workflow_execution_logs
     ✅ workflow_metrics

   Creating indexes...
     ✅ idx_workflow_status
     ✅ idx_workflow_type
     ... (18 total)

   Creating triggers...
     ✅ workflow_executions_updated_at
     ✅ workflow_update_trigger
     ... (4 total)

   ✅ Database initialized successfully
```

---

**`rufus db migrate [OPTIONS]`** - Apply migrations

```bash
# Show migration status
rufus db migrate --status

# Apply pending migrations
rufus db migrate --up

# Apply specific migration
rufus db migrate --to 002

# Rollback last migration
rufus db migrate --down

# Generate new migration
rufus db migrate --generate add_priority_field
```

**Output (status):**
```
Migration Status:

  [✅] 001_init_postgresql_schema.sql (applied 2024-01-15)
  [✅] 002_postgres_standardized.sql  (applied 2024-01-20)
  [ ] 003_add_priority_field.sql     (pending)

  Database: PostgreSQL (postgresql://localhost/rufus)
  Current version: 002
  Latest version: 003

  Run 'rufus db migrate --up' to apply pending migrations
```

---

**`rufus db validate`** - Validate schema consistency

```bash
# Validate current database against schema.yaml
rufus db validate

# Validate specific database
rufus db validate --db-url postgresql://localhost/rufus
```

**Output:**
```
🔍 Validating database schema...
   Database: PostgreSQL (postgresql://localhost/rufus)
   Schema: migrations/schema.yaml (v1.0.0)

   Checking tables... ✅ 6/6
   Checking indexes... ✅ 18/18
   Checking triggers... ✅ 4/4
   Checking views... ✅ 2/2

   ✅ Schema is valid and up-to-date
```

---

**`rufus db backup [OPTIONS]`** - Backup database

```bash
# Backup workflows to file
rufus db backup --output backup.json

# Backup only active workflows
rufus db backup --status ACTIVE --output active.json

# Backup specific workflow type
rufus db backup --type OrderProcessing --output orders.json
```

---

**`rufus db restore [OPTIONS]`** - Restore database

```bash
# Restore from backup
rufus db restore --input backup.json

# Restore and merge with existing
rufus db restore --input backup.json --merge

# Restore to different database
rufus db restore --input backup.json --db-url postgresql://localhost/rufus_dev
```

---

**`rufus db stats`** - Show database statistics

```bash
# Show database statistics
rufus db stats
```

**Output:**
```
📊 Database Statistics
   Database: PostgreSQL (postgresql://localhost/rufus)

   Workflows:
     Total: 1,234
     Active: 45
     Paused: 12
     Completed: 1,150
     Failed: 27

   By Type:
     OrderProcessing: 856
     TaskApproval: 234
     KYCVerification: 144

   Storage:
     Database size: 145 MB
     Largest table: workflow_execution_logs (89 MB)
     Oldest workflow: 45 days ago

   Performance:
     Avg workflow duration: 2.5 minutes
     Success rate: 97.8%
     Slowest step: External_API_Call (avg 1.2s)
```

---

### Phase 3: Advanced Features ⚡ (Low Priority)

#### 3.1 Workflow Inspection & Debugging

**`rufus logs <workflow-id> [OPTIONS]`** - View execution logs

```bash
# Show recent logs
rufus logs wf_abc123

# Show logs for specific step
rufus logs wf_abc123 --step Process_Payment

# Filter by log level
rufus logs wf_abc123 --level ERROR

# Follow logs (tail mode)
rufus logs wf_abc123 --follow

# Export logs
rufus logs wf_abc123 --output logs.txt
```

---

**`rufus metrics <workflow-id> [OPTIONS]`** - View metrics

```bash
# Show workflow metrics
rufus metrics wf_abc123

# Show metrics for all workflows of type
rufus metrics --type OrderProcessing --summary

# Export metrics
rufus metrics wf_abc123 --output metrics.csv
```

---

**`rufus trace <workflow-id>`** - Show execution trace

```bash
# Show complete execution trace
rufus trace wf_abc123
```

**Output:**
```
Execution Trace: wf_abc123 (OrderProcessing)

1. Validate_Order (COMPLETED - 250ms)
   ├─ Input: {"order_id": "123", "amount": 99.99}
   ├─ Output: {"valid": true, "validated_at": "2024-01-24T10:30:15Z"}
   └─ State: order_id=123, amount=99.99, validated=true

2. Process_Payment (COMPLETED - 1.2s)
   ├─ Input: {"amount": 99.99}
   ├─ Output: {"payment_id": "pay_xyz", "status": "completed"}
   └─ State: payment_id=pay_xyz, payment_status=completed

3. Ship_Order (IN PROGRESS)
   ├─ Input: {"order_id": "123"}
   └─ State: payment_id=pay_xyz, shipping_status=pending
```

---

#### 3.2 Workflow Templates & Utilities

**`rufus template list`** - List workflow templates

```bash
# List available templates
rufus template list
```

**Output:**
```
Available Templates:

  approval-workflow    Simple approval workflow with HITL
  saga-transaction     Distributed transaction with compensation
  parallel-processing  Parallel task execution with merge
  scheduled-job        Cron-scheduled recurring workflow
```

---

**`rufus template create <name> <template>`** - Create from template

```bash
# Create workflow from template
rufus template create MyApprovalWorkflow approval-workflow

# Create with custom parameters
rufus template create MyApprovalWorkflow approval-workflow --param steps=5
```

---

**`rufus export <workflow-id> [OPTIONS]`** - Export workflow

```bash
# Export workflow definition and state
rufus export wf_abc123 --output workflow.json

# Export only definition
rufus export wf_abc123 --definition-only --output workflow.yaml
```

---

#### 3.3 Interactive Mode

**`rufus interactive`** - Start interactive shell

```bash
# Start interactive REPL
rufus interactive
```

**Output:**
```
Rufus Interactive Shell (v0.1.0)
Type 'help' for commands, 'exit' to quit

rufus> list --status ACTIVE
WORKFLOW ID     TYPE             STATUS    CURRENT STEP
wf_abc123      OrderProcessing   ACTIVE    Ship_Order

rufus> show wf_abc123
Workflow: wf_abc123
Type: OrderProcessing
Status: ACTIVE
...

rufus> resume wf_abc123
⏯  Resuming workflow: wf_abc123
...

rufus> exit
Goodbye!
```

---

## Implementation Architecture

### Configuration Management

**Config file location:** `~/.rufus/config.yaml`

```yaml
version: "1.0"

persistence:
  provider: sqlite  # or postgres, redis, memory
  sqlite:
    db_path: /Users/developer/.rufus/workflows.db
  postgres:
    db_url: postgresql://localhost/rufus
    pool_min_size: 10
    pool_max_size: 50

execution:
  provider: sync  # or celery, thread_pool

observability:
  provider: logging  # or event_publisher

defaults:
  auto_execute: false  # Don't auto-execute steps by default
  interactive: true    # Prompt for HITL steps
  json_output: false   # Use table output by default
```

**Config loading priority:**
1. CLI flags (highest priority)
2. Environment variables (`RUFUS_DB_URL`, etc.)
3. Config file (`~/.rufus/config.yaml`)
4. Default values (lowest priority)

---

### Provider Management

**Centralized provider factory:** `src/rufus_cli/providers.py`

```python
async def get_persistence_provider(config: Config) -> PersistenceProvider:
    """Create persistence provider from config"""
    if config.persistence.provider == 'sqlite':
        from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
        provider = SQLitePersistenceProvider(db_path=config.persistence.sqlite.db_path)
    elif config.persistence.provider == 'postgres':
        from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
        provider = PostgresPersistenceProvider(db_url=config.persistence.postgres.db_url)
    # ... etc

    await provider.initialize()
    return provider
```

---

### Output Formatting

**Multiple output formats supported:**

1. **Table format** (default for `list`, `stats`)
2. **Detail format** (default for `show`, `trace`)
3. **JSON format** (via `--json` flag)
4. **Interactive format** (for `interactive` mode)

**Use `rich` library** for beautiful terminal output:
- Tables with colors and borders
- Progress bars for long operations
- Syntax highlighting for JSON/YAML
- Interactive prompts for confirmations

---

### Error Handling

**Consistent error messages:**

```python
# Success (exit code 0)
typer.echo("✅ Success message", fg=typer.colors.GREEN)

# Warning (exit code 0)
typer.echo("⚠️  Warning message", fg=typer.colors.YELLOW)

# Error (exit code 1)
typer.echo("❌ Error message", err=True, fg=typer.colors.RED)
raise typer.Exit(code=1)

# Info (exit code 0)
typer.echo("ℹ️  Info message", fg=typer.colors.BLUE)
```

---

## Implementation Phases

### Phase 1: Core Workflow Management (Week 1-2)
**Priority: HIGH** - Essential for workflow management

✅ **Deliverables:**
1. Config management (`rufus config`)
2. Workflow listing (`rufus list`)
3. Workflow starting (`rufus start`)
4. Workflow inspection (`rufus show`)
5. Workflow resumption (`rufus resume`)
6. Workflow retry (`rufus retry`)

**Estimated effort:** 40 hours
**Files to create:**
- `src/rufus_cli/config.py` - Config management
- `src/rufus_cli/providers.py` - Provider factory
- `src/rufus_cli/formatters.py` - Output formatting
- `src/rufus_cli/commands/` - Command modules (workflow.py, config.py)

**Files to modify:**
- `src/rufus_cli/main.py` - Add new commands
- `pyproject.toml` - Add dependencies (rich)
- `requirements.txt` - Add dependencies

---

### Phase 2: Database Management (Week 3)
**Priority: MEDIUM** - Important for production deployments

✅ **Deliverables:**
1. Database initialization (`rufus db init`)
2. Migration management (`rufus db migrate`)
3. Schema validation (`rufus db validate`)
4. Database statistics (`rufus db stats`)

**Estimated effort:** 24 hours
**Files to create:**
- `src/rufus_cli/commands/db.py` - Database commands
- `src/rufus_cli/db_manager.py` - Database management utilities

---

### Phase 3: Advanced Features (Week 4)
**Priority: LOW** - Nice to have

✅ **Deliverables:**
1. Workflow rewind (`rufus rewind`)
2. Workflow cancellation (`rufus cancel`)
3. Logs viewing (`rufus logs`)
4. Metrics viewing (`rufus metrics`)
5. Execution trace (`rufus trace`)

**Estimated effort:** 24 hours

---

## Dependencies

### New Dependencies

**Required:**
- `rich>=13.0` - Beautiful terminal formatting (already in pyproject.toml as optional)
- `click-completion` - Shell completion (optional)

**Optional:**
- `prompt-toolkit` - For interactive mode (future)
- `tabulate` - Alternative to rich for simple tables (if needed)

---

## Testing Strategy

### Unit Tests
- Test each command in isolation
- Mock persistence providers
- Test config loading/saving
- Test output formatting

### Integration Tests
- Test complete workflows (start → resume → complete)
- Test with SQLite (fast)
- Test with PostgreSQL (comprehensive)
- Test error scenarios

### End-to-End Tests
- Test CLI as user would use it
- Test shell completion
- Test interactive mode

---

## Success Criteria

### Phase 1
- ✅ Can start workflow and persist to SQLite/PostgreSQL
- ✅ Can list active workflows
- ✅ Can show workflow details
- ✅ Can resume paused workflows with user input (HITL)
- ✅ Can retry failed workflows
- ✅ Config persists across CLI sessions

### Phase 2
- ✅ Can initialize database from CLI
- ✅ Can apply migrations
- ✅ Can view database statistics
- ✅ Can validate schema consistency

### Phase 3
- ✅ Can rewind workflows for debugging
- ✅ Can view logs and metrics
- ✅ Can trace workflow execution

---

## Open Questions

1. **Workflow cancellation:** Should we support saga rollback on cancel?
   - **Recommendation:** Yes, with `--force` flag to skip rollback

2. **Interactive prompts:** How to handle HITL steps in `--auto` mode?
   - **Recommendation:** Skip HITL steps in auto mode, only work in interactive mode

3. **Multiple workflows:** Should `rufus start` support starting multiple workflows?
   - **Recommendation:** No, keep it simple. Use scripts for batch operations

4. **Workflow locking:** Should we prevent concurrent modifications?
   - **Recommendation:** Yes, add workflow locking in persistence layer (future)

5. **Shell completion:** Should we support bash/zsh completion?
   - **Recommendation:** Yes, but Phase 3 (low priority)

---

## Backwards Compatibility

✅ **All existing commands remain functional:**
- `rufus validate` - No changes
- `rufus run` - Enhanced with `--auto`, `--interactive`, persistence options

✅ **Config file is optional:**
- If no config file, use defaults (in-memory persistence)
- Explicit flags override config

---

## Documentation Updates

**Update CLAUDE.md:**
- Add CLI section with all commands
- Add configuration examples
- Add workflow management examples

**Update README.md:**
- Update "Getting Started" with new commands
- Add "CLI Reference" section

**Create CLI_GUIDE.md:**
- Complete CLI command reference
- Configuration guide
- Workflow management patterns
- Troubleshooting

---

## Risk Assessment

### Low Risk
- ✅ Config management (standard practice)
- ✅ Workflow listing (simple query)
- ✅ Database statistics (read-only)

### Medium Risk
- ⚠️ Workflow retry/rewind (state modification)
- ⚠️ Database migrations (schema changes)
- ⚠️ Workflow cancellation (rollback complexity)

### High Risk
- ❌ Concurrent workflow modifications (need locking)
- ❌ Migration rollbacks (data loss potential)

### Mitigation Strategies
1. **Dry-run mode** for destructive operations
2. **Confirmation prompts** for risky operations
3. **Comprehensive testing** with both SQLite and PostgreSQL
4. **Clear error messages** with recovery steps
5. **Transaction safety** for all state modifications

---

## Timeline

**Total estimated effort:** 88 hours (11 days at 8h/day)

- **Week 1:** Phase 1 part 1 (config, list, start, show) - 20h
- **Week 2:** Phase 1 part 2 (resume, retry) - 20h
- **Week 3:** Phase 2 (database management) - 24h
- **Week 4:** Phase 3 (advanced features) - 24h

**Milestones:**
- ✅ **M1 (End of Week 1):** Basic workflow management working
- ✅ **M2 (End of Week 2):** HITL and retry working
- ✅ **M3 (End of Week 3):** Database management working
- ✅ **M4 (End of Week 4):** All features complete

---

## Conclusion

This plan provides a **practical, incremental approach** to enhancing the Rufus CLI from a basic tool to a comprehensive workflow management interface.

**Key benefits:**
- ✅ **Developer productivity** - Manage workflows without writing code
- ✅ **Database management** - Easy schema migrations and validation
- ✅ **Production readiness** - Full lifecycle management (start, resume, retry, cancel)
- ✅ **Debugging support** - Logs, metrics, traces
- ✅ **Backwards compatible** - Existing commands unchanged

**Recommended approach:** Implement Phase 1 first (core workflow management), validate with users, then proceed with Phases 2-3 based on feedback.
