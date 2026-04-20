# System Architecture

Ruvon SDK is built on a layered architecture that separates concerns while remaining flexible enough to adapt to different deployment scenarios—from embedded edge devices to large-scale cloud deployments.

## Three Roles, One Runtime

The central architectural insight: **the same SDK powers all three deployment roles.** Only the persistence and execution backends differ.

```
┌────────────────────────────────────────────────────────────────┐
│                         Ruvon SDK (Core)                       │
│         WorkflowBuilder · Workflow · Providers · Steps         │
└─────────────┬──────────────────┬──────────────────┬───────────┘
              │                  │                  │
   ┌──────────▼──────┐  ┌───────▼────────┐  ┌─────▼──────────┐
   │  Device Runtime  │  │  Cloud Worker  │  │ Control Plane  │
   │                  │  │                │  │                │
   │  SQLite / WAL    │  │  PostgreSQL    │  │  PostgreSQL    │
   │  SyncExecution   │  │  Celery        │  │  Celery        │
   │  Offline-first   │  │  Horizontal    │  │  Fleet mgmt    │
   └──────────────────┘  └────────────────┘  └────────────────┘
```

**Device Runtime** — runs on POS terminals, ATMs, drones, surgical devices. SQLite in WAL mode, SyncExecutionProvider, operates indefinitely without network. Reconnects and syncs via Store-and-Forward.

**Cloud Worker** — distributed Celery workers processing ASYNC and PARALLEL steps. PostgreSQL for state, Redis for broker. Scales horizontally; used for the heavy computation and long-running tasks that don't need to run on-device.

**Control Plane** — FastAPI server with the full device management API (86 endpoints). Uses PostgreSQL + Celery for its own workflow steps. Configuration rollout, audit aggregation, and policy enforcement are themselves Ruvon workflows — the self-hosting model.

### The Self-Hosting Insight

There is no separate orchestration tier. The control plane that manages edge devices runs on the same SDK as those devices. This means:

- **No magic paths** — everything is a Ruvon workflow or a provider implementation
- **Battle-tested** — the control plane validates the SDK by running it in production
- **Consistent semantics** — saga rollback, zombie recovery, and versioning work identically on device and cloud

See [Self-Hosting](self-hosting.md) for a full explanation.

---

## High-Level Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Client Application                    │
└─────────────────────┬───────────────────────────────────┘
                      │
          ┌───────────▼──────────┐
          │   Ruvon SDK (Core)   │
          │  ┌──────────────┐    │
          │  │  Workflow    │    │
          │  │   Engine     │    │
          │  └──────┬───────┘    │
          │         │             │
          │  ┌──────▼───────┐    │
          │  │  Providers   │────┼──► PersistenceProvider
          │  │ (Protocols)  │    │    ExecutionProvider
          │  └──────┬───────┘    │    WorkflowObserver
          │         │             │
          │  ┌──────▼───────┐    │
          │  │Implementations│───┼──► PostgreSQL
          │  │              │    │    SQLite
          │  │              │    │    Celery
          │  └─────────────┘    │    ThreadPool
          │                      │    etc.
          └──────────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   Ruvon CLI      │  │  Ruvon Server    │  │  Ruvon Edge      │
│  (Management)    │  │   (FastAPI)      │  │  (IoT/POS)       │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

The SDK sits at the center, with three optional components built on top:
- **Ruvon CLI**: Command-line management tool
- **Ruvon Server**: REST API server with web UI
- **Ruvon Edge**: Agent for edge devices (POS, ATMs, kiosks)

## Core Layers

Ruvon uses a four-layer architecture, inherited from Confucius and enhanced with provider abstractions:

### 1. API Layer

**Purpose**: User-facing interfaces for workflow operations.

**Components**:
- `src/ruvon_server/routers/`: REST API endpoints (FastAPI)
- `src/ruvon_cli/`: Command-line interface
- `src/ruvon_edge/`: Edge device agent

**Key Responsibilities**:
- Input validation (Pydantic models)
- Authentication and authorization
- Request routing
- Response formatting

**Why Separated**: The API layer is decoupled from the core SDK, allowing Ruvon to be embedded in any application without requiring FastAPI or the CLI tool.

### 2. Engine Layer

**Purpose**: Orchestrates workflow execution and control flow.

**Components**:
- `src/ruvon/workflow.py`: Main `Workflow` class
- `src/ruvon/builder.py`: `WorkflowBuilder` for loading YAML definitions
- `src/ruvon/models.py`: Core data structures (steps, directives, context)

**Key Responsibilities**:
- Workflow lifecycle management (create, start, pause, resume, cancel)
- Step execution orchestration
- Control flow (jumps, loops, branches)
- State management and merging
- Sub-workflow coordination
- Saga pattern compensation

**Design Philosophy**: The engine knows *how* to execute workflows but delegates *where* to store state and *how* to run async tasks to providers.

### 3. Persistence Layer

**Purpose**: Abstracts storage of workflow state, audit logs, and metrics.

**Components**:
- `src/ruvon/providers/persistence.py`: `PersistenceProvider` protocol
- `src/ruvon/implementations/persistence/`:
  - `postgres.py`: PostgreSQL with asyncpg
  - `sqlite.py`: SQLite with aiosqlite
  - `memory.py`: In-memory storage for testing
  - `redis.py`: Redis-based persistence

**Key Responsibilities**:
- Workflow state CRUD operations
- Audit log storage
- Metrics recording
- Task queue management (claim/release)
- Transaction handling

**Why Pluggable**: Different deployments have different needs. Edge devices use SQLite for offline operation, while cloud deployments use PostgreSQL for ACID guarantees and scalability.

### 4. Execution Layer

**Purpose**: Abstracts how and where step functions execute.

**Components**:
- `src/ruvon/providers/execution.py`: `ExecutionProvider` protocol
- `src/ruvon/implementations/execution/`:
  - `sync.py`: Synchronous execution (development/testing)
  - `celery.py`: Distributed async execution (production)
  - `thread_pool.py`: Thread-based parallel execution
  - `postgres_executor.py`: PostgreSQL-backed task queue

**Key Responsibilities**:
- Async task dispatching
- Parallel task execution
- Sub-workflow spawning
- Child-to-parent status reporting
- Resource management (connections, threads)

**Why Pluggable**: Development uses sync execution for simplicity and debugging. Production uses Celery for distributed workers and fault tolerance. Edge devices might use thread pools to avoid Celery overhead.

## Component Interaction Flow

Here's what happens when a workflow executes a step:

```
1. Client calls workflow.next_step(user_input={})
                ↓
2. Workflow (Engine Layer) identifies next step based on current state
                ↓
3. Workflow validates user input against step's input model
                ↓
4. Workflow calls execution_provider.execute_sync_step_function()
                ↓
5. ExecutionProvider runs the step function with state + context
                ↓
6. Step function returns result dict
                ↓
7. Workflow merges result into state
                ↓
8. Workflow calls persistence_provider.save_workflow()
                ↓
9. PersistenceProvider serializes state and saves to database
                ↓
10. Workflow calls observer.on_step_executed()
                ↓
11. WorkflowObserver logs the event
                ↓
12. Workflow returns result to client
```

Notice how the Workflow class orchestrates, but delegates:
- **Execution** to ExecutionProvider
- **Storage** to PersistenceProvider
- **Observability** to WorkflowObserver

This is the provider pattern in action.

## Database Schema Architecture

Ruvon uses a hybrid approach for database management:

**Schema Definition**: SQLAlchemy Core models (`src/ruvon/db_schema/database.py`)
- Single source of truth
- Database-agnostic type mapping
- Used by Alembic for migration generation

**Runtime Queries**: Raw SQL via asyncpg/aiosqlite
- Zero abstraction overhead
- 45% faster than SQLAlchemy Core queries
- Full control over query optimization

**Migration System**: Alembic
- Auto-generate migrations from schema changes
- Version tracking via `alembic_version` table
- Supports PostgreSQL and SQLite (batch mode)

This design gives us the best of both worlds: migration tooling benefits without runtime performance cost.

## Cross-Cutting Concerns

### State Serialization

All workflow state is JSON-serializable via Pydantic models. Internally, Ruvon uses:
- **orjson** for fast serialization (3-5x faster than stdlib `json`)
- **JSONB** columns in PostgreSQL for efficient queries
- **TEXT** columns in SQLite for compatibility

### Async/Sync Bridge

Many Ruvon operations are async (persistence, HTTP steps), but Celery tasks run in sync contexts. The solution:

**PostgresExecutor** pattern (inherited from Confucius):
```python
class _PostgresExecutor:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def run_coroutine_sync(self, coro, timeout=None):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)
```

This runs async operations in a dedicated background thread, allowing sync Celery tasks to call async persistence methods safely.

### Import Caching

Step function resolution uses `importlib.import_module()`, which can be slow. Ruvon maintains a class-level cache in `WorkflowBuilder._import_cache`:
- First import: 5-10ms
- Cached import: ~0.03ms (162x faster)

This eliminates import overhead during workflow execution.

## Deployment Architectures

Ruvon supports three main deployment patterns:

### 1. Monolithic (Development)

```
┌─────────────────────────┐
│   Single Python Process │
│  ┌─────────────────┐    │
│  │ FastAPI Server  │    │
│  └────────┬────────┘    │
│           │              │
│  ┌────────▼────────┐    │
│  │ Ruvon SDK       │    │
│  │ (SyncExecutor)  │    │
│  └────────┬────────┘    │
│           │              │
│  ┌────────▼────────┐    │
│  │ SQLite          │    │
│  └─────────────────┘    │
└─────────────────────────┘
```

**Use case**: Development, demos, prototyping
**Characteristics**: No external dependencies, fast iteration, limited scalability

### 2. Distributed (Production)

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  FastAPI Server  │      │  Celery Worker 1 │      │  Celery Worker N │
│  (Ruvon Server)  │      │  (Ruvon SDK)     │      │  (Ruvon SDK)     │
└────────┬─────────┘      └────────┬─────────┘      └────────┬─────────┘
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      PostgreSQL             │
                    │  (Shared State Storage)     │
                    └─────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │         Redis               │
                    │  (Celery Broker/Backend)    │
                    └─────────────────────────────┘
```

**Use case**: Production cloud deployments
**Characteristics**: Horizontal scaling, fault tolerance, high throughput

### 3. Edge (Offline-First)

```
┌─────────────────────────────────────┐
│          Cloud Control Plane        │
│  ┌────────────────────────────┐    │
│  │  Ruvon Server (PostgreSQL) │    │
│  │  - Device registry         │    │
│  │  - Config server (ETag)    │    │
│  │  - Transaction sync        │    │
│  └────────────┬───────────────┘    │
└───────────────┼────────────────────┘
                │ HTTP/MQTT (intermittent)
                │
┌───────────────▼────────────────────┐
│      Edge Device (POS/ATM/Kiosk)  │
│  ┌────────────────────────────┐   │
│  │  RuvonEdgeAgent (SQLite)   │   │
│  │  - Offline workflows       │   │
│  │  - Store-and-forward queue │   │
│  │  - Config sync             │   │
│  └────────────────────────────┘   │
└────────────────────────────────────┘
```

**Use case**: POS terminals, ATMs, mobile readers, IoT devices
**Characteristics**: Offline-first, sync when online, minimal dependencies

## Design Principles

### 1. Separation of Concerns

Each component has a single, well-defined responsibility. The Workflow class doesn't know about PostgreSQL or Celery—it only knows about provider interfaces.

### 2. Dependency Injection

All external dependencies are injected via constructors, not hardcoded. This makes testing easy (inject mock providers) and deployment flexible (inject production providers).

### 3. Protocol-Oriented Design

Providers are defined as Python Protocols (structural subtyping), not abstract base classes. This allows any class that implements the required methods to be used as a provider, even if it doesn't explicitly inherit from a base class.

### 4. YAML-First Configuration

Workflow definitions are declarative (YAML), not imperative (code). This separates "what to do" from "how to do it" and enables non-programmers to define workflows.

### 5. SDK-First Philosophy

Ruvon is a library, not a framework. Applications import Ruvon and use it as needed, rather than extending a monolithic framework. This keeps the core small and focused.

## Performance Considerations

The architecture is designed for performance:

- **Connection pooling**: PostgreSQL persistence uses asyncpg pools (10-50 connections)
- **Lazy loading**: Workflow definitions loaded only when needed
- **Import caching**: Function paths resolved once and cached
- **Event loop optimization**: uvloop for 2-4x faster async I/O
- **Serialization optimization**: orjson for 3-5x faster JSON operations

## What's Next

Now that you understand the overall architecture, explore:
- [Provider Pattern](provider-pattern.md) - Why providers and how to implement custom ones
- [Workflow Lifecycle](workflow-lifecycle.md) - From creation to completion
- [State Management](state-management.md) - How workflow state flows through the system
