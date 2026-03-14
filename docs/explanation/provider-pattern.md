# The Provider Pattern

Rufus SDK is built on the provider pattern—a dependency injection approach that makes the engine pluggable, testable, and adaptable to different environments.

## Why Providers?

Before Rufus, Confucius hardcoded dependencies:

```python
# Confucius: Hardcoded Redis and Celery
class Workflow:
    def __init__(self, ...):
        # HARDCODED: Always uses Redis
        self.persistence = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0")
        )

        # HARDCODED: Always uses Celery
        from .tasks import execute_async_task
        self.async_executor = execute_async_task
```

This created several problems:

1. **Testing was hard**: Every test required Redis and Celery infrastructure
2. **No flexibility**: Couldn't use PostgreSQL or SQLite without rewriting code
3. **Edge deployment impossible**: Can't run Celery on a POS terminal
4. **Tight coupling**: Changing storage backend meant changing workflow engine code

The provider pattern solves all of these by **abstracting external dependencies behind interfaces**.

## What is a Provider?

A provider is an object that implements a well-defined interface (Python Protocol) for a specific concern:

```python
from typing import Protocol, Dict, Optional

class PersistenceProvider(Protocol):
    """Interface for workflow state storage."""

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict) -> None:
        """Save workflow state to storage."""
        ...

    async def load_workflow(self, workflow_id: str) -> Optional[Dict]:
        """Load workflow state from storage."""
        ...

    # + 15 more methods
```

Any class that implements these methods can be used as a persistence provider, even if it doesn't explicitly inherit from a base class.

## The Three Core Providers

Rufus has three main provider interfaces:

### 1. PersistenceProvider

**Responsibility**: Storage and retrieval of workflow state, audit logs, and metrics.

**Interface** (`src/rufus/providers/persistence.py`):
```python
class PersistenceProvider(Protocol):
    async def save_workflow(...)
    async def load_workflow(...)
    async def list_workflows(...)
    async def create_task(...)
    async def claim_next_task(...)
    async def log_execution(...)
    async def record_metric(...)
    # ... and more
```

**Implementations**:
- **PostgresPersistenceProvider**: Production storage with ACID guarantees
- **SQLitePersistenceProvider**: Embedded storage for edge devices and development
- **MemoryPersistenceProvider**: In-memory storage for testing
- **RedisPersistenceProvider**: Redis-backed storage (legacy from Confucius)

**Why Multiple Implementations?**
- **PostgreSQL**: Cloud deployments need ACID transactions, connection pooling, and scalability
- **SQLite**: Edge devices need embedded storage with no external dependencies
- **In-Memory**: Tests need fast, ephemeral storage with no setup/teardown

### 2. ExecutionProvider

**Responsibility**: Dispatching and executing workflow steps.

**Interface** (`src/rufus/providers/execution.py`):
```python
class ExecutionProvider(Protocol):
    def dispatch_async_task(...)
    def dispatch_parallel_tasks(...)
    def execute_sync_step_function(...)
    def dispatch_sub_workflow(...)
    async def report_child_status_to_parent(...)
    # ... and more
```

**Implementations**:
- **SyncExecutionProvider**: Execute steps inline (same process, same thread)
- **CeleryExecutionProvider**: Dispatch steps to Celery workers (distributed)
- **ThreadPoolExecutionProvider**: Execute parallel steps in thread pool
- **PostgresExecutorProvider**: PostgreSQL-backed task queue

**Why Multiple Implementations?**
- **Sync**: Development and debugging need deterministic, single-threaded execution
- **Celery**: Production needs distributed workers, retry logic, and fault tolerance
- **ThreadPool**: Edge devices need parallelism without Celery overhead

### 3. WorkflowObserver

**Responsibility**: Observability hooks for workflow events.

**Interface** (`src/rufus/providers/observer.py`):
```python
class WorkflowObserver(Protocol):
    def on_workflow_started(...)
    def on_step_executed(...)
    def on_workflow_completed(...)
    def on_workflow_failed(...)
    def on_workflow_status_changed(...)
    # ... and more
```

**Implementations**:
- **LoggingObserver**: Log events to console/file
- **PrometheusObserver**: Emit Prometheus metrics
- **NoOpObserver**: Do nothing (for performance-critical scenarios)

**Why Multiple Implementations?**
- **Logging**: Development needs rich console output for debugging
- **Prometheus**: Production needs metrics for monitoring and alerting
- **NoOp**: High-performance scenarios want zero observability overhead

## How Providers Work

### Dependency Injection

The Workflow class receives providers via constructor injection:

```python
# src/rufus/workflow.py
class Workflow:
    def __init__(
        self,
        persistence: PersistenceProvider,
        execution: ExecutionProvider,
        observer: WorkflowObserver,
        ...
    ):
        self.persistence = persistence
        self.execution = execution
        self.observer = observer
```

The engine doesn't create these objects—they're passed in by the caller. This is **Dependency Injection**.

### Usage Example

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.implementations.observability.logging import LoggingObserver

# Create providers
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()

execution = SyncExecutionProvider()
observer = LoggingObserver()

# Inject into builder
builder = WorkflowBuilder(
    config_dir="config/",
)

# Create workflow with injected providers
workflow = await builder.create_workflow(
    workflow_type="MyWorkflow",
    persistence_provider=persistence,
    execution_provider=execution,
    workflow_observer=observer,
    workflow_builder=builder,
    initial_data={"user_id": "123"},
)
```

Now the workflow uses SQLite for storage, synchronous execution, and console logging. To switch to production mode:

```python
# Production providers
persistence = PostgresPersistenceProvider(db_url="postgresql://...")
execution = CeleryExecutionProvider()
observer = PrometheusObserver()

# Same code, different behavior
builder = WorkflowBuilder(
    config_dir="config/",
)
# Pass providers to create_workflow() instead
```

The workflow code doesn't change—only the providers.

## Benefits of the Provider Pattern

### 1. Testability

Tests can use fast, ephemeral in-memory providers:

```python
@pytest.fixture
async def test_persistence():
    provider = MemoryPersistenceProvider()
    yield provider
    # No cleanup needed - in-memory

def test_workflow_execution(test_persistence):
    builder = WorkflowBuilder(
        config_dir="config/",
    )
    # Pass providers to create_workflow() — test runs fast, no Redis/PostgreSQL required
```

### 2. Flexibility

Different deployments use different providers without code changes:

```python
# Edge device
persistence = SQLitePersistenceProvider(db_path="/var/lib/rufus/workflows.db")
execution = ThreadPoolExecutionProvider(max_workers=4)

# Cloud deployment
persistence = PostgresPersistenceProvider(db_url=os.environ["DATABASE_URL"])
execution = CeleryExecutionProvider()
```

### 3. Loose Coupling

The workflow engine knows nothing about PostgreSQL, Celery, or Prometheus. It only knows about provider interfaces. This means:
- Engine can evolve independently of implementations
- New storage backends can be added without changing the engine
- Third-party providers can be created without modifying Rufus

### 4. Performance Optimization

Different scenarios can optimize differently:

```python
# Development: Rich observability
observer = LoggingObserver(level="DEBUG")

# Production: Metrics only
observer = PrometheusObserver()

# Performance-critical: No observability overhead
observer = NoOpObserver()
```

## Implementation Details

### Protocol vs ABC

Rufus uses Python Protocols (PEP 544) instead of Abstract Base Classes:

```python
# Protocol (structural subtyping)
class PersistenceProvider(Protocol):
    async def save_workflow(self, workflow_id: str, workflow_dict: Dict) -> None: ...

# Any class with this method is a valid provider
class MyCustomPersistence:
    async def save_workflow(self, workflow_id: str, workflow_dict: Dict) -> None:
        # Custom implementation
        ...

# Works! No inheritance needed
persistence = MyCustomPersistence()
```

**Why Protocols?**
- **Flexibility**: Don't need to inherit from a base class
- **Duck typing**: If it has the right methods, it works
- **Type safety**: Still get type checking with mypy/pyright

### Provider Lifecycle

Most providers require initialization:

```python
# Create provider
persistence = PostgresPersistenceProvider(db_url="postgresql://...")

# Initialize (connects to database, creates pool)
await persistence.initialize()

# Use provider
await persistence.save_workflow(...)

# Cleanup (closes connections, releases resources)
await persistence.close()
```

The builder handles this for you:

```python
builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence  # Builder calls initialize() automatically
)
```

## Common Provider Patterns

### Composite Providers

Combine multiple providers for different purposes:

```python
class MultiObserver(WorkflowObserver):
    """Broadcast events to multiple observers."""

    def __init__(self, observers: List[WorkflowObserver]):
        self.observers = observers

    def on_step_executed(self, workflow_id, step_name, result):
        for observer in self.observers:
            observer.on_step_executed(workflow_id, step_name, result)

# Use both logging and metrics
observer = MultiObserver([
    LoggingObserver(),
    PrometheusObserver()
])
```

### Decorator Providers

Wrap providers to add behavior:

```python
class CachingPersistenceProvider:
    """Cache workflow state in memory to reduce database queries."""

    def __init__(self, wrapped: PersistenceProvider):
        self.wrapped = wrapped
        self.cache = {}

    async def load_workflow(self, workflow_id: str):
        if workflow_id in self.cache:
            return self.cache[workflow_id]

        workflow = await self.wrapped.load_workflow(workflow_id)
        self.cache[workflow_id] = workflow
        return workflow

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict):
        self.cache[workflow_id] = workflow_dict
        await self.wrapped.save_workflow(workflow_id, workflow_dict)

# Use caching layer over PostgreSQL
persistence = CachingPersistenceProvider(
    PostgresPersistenceProvider(db_url="...")
)
```

### Fallback Providers

Try one provider, fall back to another:

```python
class FallbackPersistenceProvider:
    """Try primary, fall back to secondary on failure."""

    def __init__(self, primary: PersistenceProvider, fallback: PersistenceProvider):
        self.primary = primary
        self.fallback = fallback

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict):
        try:
            await self.primary.save_workflow(workflow_id, workflow_dict)
        except Exception as e:
            logger.warning(f"Primary save failed: {e}, using fallback")
            await self.fallback.save_workflow(workflow_id, workflow_dict)
```

## Creating Custom Providers

Let's create a custom persistence provider that stores workflows in a cloud object store:

```python
import boto3
import json
from typing import Dict, Optional
from rufus.providers.persistence import PersistenceProvider

class S3PersistenceProvider:
    """Store workflow state in AWS S3."""

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.s3 = boto3.client('s3')

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict) -> None:
        """Save workflow to S3."""
        key = f"workflows/{workflow_id}.json"
        body = json.dumps(workflow_dict)
        self.s3.put_object(Bucket=self.bucket_name, Key=key, Body=body)

    async def load_workflow(self, workflow_id: str) -> Optional[Dict]:
        """Load workflow from S3."""
        key = f"workflows/{workflow_id}.json"
        try:
            obj = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(obj['Body'].read())
        except self.s3.exceptions.NoSuchKey:
            return None

    # Implement remaining methods...
```

Use it just like any other provider:

```python
persistence = S3PersistenceProvider(bucket_name="my-workflows")
builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    ...
)
```

## Provider Configuration

Production deployments often configure providers via environment variables:

```python
import os
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

def get_persistence_provider():
    """Factory function to select provider based on environment."""
    backend = os.getenv("RUFUS_PERSISTENCE", "sqlite")

    if backend == "postgres":
        return PostgresPersistenceProvider(
            db_url=os.getenv("DATABASE_URL"),
            pool_min_size=int(os.getenv("DB_POOL_MIN", "10")),
            pool_max_size=int(os.getenv("DB_POOL_MAX", "50"))
        )
    elif backend == "sqlite":
        return SQLitePersistenceProvider(
            db_path=os.getenv("SQLITE_PATH", "workflows.db")
        )
    else:
        raise ValueError(f"Unknown persistence backend: {backend}")

# Use in application
persistence = get_persistence_provider()
await persistence.initialize()
```

## Provider Trade-offs

Different providers have different characteristics:

| Provider | Speed | Scalability | Offline Support | Setup |
|----------|-------|-------------|-----------------|-------|
| **PostgreSQL** | Fast | Excellent | ❌ | Medium |
| **SQLite** | Fast | Limited | ✅ | None |
| **In-Memory** | Fastest | Limited | ❌ | None |
| **Redis** | Very Fast | Good | ❌ | Easy |

Choose based on your deployment needs:
- **Development**: SQLite or In-Memory (fast iteration, no setup)
- **Production Cloud**: PostgreSQL (ACID, scalability, reliability)
- **Edge Devices**: SQLite (offline-first, no dependencies)
- **Testing**: In-Memory (fastest, no cleanup)

## What's Next

Now that you understand the provider pattern:
- [Architecture](architecture.md) - How providers fit into the overall system
- [State Management](state-management.md) - How persistence providers store state
- [Performance](performance.md) - Provider performance characteristics
