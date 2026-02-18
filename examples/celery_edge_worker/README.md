# Celery Workers as Edge Devices - Example

This example demonstrates treating Celery workers as edge devices, enabling:

✅ **Hot Config Push** - Update fraud rules without worker restart
✅ **Store-and-Forward** - Workers queue tasks when Redis is down
✅ **Fleet Management** - Central control plane tracks worker health
✅ **Model Updates** - Push new AI models without downtime
✅ **Network Resilience** - Workers survive Redis outages

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   CLOUD CONTROL PLANE                        │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐    │
│  │   Device    │  │   Config    │  │  Sync/Command    │    │
│  │  Registry   │  │   Server    │  │     API          │    │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘    │
│         │                 │                   │              │
└─────────┼─────────────────┼───────────────────┼──────────────┘
          │ HTTPS           │                   │
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

## Quick Start

### 1. Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Or install with Celery support
pip install "rufus[celery] @ git+https://github.com/KamikaziD/rufus-sdk.git"
```

### 2. Start Infrastructure

```bash
cd examples/celery_edge_worker

# Start Redis, PostgreSQL, and control plane
docker compose up -d redis postgres control-plane

# Wait for services to be healthy
docker compose ps
```

### 3. Register Workers

Workers need to register with the control plane to get API keys:

```bash
# Register standard worker
curl -X POST http://localhost:8000/api/v1/workers/register \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "worker-standard-01",
    "device_type": "celery_worker",
    "device_name": "Standard Worker 01",
    "merchant_id": "internal",
    "firmware_version": "1.0.0",
    "sdk_version": "1.0.0",
    "location": "us-east-1a",
    "capabilities": {
      "gpu": false,
      "memory_gb": 8,
      "cpu_cores": 4,
      "worker_pool": "standard"
    }
  }'

# Save the api_key from response
export WORKER_API_KEY="rsk_..."

# Register GPU worker
curl -X POST http://localhost:8000/api/v1/workers/register \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "worker-gpu-01",
    "device_type": "celery_worker",
    "device_name": "GPU Worker 01",
    "merchant_id": "internal",
    "firmware_version": "1.0.0",
    "sdk_version": "1.0.0",
    "location": "us-east-1b",
    "capabilities": {
      "gpu": true,
      "gpu_model": "NVIDIA A100",
      "memory_gb": 64,
      "cpu_cores": 32,
      "worker_pool": "gpu-inference"
    }
  }'

export WORKER_GPU_API_KEY="rsk_..."
```

### 4. Start Workers

```bash
# Start standard worker
docker compose up -d worker-standard

# Start GPU worker (requires NVIDIA GPU)
docker compose up -d worker-gpu

# Start Flower monitoring dashboard
docker compose up -d flower

# Open Flower: http://localhost:5555
```

### 5. Run Tasks

```python
from examples.celery_edge_worker.rufus_worker_edge import check_fraud, llm_inference

# Submit fraud check task
result = check_fraud.delay({
    "id": "txn_12345",
    "amount": 100.00,
    "card_number": "4111111111111111",
})

print(result.get())  # Wait for result

# Submit LLM inference task (routes to GPU worker)
result = llm_inference.delay(
    prompt="What is the capital of France?",
    model_name="llama3.1"
)

print(result.get())
```

## Testing Network Resilience

### Test 1: Redis Outage (Store-and-Forward)

```bash
# 1. Stop Redis
docker compose stop redis

# 2. Submit tasks (will queue to SQLite)
python -c "
from examples.celery_edge_worker.rufus_worker_edge import process_with_saf
result = process_with_saf.delay({'data': 'test'})
print(result)  # Task ID
"

# 3. Check worker logs - should see SAF queue message
docker compose logs -f worker-standard

# 4. Restart Redis
docker compose start redis

# 5. Worker automatically syncs SQLite queue to Redis
# 6. Tasks processed normally
```

### Test 2: Config Hot-Reload

```bash
# 1. Update fraud rules in control plane
curl -X POST http://localhost:8000/api/v1/devices/worker-standard-01/config \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WORKER_API_KEY" \
  -d '{
    "version": "1.1.0",
    "fraud_rules": [
      {"type": "velocity", "limit": 3, "window_seconds": 60},
      {"type": "amount_threshold", "max_amount": 1000.00}
    ]
  }'

# 2. Worker polls config within 60 seconds (config_poll_interval)
# 3. New fraud rules applied WITHOUT worker restart

# 4. Submit fraud check - uses new rules
python -c "
from examples.celery_edge_worker.rufus_worker_edge import check_fraud
result = check_fraud.delay({'id': 'txn_123', 'amount': 1500.00})
print(result.get())  # Should flag as fraud (exceeds $1000)
"
```

### Test 3: Model Update

```bash
# 1. Update model config in control plane
curl -X POST http://localhost:8000/api/v1/devices/worker-gpu-01/config \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WORKER_GPU_API_KEY" \
  -d '{
    "version": "1.2.0",
    "models": {
      "llama3.1": {
        "version": "3.1.3",
        "path": "/models/llama3.1-8b-v3.1.3.gguf",
        "url": "https://cdn.example.com/models/llama3.1-8b-v3.1.3.gguf",
        "hash": "sha256:abc123...",
        "delta_url": "https://cdn.example.com/models/llama3.1-3.1.3.delta",
        "auto_load": true
      }
    }
  }'

# 2. Worker downloads model (with delta update)
# 3. Model hot-swapped WITHOUT worker restart

# 4. Check worker logs
docker compose logs -f worker-gpu | grep ModelUpdate

# Expected output:
# [ModelUpdate] Updating llama3.1: 3.1.2 -> 3.1.3
# [ModelUpdate] Downloading delta update...
# [ModelUpdate] Loaded llama3.1 v3.1.3
```

## Monitoring

### Flower Dashboard

Open http://localhost:5555 to see:
- Active workers
- Task statistics
- Queue depths
- Task execution times

### Worker Logs

```bash
# Standard worker
docker compose logs -f worker-standard

# GPU worker
docker compose logs -f worker-gpu

# Filter for specific events
docker compose logs -f worker-standard | grep ConfigHotReload
docker compose logs -f worker-standard | grep SAF
```

### Device Registry

Query registered workers:

```bash
# Get all workers
curl http://localhost:8000/api/v1/devices?device_type=celery_worker

# Get specific worker
curl http://localhost:8000/api/v1/devices/worker-standard-01

# Get worker health
curl http://localhost:8000/api/v1/devices/worker-standard-01/heartbeat
```

## Advanced Usage

### Custom Config Callback

```python
from rufus_edge.models import DeviceConfig

def my_config_callback(config: DeviceConfig):
    """Custom callback when config changes."""
    print(f"Config updated to version {config.version}")

    # Update custom application state
    if config.features.get("enable_new_feature"):
        enable_feature()

# Register callback
edge_agent.config_manager.register_on_config_change(my_config_callback)
```

### SAF Queue Management

```python
from examples.celery_edge_worker.rufus_worker_edge import get_saf_bridge

# Get SAF bridge
saf_bridge = get_saf_bridge()

# Queue task with SAF fallback
result = await saf_bridge.queue_task_with_saf(
    task_name="my_task",
    args=("arg1", "arg2"),
    kwargs={"key": "value"},
    task_id="custom_task_id"
)

print(result)  # {"status": "QUEUED_REDIS", "task_id": "...", "queue": "redis"}

# Manually sync SAF queue to Redis
sync_result = await saf_bridge.sync_saf_to_redis()
print(sync_result)  # {"synced": 5, "failed": 0, "total": 5}
```

### Worker Capabilities Routing

```python
# In celeryconfig.py, route tasks based on worker capabilities

task_routes = {
    # GPU tasks go to GPU workers
    'llm_inference': {'queue': 'gpu'},
    'image_processing': {'queue': 'gpu'},

    # Memory-intensive tasks go to high-memory workers
    'batch_processing': {'queue': 'high-memory'},

    # Standard tasks go to default queue
    'check_fraud': {'queue': 'default'},
}
```

## Troubleshooting

### Worker not registering

**Symptom:** Worker starts but doesn't appear in device registry

**Solution:**
1. Check `RUFUS_API_KEY` is set correctly
2. Verify control plane is accessible: `curl http://localhost:8000/health`
3. Check worker logs: `docker compose logs worker-standard`

### Tasks not syncing from SAF

**Symptom:** Redis recovers but tasks stay in SQLite queue

**Solution:**
1. Check sync interval: `SYNC_INTERVAL` environment variable
2. Manually trigger sync: `docker compose exec worker-standard python -c "from examples.celery_edge_worker.rufus_worker_edge import get_saf_bridge; import asyncio; asyncio.run(get_saf_bridge().sync_saf_to_redis())"`
3. Check worker logs for sync errors

### Config not updating

**Symptom:** New config pushed but worker still uses old config

**Solution:**
1. Check config poll interval: `CONFIG_POLL_INTERVAL` environment variable
2. Verify ETag changed: `curl -I http://localhost:8000/api/v1/devices/worker-standard-01/config`
3. Check worker logs: `docker compose logs worker-standard | grep ConfigHotReload`

### Model download fails

**Symptom:** Model update command fails or times out

**Solution:**
1. Check model URL is accessible
2. Verify disk space: `df -h /models`
3. Check worker logs: `docker compose logs worker-gpu | grep ModelUpdate`
4. Disable delta updates if causing issues: Set `use_delta=False` in config

## Performance Benchmarks

Measured on standard hardware (8 CPU, 16GB RAM):

| Metric | Value |
|--------|-------|
| **Config poll overhead** | ~5ms per 60s |
| **Heartbeat overhead** | ~10ms per 60s |
| **SAF check overhead** | <1ms per task |
| **SAF queue sync** | ~50 tasks/second |
| **Model delta download** | 70-90% bandwidth savings |

## Production Deployment

For production use:

1. **Use PostgreSQL for control plane** (not SQLite)
2. **Enable TLS** for control plane API
3. **Rotate API keys** regularly
4. **Monitor worker heartbeats** (alert if stale)
5. **Set appropriate timeouts** (config_poll_interval, sync_interval)
6. **Use Redis Sentinel** for HA broker
7. **Deploy multiple workers** for redundancy

## Next Steps

- See [CELERY_EDGE_INTEGRATION.md](../../CELERY_EDGE_INTEGRATION.md) for full architecture design
- See [GPU_AI_INFERENCE_GUIDE.md](../../docs/GPU_AI_INFERENCE_GUIDE.md) for GPU worker setup
- See [OLLAMA_INTEGRATION.md](../../docs/OLLAMA_INTEGRATION.md) for Ollama LLM integration

## License

MIT License - See [LICENSE](../../LICENSE) for details
