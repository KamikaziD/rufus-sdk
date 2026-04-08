# Advanced: Executor Portability

**Critical Warning:** Step functions must be **stateless and process-isolated** to work across all executors.

---

## The Problem

Developers often test with `SyncExecutionProvider` (single process, shared memory) and deploy with `CeleryExecutor` (distributed, fresh process per task). Code that works locally breaks in production because:

- **SyncExecutor**: All steps run in the same Python process. Global variables, module-level state, and in-memory caches are shared.
- **CeleryExecutor/ThreadPoolExecutor**: Each step runs in a separate worker process/thread. No shared memory.

---

## Common Pitfalls

### 1. Global State Lost Between Steps

```python
# ❌ BREAKS in CeleryExecutor - global state lost between steps
global_cache = {}

def step_a(state: MyState, context: StepContext):
    global_cache['user_data'] = fetch_user(state.user_id)
    return {}

def step_b(state: MyState, context: StepContext):
    user_data = global_cache['user_data']  # KeyError in Celery!
    return {"name": user_data['name']}
```

**Why it fails:**
- `step_a` runs in Celery worker process #1, sets `global_cache`
- `step_b` runs in Celery worker process #2, `global_cache` is empty
- **Result**: `KeyError: 'user_data'`

**Fix: Store in workflow state**

```python
# ✅ WORKS everywhere - state persisted in workflow state
def step_a_correct(state: MyState, context: StepContext):
    user_data = fetch_user(state.user_id)
    state.user_data = user_data  # Persisted to database
    return {"user_data": user_data}

def step_b_correct(state: MyState, context: StepContext):
    user_data = state.user_data  # Loaded from database
    return {"name": user_data['name']}
```

---

### 2. Module-Level State

```python
# ❌ BREAKS in CeleryExecutor - module-level state lost
_connection = None

def step_c(state: MyState, context: StepContext):
    global _connection
    if _connection is None:
        _connection = create_db_connection()  # Created in worker process
    _connection.query(...)  # Different worker, _connection is None!
```

**Why it fails:**
- Each Celery worker imports the module fresh
- `_connection` is `None` in every worker process
- **Result**: New connection created for every task (connection leak!)

**Fix: Create resources per step**

```python
# ✅ WORKS everywhere - return data to workflow state
def step_c_correct(state: MyState, context: StepContext):
    # Create connection per step (Celery worker will clean up)
    connection = create_db_connection()
    result = connection.query(...)
    connection.close()  # Clean up
    return {"query_result": result}  # Result saved to state
```

---

### 3. In-Memory Caching

```python
# ❌ BREAKS in CeleryExecutor - cache not shared
from functools import lru_cache

@lru_cache(maxsize=100)
def get_user_settings(user_id: str):
    """Cache user settings in memory"""
    return fetch_from_db(user_id)

def step_d(state: MyState, context: StepContext):
    settings = get_user_settings(state.user_id)  # Cache miss in every worker!
    return {"settings": settings}
```

**Why it fails:**
- Each Celery worker has its own LRU cache
- Cache misses in every worker process
- **Result**: Cache ineffective, database hit for every task

**Fix: Use external cache (Redis)**

```python
# ✅ WORKS everywhere - external cache shared across workers
import redis

redis_client = redis.Redis(host='localhost', port=6379)

def get_user_settings(user_id: str):
    """Cache user settings in Redis"""
    cached = redis_client.get(f"user:{user_id}:settings")
    if cached:
        return json.loads(cached)

    settings = fetch_from_db(user_id)
    redis_client.setex(f"user:{user_id}:settings", 300, json.dumps(settings))
    return settings

def step_d_correct(state: MyState, context: StepContext):
    settings = get_user_settings(state.user_id)  # Shared cache
    return {"settings": settings}
```

---

### 4. File System State

```python
# ❌ BREAKS in CeleryExecutor - workers on different machines
def step_e(state: MyState, context: StepContext):
    # Write to local file
    with open("/tmp/workflow_data.json", "w") as f:
        json.dump({"user_id": state.user_id}, f)
    return {}

def step_f(state: MyState, context: StepContext):
    # Read from local file
    with open("/tmp/workflow_data.json", "r") as f:
        data = json.load(f)  # FileNotFoundError on different worker!
    return {"user_id": data["user_id"]}
```

**Why it fails:**
- Celery workers may run on different machines
- File written on worker #1 not accessible on worker #2
- **Result**: `FileNotFoundError`

**Fix: Use shared storage (S3, database)**

```python
# ✅ WORKS everywhere - shared storage
def step_e_correct(state: MyState, context: StepContext):
    # Write to S3 or database
    s3.put_object(
        Bucket='workflow-data',
        Key=f'{state.workflow_id}/data.json',
        Body=json.dumps({"user_id": state.user_id})
    )
    return {}

def step_f_correct(state: MyState, context: StepContext):
    # Read from S3 or database
    obj = s3.get_object(
        Bucket='workflow-data',
        Key=f'{state.workflow_id}/data.json'
    )
    data = json.loads(obj['Body'].read())
    return {"user_id": data["user_id"]}
```

---

### 5. Singleton Pattern

```python
# ❌ BREAKS in CeleryExecutor - singleton per worker, not global
class ConfigManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.config = load_config()  # Expensive operation

def step_g(state: MyState, context: StepContext):
    config = ConfigManager.get_instance()  # New instance in each worker!
    return {"config": config.config}
```

**Why it fails:**
- Each Celery worker creates its own singleton
- Defeats the purpose of singleton (one instance)
- **Result**: Multiple instances, high memory usage

**Fix: Load config per step or use environment variables**

```python
# ✅ WORKS everywhere - load from environment
import os

def step_g_correct(state: MyState, context: StepContext):
    config = {
        "api_key": os.getenv("API_KEY"),
        "api_url": os.getenv("API_URL"),
    }
    return {"config": config}

# Or load from external config service (etcd, Consul)
def step_g_better(state: MyState, context: StepContext):
    config = consul_client.get("app/config")  # Shared across workers
    return {"config": config}
```

---

## Testing for Portability

### Strategy 1: Test with ThreadPoolExecutor

ThreadPoolExecutor is closer to Celery's behavior (separate threads, less shared state):

```python
import pytest
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.execution.thread_pool import ThreadPoolExecutionProvider

@pytest.mark.parametrize("executor", [
    SyncExecutor(),
    ThreadPoolExecutionProvider()  # Closer to Celery behavior
])
def test_workflow_executor_portable(executor):
    """Test that workflow works with both sync and threaded execution."""
    builder = WorkflowBuilder(
        config_dir="config/",
        execution_provider=executor
    )
    workflow = builder.create_workflow("MyWorkflow", initial_data={...})

    # Run workflow - should work with both executors
    while workflow.status == "ACTIVE":
        result = await workflow.next_step()

    assert workflow.status == "COMPLETED"
```

**If test passes with ThreadPoolExecutor, likely works with Celery.**

---

### Strategy 2: Lint for Global State

Use static analysis to detect global variables:

```bash
# Custom linter (pseudocode)
grep -r "^[A-Z_]* = " your_workflow_steps/  # Find module-level constants
grep -r "global " your_workflow_steps/       # Find global keyword usage
```

Or use pylint:

```bash
pylint --disable=all --enable=global-statement your_workflow_steps/
```

---

### Strategy 3: Run Tests with CELERY_ALWAYS_EAGER

Celery's eager mode runs tasks synchronously but still imports modules fresh:

```python
# conftest.py
import pytest
from celery import Celery

@pytest.fixture(scope="session")
def celery_config():
    return {
        "task_always_eager": True,  # Run tasks synchronously
        "task_eager_propagates": True,  # Propagate exceptions
    }
```

**Not perfect** (still same process), but helps catch import issues.

---

## Best Practices

### ✅ Do:

1. **Store everything in workflow state**
   ```python
   state.user_data = fetch_user(state.user_id)
   ```

2. **Return data from steps**
   ```python
   return {"user_data": user_data}  # Merged into state
   ```

3. **Create resources per step**
   ```python
   connection = create_db_connection()
   # ... use connection ...
   connection.close()
   ```

4. **Use external caching (Redis, Memcached)**
   ```python
   redis_client.set(f"key:{id}", value)
   ```

5. **Use environment variables for config**
   ```python
   API_KEY = os.getenv("API_KEY")
   ```

6. **Test with ThreadPoolExecutor before Celery**
   ```python
   executor = ThreadPoolExecutionProvider()
   ```

---

### ❌ Don't:

1. **Use global variables**
   ```python
   global_cache = {}  # ❌ Won't work in Celery
   ```

2. **Use module-level state**
   ```python
   _connection = None  # ❌ New instance per worker
   ```

3. **Use in-memory caching**
   ```python
   @lru_cache  # ❌ Cache per worker, not shared
   ```

4. **Write to local file system**
   ```python
   open("/tmp/data.json", "w")  # ❌ Not accessible across workers
   ```

5. **Use singleton pattern**
   ```python
   class Singleton:  # ❌ Singleton per worker
       _instance = None
   ```

6. **Assume step functions share memory**
   ```python
   # ❌ step_a's variables not visible in step_b
   ```

---

## Migration Guide

### Convert Non-Portable Code

**Before (Non-Portable):**

```python
# Global state
user_cache = {}

def fetch_user_step(state: OrderState, context: StepContext):
    global user_cache
    user = fetch_user_from_api(state.user_id)
    user_cache[state.user_id] = user
    return {}

def process_order_step(state: OrderState, context: StepContext):
    global user_cache
    user = user_cache[state.user_id]  # KeyError in Celery!
    # ... process order ...
```

**After (Portable):**

```python
# No global state

def fetch_user_step(state: OrderState, context: StepContext):
    user = fetch_user_from_api(state.user_id)
    state.user_data = user  # Store in state
    return {"user_data": user}

def process_order_step(state: OrderState, context: StepContext):
    user = state.user_data  # Load from state
    # ... process order ...
```

---

### Convert In-Memory Cache to Redis

**Before:**

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_config(key: str):
    return expensive_config_lookup(key)

def step(state: MyState, context: StepContext):
    config = get_config("api_url")  # Cache miss in every worker
```

**After:**

```python
import redis
redis_client = redis.Redis(host='redis', port=6379)

def get_config(key: str):
    cached = redis_client.get(f"config:{key}")
    if cached:
        return cached.decode()

    value = expensive_config_lookup(key)
    redis_client.setex(f"config:{key}", 3600, value)
    return value

def step(state: MyState, context: StepContext):
    config = get_config("api_url")  # Shared cache across workers
```

---

## Quick Check: Is Your Code Portable?

Ask yourself:

1. ❓ **Do I use `global` keyword?** → ❌ Not portable
2. ❓ **Do I modify module-level variables?** → ❌ Not portable
3. ❓ **Do I use `@lru_cache` or similar?** → ❌ Not portable
4. ❓ **Do I write to local file system?** → ❌ Not portable
5. ❓ **Do I use singletons?** → ❌ Not portable
6. ❓ **Do I store data in `state` object?** → ✅ Portable
7. ❓ **Do I return dict from step functions?** → ✅ Portable
8. ❓ **Do I use Redis/external cache?** → ✅ Portable
9. ❓ **Do I create resources per step?** → ✅ Portable

If you answered ❌ to any of 1-5, **your code will break in distributed execution**.

---

## Real-World Example

### Non-Portable (Works in SyncExecutor, Breaks in Celery)

```python
# Module-level connection pool
db_pool = create_db_pool()

def step_a(state: OrderState, context: StepContext):
    # Uses module-level pool
    with db_pool.get_connection() as conn:
        user = conn.query("SELECT * FROM users WHERE id = ?", state.user_id)
    state.user_name = user['name']
    return {}

def step_b(state: OrderState, context: StepContext):
    # Uses module-level pool
    with db_pool.get_connection() as conn:
        conn.execute("INSERT INTO orders ...", state.order_id)
    return {}
```

**Problem in Celery:**
- Each worker creates its own `db_pool`
- High memory usage (N workers × pool size)
- Connection leaks if workers crash

---

### Portable (Works Everywhere)

```python
# No module-level state

def get_db_connection():
    """Create connection per-step"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

def step_a(state: OrderState, context: StepContext):
    conn = get_db_connection()
    try:
        user = conn.query("SELECT * FROM users WHERE id = ?", state.user_id)
        state.user_name = user['name']
        return {}
    finally:
        conn.close()

def step_b(state: OrderState, context: StepContext):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO orders ...", state.order_id)
        return {}
    finally:
        conn.close()
```

**Or use connection from context:**

```python
def step_a(state: OrderState, context: StepContext):
    # PersistenceProvider has connection pooling
    async with context.persistence.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", state.user_id)
    state.user_name = user['name']
    return {}
```

---

## Summary

**Golden Rule**: Treat each step function as an **isolated, stateless function**.

- ✅ Input: `state` (from database), `context`, `user_input`
- ✅ Output: `dict` (merged into state)
- ❌ No shared memory, global variables, or module-level state

**If you follow this rule, your workflows work everywhere:**
- SyncExecutor (development)
- ThreadPoolExecutor (testing)
- CeleryExecutor (production)
- Kubernetes (horizontal scaling)

**Test early, test often** with ThreadPoolExecutor to catch issues before production.
