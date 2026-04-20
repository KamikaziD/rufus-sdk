# Celery Implementation Plan V2 - Based on Confucius Extraction

## 📊 Discovery Summary

Found **~5,000 lines** of production-ready Celery code in `/Users/kim/PycharmProjects/ruvon/confucius/`:

- ✅ Complete Celery app with auto-discovery
- ✅ 8 production Celery tasks (async, parallel, sub-workflows, HTTP, scheduled)
- ✅ Worker registry with heartbeat monitoring
- ✅ PostgreSQL executor (solves async concurrency issues)
- ✅ Event publishing system (Redis Pub/Sub + Streams)
- ✅ 5 database migrations (production schema)
- ✅ Complete persistence layer with encryption
- ✅ All step types (already similar to Ruvon)

---

## 🎯 Extraction Strategy

### Phase 1: Core Celery Infrastructure (2-3 hours)

**Files to Extract →  Ruvon:**

1. **`confucius/src/confucius/celery_app.py`** (144 lines)
   - **→ `src/ruvon/celery_app.py`** (new)
   - **Changes needed:**
     - Replace `confucius.tasks` → `ruvon.tasks`
     - Replace `confucius.worker_registry` → `ruvon.worker_registry`
     - Replace `confucius.events` → `ruvon.events`
     - Update import paths

2. **`confucius/src/confucius/tasks.py`** (545 lines)
   - **→ `src/ruvon/tasks.py`** (new)
   - **Extract these 8 tasks:**
     - `execute_http_request()` - HTTP polyglot steps
     - `resume_from_async_task()` - Async callback
     - `merge_and_resume_parallel_tasks()` - Parallel merging
     - `execute_sub_workflow()` - Child workflow execution
     - `execute_independent_workflow()` - Fire-and-forget
     - `resume_parent_from_child()` - Parent resumption
     - `trigger_scheduled_workflow()` - Cron workflows
     - `poll_scheduled_workflows()` - Schedule polling
   - **Changes needed:**
     - Update imports to use `ruvon.*`
     - Use `ruvon.builder.WorkflowBuilder`
     - Use `ruvon.implementations.persistence.postgres`

3. **`confucius/src/confucius/worker_registry.py`** (97 lines)
   - **→ `src/ruvon/worker_registry.py`** (new)
   - **Minimal changes:**
     - Update logger name
     - Already uses asyncpg directly (no Confucius dependencies)

4. **`confucius/src/confucius/postgres_executor.py`** (120+ lines)
   - **→ `src/ruvon/postgres_executor.py`** (new)
   - **Why:** Solves "another operation in progress" errors with PostgreSQL
   - **No changes needed** - Pure utility module

---

### Phase 2: Celery Execution Provider (1 hour)

**New File:** `src/ruvon/implementations/execution/celery_executor.py`

**Implementation:**
```python
"""
Celery-based execution provider using production-tested task patterns.
"""

from typing import Dict, Any, Optional, List
from celery import Celery, current_app
from ruvon.providers.execution import ExecutionProvider
import logging

logger = logging.getLogger(__name__)


class CeleryExecutionProvider(ExecutionProvider):
    """Execute workflow steps using Celery distributed task queue."""

    def __init__(self, celery_app: Optional[Celery] = None):
        self.celery_app = celery_app or current_app
        logger.info("Celery execution provider initialized")

    async def dispatch_async_task(
        self,
        workflow_id: str,
        step_name: str,
        function_path: str,
        state_dict: Dict[str, Any],
        context_dict: Dict[str, Any],
        user_input: Dict[str, Any]
    ) -> str:
        """Dispatch async step to Celery queue."""
        from ruvon.tasks import resume_from_async_task

        # Import and execute function
        from ruvon.builder import WorkflowBuilder
        func = WorkflowBuilder._import_from_string(function_path)

        # Execute sync (function itself is sync)
        result = func(state_dict, context_dict, **user_input)

        # Chain with resume task
        resume_from_async_task.apply_async(
            kwargs={
                'result': result,
                'workflow_id': workflow_id,
                'current_step_index': context_dict.get('step_index', 0)
            },
            queue=context_dict.get('data_region', 'celery')
        )

        return f"{workflow_id}_{step_name}"

    async def dispatch_parallel_tasks(
        self,
        workflow_id: str,
        parent_step_name: str,
        tasks: List[Dict[str, Any]],
        state_dict: Dict[str, Any],
        context_dict: Dict[str, Any]
    ) -> List[str]:
        """Dispatch parallel tasks to Celery."""
        from ruvon.tasks import merge_and_resume_parallel_tasks
        from celery import group

        # Create task group
        task_group = group([
            self._create_parallel_task(workflow_id, task_config, state_dict, context_dict)
            for task_config in tasks
        ])

        # Execute group, then merge
        callback = merge_and_resume_parallel_tasks.s(
            workflow_id=workflow_id,
            parent_step_name=parent_step_name,
            merge_strategy=context_dict.get('merge_strategy', 'SHALLOW'),
            merge_conflict_behavior=context_dict.get('merge_conflict_behavior', 'PREFER_NEW')
        )

        task_group.apply_async(link=callback)

        return [f"{workflow_id}_{parent_step_name}_{t['name']}" for t in tasks]

    def _create_parallel_task(self, workflow_id, task_config, state_dict, context_dict):
        """Create a single parallel task signature."""
        from ruvon.builder import WorkflowBuilder

        func = WorkflowBuilder._import_from_string(task_config['function_path'])

        # Return Celery signature
        from celery import signature
        return signature(
            'ruvon.tasks.execute_parallel_task_function',
            kwargs={
                'function_path': task_config['function_path'],
                'state_dict': state_dict,
                'context_dict': context_dict,
                'task_name': task_config['name']
            }
        )

    async def dispatch_sub_workflow(
        self,
        parent_workflow_id: str,
        workflow_type: str,
        initial_data: Dict[str, Any],
        owner_id: Optional[str] = None,
        data_region: Optional[str] = None
    ) -> str:
        """Dispatch sub-workflow creation."""
        from ruvon.tasks import execute_sub_workflow

        result = execute_sub_workflow.apply_async(
            kwargs={
                'parent_workflow_id': parent_workflow_id,
                'workflow_type': workflow_type,
                'initial_data': initial_data,
                'owner_id': owner_id,
                'data_region': data_region
            },
            queue=data_region or 'celery'
        )

        return result.id

    def execute_sync_step_function(
        self,
        func: callable,
        state: Any,
        context: Any,
        user_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute synchronous step directly (no Celery)."""
        return func(state, context, **user_input)
```

**Why this approach:**
- Uses proven task patterns from Confucius
- Leverages `resume_from_async_task` callback pattern
- Supports regional queue routing
- Compatible with existing Celery infrastructure

---

### Phase 3: Database Migrations (30 minutes)

**Copy Migrations:**

```bash
# Copy all 5 production migrations
cp confucius/migrations/postgresql/001_init_postgresql_schema.sql \
   src/ruvon/alembic/versions/002_celery_support.sql

cp confucius/migrations/postgresql/002_add_scheduled_workflows.sql \
   src/ruvon/alembic/versions/003_scheduled_workflows.sql

cp confucius/migrations/postgresql/005_add_worker_registry.sql \
   src/ruvon/alembic/versions/004_worker_registry.sql
```

**What they add:**
- `tasks` table (idempotency, task queue)
- `compensation_log` (saga rollback tracking)
- `workflow_execution_logs` (detailed logging)
- `workflow_metrics` (performance tracking)
- `scheduled_workflows` + `scheduled_workflow_runs` (cron)
- `worker_nodes` (fleet management)
- Triggers for notifications, timestamps
- Views for monitoring

**Alembic wrapper:**
Create Alembic migration that runs these SQL files.

---

### Phase 4: Event Publishing (1 hour)

**Extract:** `confucius/src/confucius/events.py` (150+ lines)

**→** `src/ruvon/events.py` (new)

**What it provides:**
- Redis Streams + Pub/Sub dual publishing
- Event types: `workflow.created`, `workflow.updated`, `workflow.completed`, etc.
- Loop-aware Redis client management (prevents async errors)
- Prometheus metrics integration

**Integration:**
```python
# In workflow.py
from ruvon.events import event_publisher

# Publish workflow events
await event_publisher.publish_event(
    event_type='workflow.created',
    workflow_id=self.id,
    data={'workflow_type': self.workflow_type}
)
```

---

### Phase 5: Enhanced Persistence (Optional, 2 hours)

**Extract:** `confucius/src/confucius/persistence_postgres.py`

**→** Compare with `src/ruvon/implementations/persistence/postgres.py`

**What Confucius adds:**
- Encryption-at-rest support
- Compensation logging methods
- Execution logging methods
- Metrics recording methods
- Task record creation
- More comprehensive audit logging

**Strategy:**
1. Compare both files
2. Extract missing methods from Confucius
3. Add to Ruvon PostgresPersistenceProvider
4. Mark encryption as optional feature

---

### Phase 6: Update pyproject.toml (5 minutes)

```toml
[tool.poetry.dependencies]
# ... existing ...

# Celery support
celery = {version = "^5.3", optional = true}
redis = {version = "^4.5", optional = true}
prometheus-client = {version = "^0.17", optional = true}  # For metrics

[tool.poetry.extras]
celery = ["celery", "redis", "prometheus-client"]
all = [
    "fastapi", "uvicorn", "starlette", "slowapi",
    "asyncpg", "rich", "uvloop",
    "websockets", "psutil", "numpy",
    "celery", "redis", "prometheus-client"
]
```

---

## 📁 File Structure After Extraction

```
ruvon-sdk/
├── src/
│   └── ruvon/
│       ├── celery_app.py              # ← From Confucius
│       ├── tasks.py                   # ← From Confucius (8 tasks)
│       ├── worker_registry.py         # ← From Confucius
│       ├── postgres_executor.py       # ← From Confucius
│       ├── events.py                  # ← From Confucius
│       ├── implementations/
│       │   └── execution/
│       │       └── celery_executor.py # ← New (uses tasks.py)
│       └── alembic/
│           └── versions/
│               ├── 002_celery_support.sql     # ← From Confucius 001
│               ├── 003_scheduled_workflows.sql # ← From Confucius 002
│               └── 004_worker_registry.sql    # ← From Confucius 005
└── celery_app.py                      # ← Root-level for celery CLI
```

---

## 🔄 Step-by-Step Extraction Process

### Step 1: Copy Worker Registry (Zero Dependencies)

```bash
# This file has NO Confucius dependencies
cp confucius/src/confucius/worker_registry.py \
   src/ruvon/worker_registry.py

# Update logger name
sed -i '' 's/confucius.worker_registry/ruvon.worker_registry/g' \
   src/ruvon/worker_registry.py
```

**Test:**
```python
from ruvon.worker_registry import WorkerRegistry
import os

db_url = os.environ['DATABASE_URL']
registry = WorkerRegistry(db_url)
registry.register()
# Should register worker in database
```

---

### Step 2: Copy PostgreSQL Executor

```bash
cp confucius/src/confucius/postgres_executor.py \
   src/ruvon/postgres_executor.py

# No changes needed - utility module
```

---

### Step 3: Extract Celery Tasks

```bash
cp confucius/src/confucius/tasks.py \
   src/ruvon/tasks.py

# Update imports
sed -i '' 's/from confucius./from ruvon./g' src/ruvon/tasks.py
sed -i '' 's/import confucius./import ruvon./g' src/ruvon/tasks.py
```

**Manual updates needed:**
1. Import `WorkflowBuilder` from `ruvon.builder`
2. Import `PostgresPersistenceProvider` from `ruvon.implementations.persistence.postgres`
3. Update `event_publisher` imports if using events

---

### Step 4: Extract Celery App

```bash
cp confucius/src/confucius/celery_app.py \
   src/ruvon/celery_app.py

# Update imports
sed -i '' 's/from confucius./from ruvon./g' src/ruvon/celery_app.py
sed -i '' 's/import confucius./import ruvon./g' src/ruvon/celery_app.py
```

**Also create root-level celery_app.py:**
```python
# Root celery_app.py (for celery CLI)
from src.ruvon.celery_app import celery_app

__all__ = ['celery_app']
```

---

### Step 5: Extract Event Publishing (Optional)

```bash
cp confucius/src/confucius/events.py \
   src/ruvon/events.py

# Update logger
sed -i '' 's/confucius.events/ruvon.events/g' src/ruvon/events.py
```

---

### Step 6: Create Celery Execution Provider

Create `src/ruvon/implementations/execution/celery_executor.py` using code from Phase 2 above.

---

### Step 7: Copy Database Migrations

```bash
# Create Alembic migration that includes Confucius SQL
cd src/ruvon/alembic/versions

# Create new migration
alembic revision -m "Add Celery support tables"

# Edit the migration file to include SQL from Confucius migrations
```

---

## 🧪 Testing Plan

### Test 1: Worker Registration

```python
import asyncio
from ruvon.worker_registry import WorkerRegistry

async def test_registry():
    registry = WorkerRegistry("postgresql://...")
    registry.register()
    # Check worker_nodes table
    registry.deregister()

asyncio.run(test_registry())
```

### Test 2: Async Task Execution

```python
from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
from ruvon.implementations.execution.celery_executor import CeleryExecutionProvider
from ruvon.celery_app import celery_app

async def test_async_workflow():
    persistence = PostgresPersistenceProvider(db_url)
    await persistence.initialize()

    execution = CeleryExecutionProvider(celery_app)

    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=execution
    )

    workflow = await builder.create_workflow(
        workflow_type="TestWorkflow",
        initial_data={"test": "data"}
    )

    # Async step should dispatch to Celery
    await workflow.next_step()

    print(f"Workflow {workflow.id} dispatched to Celery")

asyncio.run(test_async_workflow())
```

### Test 3: Sub-Workflow

```python
# Define workflow with sub-workflow step
# Execute and verify child workflow created
# Verify parent resumes when child completes
```

---

## 📊 Comparison: Confucius vs Ruvon Architecture

| Component | Confucius | Ruvon | Action |
|-----------|-----------|-------|--------|
| **Core Engine** | `workflow.py` (step types) | `workflow.py` (similar) | ✅ Compare, enhance Ruvon |
| **Builder** | `workflow_loader.py` | `builder.py` | ✅ Already similar |
| **Persistence** | `persistence_postgres.py` | `postgres.py` | ⚠️ Enhance Ruvon with Confucius features |
| **Celery Tasks** | `tasks.py` (8 tasks) | ❌ Missing | 🔧 Extract |
| **Celery App** | `celery_app.py` | ❌ Missing | 🔧 Extract |
| **Worker Registry** | `worker_registry.py` | ❌ Missing | 🔧 Extract |
| **Events** | `events.py` (Redis) | ❌ Missing | 🔧 Extract (optional) |
| **Migrations** | 5 SQL files | 1 baseline | 🔧 Port to Alembic |
| **Async Executor** | `postgres_executor.py` | ❌ Missing | 🔧 Extract |
| **HTTP Steps** | In tasks.py | ❌ Missing task | 🔧 Extract |

---

## ⚡ Quick Start (Minimal Viable Implementation)

**30-Minute MVP:**

1. **Copy 3 files:**
   ```bash
   cp confucius/src/confucius/worker_registry.py src/ruvon/
   cp confucius/src/confucius/postgres_executor.py src/ruvon/
   cp confucius/src/confucius/tasks.py src/ruvon/
   ```

2. **Update imports** in `tasks.py`:
   ```bash
   sed -i '' 's/from confucius./from ruvon./g' src/ruvon/tasks.py
   ```

3. **Create minimal celery_app.py:**
   ```python
   # src/ruvon/celery_app.py
   from celery import Celery
   import os

   celery_app = Celery('ruvon')
   celery_app.conf.update(
       broker_url=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
       result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
       include=['ruvon.tasks'],
   )
   ```

4. **Test:**
   ```bash
   celery -A src.ruvon.celery_app worker --loglevel=info
   ```

---

## 🎯 Priority Order

### Must Have (Core Functionality):
1. ✅ `worker_registry.py` - Fleet management
2. ✅ `postgres_executor.py` - Async-safe PostgreSQL
3. ✅ `tasks.py` - 8 Celery tasks
4. ✅ `celery_app.py` - Celery configuration
5. ✅ `celery_executor.py` - ExecutionProvider implementation

### Should Have (Production Features):
6. ⚠️ Database migrations - Task queue, compensation log, metrics
7. ⚠️ Enhanced persistence - Encryption, advanced logging
8. ⚠️ Event publishing - Redis Pub/Sub for monitoring

### Nice to Have (Advanced Features):
9. 📊 Scheduled workflows - Cron support
10. 📊 Worker CLI commands - `ruvon worker start/stop`
11. 📊 Monitoring dashboards - Prometheus metrics

---

## 🚀 Implementation Timeline

| Phase | Time | What |
|-------|------|------|
| **Phase 1** | 2-3 hours | Copy & update core files (tasks, worker_registry, celery_app) |
| **Phase 2** | 1 hour | Create CeleryExecutionProvider |
| **Phase 3** | 30 min | Port database migrations |
| **Phase 4** | 1 hour | Extract event publishing (optional) |
| **Phase 5** | 2 hours | Enhance persistence (optional) |
| **Testing** | 2 hours | Integration testing |
| **Total** | **6-9 hours** | Production-ready Celery support |

---

## 🎁 Bonus: What You Get for Free

By extracting Confucius code, you get:

- ✅ **Battle-tested** - 5+ years production use
- ✅ **Complete** - All 8 task types covered
- ✅ **Scalable** - Regional routing, worker fleet
- ✅ **Observable** - Events, metrics, logging
- ✅ **Reliable** - Idempotency, retry logic
- ✅ **Safe** - Async-safe PostgreSQL access
- ✅ **Monitored** - Worker health tracking

---

## 🤔 Decision: Start Now or Plan More?

**Option A: Start extracting immediately** (recommended)
- Begin with Phase 1 (core files)
- Get Celery workers running in 2-3 hours
- Iterate on enhancements

**Option B: Deep dive comparison**
- Compare Confucius workflow.py vs Ruvon workflow.py
- Identify all differences
- Plan unified architecture
- Higher upfront cost, better long-term result

**Recommendation:** Start with Option A, since Confucius code is proven and Ruvon architecture is already similar.

---

**Ready to begin extraction?** I can start copying files and updating imports now.
