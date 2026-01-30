# Missing Features Implementation Plan

## Overview

This document outlines the missing features and unimplemented functionality in Rufus SDK and CLI, prioritized by impact and complexity.

---

## Current Status Summary

### ✅ Completed Features
- Core workflow engine and execution
- Workflow state management and persistence
- SQLite and PostgreSQL persistence providers
- Sync and thread pool executors
- Workflow definition snapshots
- Zombie workflow detection and recovery
- CLI commands: config, list, show, resume, retry, cancel, logs, metrics
- Basic testing infrastructure
- Example applications

### ⚠️ Partially Implemented
- Auto-execute next step (flag exists but not functional)
- Workflow validation (basic structure only)
- Database migration system (exists but not integrated with CLI)

### ❌ Not Implemented
- Celery executor integration
- Interactive HITL prompts in CLI
- Real-time log following (`--follow`)
- Workflow scheduling (cron-based)
- Advanced metrics aggregation
- Performance benchmarking tools

---

## Priority 1: Critical Missing Features

### 1.1 Auto-Execute Next Step

**Current State:** `--auto` flag exists in `resume` and `retry` commands but prints "not yet implemented"

**Goal:** Automatically execute all remaining workflow steps without user intervention

**Implementation Plan:**

**Phase 1: Basic Auto-Execute (2-3 hours)**
1. **Update `resume` command:**
   ```python
   # In workflow_cmd.py resume function
   if auto_execute:
       while workflow.status == 'ACTIVE' and workflow.current_step < len(workflow.workflow_steps):
           result, error = await workflow.next_step(user_input={})
           if error or workflow.status in ['WAITING_HUMAN', 'FAILED']:
               break
           await asyncio.sleep(0.1)  # Brief pause between steps
   ```

2. **Update `retry` command:**
   - Similar loop after resetting workflow state

3. **Add progress indicators:**
   - Use Rich progress bar
   - Show current step name
   - Display estimated completion

**Phase 2: Advanced Auto-Execute (3-4 hours)**
4. **Handle WAITING_HUMAN states:**
   - Detect when workflow pauses for input
   - Option to auto-skip with defaults
   - `--auto-approve` flag for approval steps

5. **Error handling:**
   - Retry failed steps automatically (with `--auto-retry` flag)
   - Configurable retry attempts
   - Exponential backoff

6. **Progress reporting:**
   - Real-time status updates
   - Step execution times
   - ETA calculation

**Files to Modify:**
- `src/rufus_cli/commands/workflow_cmd.py` - Add auto-execute logic
- `tests/cli/test_workflow_cmd.py` - Add auto-execute tests

**Success Criteria:**
- ✅ `rufus resume <id> --auto` executes all steps to completion
- ✅ Progress bar shows current step
- ✅ Handles WAITING_HUMAN gracefully
- ✅ Reports final status

---

### 1.2 Interactive HITL (Human-in-the-Loop) Prompts

**Current State:** CLI doesn't have interactive workflow execution

**Goal:** Run workflows interactively, prompting for input when needed

**Implementation Plan:**

**Phase 1: Basic Interactive Mode (3-4 hours)**
1. **Add `run-interactive` command:**
   ```bash
   rufus run-interactive <workflow-type> --config <file>
   ```

2. **Detect WAITING_HUMAN states:**
   - Check workflow status after each step
   - Prompt user for input using Rich prompts

3. **Input collection:**
   ```python
   from rich.prompt import Prompt, Confirm

   if workflow.status == 'WAITING_HUMAN':
       # Determine expected input from workflow definition
       user_input = {}
       user_input['approved'] = Confirm.ask("Approve this action?")
       user_input['notes'] = Prompt.ask("Enter notes (optional)", default="")

       # Continue workflow
       result, error = await workflow.next_step(user_input=user_input)
   ```

**Phase 2: Schema-based Input (4-5 hours)**
4. **Define input schemas in YAML:**
   ```yaml
   - name: "Approval_Step"
     type: "STANDARD"
     function: "steps.check_approval"
     input_schema:
       - name: "approved"
         type: "boolean"
         prompt: "Approve this request?"
         required: true
       - name: "notes"
         type: "string"
         prompt: "Enter approval notes"
         required: false
   ```

5. **Auto-generate prompts from schema:**
   - Parse input_schema from step config
   - Create Rich prompts dynamically
   - Validate input before submission

**Files to Create:**
- `src/rufus_cli/commands/interactive.py` - Interactive execution logic
- `src/rufus_cli/input_collector.py` - Input schema parsing and collection

**Files to Modify:**
- `src/rufus_cli/main.py` - Add run-interactive command
- `tests/cli/test_interactive.py` - Interactive tests

**Success Criteria:**
- ✅ `rufus run-interactive <type>` prompts for input at each HITL step
- ✅ Input validated against schema
- ✅ Workflow completes with user inputs

---

### 1.3 Workflow Validation Improvements

**Current State:** Basic YAML validation exists but limited

**Goal:** Comprehensive workflow definition validation

**Implementation Plan:**

**Phase 1: Enhanced YAML Validation (2-3 hours)**
1. **Validate step references:**
   - Check `dependencies` reference existing steps
   - Validate `WorkflowJumpDirective` targets exist
   - Ensure no circular dependencies

2. **Validate function paths:**
   - Check that `function` paths are importable
   - Verify functions have correct signature
   - Check compensate_function paths (for Saga)

3. **Validate state models:**
   - Check `initial_state_model` path is importable
   - Verify it's a Pydantic BaseModel
   - Validate required fields

**Phase 2: Runtime Validation (2-3 hours)**
4. **Dry-run execution:**
   ```bash
   rufus validate <workflow.yaml> --dry-run
   ```
   - Mock step execution
   - Check state transitions
   - Verify data flow

5. **Dependency graph visualization:**
   ```bash
   rufus validate <workflow.yaml> --graph
   ```
   - Generate graphviz/mermaid diagram
   - Show step dependencies
   - Highlight potential issues

**Files to Modify:**
- `src/rufus_cli/validation.py` - Enhanced validation logic
- `tests/cli/test_validate_and_run.py` - Validation tests

**Success Criteria:**
- ✅ Catches invalid function paths
- ✅ Detects circular dependencies
- ✅ Validates state model structure
- ✅ Generates dependency graph

---

## Priority 2: Important Missing Features

### 2.1 Real-time Log Following

**Current State:** `--follow` flag exists but not implemented

**Goal:** Stream workflow logs in real-time

**Implementation Plan:**

**Phase 1: Polling-based Following (2-3 hours)**
1. **Implement log polling:**
   ```python
   # In workflow_cmd.py logs function
   if follow:
       last_log_id = 0
       try:
           while True:
               new_logs = await persistence.get_workflow_logs(
                   workflow_id=workflow_id,
                   after_id=last_log_id
               )
               for log in new_logs:
                   print_log(log)
                   last_log_id = log['log_id']

               # Check if workflow completed
               workflow = await persistence.load_workflow(workflow_id)
               if workflow['status'] in ['COMPLETED', 'FAILED', 'CANCELLED']:
                   break

               await asyncio.sleep(1)  # Poll every second
       except KeyboardInterrupt:
           console.print("\nStopped following logs")
   ```

**Phase 2: Event-based Following (PostgreSQL only) (3-4 hours)**
2. **Use PostgreSQL LISTEN/NOTIFY:**
   - Add trigger to notify on log insert
   - Listen for notifications in CLI
   - Push logs immediately (no polling delay)

**Files to Modify:**
- `src/rufus_cli/commands/workflow_cmd.py` - Add follow logic
- `src/rufus/implementations/persistence/postgres.py` - Add NOTIFY trigger
- `tests/cli/test_workflow_cmd.py` - Add follow tests

**Success Criteria:**
- ✅ `rufus logs <id> --follow` streams logs in real-time
- ✅ Stops when workflow completes
- ✅ Handles Ctrl+C gracefully

---

### 2.2 Database Management Commands

**Current State:** Commands exist but not fully implemented

**Goal:** Full database lifecycle management via CLI

**Implementation Plan:**

**Phase 1: DB Init (2 hours)**
1. **Implement `rufus db init`:**
   ```python
   async def init_database(db_url):
       # Detect database type from URL
       if "sqlite" in db_url:
           # Apply SQLite migration
           schema_path = Path(__file__).parent.parent.parent / "migrations" / "002_sqlite_initial.sql"
       elif "postgresql" in db_url:
           # Apply PostgreSQL migration
           schema_path = Path(__file__).parent.parent.parent / "migrations" / "002_postgres_standardized.sql"

       # Execute schema
       # Create schema_migrations table
       # Mark initial migration as applied
   ```

**Phase 2: DB Migrate (2-3 hours)**
2. **Implement `rufus db migrate`:**
   - Scan migrations/ directory
   - Check schema_migrations table
   - Apply pending migrations in order
   - Support --dry-run

**Phase 3: DB Status & Stats (1-2 hours)**
3. **Implement status and stats:**
   - Show applied migrations
   - Show pending migrations
   - Database size, table counts
   - Workflow statistics

**Files to Modify:**
- `src/rufus_cli/commands/db_cmd.py` - Implement all commands
- `src/rufus_cli/migrations.py` - **NEW** - Migration management
- `tests/cli/test_db_cmd.py` - Enable database tests

**Success Criteria:**
- ✅ `rufus db init` creates schema
- ✅ `rufus db migrate` applies migrations
- ✅ `rufus db status` shows migration state
- ✅ `rufus db stats` shows database metrics

---

### 2.3 Workflow Scheduling (Cron)

**Current State:** `CronScheduleWorkflowStep` model exists but no execution

**Goal:** Schedule workflows to run on cron schedules

**Implementation Plan:**

**Phase 1: Scheduler Daemon (4-5 hours)**
1. **Create scheduler service:**
   ```python
   # src/rufus/scheduler.py
   class WorkflowScheduler:
       def __init__(self, persistence, engine):
           self.persistence = persistence
           self.engine = engine
           self.schedules = []  # List of (cron_expr, workflow_type, data)

       async def load_schedules(self):
           # Load from database or config file
           pass

       async def run(self):
           while True:
               now = datetime.now()
               for schedule in self.schedules:
                   if schedule.should_run(now):
                       await self.engine.start_workflow(
                           workflow_type=schedule.workflow_type,
                           initial_data=schedule.initial_data
                       )
               await asyncio.sleep(60)  # Check every minute
   ```

2. **CLI command:**
   ```bash
   rufus scheduler start  # Run scheduler daemon
   rufus schedule add <workflow-type> --cron "0 */6 * * *"
   rufus schedule list
   rufus schedule remove <schedule-id>
   ```

**Phase 2: Cron Expression Support (2-3 hours)**
3. **Parse and validate cron expressions:**
   - Use `croniter` library
   - Support standard cron syntax
   - Calculate next run time

4. **Persistent schedule storage:**
   - Add `workflow_schedules` table
   - Store cron expression, workflow_type, data
   - Enable/disable schedules

**Files to Create:**
- `src/rufus/scheduler.py` - Scheduler service
- `src/rufus_cli/commands/schedule_cmd.py` - CLI commands
- `migrations/003_add_schedules.sql` - Schedules table

**Success Criteria:**
- ✅ Workflows run on schedule
- ✅ Missed runs handled correctly
- ✅ Schedules persist across restarts

---

## Priority 3: Nice-to-Have Features

### 3.1 Celery Executor Integration

**Current State:** Config exists but executor not implemented

**Goal:** Distributed async execution via Celery

**Complexity:** High (5-7 hours)

**Implementation Needed:**
- Celery task definitions
- Task routing configuration
- Result backend setup
- Worker pool management

**Files to Create:**
- `src/rufus/implementations/execution/celery.py` - Full implementation
- `tests/sdk/test_celery_executor.py` - Integration tests

---

### 3.2 Performance Benchmarking

**Goal:** Built-in performance testing tools

**Complexity:** Medium (3-4 hours)

**Features:**
```bash
rufus benchmark <workflow-type> --iterations 100 --concurrency 10
```
- Measure throughput (workflows/second)
- Measure latency (p50, p95, p99)
- Step-by-step timing
- Resource usage (CPU, memory)

**Files to Create:**
- `src/rufus_cli/commands/benchmark_cmd.py`
- `src/rufus_cli/benchmarking.py`

---

### 3.3 Advanced Metrics Aggregation

**Goal:** Statistical analysis of workflow metrics

**Complexity:** Medium (2-3 hours)

**Features:**
```bash
rufus metrics --summary  # Show aggregated stats
rufus metrics --type execution_time --workflow-type OrderProcessing --plot
```
- Average, median, p95, p99
- Time series analysis
- Matplotlib/plotly charts
- Export to CSV/JSON

**Files to Modify:**
- `src/rufus_cli/commands/workflow_cmd.py`
- `src/rufus_cli/metrics_analyzer.py` - **NEW**

---

### 3.4 Workflow Templates

**Goal:** Pre-built workflow templates

**Complexity:** Low (2-3 hours)

**Features:**
```bash
rufus template list
rufus template create <name> --from <workflow.yaml>
rufus template apply <name> --data '{"key": "value"}'
```

**Templates:**
- Approval workflow
- Data processing pipeline
- Order fulfillment
- ML model training

**Files to Create:**
- `src/rufus_cli/commands/template_cmd.py`
- `templates/` - Template YAML files

---

## Implementation Roadmap

### Sprint 1 (Week 1): Auto-Execute & Interactive
**Time:** 10-15 hours
- ✅ Fix remaining tests (completed)
- Auto-execute next step (Phase 1 & 2)
- Interactive HITL prompts (Phase 1)

### Sprint 2 (Week 2): Validation & Database
**Time:** 10-12 hours
- Enhanced validation
- Database management commands
- Real-time log following

### Sprint 3 (Week 3): Scheduling & Polish
**Time:** 8-10 hours
- Workflow scheduling
- Advanced metrics
- Documentation updates

### Sprint 4 (Week 4): Advanced Features
**Time:** 10-12 hours
- Celery executor
- Performance benchmarking
- Workflow templates

---

## Testing Strategy

For each feature:
1. **Unit tests** - Test individual functions
2. **Integration tests** - Test end-to-end workflows
3. **CLI tests** - Test command invocation
4. **Example application** - Demonstrate usage

**Target Coverage:** 85%+ for new code

---

## Documentation Requirements

For each feature:
1. Update `CLAUDE.md` with usage examples
2. Update CLI help text
3. Create example in `examples/` directory
4. Add to `USAGE_GUIDE.md` (if exists)

---

## Dependencies

**New Python Packages Needed:**
- `croniter` - Cron expression parsing (for scheduler)
- `matplotlib` or `plotly` - Metrics visualization (optional)
- `graphviz` - Dependency graph generation (optional)

---

## Success Metrics

### Feature Completeness
- [ ] All Priority 1 features implemented
- [ ] All Priority 2 features implemented
- [ ] 50%+ of Priority 3 features implemented

### Quality
- [ ] 85%+ test coverage
- [ ] All CLI commands documented
- [ ] Examples for major features

### Performance
- [ ] Auto-execute: < 100ms overhead per step
- [ ] Log following: < 1s latency
- [ ] CLI commands: < 500ms response time

---

## Next Immediate Action

**Start with: Auto-Execute Next Step (Priority 1.1)**

This is the highest-impact feature with moderate complexity. It directly addresses user pain points and enables unattended workflow execution.

**Estimated Time:** 4-6 hours for Phase 1 & 2
**Files to Modify:** 2 (workflow_cmd.py, test_workflow_cmd.py)
**Risk:** Low - well-understood requirement

---

## Questions for Consideration

1. **Auto-execute retry logic:** How many retries? What delay?
2. **Interactive mode:** Should it be a separate command or a flag?
3. **Scheduler:** Daemon or cron job approach?
4. **Celery:** Required for MVP or can be deferred?
5. **Metrics visualization:** Text-based or graphical?

---

## Conclusion

This plan provides a clear roadmap for implementing missing features in order of priority. Focus on Priority 1 features first for maximum impact, then move to Priority 2 for completeness, and finally Priority 3 for polish and advanced capabilities.

**Recommended Start:** Implement Auto-Execute Next Step immediately.
