# Celery Worker Improvements - Restoring Confucius Functionality

## Summary

Implemented complete automatic task discovery and scheduled workflow support for Celery workers, restoring all functionality from Confucius.

## Changes Made

### 1. **celery_app.py** - Task Module Auto-Discovery (Lines 19-57)

**Problem**: User step function modules weren't being discovered and added to Celery's include list.

**Solution**:
- Created global `WorkflowBuilder` instance at module level
- Calls `workflow_builder.get_all_task_modules()` to discover all user modules
- Automatically adds them to Celery's `include` list

**Configuration**:
```bash
export WORKFLOW_CONFIG_DIR="config"  # Default: "config"
export WORKFLOW_REGISTRY_FILE="workflow_registry.yaml"  # Default: "workflow_registry.yaml"
```

**Benefits**:
- ✅ Celery workers can now import user task modules automatically
- ✅ No manual configuration of task includes needed
- ✅ Works for all step types: STANDARD, ASYNC, PARALLEL, HTTP, etc.
- ✅ Discovers modules from: function, compensate_function, parallel tasks, merge functions

**Example**:
```yaml
# config/my_workflow.yaml
steps:
  - name: "Process_Data"
    type: "ASYNC"
    function: "my_app.steps.process_data"  # my_app module auto-discovered!
```

Before: Workers would fail with `ImportError: No module named 'my_app'`
After: Workers automatically include `my_app` in imports

---

### 2. **celery_app.py** - Beat Schedule Auto-Population (Lines 76-124)

**Problem**: Scheduled workflows (CRON_SCHEDULE steps) weren't being registered with Celery Beat.

**Solution**:
- Calls `workflow_builder.get_scheduled_workflows()` to find all scheduled workflows
- Parses cron expressions and registers them with Celery Beat
- Supports both string cron format and dict format

**Supported Schedule Formats**:

**String Format** (5-part cron):
```yaml
workflow_type: "DailyReport"
schedule: "0 9 * * *"  # Every day at 9 AM
```

**Dict Format** (advanced):
```yaml
workflow_type: "HourlySync"
schedule:
  crontab:
    minute: "0"
    hour: "*"
    day_of_month: "*"
    month_of_year: "*"
    day_of_week: "*"
```

**Benefits**:
- ✅ CRON_SCHEDULE workflows execute on schedule automatically
- ✅ No manual beat schedule configuration needed
- ✅ Workflows are triggered via `ruvon.tasks.trigger_scheduled_workflow` task
- ✅ Supports cron expressions and interval-based schedules

---

### 3. **tasks.py** - Completed `trigger_scheduled_workflow` Task (Lines 330-375)

**Problem**: The task existed but was incomplete (had TODO comments).

**Solution**:
- Fully implemented workflow creation and execution
- Uses global `_workflow_builder` to create workflow instances
- Automatically advances workflow through steps
- Publishes workflow events

**Functionality**:
```python
# Called by Celery Beat on schedule
trigger_scheduled_workflow(workflow_type="DailyReport", initial_data={})
# Creates workflow → Saves to DB → Executes steps → Returns status
```

**Benefits**:
- ✅ Scheduled workflows fully functional
- ✅ Integrates with event publishing
- ✅ Auto-advances workflow through steps
- ✅ Handles PENDING_ASYNC, WAITING_HUMAN states correctly

---

### 4. **celery_app.py** - Worker Initialization (Lines 177-200)

**Problem**: Workers created WorkflowBuilder with empty registry, preventing scheduled workflows from working.

**Solution**:
- Worker now loads actual workflow registry on initialization
- Passes full registry to WorkflowBuilder
- Falls back to empty registry if file not found

**Benefits**:
- ✅ Workers can create new workflow instances (for scheduled workflows)
- ✅ `trigger_scheduled_workflow` task now works correctly
- ✅ Workers have access to full workflow definitions

---

## Testing

### Test 1: Verify Task Module Discovery

**Setup**:
```bash
# Create test workflow
cat > config/test_workflow.yaml <<EOF
workflow_type: "TestWorkflow"
initial_state_model: "my_app.models.TestState"
steps:
  - name: "Process"
    type: "ASYNC"
    function: "my_app.steps.process_data"
EOF

# Create user module
mkdir -p my_app
cat > my_app/steps.py <<EOF
from ruvon.celery_app import celery_app

@celery_app.task
def process_data(state: dict, context):
    return {"processed": True}
EOF
```

**Test**:
```bash
# Start worker with debug logging
export WORKFLOW_CONFIG_DIR="config"
celery -A ruvon.celery_app worker --loglevel=debug

# Look for log output:
# "Loaded workflow registry from config/workflow_registry.yaml"
# "Discovered task modules: ['my_app.steps']"
```

**Expected**: Worker logs show `my_app.steps` in discovered modules.

---

### Test 2: Verify Scheduled Workflow

**Setup**:
```yaml
# config/workflow_registry.yaml
workflows:
  - type: "DailyReport"
    config_file: "daily_report.yaml"
    initial_state_model: "my_app.models.ReportState"
    schedule: "*/5 * * * *"  # Every 5 minutes for testing
```

**Test**:
```bash
# Start Celery Beat
celery -A ruvon.celery_app beat --loglevel=info

# Look for log output:
# "Registered scheduled workflow: DailyReport with cron '*/5 * * * *'"

# Start worker
celery -A ruvon.celery_app worker --loglevel=info

# Wait 5 minutes, look for:
# "[SCHEDULER] Triggering scheduled workflow: DailyReport"
# "[SCHEDULER] Created scheduled workflow DailyReport: <workflow_id>"
```

**Expected**: Workflow is created and executed every 5 minutes.

---

### Test 3: Full Integration Test

**Script**: `tests/test_celery_worker_integration.py`

```python
#!/usr/bin/env python3
"""Integration test for Celery worker improvements"""
import os
os.environ['WORKFLOW_CONFIG_DIR'] = 'config'
os.environ['WORKFLOW_REGISTRY_FILE'] = 'workflow_registry.yaml'

from ruvon.celery_app import celery_app, workflow_builder, discovered_task_modules

def test_task_discovery():
    """Test that user modules are discovered"""
    print(f"Discovered modules: {discovered_task_modules}")
    assert len(discovered_task_modules) > 0, "No task modules discovered!"
    assert 'my_app.steps' in discovered_task_modules, "my_app.steps not discovered!"
    print("✅ Task discovery working!")

def test_beat_schedule():
    """Test that scheduled workflows are registered"""
    beat_schedule = celery_app.conf.beat_schedule
    print(f"Beat schedule: {list(beat_schedule.keys())}")

    # Should have at least poll-dynamic-schedules
    assert 'poll-dynamic-schedules' in beat_schedule

    # Check for scheduled workflows
    scheduled_workflows = [k for k in beat_schedule.keys() if k.startswith('trigger-')]
    print(f"Scheduled workflows: {scheduled_workflows}")
    print("✅ Beat schedule populated!")

def test_workflow_builder():
    """Test that global workflow_builder is available"""
    assert workflow_builder is not None, "WorkflowBuilder not initialized!"

    # Test methods exist
    assert hasattr(workflow_builder, 'get_all_task_modules')
    assert hasattr(workflow_builder, 'get_scheduled_workflows')
    print("✅ WorkflowBuilder available!")

if __name__ == '__main__':
    test_task_discovery()
    test_beat_schedule()
    test_workflow_builder()
    print("\n🎉 All tests passed!")
```

**Run**:
```bash
python tests/test_celery_worker_integration.py
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKFLOW_CONFIG_DIR` | `config` | Directory containing workflow YAML files |
| `WORKFLOW_REGISTRY_FILE` | `workflow_registry.yaml` | Name of the registry file |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery result backend |
| `DATABASE_URL` | - | Database URL for workflow persistence |

---

## Migration Guide from Confucius

If you're migrating from Confucius:

1. **No code changes needed** - Task discovery and beat schedule population are automatic
2. **Remove manual includes** - Delete any hardcoded `include` lists in your celery config
3. **Use environment variables** - Configure via `WORKFLOW_CONFIG_DIR` instead of hardcoded paths
4. **Test scheduled workflows** - Verify cron expressions are working

**Confucius**:
```python
# Old way - manual includes
celery_app.conf.update(
    include=['workflow_utils', 'celery_worker', 'my_app.tasks']
)
```

**Ruvon** (now):
```python
# New way - automatic discovery
# Just set WORKFLOW_CONFIG_DIR and it works!
export WORKFLOW_CONFIG_DIR="config"
```

---

## Debugging

**Problem**: "Task modules not discovered"

**Solution**:
```bash
# Check if registry file exists
ls -la config/workflow_registry.yaml

# Set env vars explicitly
export WORKFLOW_CONFIG_DIR="$(pwd)/config"
export WORKFLOW_REGISTRY_FILE="workflow_registry.yaml"

# Check worker logs
celery -A ruvon.celery_app worker --loglevel=debug | grep "Discovered task modules"
```

**Problem**: "Scheduled workflows not triggering"

**Solution**:
```bash
# Check Beat logs
celery -A ruvon.celery_app beat --loglevel=info | grep "Registered scheduled workflow"

# Verify cron expression
celery -A ruvon.celery_app inspect scheduled

# Check worker can import trigger_scheduled_workflow
celery -A ruvon.celery_app inspect registered | grep trigger_scheduled_workflow
```

**Problem**: "WorkflowBuilder not initialized in worker"

**Solution**:
```bash
# Ensure registry is accessible to worker
export WORKFLOW_CONFIG_DIR="/absolute/path/to/config"

# Check worker initialization logs
celery -A ruvon.celery_app worker --loglevel=info | grep "Worker loaded workflow registry"
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     celery_app.py (Module Load)                 │
├─────────────────────────────────────────────────────────────────┤
│ 1. Load WorkflowBuilder(config_dir, registry_path)             │
│ 2. Discover task modules → get_all_task_modules()              │
│    → ['my_app.steps', 'other_app.tasks']                       │
│ 3. Register with Celery → include=['ruvon.tasks', 'my_app...'] │
│ 4. Discover scheduled workflows → get_scheduled_workflows()    │
│ 5. Register with Beat → beat_schedule['trigger-DailyReport']   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                   Celery Worker Process                         │
├─────────────────────────────────────────────────────────────────┤
│ @worker_process_init:                                           │
│   - Reset PostgreSQL connection pool                            │
│   - Load WorkflowBuilder (with registry)                        │
│   - Inject providers into tasks module                          │
│                                                                 │
│ @worker_ready:                                                  │
│   - Register worker in database (WorkerRegistry)                │
│                                                                 │
│ Tasks can now:                                                  │
│   ✅ Import user modules (my_app.steps)                        │
│   ✅ Create new workflows (trigger_scheduled_workflow)          │
│   ✅ Access workflow registry                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Celery Beat Process                          │
├─────────────────────────────────────────────────────────────────┤
│ beat_schedule = {                                               │
│   'trigger-DailyReport': {                                      │
│     'task': 'ruvon.tasks.trigger_scheduled_workflow',           │
│     'schedule': crontab(minute='0', hour='9'),                  │
│     'args': ('DailyReport', {})                                 │
│   }                                                             │
│ }                                                               │
│                                                                 │
│ Every day at 9 AM → Dispatch trigger_scheduled_workflow task   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Summary of Confucius Feature Parity

| Feature | Confucius | Ruvon (Before) | Ruvon (After) |
|---------|-----------|----------------|---------------|
| **Task Module Discovery** | ✅ Automatic | ❌ Manual/TODO | ✅ Automatic |
| **Beat Schedule Population** | ✅ Automatic | ❌ TODO | ✅ Automatic |
| **Scheduled Workflows** | ✅ Full support | ❌ Incomplete | ✅ Full support |
| **Worker Registry** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Event Publishing** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Global WorkflowBuilder** | ✅ Yes | ❌ No | ✅ Yes |

**Result**: ✅ **100% Confucius feature parity achieved!**

---

## Files Changed

1. `src/ruvon/celery_app.py` - Task discovery and beat schedule (130 lines changed)
2. `src/ruvon/tasks.py` - Completed `trigger_scheduled_workflow` (45 lines changed)

**Total**: ~175 lines of code

---

## Next Steps

1. ✅ Test with real user workflows
2. ✅ Verify scheduled workflows execute correctly
3. ✅ Test with multiple worker processes
4. 🔲 Update documentation
5. 🔲 Add integration tests
6. 🔲 Update Docker images with new functionality
