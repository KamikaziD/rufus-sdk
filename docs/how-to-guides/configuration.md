# How to configure Ruvon

This guide covers configuring persistence, execution, and observability providers.

## Configuration overview

Ruvon uses provider interfaces to abstract external dependencies:

- **PersistenceProvider** - Where workflow state is stored (SQLite, PostgreSQL, Redis)
- **ExecutionProvider** - How steps are executed (Sync, Thread Pool, Celery)
- **WorkflowObserver** - Event logging and monitoring

## Configure persistence

### SQLite (development)

Use SQLite for development and testing with zero infrastructure:

```python
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider

# In-memory database (ephemeral)
persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

# File-based database (persistent)
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()
```

**Configuration options:**

```python
SQLitePersistenceProvider(
    db_path: str = ":memory:",        # Database file path or ":memory:"
    timeout: float = 5.0,              # Lock timeout in seconds
    check_same_thread: bool = False    # Allow multi-threaded access
)
```

**CLI configuration:**

```bash
ruvon config set-persistence
# Choose: SQLite
# Database path: workflow.db

ruvon db init
```

### PostgreSQL (production)

Use PostgreSQL for production deployments with high concurrency:

```python
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(
    db_url="postgresql://user:pass@localhost:5432/dbname",
    pool_min_size=10,
    pool_max_size=50
)
await persistence.initialize()
```

**Configuration options:**

```python
PostgresPersistenceProvider(
    db_url: str,                       # PostgreSQL connection URL
    pool_min_size: int = 10,           # Minimum pool connections
    pool_max_size: int = 50,           # Maximum pool connections
    pool_command_timeout: int = 10,    # Command timeout (seconds)
    pool_max_queries: int = 50000,     # Queries before connection recycling
    pool_max_inactive_lifetime: int = 300  # Max inactive time (seconds)
)
```

**Environment variables:**

```bash
export POSTGRES_POOL_MIN_SIZE=10
export POSTGRES_POOL_MAX_SIZE=50
export POSTGRES_POOL_COMMAND_TIMEOUT=10
export POSTGRES_POOL_MAX_QUERIES=50000
export POSTGRES_POOL_MAX_INACTIVE_LIFETIME=300
```

**Apply database migrations:**

```bash
cd src/ruvon
export DATABASE_URL="postgresql://user:pass@localhost:5432/dbname"
alembic upgrade head
```

### Redis (alternative)

Use Redis for fast in-memory persistence:

```python
from ruvon.implementations.persistence.redis import RedisPersistenceProvider

persistence = RedisPersistenceProvider(
    redis_url="redis://localhost:6379/0"
)
await persistence.initialize()
```

## Configure execution

### Synchronous executor (testing)

Execute all steps synchronously in a single process:

```python
from ruvon.implementations.execution.sync import SyncExecutionProvider

execution = SyncExecutionProvider()
```

Best for: Testing, simple workflows, debugging

### Thread pool executor (parallel)

Execute steps in parallel using thread pools:

```python
from ruvon.implementations.execution.thread_pool import ThreadPoolExecutionProvider

execution = ThreadPoolExecutionProvider(
    max_workers=10  # Number of worker threads
)
```

Best for: CPU-bound tasks, moderate parallelism

### Celery executor (distributed)

Execute steps across distributed workers:

```python
from ruvon.implementations.execution.celery import CeleryExecutionProvider

execution = CeleryExecutionProvider(
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/0"
)
```

**Environment variables:**

```bash
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"
```

**Start Celery worker:**

```bash
celery -A ruvon.celery_app worker --loglevel=info --concurrency=4
```

Best for: High concurrency, distributed systems, async tasks

### PostgreSQL executor (queue-based)

Execute steps using PostgreSQL-backed task queue:

```python
from ruvon.implementations.execution.postgres_executor import PostgresExecutionProvider

execution = PostgresExecutionProvider(
    db_url="postgresql://user:pass@localhost:5432/dbname"
)
```

Best for: PostgreSQL-only deployments, no external queue needed

## Configure observability

### Logging observer (console)

Log workflow events to console:

```python
from ruvon.implementations.observability.logging import LoggingObserver

observer = LoggingObserver()
```

## Build workflow with providers

Combine providers using WorkflowBuilder:

```python
from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.execution.sync import SyncExecutionProvider
from ruvon.implementations.observability.logging import LoggingObserver

# Initialize providers
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()

execution = SyncExecutionProvider()
observer = LoggingObserver()

# Create builder
builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    execution_provider=execution,
    observer=observer
)

# Create workflow
workflow = await builder.create_workflow(
    workflow_type="MyWorkflow",
    initial_data={"user_id": "123"}
)
```

## Configuration profiles

### Development profile

```python
# Fast, zero infrastructure
persistence = SQLitePersistenceProvider(db_path=":memory:")
execution = SyncExecutionProvider()
observer = LoggingObserver()
```

### Testing profile

```python
# In-memory, synchronous for predictable tests
persistence = SQLitePersistenceProvider(db_path=":memory:")
execution = SyncExecutionProvider()
observer = LoggingObserver()
```

### Production profile (single server)

```python
# PostgreSQL with thread pool
persistence = PostgresPersistenceProvider(
    db_url="postgresql://...",
    pool_min_size=10,
    pool_max_size=50
)
execution = ThreadPoolExecutionProvider(max_workers=20)
observer = LoggingObserver()
```

### Production profile (distributed)

```python
# PostgreSQL with Celery
persistence = PostgresPersistenceProvider(
    db_url="postgresql://...",
    pool_min_size=20,
    pool_max_size=100
)
execution = CeleryExecutionProvider(
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/0"
)
observer = LoggingObserver()
```

## Performance tuning

### PostgreSQL connection pool

**Low concurrency** (< 10 concurrent workflows):
```bash
export POSTGRES_POOL_MIN_SIZE=5
export POSTGRES_POOL_MAX_SIZE=20
```

**Medium concurrency** (10-100 concurrent workflows):
```bash
export POSTGRES_POOL_MIN_SIZE=10
export POSTGRES_POOL_MAX_SIZE=50
```

**High concurrency** (> 100 concurrent workflows):
```bash
export POSTGRES_POOL_MIN_SIZE=20
export POSTGRES_POOL_MAX_SIZE=100
```

### Disable optimizations (debugging)

```bash
export RUVON_USE_UVLOOP=false  # Use stdlib asyncio
export RUVON_USE_ORJSON=false  # Use stdlib json
```

## CLI configuration

### View current configuration

```bash
ruvon config show
```

### Set persistence provider

```bash
ruvon config set-persistence
# Interactive prompts for SQLite or PostgreSQL
```

### Set execution provider

```bash
ruvon config set-execution
# Interactive prompts for sync or thread_pool
```

### Reset to defaults

```bash
ruvon config reset
```

### Show config file location

```bash
ruvon config path
```

## Next steps

- [Create your first workflow](create-workflow.md)
- [Deploy to production](deployment.md)
- [Test your configuration](testing.md)

## See also

- [Installation guide](installation.md)
- [Deployment guide](deployment.md)
- CLAUDE.md for configuration reference
