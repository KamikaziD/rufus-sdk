# Rufus SDK Performance Optimization Plan

## Executive Summary

This document outlines a phased approach to optimize Rufus SDK performance focusing on async I/O, messaging infrastructure, and data serialization. The plan targets **10-100x throughput improvements** for high-concurrency workflows.

**Target Metrics:**
- **Current**: ~100 workflows/sec (estimated, single worker)
- **Goal**: 1,000-10,000 workflows/sec (distributed deployment)
- **Latency**: <50ms p50, <200ms p99 for step execution
- **Memory**: <100MB per worker process

---

## Current Architecture Bottlenecks

### Identified Performance Issues

1. **AsyncIO Event Loop** (stdlib `asyncio`)
   - Pure Python implementation
   - ~20-30% slower than optimized C-based loops
   - Impact: **All async operations** (DB, Redis, HTTP)

2. **Message Broker Overhead** (Celery + Redis/RabbitMQ)
   - Heavy serialization (pickle/JSON)
   - High memory footprint (~50MB per worker)
   - Network round-trips for task dispatch
   - Impact: **ASYNC, PARALLEL, SUB_WORKFLOW steps**

3. **JSON Serialization** (stdlib `json`)
   - Slow serialization of workflow state
   - ~5-10ms per workflow save operation
   - Impact: **Every state persistence call**

4. **Database Connection Pooling** (asyncpg)
   - Current pool size: 5-20 connections
   - No connection reuse metrics
   - Impact: **All persistence operations**

5. **Synchronous Blocking Operations**
   - `importlib.import_module` blocks event loop
   - YAML parsing blocks on load
   - Impact: **Workflow startup, dynamic step loading**

6. **No Caching Layer**
   - Workflow configs reloaded from DB
   - Step functions re-imported
   - Impact: **High-frequency workflow execution**

---

## Optimization Strategy

### Phase 1: Low-Hanging Fruit (1-2 weeks)
Quick wins with minimal code changes and high ROI.

### Phase 2: Infrastructure Modernization (3-4 weeks)
Replace core infrastructure components (event loop, message broker).

### Phase 3: Advanced Optimizations (2-3 weeks)
Caching, batching, query optimization.

### Phase 4: Observability & Tuning (1-2 weeks)
Metrics, profiling, and continuous optimization.

---

## Phase 1: Low-Hanging Fruit

### 1.1 uvloop Integration ⚡

**Description:**
Replace stdlib `asyncio` with `uvloop`, a Cython-based event loop that's 2-4x faster.

**Implementation:**
```python
# src/rufus/__init__.py
import asyncio
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass  # Fallback to stdlib asyncio
```

**Changes Required:**
- Add `uvloop>=0.19.0` to `requirements.txt`
- Update `src/rufus/__init__.py` to set event loop policy
- Add environment variable `RUFUS_USE_UVLOOP=true` (default: true)
- Test all async operations (Postgres, Redis, HTTP steps)

**Impact:**
- **Throughput**: +50-100% for I/O-bound workflows
- **Latency**: -30-40% reduction in async task dispatch
- **Risk**: Low (drop-in replacement, well-tested)

**Effort**: 1-2 days
**Priority**: **HIGH** ⭐⭐⭐

---

### 1.2 orjson for State Serialization 🚀

**Description:**
Replace `json.dumps/loads` with `orjson`, a Rust-based JSON library that's 3-5x faster.

**Implementation:**
```python
# src/rufus/implementations/persistence/postgres.py
import orjson

# Before:
state_json = json.dumps(workflow_dict['state'])

# After:
state_json = orjson.dumps(workflow_dict['state']).decode('utf-8')
```

**Changes Required:**
- Add `orjson>=3.9.0` to `requirements.txt`
- Create `src/rufus/utils/serialization.py`:
  ```python
  import orjson
  from typing import Any

  def serialize(obj: Any) -> str:
      """Fast JSON serialization using orjson"""
      return orjson.dumps(obj).decode('utf-8')

  def deserialize(json_str: str) -> Any:
      """Fast JSON deserialization using orjson"""
      return orjson.loads(json_str)
  ```
- Replace all `json.dumps/loads` calls in:
  - `src/rufus/implementations/persistence/postgres.py`
  - `src/rufus/implementations/persistence/redis.py`
  - `src/rufus/implementations/execution/celery.py`

**Impact:**
- **Serialization**: 3-5x faster (5-10ms → 1-2ms per workflow)
- **Memory**: -20% (more efficient encoding)
- **Risk**: Low (API-compatible with stdlib `json`)

**Effort**: 2-3 days
**Priority**: **HIGH** ⭐⭐⭐

---

### 1.3 Optimize Postgres Connection Pool 💾

**Description:**
Tune `asyncpg` pool settings based on workload characteristics.

**Current Configuration:**
```python
self.pool = await asyncpg.create_pool(
    self.db_url,
    min_size=5,
    max_size=20,
    command_timeout=60,
)
```

**Optimized Configuration:**
```python
self.pool = await asyncpg.create_pool(
    self.db_url,
    min_size=10,              # ↑ from 5 (reduce cold connection overhead)
    max_size=50,              # ↑ from 20 (handle burst traffic)
    max_queries=50000,        # ✨ NEW: Recycle connections after 50K queries
    max_inactive_connection_lifetime=300,  # ✨ NEW: Close idle conns after 5min
    command_timeout=10,       # ↓ from 60 (fail fast for stuck queries)
    server_settings={
        'application_name': 'rufus_workflow_engine',
        'statement_timeout': '5000',  # ✨ NEW: Kill queries after 5s
    }
)
```

**Changes Required:**
- Add configuration via environment variables:
  ```python
  POSTGRES_POOL_MIN_SIZE=10
  POSTGRES_POOL_MAX_SIZE=50
  POSTGRES_POOL_COMMAND_TIMEOUT=10
  ```
- Add pool metrics logging (connections in use, wait time)
- Add connection health checks

**Impact:**
- **Throughput**: +20-30% under high concurrency
- **Latency**: -15-20% for DB operations
- **Risk**: Medium (requires load testing)

**Effort**: 2-3 days
**Priority**: **MEDIUM** ⭐⭐

---

### 1.4 Lazy Import of Step Functions 📦

**Description:**
Cache imported step functions to avoid redundant `importlib` calls.

**Current Behavior:**
```python
# Every execution re-imports the function
func = self.builder._import_from_string("my_app.steps.process_data")
```

**Optimized Approach:**
```python
# src/rufus/builder.py
class WorkflowBuilder:
    def __init__(self, ...):
        self._function_cache = {}  # ✨ NEW: Cache imported functions

    def _import_from_string(self, path: str):
        if path in self._function_cache:
            return self._function_cache[path]

        module_path, attr_name = path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        func = getattr(module, attr_name)

        self._function_cache[path] = func  # ✨ Cache for reuse
        return func
```

**Impact:**
- **Latency**: -5-10ms per step execution
- **CPU**: -10-15% reduction in import overhead
- **Risk**: Low (simple in-memory cache)

**Effort**: 1 day
**Priority**: **HIGH** ⭐⭐⭐

---

## Phase 2: Infrastructure Modernization

### 2.1 NATS as Message Broker 🚀

**Description:**
Replace Celery + Redis/RabbitMQ with NATS for lightweight, high-performance messaging.

**Why NATS?**
- **Performance**: 11M+ msgs/sec (vs Celery ~50K msgs/sec)
- **Latency**: <1ms p99 (vs Celery 10-50ms)
- **Memory**: ~10MB footprint (vs Celery worker ~50MB)
- **Features**: Built-in JetStream for persistence, key-value store
- **Deployment**: Single binary, no Redis/RabbitMQ dependency

**Architecture:**
```
┌─────────────────────────────────────────┐
│     Rufus Workflow Engine               │
│  (FastAPI Server / CLI)                 │
└───────────┬─────────────────────────────┘
            │
            │ Publish tasks to NATS subjects
            ▼
┌─────────────────────────────────────────┐
│         NATS JetStream                  │
│  - Subject: rufus.tasks.async           │
│  - Subject: rufus.tasks.parallel        │
│  - Subject: rufus.workflows.status      │
└───────────┬─────────────────────────────┘
            │
            │ Workers subscribe to subjects
            ▼
┌─────────────────────────────────────────┐
│     Rufus Worker Pool                   │
│  (Multiple workers, auto-scaling)       │
└─────────────────────────────────────────┘
```

**Implementation:**

**Step 1: Add NATS Client**
```python
# requirements.txt
nats-py>=2.7.0

# src/rufus/implementations/execution/nats_executor.py
import asyncio
import nats
from nats.js.api import StreamConfig
from rufus.providers.execution import ExecutionProvider

class NATSExecutor(ExecutionProvider):
    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc = None
        self.js = None

    async def initialize(self, engine):
        self._engine = engine
        self.nc = await nats.connect(self.nats_url)
        self.js = self.nc.jetstream()

        # Create stream for workflow tasks
        await self.js.add_stream(
            name="RUFUS_TASKS",
            subjects=["rufus.tasks.>", "rufus.workflows.>"],
            retention="limits",
            max_age=3600,  # 1 hour
        )

    async def dispatch_async_task(self, func_path: str, state_data: dict,
                                  workflow_id: str, current_step_index: int,
                                  data_region: str = None, **kwargs) -> str:
        """Publish async task to NATS"""
        task_payload = {
            "func_path": func_path,
            "state_data": state_data,
            "workflow_id": workflow_id,
            "current_step_index": current_step_index,
            "data_region": data_region,
            **kwargs
        }

        ack = await self.js.publish(
            subject=f"rufus.tasks.async.{workflow_id}",
            payload=orjson.dumps(task_payload),
            headers={"priority": str(self._engine.get_workflow(workflow_id).priority)}
        )

        return ack.seq  # Return sequence number as task ID
```

**Step 2: NATS Worker**
```python
# src/rufus_worker/nats_worker.py
import asyncio
from nats.js import JetStreamContext
from rufus.implementations.execution.nats_executor import NATSExecutor

async def handle_async_task(msg):
    """Handle async task from NATS"""
    payload = orjson.loads(msg.data)

    # Execute step function
    result = await execute_step_function(
        func_path=payload['func_path'],
        state_data=payload['state_data'],
        workflow_id=payload['workflow_id'],
    )

    # Resume workflow
    await resume_workflow(payload['workflow_id'], result)
    await msg.ack()

async def main():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()

    # Subscribe to async tasks
    await js.subscribe(
        subject="rufus.tasks.async.>",
        cb=handle_async_task,
        durable="rufus-workers",
        manual_ack=True,
    )

    print("NATS worker started")
    await asyncio.Event().wait()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
```

**Step 3: CLI Command**
```bash
# Start NATS server (via Docker or binary)
nats-server -js

# Start Rufus worker
rufus worker --executor nats --concurrency 10
```

**Migration Path:**
1. **Week 1**: Implement `NATSExecutor` alongside `CeleryExecutor`
2. **Week 2**: Add NATS worker and test with sample workflows
3. **Week 3**: Run A/B test (50% NATS, 50% Celery)
4. **Week 4**: Full migration, deprecate Celery

**Impact:**
- **Throughput**: 10-100x improvement (50K → 500K-5M tasks/sec)
- **Latency**: -80-90% for task dispatch (50ms → 1-5ms)
- **Infrastructure**: Remove Redis/RabbitMQ dependency
- **Ops**: Simpler deployment (single NATS binary)

**Effort**: 3-4 weeks
**Priority**: **HIGH** ⭐⭐⭐
**Risk**: Medium (requires worker coordination, testing)

---

### 2.2 gRPC for Step Execution 🔌

**Description:**
Enable step functions to run as gRPC services for language-agnostic, high-performance execution.

**Use Case:**
Allow users to implement step functions in **any language** (Python, Go, Rust, Node.js) as gRPC services.

**Architecture:**
```
┌─────────────────────────────────────────┐
│     Rufus Workflow Engine (Python)      │
└───────────┬─────────────────────────────┘
            │
            │ gRPC call: ExecuteStep(state, context)
            ▼
┌─────────────────────────────────────────┐
│     Step Function Services              │
│  - Python service (FastAPI + gRPC)      │
│  - Go service (high-performance)        │
│  - Rust service (ML inference)          │
└─────────────────────────────────────────┘
```

**Implementation:**

**Step 1: Define gRPC Protocol**
```protobuf
// src/rufus/protos/step_execution.proto
syntax = "proto3";

package rufus.steps;

service StepExecutor {
  rpc ExecuteStep(ExecuteStepRequest) returns (ExecuteStepResponse);
}

message ExecuteStepRequest {
  string workflow_id = 1;
  string step_name = 2;
  bytes state_data = 3;  // JSON-serialized state
  map<string, string> context = 4;
}

message ExecuteStepResponse {
  bytes result_data = 1;  // JSON-serialized result
  bool success = 2;
  string error_message = 3;
}
```

**Step 2: Python gRPC Step Executor**
```python
# src/rufus/implementations/execution/grpc_executor.py
import grpc
from rufus.protos import step_execution_pb2, step_execution_pb2_grpc
from rufus.providers.execution import ExecutionProvider

class GRPCStepExecutor(ExecutionProvider):
    def __init__(self, service_registry: dict):
        """
        service_registry = {
            "my_app.steps.process_data": "localhost:50051",
            "my_app.steps.fraud_check": "fraud-service:50052",
        }
        """
        self.service_registry = service_registry
        self.channels = {}

    async def execute_sync_step_function(self, func_path: str, state, context):
        """Execute step via gRPC call"""
        service_address = self.service_registry.get(func_path)
        if not service_address:
            raise ValueError(f"No gRPC service registered for {func_path}")

        # Reuse gRPC channel
        if service_address not in self.channels:
            self.channels[service_address] = grpc.aio.insecure_channel(service_address)

        stub = step_execution_pb2_grpc.StepExecutorStub(self.channels[service_address])

        request = step_execution_pb2.ExecuteStepRequest(
            workflow_id=context.workflow_id,
            step_name=context.step_name,
            state_data=orjson.dumps(state.dict()),
            context={"previous_result": str(context.previous_step_result)}
        )

        response = await stub.ExecuteStep(request, timeout=30)

        if not response.success:
            raise Exception(f"gRPC step failed: {response.error_message}")

        return orjson.loads(response.result_data)
```

**Step 3: Example Go Step Service**
```go
// examples/grpc_steps/fraud_check/main.go
package main

import (
    "context"
    "log"
    "net"
    pb "rufus/protos"
    "google.golang.org/grpc"
)

type server struct {
    pb.UnimplementedStepExecutorServer
}

func (s *server) ExecuteStep(ctx context.Context, req *pb.ExecuteStepRequest) (*pb.ExecuteStepResponse, error) {
    // High-performance fraud check logic in Go
    log.Printf("Executing fraud check for workflow %s", req.WorkflowId)

    // Parse state, run fraud detection
    // ...

    return &pb.ExecuteStepResponse{
        ResultData: []byte(`{"fraud_score": 0.05, "approved": true}`),
        Success: true,
    }, nil
}

func main() {
    lis, _ := net.Listen("tcp", ":50052")
    s := grpc.NewServer()
    pb.RegisterStepExecutorServer(s, &server{})
    log.Println("gRPC step service listening on :50052")
    s.Serve(lis)
}
```

**Configuration:**
```yaml
# config/grpc_services.yaml
grpc_step_services:
  "my_app.steps.fraud_check": "fraud-service:50052"
  "my_app.steps.ml_inference": "ml-service:50053"
```

**Impact:**
- **Language Support**: Python, Go, Rust, Node.js, Java step functions
- **Performance**: 10-50x for CPU-bound steps (Go/Rust vs Python)
- **Scalability**: Horizontal scaling per step type
- **Latency**: ~1-5ms gRPC overhead (vs 0ms local function call)

**Effort**: 2-3 weeks
**Priority**: **MEDIUM** ⭐⭐
**Risk**: Medium (requires service orchestration)

---

## Phase 3: Advanced Optimizations

### 3.1 Redis Caching Layer 💾

**Description:**
Cache hot workflows and step definitions in Redis to reduce DB load.

**Implementation:**
```python
# src/rufus/implementations/persistence/cached_postgres.py
import redis.asyncio as redis
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

class CachedPostgresPersistence(PostgresPersistenceProvider):
    def __init__(self, db_url: str, redis_url: str, ttl: int = 300):
        super().__init__(db_url)
        self.redis_url = redis_url
        self.redis_client = None
        self.cache_ttl = ttl

    async def initialize(self):
        await super().initialize()
        self.redis_client = await redis.from_url(self.redis_url)

    async def load_workflow(self, workflow_id: str) -> dict:
        # Try cache first
        cached = await self.redis_client.get(f"workflow:{workflow_id}")
        if cached:
            return orjson.loads(cached)

        # Cache miss - load from DB
        workflow_dict = await super().load_workflow(workflow_id)

        # Cache for future reads
        await self.redis_client.setex(
            f"workflow:{workflow_id}",
            self.cache_ttl,
            orjson.dumps(workflow_dict)
        )
        return workflow_dict

    async def save_workflow(self, workflow_id: str, workflow_dict: dict):
        # Write through to DB
        await super().save_workflow(workflow_id, workflow_dict)

        # Invalidate cache
        await self.redis_client.delete(f"workflow:{workflow_id}")
```

**Impact:**
- **Read Latency**: -70-90% for hot workflows (10ms → 1-2ms)
- **DB Load**: -50-80% reduction in SELECT queries
- **Throughput**: +2-3x for read-heavy workloads

**Effort**: 1 week
**Priority**: **HIGH** ⭐⭐⭐

---

### 3.2 Database Query Optimization 📊

**Description:**
Add indexes, materialized views, and query optimizations.

**Changes:**

**1. Add Composite Indexes**
```sql
-- Fast workflow lookup by status and priority
CREATE INDEX CONCURRENTLY idx_workflows_status_priority
ON workflow_executions(status, priority DESC, updated_at DESC);

-- Fast parent-child workflow queries
CREATE INDEX CONCURRENTLY idx_workflows_parent_child
ON workflow_executions(parent_execution_id, blocked_on_child_id);

-- Fast task claiming (FOR UPDATE SKIP LOCKED)
CREATE INDEX CONCURRENTLY idx_workflows_claim
ON workflow_executions(status, priority DESC, data_region)
WHERE status IN ('ACTIVE', 'PENDING_ASYNC_TASK');
```

**2. Materialized View for Metrics**
```sql
-- Pre-aggregate workflow metrics
CREATE MATERIALIZED VIEW workflow_metrics AS
SELECT
    workflow_type,
    status,
    DATE_TRUNC('hour', updated_at) as hour,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_duration_seconds
FROM workflow_executions
GROUP BY workflow_type, status, hour;

CREATE UNIQUE INDEX ON workflow_metrics(workflow_type, status, hour);

-- Refresh every 5 minutes
CREATE OR REPLACE FUNCTION refresh_workflow_metrics()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY workflow_metrics;
END;
$$ LANGUAGE plpgsql;
```

**3. Optimize Task Claiming Query**
```python
# src/rufus/implementations/persistence/postgres.py

# Before (slow full table scan):
await conn.fetch("""
    SELECT * FROM workflow_executions
    WHERE status = 'PENDING_ASYNC_TASK'
    ORDER BY priority DESC
    LIMIT 10
""")

# After (index-optimized with SKIP LOCKED):
await conn.fetch("""
    SELECT * FROM workflow_executions
    WHERE status = 'PENDING_ASYNC_TASK'
      AND data_region = $1  -- Partition by region
    ORDER BY priority DESC, updated_at ASC
    LIMIT 10
    FOR UPDATE SKIP LOCKED  -- Non-blocking claim
""", data_region)
```

**Impact:**
- **Query Latency**: -60-80% for task claiming
- **DB CPU**: -40-50% reduction
- **Throughput**: +3-5x for high-concurrency scenarios

**Effort**: 1 week
**Priority**: **HIGH** ⭐⭐⭐

---

### 3.3 Batch Operations 📦

**Description:**
Batch multiple DB writes/reads into single queries.

**Implementation:**
```python
# src/rufus/implementations/persistence/postgres.py

class PostgresPersistenceProvider:
    async def save_workflows_batch(self, workflows: List[dict]):
        """Save multiple workflows in a single transaction"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany("""
                    INSERT INTO workflow_executions (...) VALUES (...)
                    ON CONFLICT (id) DO UPDATE SET ...
                """, [(w['id'], w['workflow_type'], ...) for w in workflows])

    async def load_workflows_batch(self, workflow_ids: List[str]) -> List[dict]:
        """Load multiple workflows in a single query"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM workflow_executions
                WHERE id = ANY($1)
            """, workflow_ids)
            return [dict(row) for row in rows]
```

**Impact:**
- **Throughput**: +5-10x for batch operations
- **DB Connections**: -80% reduction (1 query vs N queries)

**Effort**: 3-4 days
**Priority**: **MEDIUM** ⭐⭐

---

## Phase 4: Observability & Continuous Optimization

### 4.1 Performance Metrics & Tracing 📊

**Description:**
Add comprehensive metrics and distributed tracing.

**Implementation:**

**1. Prometheus Metrics**
```python
# requirements.txt
prometheus-client>=0.19.0

# src/rufus/implementations/observability/prometheus.py
from prometheus_client import Counter, Histogram, Gauge

workflow_executions = Counter(
    'rufus_workflow_executions_total',
    'Total workflow executions',
    ['workflow_type', 'status']
)

step_execution_duration = Histogram(
    'rufus_step_execution_duration_seconds',
    'Step execution duration',
    ['workflow_type', 'step_name'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

active_workflows = Gauge(
    'rufus_active_workflows',
    'Number of active workflows',
    ['workflow_type']
)
```

**2. OpenTelemetry Tracing**
```python
# requirements.txt
opentelemetry-api>=1.22.0
opentelemetry-sdk>=1.22.0
opentelemetry-instrumentation-asyncpg>=0.42b0

# src/rufus/workflow.py
from opentelemetry import trace

tracer = trace.get_tracer("rufus.workflow")

class Workflow:
    async def next_step(self, user_input: dict):
        with tracer.start_as_current_span("workflow.next_step") as span:
            span.set_attribute("workflow_id", self.id)
            span.set_attribute("workflow_type", self.workflow_type)
            span.set_attribute("current_step", self.current_step)

            # Existing logic...
            result = await self._execute_step()

            span.set_attribute("result_keys", list(result.keys()))
            return result
```

**3. Grafana Dashboards**
```yaml
# grafana/dashboards/rufus_performance.json
{
  "title": "Rufus Workflow Performance",
  "panels": [
    {
      "title": "Workflow Throughput",
      "targets": [
        "rate(rufus_workflow_executions_total[5m])"
      ]
    },
    {
      "title": "Step Execution Latency (p50, p95, p99)",
      "targets": [
        "histogram_quantile(0.50, rufus_step_execution_duration_seconds)",
        "histogram_quantile(0.95, rufus_step_execution_duration_seconds)",
        "histogram_quantile(0.99, rufus_step_execution_duration_seconds)"
      ]
    }
  ]
}
```

**Impact:**
- **Visibility**: Real-time performance monitoring
- **Debugging**: Identify slow steps and bottlenecks
- **SLOs**: Track SLAs (e.g., 99% of workflows < 500ms)

**Effort**: 1-2 weeks
**Priority**: **HIGH** ⭐⭐⭐

---

### 4.2 Load Testing & Profiling 🔬

**Description:**
Establish continuous performance testing.

**Tools:**
- **Locust** - Load testing framework
- **py-spy** - Python profiler
- **pgBadger** - PostgreSQL log analyzer

**Implementation:**
```python
# tests/performance/locustfile.py
from locust import HttpUser, task, between

class WorkflowUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def start_workflow(self):
        self.client.post("/workflows", json={
            "workflow_type": "LoanApplication",
            "initial_data": {"loan_amount": 50000}
        })

    @task(3)
    def execute_next_step(self):
        # Execute next step for active workflows
        response = self.client.get("/workflows/active")
        workflows = response.json()
        if workflows:
            wf_id = workflows[0]['id']
            self.client.post(f"/workflows/{wf_id}/next", json={})
```

**Run Load Tests:**
```bash
# Target: 1,000 workflows/sec
locust -f tests/performance/locustfile.py \
  --host http://localhost:8000 \
  --users 100 \
  --spawn-rate 10 \
  --run-time 5m

# Profile slow code paths
py-spy record -o profile.svg -- python -m rufus_server.main
```

**Effort**: 1 week
**Priority**: **MEDIUM** ⭐⭐

---

## Additional Optimization Suggestions

### 5.1 msgpack for Binary Serialization 📦

**Alternative to orjson** for even faster serialization (10-20% faster, smaller payload).

```python
import msgpack

# Serialize
data_bytes = msgpack.packb(workflow_dict)

# Deserialize
workflow_dict = msgpack.unpackb(data_bytes)
```

**Trade-off**: Less human-readable than JSON, but excellent for internal communication (NATS, Redis).

**Effort**: 2-3 days
**Priority**: **LOW** ⭐

---

### 5.2 Read Replicas for PostgreSQL 📚

**Description:**
Use PostgreSQL read replicas for high-read workloads.

```python
# src/rufus/implementations/persistence/postgres.py

class PostgresPersistenceProvider:
    def __init__(self, write_db_url: str, read_db_urls: List[str]):
        self.write_pool = None
        self.read_pools = []

    async def initialize(self):
        self.write_pool = await asyncpg.create_pool(write_db_url)
        for read_url in read_db_urls:
            pool = await asyncpg.create_pool(read_url)
            self.read_pools.append(pool)

    async def load_workflow(self, workflow_id: str):
        # Read from replica (round-robin)
        pool = random.choice(self.read_pools)
        async with pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM workflows WHERE id=$1", workflow_id)

    async def save_workflow(self, workflow_id: str, data: dict):
        # Write to primary
        async with self.write_pool.acquire() as conn:
            await conn.execute("INSERT INTO workflows ...")
```

**Impact:**
- **Read Throughput**: +3-5x (distribute reads across replicas)
- **Write Latency**: No change (still single primary)

**Effort**: 1 week
**Priority**: **MEDIUM** ⭐⭐

---

### 5.3 Async Everywhere 🔄

**Description:**
Identify and remove remaining blocking operations.

**Checklist:**
- ✅ Database operations (asyncpg)
- ✅ Redis operations (redis.asyncio)
- ❌ YAML parsing (`yaml.safe_load` blocks event loop)
- ❌ `importlib.import_module` (blocks event loop)
- ❌ File I/O (use `aiofiles`)

**Fix YAML Parsing:**
```python
# Before (blocking):
with open("workflow.yaml") as f:
    config = yaml.safe_load(f)

# After (async):
import aiofiles
import asyncio

async with aiofiles.open("workflow.yaml") as f:
    content = await f.read()
    config = await asyncio.to_thread(yaml.safe_load, content)
```

**Fix Dynamic Imports:**
```python
# Run in thread pool to avoid blocking event loop
func = await asyncio.to_thread(
    importlib.import_module,
    "my_app.steps"
)
```

**Effort**: 3-4 days
**Priority**: **MEDIUM** ⭐⭐

---

## Implementation Roadmap

### Timeline (12 weeks total)

| Phase | Tasks | Duration | Dependency |
|-------|-------|----------|------------|
| **Phase 1** | uvloop, orjson, pool tuning, lazy imports | 1-2 weeks | None |
| **Phase 2** | NATS executor, gRPC support | 3-4 weeks | Phase 1 |
| **Phase 3** | Redis cache, DB optimization, batching | 2-3 weeks | Phase 1 |
| **Phase 4** | Metrics, tracing, load testing | 1-2 weeks | Phase 1 |
| **Additional** | msgpack, read replicas, async cleanup | 2-3 weeks | Parallel |

---

## Expected Performance Gains

### Conservative Estimates

| Metric | Baseline | After Phase 1 | After Phase 2 | After Phase 3 | After Phase 4 |
|--------|----------|---------------|---------------|---------------|---------------|
| **Throughput (workflows/sec)** | 100 | 200 | 1,000 | 2,000 | 5,000 |
| **Latency p50 (ms)** | 100 | 60 | 20 | 15 | 10 |
| **Latency p99 (ms)** | 500 | 300 | 100 | 50 | 30 |
| **Memory/Worker (MB)** | 100 | 90 | 40 | 35 | 30 |
| **DB QPS** | 1,000 | 1,200 | 1,500 | 800 | 500 |

### Aggressive Estimates (with Rust rewrite)

| Metric | Python + Optimizations | Rust Core + Python Steps |
|--------|------------------------|--------------------------|
| **Throughput** | 5,000 workflows/sec | 50,000 workflows/sec |
| **Latency p50** | 10ms | 1ms |
| **Memory/Worker** | 30MB | 10MB |

---

## Risk Mitigation

### High-Risk Changes
1. **NATS Migration** - Run A/B test before full rollout
2. **gRPC Services** - Start with optional, non-critical steps
3. **DB Optimization** - Test indexes on staging replica first

### Rollback Strategy
- Feature flags for each optimization (e.g., `RUFUS_USE_UVLOOP=false`)
- Blue-green deployment for NATS workers
- Database migration scripts with rollback procedures

---

## Success Metrics

### Key Performance Indicators (KPIs)

1. **Throughput**: 1,000+ workflows/sec (10x improvement)
2. **Latency**: <50ms p99 step execution
3. **Cost**: -50% infrastructure cost per workflow
4. **Reliability**: 99.9% uptime, zero data loss
5. **Developer Experience**: No breaking changes to user API

---

## Appendix: Benchmark Scripts

### A.1 Workflow Execution Benchmark
```python
# tests/benchmarks/workflow_throughput.py
import asyncio
import time
from rufus.builder import WorkflowBuilder

async def benchmark_workflow_throughput(num_workflows=1000):
    builder = WorkflowBuilder(...)

    start = time.perf_counter()

    tasks = []
    for i in range(num_workflows):
        workflow = builder.create_workflow("QuickWorkflow", {"id": i})
        tasks.append(workflow.next_step())

    await asyncio.gather(*tasks)

    elapsed = time.perf_counter() - start
    throughput = num_workflows / elapsed

    print(f"Executed {num_workflows} workflows in {elapsed:.2f}s")
    print(f"Throughput: {throughput:.2f} workflows/sec")

asyncio.run(benchmark_workflow_throughput())
```

---

## Review Checklist

**Before starting implementation:**

- [ ] Phase 1 tasks approved (uvloop, orjson, pool tuning)
- [ ] NATS vs Celery decision finalized
- [ ] gRPC use cases validated (multi-language steps needed?)
- [ ] Load testing infrastructure ready
- [ ] Monitoring/metrics dashboards designed
- [ ] Migration timeline communicated to stakeholders

**Post-Phase 1 (Quick Wins):**
- [ ] 50%+ throughput improvement measured
- [ ] No regressions in existing tests
- [ ] Latency p99 reduced by 30%+

**Post-Phase 2 (NATS):**
- [ ] 10x+ throughput improvement measured
- [ ] NATS production deployment stable for 2 weeks
- [ ] Celery fully deprecated and removed

**Post-Phase 3 (Advanced Optimizations):**
- [ ] Target KPIs achieved (1,000+ workflows/sec)
- [ ] Cost reduction measured ($ per workflow)

---

## Conclusion

This optimization plan provides a **structured, phased approach** to achieving 10-100x performance improvements for Rufus SDK. The focus on **low-risk, high-ROI changes** (Phase 1) ensures quick wins, while the infrastructure modernization (NATS, gRPC) sets the foundation for massive scalability.

**Recommended First Steps:**
1. ✅ Implement Phase 1 (uvloop + orjson + lazy imports) - **2 weeks, low risk**
2. ✅ Set up metrics/tracing (Phase 4) - **Run in parallel**
3. ✅ Benchmark current performance - **Establish baseline**
4. 🤔 Decide on NATS migration timeline - **Requires stakeholder buy-in**

Let's start with Phase 1 and measure the impact before committing to larger infrastructure changes!
