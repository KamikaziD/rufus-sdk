# Celery Workers as Edge Devices: Architecture Design

**Author:** Claude AI
**Date:** 2026-02-18
**Status:** Proposal / Design Document

---

## Executive Summary

This document proposes treating **Celery workers as edge devices**, enabling fleet management, config push, offline resilience, and model updates without worker restarts. By embedding `RufusEdgeAgent` into Celery workers, we gain:

✅ **Hot Config Push** - Update fraud rules, model configs, task definitions without redeployment
✅ **Store-and-Forward** - Workers queue tasks locally when broker/server is unreachable
✅ **Fleet Management** - Central control plane tracks worker health, capabilities, and status
✅ **Model Updates** - Push new AI models to GPU workers with delta updates
✅ **Network Resilience** - Workers survive Redis outages and network partitions
✅ **Unified Monitoring** - Same device registry for POS terminals, ATMs, and Celery workers

---

## Table of Contents

1. [Motivation](#motivation)
2. [Architecture Overview](#architecture-overview)
3. [Integration Design](#integration-design)
4. [Database Schema](#database-schema)
5. [API Endpoints](#api-endpoints)
6. [Code Examples](#code-examples)
7. [Network Failure Scenarios](#network-failure-scenarios)
8. [Migration Path](#migration-path)
9. [Trade-offs and Considerations](#trade-offs-and-considerations)
10. [Implementation Roadmap](#implementation-roadmap)

---

## Motivation

### Current Limitations

**Celery Workers Today:**
- ❌ Config changes require worker restart
- ❌ No offline resilience (Redis down = worker idle)
- ❌ Limited visibility into worker fleet status
- ❌ Model updates require redeployment
- ❌ No central control plane for worker management

**Rufus Edge Devices Today:**
- ✅ Offline-first with store-and-forward
- ✅ Hot config push via ETag polling
- ✅ Central device registry
- ✅ Model update infrastructure
- ⚠️ Synchronous execution only (no distributed workers)

### Proposed Solution

Combine the best of both worlds:

```
CELERY WORKER = EDGE DEVICE
├── Celery Task Consumer (distributed execution)
├── RufusEdgeAgent (edge resilience)
│   ├── ConfigManager (hot reload configs)
│   ├── SyncManager (SAF for tasks)
│   └── Heartbeat Loop (fleet monitoring)
└── Local SQLite (durable task queue)
```

### Use Cases

| Use Case | Description |
|----------|-------------|
| **GPU Model Updates** | Push new Llama/ONNX models to GPU workers without downtime |
| **Fraud Rule Updates** | Deploy new fraud detection rules instantly |
| **Network Partition** | Workers continue processing queued tasks when Redis is down |
| **Fleet Scaling** | Monitor worker capabilities (GPU, memory) for smart routing |
| **Regional Deployment** | Workers auto-configure based on region (GDPR, data residency) |
| **A/B Testing** | Push experimental configs to subset of workers |

---

## Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   CLOUD CONTROL PLANE                        │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐    │
│  │   Device    │  │   Config    │  │  Sync/Command    │    │
│  │  Registry   │  │   Server    │  │     API          │    │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘    │
│         │                 │                   │              │
│    PostgreSQL         ETag Cache          Redis Streams     │
└─────────┼─────────────────┼───────────────────┼──────────────┘
          │                 │                   │
          │ HTTPS (Registration, Heartbeat, Commands)
          │                 │                   │
┌─────────▼─────────────────▼───────────────────▼──────────────┐
│             CELERY WORKER (Hybrid Architecture)               │
│  ┌────────────────────────────────────────────────────┐      │
│  │               RufusEdgeAgent                       │      │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────┐ │      │
│  │  │ConfigManager │  │ SyncManager  │  │Heartbeat│ │      │
│  │  │(ETag polling)│  │(SAF queue)   │  │ Loop    │ │      │
│  │  └──────────────┘  └──────────────┘  └─────────┘ │      │
│  └────────────┬───────────────────────────────────────┘      │
│               │                                               │
│  ┌────────────▼───────────────────────────────────────┐      │
│  │        Celery Task Consumer                        │      │
│  │  • Consume from Redis queues                       │      │
│  │  • Fallback to SQLite SAF queue when Redis down    │      │
│  │  • Execute tasks with hot-loaded configs           │      │
│  └────────────────────────────────────────────────────┘      │
│               │                                               │
│  ┌────────────▼───────────────────────────────────────┐      │
│  │        Local SQLite Database                       │      │
│  │  • Durable SAF task queue                          │      │
│  │  • Config cache (survives restarts)                │      │
│  │  • Worker state and metrics                        │      │
│  └────────────────────────────────────────────────────┘      │
└───────────────────────────────────────────────────────────────┘
```

### Data Flow

**Normal Operation (Online):**
```
1. Celery Broker → Worker receives task
2. Worker executes task with current config
3. Worker reports metrics via heartbeat
4. ConfigManager polls for updates (ETag 304)
```

**Config Update:**
```
1. Admin deploys new config to control plane
2. ConfigManager polls → ETag 200 (new config)
3. Worker hot-reloads fraud rules, model paths, etc.
4. Next tasks use updated config (no restart!)
```

**Network Failure (Redis Down):**
```
1. Worker detects Redis broker unavailable
2. SyncManager switches to SQLite SAF queue
3. Worker continues processing local queue
4. When Redis recovers → sync queued tasks
5. Resume normal operation
```

**Model Update:**
```
1. Admin uploads new model to control plane
2. Heartbeat response includes "update_model" command
3. Worker downloads model (with delta update)
4. Worker swaps model hot (no downtime)
5. Worker ACKs command completion
```

---

## Integration Design

### Worker Lifecycle Integration

```python
# rufus_worker_edge.py (new file)

from celery import Celery
from celery.signals import worker_ready, worker_shutdown
from rufus_edge.agent import RufusEdgeAgent
import asyncio
import os

app = Celery('rufus_worker')

# Global agent instance
edge_agent: Optional[RufusEdgeAgent] = None
edge_loop: Optional[asyncio.AbstractEventLoop] = None


@worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    """Initialize RufusEdgeAgent when Celery worker starts."""
    global edge_agent, edge_loop

    # Extract worker metadata
    worker_id = sender.hostname  # e.g., "celery@worker-gpu-01"
    worker_capabilities = {
        "gpu": os.getenv("WORKER_GPU_ENABLED", "false") == "true",
        "memory_gb": int(os.getenv("WORKER_MEMORY_GB", "8")),
        "cpu_cores": os.cpu_count(),
        "region": os.getenv("WORKER_REGION", "us-east-1"),
        "zone": os.getenv("WORKER_ZONE", "us-east-1a"),
    }

    # Create event loop for edge agent
    edge_loop = asyncio.new_event_loop()

    # Initialize edge agent
    edge_agent = RufusEdgeAgent(
        device_id=worker_id,
        cloud_url=os.getenv("RUFUS_CONTROL_PLANE_URL", "http://localhost:8000"),
        api_key=os.getenv("RUFUS_API_KEY"),  # From registration
        db_path=f"/var/lib/rufus/workers/{worker_id}.db",
        encryption_key=os.getenv("RUFUS_ENCRYPTION_KEY"),
        config_poll_interval=60,
        sync_interval=30,
        heartbeat_interval=60,
    )

    # Start edge agent in background thread
    def run_edge_agent():
        asyncio.set_event_loop(edge_loop)
        edge_loop.run_until_complete(edge_agent.start())

    import threading
    edge_thread = threading.Thread(target=run_edge_agent, daemon=True)
    edge_thread.start()

    print(f"[RufusEdge] Worker {worker_id} registered as edge device")


@worker_shutdown.connect
def on_worker_shutdown(sender=None, **kwargs):
    """Cleanup RufusEdgeAgent when Celery worker stops."""
    global edge_agent, edge_loop

    if edge_agent:
        # Graceful shutdown
        asyncio.run_coroutine_threadsafe(edge_agent.stop(), edge_loop)
        edge_loop.stop()

    print("[RufusEdge] Worker shutdown complete")


# Task wrapper with SAF support
@app.task(bind=True, acks_late=True)
def process_with_saf(self, task_data: dict):
    """
    Execute task with store-and-forward resilience.

    If Redis is down, task is queued to SQLite SAF.
    When Redis recovers, SAF tasks are synced.
    """
    global edge_agent

    try:
        # Check if we should use SAF
        if not edge_agent or not edge_agent._is_online:
            # Queue to SQLite for later sync
            asyncio.run_coroutine_threadsafe(
                edge_agent.sync_manager.queue_for_sync(task_data),
                edge_loop
            ).result()
            return {"status": "QUEUED_SAF", "task_id": self.request.id}

        # Normal execution
        result = execute_task(task_data)
        return result

    except Exception as e:
        # On error, queue to SAF for retry
        asyncio.run_coroutine_threadsafe(
            edge_agent.sync_manager.queue_for_sync({
                "task_id": self.request.id,
                "task_data": task_data,
                "error": str(e),
                "retry_count": self.request.retries,
            }),
            edge_loop
        ).result()
        raise
```

### Config Hot-Reload

```python
# rufus_worker_edge.py (continued)

class WorkerConfigManager:
    """Manages worker-specific config hot-reloading."""

    def __init__(self, edge_agent: RufusEdgeAgent):
        self.edge_agent = edge_agent
        self.current_config = None

        # Register config change callback
        edge_agent.config_manager.register_on_config_change(
            self._on_config_update
        )

    def _on_config_update(self, config: DeviceConfig):
        """Called when control plane pushes new config."""
        print(f"[ConfigHotReload] Received config version {config.version}")

        # Update fraud rules
        if config.fraud_rules:
            global FRAUD_RULES
            FRAUD_RULES = config.fraud_rules
            print(f"[ConfigHotReload] Updated {len(FRAUD_RULES)} fraud rules")

        # Update model paths
        if config.models:
            for model_name, model_config in config.models.items():
                if model_config.get("auto_load", True):
                    self._load_model(model_name, model_config)

        # Update feature flags
        if config.features:
            global FEATURE_FLAGS
            FEATURE_FLAGS = config.features
            print(f"[ConfigHotReload] Updated feature flags: {FEATURE_FLAGS}")

        # Update task routing
        if config.workflows:
            self._update_task_routes(config.workflows)

        self.current_config = config

    def _load_model(self, model_name: str, model_config: dict):
        """Hot-load AI model without worker restart."""
        model_path = model_config.get("path")
        model_version = model_config.get("version")

        # Check if update needed
        if self.edge_agent.config_manager.is_model_update_available(
            model_name, current_version=CURRENT_MODEL_VERSIONS.get(model_name)
        ):
            print(f"[ModelUpdate] Downloading {model_name} v{model_version}")

            # Download with delta update
            asyncio.run_coroutine_threadsafe(
                self.edge_agent.config_manager.download_model(
                    model_name=model_name,
                    destination_path=f"/models/{model_name}.onnx",
                    use_delta=True,
                ),
                edge_loop
            ).result()

            # Swap model (implementation depends on inference engine)
            swap_model(model_name, model_path)
            CURRENT_MODEL_VERSIONS[model_name] = model_version

            print(f"[ModelUpdate] Loaded {model_name} v{model_version}")

    def _update_task_routes(self, workflows: dict):
        """Update Celery task routing based on workflow config."""
        # This would integrate with Celery's task routing
        # Example: route GPU tasks to GPU-capable workers
        for workflow_type, workflow_config in workflows.items():
            if workflow_config.get("requires_gpu"):
                # Only workers with GPU capability should handle this
                if not edge_agent.capabilities.get("gpu"):
                    app.conf.task_routes[workflow_type] = {"queue": "non-gpu"}
```

### Store-and-Forward Task Queue

```python
# rufus_worker_edge.py (continued)

class CelerySAFBridge:
    """
    Bridges Celery task queue with SQLite SAF queue.

    When Redis is down:
    - Tasks queued to SQLite
    - Worker processes from SQLite queue

    When Redis recovers:
    - SQLite tasks synced to Redis
    - Resume normal operation
    """

    def __init__(self, edge_agent: RufusEdgeAgent, celery_app: Celery):
        self.edge_agent = edge_agent
        self.celery_app = celery_app
        self._saf_mode = False

    async def queue_task(self, task_name: str, args: tuple, kwargs: dict, task_id: str):
        """Queue task with automatic SAF fallback."""
        try:
            # Try Redis first
            result = self.celery_app.send_task(
                task_name,
                args=args,
                kwargs=kwargs,
                task_id=task_id,
                expires=3600,
            )
            return {"status": "QUEUED_REDIS", "task_id": result.id}

        except Exception as e:
            # Redis unavailable - use SAF
            print(f"[SAF] Redis unavailable, queueing to SQLite: {e}")
            self._saf_mode = True

            # Queue to SQLite
            saf_task = {
                "task_id": task_id,
                "task_name": task_name,
                "args": args,
                "kwargs": kwargs,
                "queued_at": datetime.utcnow().isoformat(),
            }

            await self.edge_agent.sync_manager.queue_for_sync(saf_task)
            return {"status": "QUEUED_SAF", "task_id": task_id}

    async def sync_saf_queue(self):
        """
        Sync SQLite SAF queue to Redis when connectivity recovers.

        Called periodically by edge agent's sync loop.
        """
        if not self._saf_mode:
            return

        # Check if Redis is back
        try:
            self.celery_app.broker_connection().connect()
            redis_available = True
        except Exception:
            redis_available = False

        if not redis_available:
            return

        print("[SAF] Redis recovered, syncing SAF queue...")

        # Get pending tasks from SQLite
        pending_tasks = await self.edge_agent.sync_manager.get_pending_tasks()

        synced_count = 0
        for task in pending_tasks:
            task_data = task["task_data"]

            try:
                # Re-queue to Redis
                self.celery_app.send_task(
                    task_data["task_name"],
                    args=task_data.get("args", ()),
                    kwargs=task_data.get("kwargs", {}),
                    task_id=task_data["task_id"],
                )

                # Mark as synced in SQLite
                await self.edge_agent.sync_manager.mark_synced(task["task_id"])
                synced_count += 1

            except Exception as e:
                print(f"[SAF] Failed to sync task {task['task_id']}: {e}")

        print(f"[SAF] Synced {synced_count} tasks from SAF queue to Redis")
        self._saf_mode = False
```

---

## Database Schema

### Existing `edge_devices` Table (Extended)

```sql
-- Add worker-specific columns
ALTER TABLE edge_devices
ADD COLUMN worker_pool VARCHAR(100),           -- Celery pool name
ADD COLUMN queue_names TEXT[],                 -- Queues this worker consumes
ADD COLUMN concurrency INTEGER DEFAULT 1,      -- Worker concurrency setting
ADD COLUMN prefetch_multiplier INTEGER DEFAULT 4,
ADD COLUMN max_tasks_per_child INTEGER,
ADD COLUMN time_limit INTEGER,                 -- Task time limit (seconds)
ADD COLUMN soft_time_limit INTEGER;

-- Index for filtering by device_type
CREATE INDEX idx_edge_devices_type ON edge_devices(device_type);
```

### Worker Registry Query

```sql
-- Get all active Celery workers
SELECT
    device_id,
    capabilities,
    status,
    last_heartbeat_at,
    queue_names,
    concurrency
FROM edge_devices
WHERE device_type = 'celery_worker'
  AND status = 'online'
  AND last_heartbeat_at > NOW() - INTERVAL '2 minutes'
ORDER BY last_heartbeat_at DESC;
```

### Worker Capabilities Example

```json
{
    "device_type": "celery_worker",
    "capabilities": {
        "gpu": true,
        "gpu_model": "NVIDIA A100",
        "cuda_version": "12.1",
        "memory_gb": 64,
        "cpu_cores": 32,
        "region": "us-east-1",
        "zone": "us-east-1a",
        "worker_pool": "gpu-inference",
        "supported_models": ["llama3.1", "onnx-resnet50"],
        "max_batch_size": 32
    }
}
```

---

## API Endpoints

### 1. Worker Registration

```http
POST /api/v1/workers/register
Content-Type: application/json

{
    "device_id": "celery@worker-gpu-01",
    "device_type": "celery_worker",
    "device_name": "GPU Worker 01",
    "merchant_id": "internal",
    "firmware_version": "1.0.0",
    "sdk_version": "1.0.0",
    "location": "us-east-1a",
    "capabilities": {
        "gpu": true,
        "memory_gb": 64,
        "worker_pool": "gpu-inference"
    }
}

Response 200 OK:
{
    "device_id": "celery@worker-gpu-01",
    "api_key": "rsk_...",
    "config_url": "/api/v1/workers/celery@worker-gpu-01/config",
    "sync_url": "/api/v1/workers/celery@worker-gpu-01/sync",
    "heartbeat_interval": 60
}
```

### 2. Worker Config (ETag-Optimized)

```http
GET /api/v1/workers/celery@worker-gpu-01/config
If-None-Match: "abc123def456"

Response 304 Not Modified (if config unchanged)

Response 200 OK (if config changed):
ETag: "xyz789abc123"
{
    "version": "1.2.0",
    "floor_limit": 25.00,
    "fraud_rules": [...],
    "models": {
        "llama3.1": {
            "version": "3.1.2",
            "path": "/models/llama3.1-8b.gguf",
            "url": "https://cdn.example.com/models/llama3.1-8b.gguf",
            "hash": "sha256:abc123...",
            "delta_url": "https://cdn.example.com/models/llama3.1-8b.delta",
            "auto_load": true
        }
    },
    "workflows": {
        "LLMInference": {
            "requires_gpu": true,
            "max_batch_size": 32,
            "timeout": 300
        }
    },
    "features": {
        "enable_batching": true,
        "enable_caching": true
    }
}
```

### 3. Worker Heartbeat

```http
POST /api/v1/workers/celery@worker-gpu-01/heartbeat
Content-Type: application/json

{
    "status": "online",
    "queue_depth": 15,
    "tasks_processed": 1250,
    "tasks_failed": 3,
    "uptime_seconds": 86400,
    "cpu_usage_percent": 45.2,
    "memory_usage_percent": 62.1,
    "gpu_usage_percent": 78.5,
    "config_version": "1.2.0",
    "pending_saf_tasks": 0
}

Response 200 OK:
{
    "ack": true,
    "commands": [
        {
            "command_id": "cmd_12345",
            "command_type": "update_model",
            "command_data": {
                "model_name": "llama3.1",
                "version": "3.1.3",
                "delta_url": "https://cdn.example.com/models/llama3.1-3.1.3.delta"
            }
        }
    ]
}
```

### 4. SAF Task Sync

```http
POST /api/v1/workers/celery@worker-gpu-01/sync
Content-Type: application/json

{
    "transactions": [
        {
            "task_id": "task_12345",
            "task_name": "process_llm_inference",
            "task_data": {...},
            "queued_at": "2026-02-18T10:30:00Z",
            "hmac": "abc123..."
        }
    ]
}

Response 200 OK:
{
    "accepted": ["task_12345"],
    "rejected": [],
    "duplicates": []
}
```

---

## Code Examples

### Example 1: Fraud Rule Hot-Reload

**Before (Requires Worker Restart):**
```python
# Fraud rules hardcoded in task
FRAUD_RULES = [
    {"type": "velocity", "limit": 5, "window_seconds": 60},
]

@app.task
def check_fraud(transaction):
    for rule in FRAUD_RULES:  # Static rules
        if violates_rule(transaction, rule):
            return {"fraud": True}
```

**After (Hot-Reload from Control Plane):**
```python
# Fraud rules loaded from edge config
FRAUD_RULES = []  # Empty initially

@app.task
def check_fraud(transaction):
    global FRAUD_RULES

    # Rules are updated via config callback
    for rule in FRAUD_RULES:  # Dynamic rules
        if violates_rule(transaction, rule):
            return {"fraud": True}
```

**Config update flow:**
```bash
# Admin updates fraud rules in control plane
curl -X POST https://control-plane/api/v1/fraud-rules \
  -d '{"rules": [{"type": "velocity", "limit": 3, "window_seconds": 60}]}'

# Within 60 seconds (config poll interval):
# 1. Worker ConfigManager polls control plane
# 2. ETag changed → new config downloaded
# 3. _on_config_update() callback fires
# 4. FRAUD_RULES updated globally
# 5. Next task uses new rules (no restart!)
```

### Example 2: Model Update

```python
# Worker startup
MODELS = {}

@worker_ready.connect
def load_models(sender=None, **kwargs):
    global MODELS
    # Initial model load
    MODELS["llama"] = load_model("/models/llama3.1-8b.gguf")

# Model update via heartbeat command
def _on_model_update_command(command_data):
    model_name = command_data["model_name"]
    new_version = command_data["version"]
    delta_url = command_data.get("delta_url")

    # Download model (with delta if available)
    new_model_path = f"/models/{model_name}-{new_version}.gguf"

    asyncio.run_coroutine_threadsafe(
        edge_agent.config_manager.download_model(
            model_name=model_name,
            destination_path=new_model_path,
            use_delta=True,
        ),
        edge_loop
    ).result()

    # Hot-swap model
    old_model = MODELS.get(model_name)
    MODELS[model_name] = load_model(new_model_path)

    if old_model:
        old_model.unload()  # Free memory

    print(f"[ModelUpdate] Swapped {model_name} to version {new_version}")

# Task uses latest model
@app.task
def llm_inference(prompt: str):
    model = MODELS["llama"]  # Always uses latest version
    return model.generate(prompt)
```

### Example 3: Network Partition Recovery

```python
@app.task(bind=True)
def process_payment(self, payment_data):
    """
    Process payment with automatic SAF fallback.

    Scenario:
    1. Redis broker goes down
    2. Task queued to SQLite SAF
    3. Redis recovers
    4. SAF queue synced to Redis
    5. Task processed normally
    """
    try:
        # Attempt normal processing
        result = charge_payment_gateway(payment_data)
        return {"status": "COMPLETED", "result": result}

    except NetworkError as e:
        # Payment gateway unreachable
        # Queue to SAF for retry when network recovers
        saf_data = {
            "task_id": self.request.id,
            "payment_data": payment_data,
            "error": str(e),
            "queued_at": datetime.utcnow().isoformat(),
        }

        asyncio.run_coroutine_threadsafe(
            edge_agent.sync_manager.queue_for_sync(saf_data),
            edge_loop
        ).result()

        return {"status": "QUEUED_SAF", "will_retry": True}
```

---

## Network Failure Scenarios

### Scenario 1: Redis Broker Outage

**Timeline:**
```
T+0:00  Redis broker crashes
T+0:01  Celery worker detects connection failure
T+0:01  CelerySAFBridge switches to SQLite mode
T+0:02  New tasks queued to SQLite (not Redis)
T+0:05  Worker processes tasks from SQLite queue
T+15:00 Redis recovers
T+15:01 Worker detects Redis availability
T+15:02 CelerySAFBridge syncs SQLite queue to Redis
T+15:05 Normal operation resumed
```

**Worker Logs:**
```
[2026-02-18 10:00:01] [SAF] Redis unavailable, queueing to SQLite: ConnectionRefusedError
[2026-02-18 10:00:02] [SAF] Queued task task_12345 to SQLite
[2026-02-18 10:15:01] [SAF] Redis recovered, syncing SAF queue...
[2026-02-18 10:15:02] [SAF] Synced 15 tasks from SAF queue to Redis
```

### Scenario 2: Control Plane Outage

**Timeline:**
```
T+0:00  Control plane API goes down
T+0:01  ConfigManager poll fails (connection timeout)
T+0:01  Worker uses cached config from SQLite
T+1:00  Next config poll fails (still down)
T+1:00  Worker continues with cached config
T+30:00 Control plane recovers
T+30:01 ConfigManager poll succeeds (ETag check)
T+30:01 Worker syncs any missed config updates
```

**Key Insight:** Worker survives control plane outages indefinitely by using cached config.

### Scenario 3: Network Partition (Worker Isolated)

**Timeline:**
```
T+0:00  Network partition (worker isolated from Redis + control plane)
T+0:01  Worker switches to full offline mode
T+0:02  Tasks queued to SQLite
T+0:05  Worker processes tasks from SQLite using cached config
T+1:00  ConfigManager poll fails → cached config used
T+1:00  SyncManager can't sync → tasks stay in SQLite
T+60:00 Network recovers
T+60:01 Worker detects connectivity
T+60:02 ConfigManager syncs config (ETag check)
T+60:03 SyncManager syncs all pending tasks to Redis
T+60:05 Normal operation resumed
```

**Metrics:**
- **Uptime:** 100% (worker never stopped)
- **Tasks processed during partition:** All queued tasks from SQLite
- **Data loss:** Zero (SQLite is durable)

---

## Migration Path

### Phase 1: Proof of Concept (1-2 weeks)

**Goal:** Validate architecture with single worker

1. Create `rufus_worker_edge.py` integration module
2. Extend `edge_devices` table with worker columns
3. Add worker registration endpoint
4. Test hot config reload
5. Test SAF with Redis outage simulation

**Success Criteria:**
- ✅ Worker registers as edge device
- ✅ Config updates without restart
- ✅ Tasks queued to SQLite when Redis down
- ✅ Tasks synced when Redis recovers

### Phase 2: GPU Model Updates (2-3 weeks)

**Goal:** Hot-swap AI models without worker downtime

1. Implement model download in ConfigManager
2. Add delta update support for large models
3. Test model swap with Ollama/ONNX workers
4. Benchmark delta vs. full download

**Success Criteria:**
- ✅ 500MB model updated in <60 seconds (delta)
- ✅ No worker downtime during update
- ✅ Old model unloaded, new model loaded hot

### Phase 3: Fleet Management (3-4 weeks)

**Goal:** Central control plane for worker fleet

1. Build worker dashboard (device registry UI)
2. Add worker health monitoring
3. Implement worker commands (force_sync, reload_config)
4. Add worker capability-based routing

**Success Criteria:**
- ✅ Dashboard shows all workers with status
- ✅ Admin can push config to subset of workers
- ✅ Tasks routed based on worker capabilities

### Phase 4: Production Hardening (4-6 weeks)

**Goal:** Production-ready deployment

1. Add comprehensive tests (unit, integration, chaos)
2. Performance benchmarks (SAF overhead, config poll)
3. Security audit (API key storage, HMAC validation)
4. Documentation and runbooks
5. Monitoring and alerting

**Success Criteria:**
- ✅ 95%+ test coverage
- ✅ <5ms overhead per task (SAF check)
- ✅ Security review passed
- ✅ Production deployment successful

---

## Trade-offs and Considerations

### Advantages

✅ **No Single Point of Failure:** Workers survive Redis/control plane outages
✅ **Hot Configuration:** Update rules/models without downtime
✅ **Unified Management:** Same API for POS terminals and Celery workers
✅ **Network Resilience:** Store-and-forward handles partitions gracefully
✅ **Fleet Visibility:** Central dashboard for worker health/capabilities
✅ **Cost Savings:** Delta model updates save bandwidth (70-90% reduction)

### Disadvantages

❌ **Increased Complexity:** Edge agent adds moving parts
❌ **Storage Overhead:** Each worker needs SQLite database
❌ **CPU Overhead:** Config polling, heartbeats, SAF sync (~5-10% CPU)
❌ **Latency:** ETag polling means config updates take 1-60 seconds
❌ **Memory Overhead:** Edge agent ~50-100MB per worker

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| **SQLite for SAF Queue** | Durable, embedded, no external dependencies |
| **ETag Polling (not Push)** | Works through NAT/firewalls, simpler than WebSocket |
| **Heartbeat as Command Channel** | Reuses existing HTTP connection, no separate protocol |
| **HMAC Signing** | Prevent replay attacks, verify task integrity |
| **Delta Model Updates** | Save bandwidth for large models (LLMs, ONNX) |

### Open Questions

1. **Task Deduplication:** How to handle duplicate tasks in SAF queue + Redis?
   - **Proposal:** Use `idempotency_key` (same as edge SAF)

2. **Config Rollback:** What if new config breaks workers?
   - **Proposal:** Add config versioning + rollback command

3. **Worker Auto-Scaling:** How to integrate with K8s HPA?
   - **Proposal:** Device registry API exposes worker count for HPA

4. **Multi-Tenancy:** Can workers serve multiple tenants?
   - **Proposal:** Use `merchant_id` in device registration

---

## Implementation Roadmap

### Sprint 1-2: Foundation (2 weeks)

- [ ] Create `rufus_worker_edge.py` module
- [ ] Extend `edge_devices` schema
- [ ] Add worker registration endpoint
- [ ] Implement Celery signal hooks
- [ ] Unit tests for core integration

### Sprint 3-4: Config Management (2 weeks)

- [ ] Implement `WorkerConfigManager`
- [ ] Add config hot-reload callback
- [ ] Test fraud rule updates
- [ ] Test feature flag updates
- [ ] Integration tests for config push

### Sprint 5-6: Store-and-Forward (2 weeks)

- [ ] Implement `CelerySAFBridge`
- [ ] Add SAF queue sync logic
- [ ] Test Redis outage scenario
- [ ] Test network partition scenario
- [ ] Chaos engineering tests

### Sprint 7-8: Model Updates (2 weeks)

- [ ] Add model download to ConfigManager
- [ ] Implement delta update support
- [ ] Test Ollama model updates
- [ ] Test ONNX model updates
- [ ] Benchmark delta vs. full download

### Sprint 9-10: Fleet Management (2 weeks)

- [ ] Build worker dashboard UI
- [ ] Add worker health monitoring
- [ ] Implement worker commands
- [ ] Add capability-based routing
- [ ] End-to-end tests

### Sprint 11-12: Production Hardening (2 weeks)

- [ ] Comprehensive test suite
- [ ] Performance benchmarks
- [ ] Security audit
- [ ] Documentation
- [ ] Production deployment

---

## Conclusion

Treating Celery workers as edge devices is a novel architectural pattern that combines:
- **Distributed task processing** (Celery's strength)
- **Offline resilience** (edge computing's strength)
- **Fleet management** (Rufus Edge's strength)

This integration enables hot config push, model updates, and network resilience without the complexity of distributed consensus or external orchestration systems.

**Next Steps:**
1. Review this design document
2. Validate assumptions with team
3. Build POC (Phase 1)
4. Iterate based on learnings

**References:**
- [Celery Task Resilience Strategies](https://blog.gitguardian.com/celery-tasks-retries-errors/)
- [Edge Orchestration in 2026](https://itbusinesstoday.com/iot/edge-orchestration-in-2026-how-enterprises-are-managing-thousands-of-distributed-devices-efficiently/)
- [Edge Computing in Retail](https://www.edge-ai-vision.com/2026/01/how-edge-computing-in-retail-is-transforming-the-shopping-experience/)
- [Cloud Native Edge Architectures 2026](https://resolvetech.com/cloud-native-serverless-edge-architectures-redefining-enterprise-agility-in-2026/)

---

**End of Design Document**
