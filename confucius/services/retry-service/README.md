# BullMQ Retry Service

This service handles automatic retries for failed workflow steps using exponential backoff.

## Architecture

1.  **Bridge (`bridge.js`):** Listens to Redis Stream `workflow:retry:bridge` for failure events from Python. Enqueues jobs into BullMQ with a calculated delay.
2.  **Worker (`worker.js`):** Consumes BullMQ jobs when they become ready. Calls the Python API (`POST /api/v1/internal/retry`) to trigger the step re-execution.

## Setup

1.  Install dependencies:
    ```bash
    npm install
    ```

2.  Configure environment variables (create `.env`):
    ```env
    REDIS_HOST=localhost
    REDIS_PORT=6379
    API_BASE_URL=http://localhost:8000
    ```

## Running

Start both the bridge and worker:

```bash
node src/index.js
```

## Integration with Python

The Python application (FastAPI) must publish failure events to the Redis stream:

```python
from .events import event_publisher

# On failure
await event_publisher.publish_to_retry_queue(
    workflow_id="...",
    step_index=1,
    task_name="MyTask",
    error="Something went wrong",
    context={"retry_count": 0}
)
```
