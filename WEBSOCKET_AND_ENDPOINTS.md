# WebSocket and Control Endpoints Implementation

## Overview

This document describes the implementation of real-time workflow updates via WebSocket and control endpoints (retry, rewind, resume) for the Ruvon workflow engine.

**Version**: 0.3.9
**Date**: 2025-02-18

## Implementation Summary

### Endpoints Added

1. **WebSocket**: `WS /api/v1/workflow/{workflow_id}/subscribe`
   - Real-time workflow event streaming
   - Uses Redis pub/sub for event delivery
   - Automatically reconnects on disconnect

2. **Retry**: `POST /api/v1/workflow/{workflow_id}/retry`
   - Resets failed workflows to ACTIVE status
   - Dispatches Celery task to resume execution
   - Publishes status change event

3. **Rewind**: `POST /api/v1/workflow/{workflow_id}/rewind`
   - Decrements current_step by 1
   - Resets workflow to ACTIVE status
   - Clears last step result
   - Used for debugging and correction

4. **Resume**: `POST /api/v1/workflow/{workflow_id}/resume`
   - Resumes paused workflows with user input
   - Supports human-in-the-loop workflows
   - Dispatches Celery task with user data

---

## WebSocket Real-time Updates

### Architecture

```
Browser                  FastAPI Server           Redis Pub/Sub
   │                           │                        │
   │──── WS Connect ──────────>│                        │
   │                           │                        │
   │                           │─── Subscribe ─────────>│
   │                           │   (workflow:events:{id})│
   │                           │                        │
   │                           │<─── Event Stream ──────│
   │<── JSON Event ────────────│                        │
   │                           │                        │
   │                      (Repeat for all events)       │
   │                           │                        │
   │──── Disconnect ──────────>│                        │
   │                           │─── Unsubscribe ───────>│
```

### Endpoint

**URL**: `ws://localhost:8000/api/v1/workflow/{workflow_id}/subscribe`

**Authentication**: None (for debug UI - add auth for production)

**Connection Flow**:
1. Client connects via WebSocket
2. Server accepts connection
3. Server subscribes to Redis channel: `workflow:events:{workflow_id}`
4. Server streams events to client as JSON
5. On disconnect, server unsubscribes and closes Redis connection

### Event Format

All events are JSON objects with:

```json
{
  "event_type": "workflow.updated",
  "timestamp": 1708285432.123,
  "workflow_id": "uuid-here",
  "status": "ACTIVE",
  "current_step": 2,
  ...additional fields...
}
```

### Event Types

| Event Type | Description | Payload |
|------------|-------------|---------|
| `workflow.created` | New workflow started | Full workflow dict |
| `workflow.updated` | Workflow state changed | Full workflow dict |
| `workflow.status_changed` | Status transition | old_status, new_status |
| `workflow.completed` | Workflow finished | Full workflow dict |
| `workflow.failed` | Workflow failed | Full workflow dict + error |
| `step.started` | Step execution began | step_name, step_index |
| `step.completed` | Step execution finished | step_name, result |
| `step.failed` | Step execution failed | step_name, error |

### JavaScript Client Example

```javascript
const workflowId = "uuid-here";
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/workflow/${workflowId}/subscribe`;

const socket = new WebSocket(wsUrl);

socket.onopen = () => {
  console.log('WebSocket connected');
};

socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Workflow event:', data);

  // Update UI based on event
  if (data.event_type === 'workflow.status_changed') {
    updateStatusBadge(data.new_status);
  } else if (data.event_type === 'step.completed') {
    updateStepProgress(data.step_name);
  }
};

socket.onerror = (error) => {
  console.error('WebSocket error:', error);
};

socket.onclose = () => {
  console.log('WebSocket disconnected');
  // Optionally reconnect
  setTimeout(() => connectWebSocket(), 5000);
};
```

### Python Client Example (Testing)

```python
import asyncio
import websockets
import json

async def subscribe_to_workflow(workflow_id: str):
    uri = f"ws://localhost:8000/api/v1/workflow/{workflow_id}/subscribe"

    async with websockets.connect(uri) as websocket:
        print(f"Connected to workflow {workflow_id}")

        async for message in websocket:
            event = json.loads(message)
            print(f"Event: {event['event_type']}")
            print(f"Data: {event}")

# Run
asyncio.run(subscribe_to_workflow("your-workflow-id"))
```

---

## Retry Endpoint

### Purpose

Reset failed workflows to ACTIVE status and attempt re-execution from the failed step.

### Endpoint

**URL**: `POST /api/v1/workflow/{workflow_id}/retry`

**Method**: POST

**Authentication**: Optional (via X-User-ID header)

**Request Body**: None

**Response**:
```json
{
  "status": "retry_initiated",
  "workflow_id": "uuid-here"
}
```

### Behavior

1. Validates workflow exists
2. Checks workflow status is FAILED
3. Changes status to ACTIVE
4. Publishes `workflow.status_changed` event
5. Dispatches `resume_from_async_task` Celery task
6. Returns immediately (async execution)

### Example

```bash
curl -X POST http://localhost:8000/api/v1/workflow/uuid-here/retry
```

```json
{
  "status": "retry_initiated",
  "workflow_id": "uuid-here"
}
```

### Error Responses

| Status Code | Condition | Message |
|-------------|-----------|---------|
| 400 | Invalid UUID | "Invalid workflow ID format" |
| 404 | Workflow not found | "Workflow not found" |
| 400 | Workflow not failed | "Only failed workflows can be retried" |
| 503 | Engine not initialized | "Workflow Engine not initialized." |

### Use Cases

- Retry after fixing external service
- Retry after transient network error
- Retry after database deadlock
- Manual intervention after review

---

## Rewind Endpoint

### Purpose

Move workflow back one step for debugging or correction purposes.

### Endpoint

**URL**: `POST /api/v1/workflow/{workflow_id}/rewind`

**Method**: POST

**Authentication**: Optional (via X-User-ID header)

**Request Body**: None

**Response**:
```json
{
  "status": "rewound",
  "current_step": 1,
  "workflow_id": "uuid-here"
}
```

### Behavior

1. Validates workflow exists
2. Checks current_step > 0
3. Decrements current_step by 1
4. Clears step result for decremented step
5. Sets status to ACTIVE
6. Publishes `workflow.status_changed` event with `rewound: true`
7. Returns new current_step

### Example

```bash
curl -X POST http://localhost:8000/api/v1/workflow/uuid-here/rewind
```

```json
{
  "status": "rewound",
  "current_step": 1,
  "workflow_id": "uuid-here"
}
```

### Error Responses

| Status Code | Condition | Message |
|-------------|-----------|---------|
| 400 | Invalid UUID | "Invalid workflow ID format" |
| 404 | Workflow not found | "Workflow not found" |
| 400 | At first step | "Cannot rewind: already at first step" |
| 503 | Engine not initialized | "Workflow Engine not initialized." |

### Use Cases

- Re-execute step with different data
- Debug step function logic
- Test workflow branching
- Correct data entry error

### ⚠️ Warnings

- **Side Effects**: Rewind does NOT undo side effects (DB writes, API calls, etc.)
- **Idempotency**: Step functions should be idempotent for safe rewind
- **Production**: Use with caution in production - primarily a debugging tool

---

## Resume Endpoint

### Purpose

Resume paused workflows with user input (human-in-the-loop).

### Endpoint

**URL**: `POST /api/v1/workflow/{workflow_id}/resume`

**Method**: POST

**Authentication**: Optional (via X-User-ID header)

**Request Body**:
```json
{
  "user_input": {
    "approved": true,
    "reviewer_notes": "Looks good",
    "approval_code": "ABC123"
  }
}
```

**Response**:
```json
{
  "status": "resume_initiated",
  "workflow_id": "uuid-here"
}
```

### Behavior

1. Validates workflow exists
2. Checks workflow status is PAUSED
3. Dispatches `resume_from_async_task` with user_input
4. Publishes `workflow.resume_requested` event
5. Returns immediately (async execution)

### Example

```bash
curl -X POST http://localhost:8000/api/v1/workflow/uuid-here/resume \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": {
      "approved": true,
      "amount": 10000,
      "reviewer_id": "user123"
    }
  }'
```

```json
{
  "status": "resume_initiated",
  "workflow_id": "uuid-here"
}
```

### Error Responses

| Status Code | Condition | Message |
|-------------|-----------|---------|
| 400 | Invalid UUID | "Invalid workflow ID format" |
| 404 | Workflow not found | "Workflow not found" |
| 400 | Workflow not paused | "Only paused workflows can be resumed" |
| 503 | Engine not initialized | "Workflow Engine not initialized." |

### Use Cases

- Human approval workflows
- Manual review before high-value transactions
- Data validation by expert
- Multi-stage approval processes

---

## Testing

### Unit Tests

All endpoints have comprehensive unit tests in `tests/test_server_endpoints.py`:

```bash
# Run all endpoint tests
pytest tests/test_server_endpoints.py -v

# Run specific test
pytest tests/test_server_endpoints.py::test_retry_endpoint_success -v
```

### Integration Testing

**1. Test WebSocket with browser console**:
```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/workflow/uuid-here/subscribe');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

**2. Test retry endpoint**:
```bash
# Create failed workflow first
curl -X POST http://localhost:8000/api/v1/workflow/start \
  -H "Content-Type: application/json" \
  -d '{"workflow_type": "TestWorkflow", "initial_data": {}}'

# Get workflow ID, let it fail, then retry
curl -X POST http://localhost:8000/api/v1/workflow/{id}/retry
```

**3. Test rewind endpoint**:
```bash
# Create workflow, advance 2 steps, then rewind
curl -X POST http://localhost:8000/api/v1/workflow/{id}/rewind
```

**4. Test resume endpoint**:
```bash
# Create workflow that pauses, then resume
curl -X POST http://localhost:8000/api/v1/workflow/{id}/resume \
  -H "Content-Type: application/json" \
  -d '{"user_input": {"approved": true}}'
```

---

## Event Publishing

All endpoints publish events to Redis for real-time updates and audit logging.

### Event Publisher

Located in `src/ruvon/events.py`, the `EventPublisher` class:
- Publishes to **Redis Streams** (persistent audit log)
- Publishes to **Redis Pub/Sub** (real-time updates)
- Supports Prometheus metrics

### Channel Pattern

All workflow events published to:
- **Stream**: `workflow:persistence` (persistent)
- **Pub/Sub**: `workflow:events:{workflow_id}` (real-time)

### Publishing Examples

```python
from ruvon.events import event_publisher

# Publish status change
await event_publisher._publish(
    'workflow:persistence',
    'workflow.status_changed',
    {
        "workflow_id": str(workflow_id),
        "old_status": "FAILED",
        "new_status": "ACTIVE",
        "retried": True
    }
)

# Publish resume request
await event_publisher._publish(
    'workflow:persistence',
    'workflow.resume_requested',
    {
        "workflow_id": str(workflow_id),
        "user_input": user_data
    }
)
```

---

## Deployment

### Docker Compose

The `docker-compose.production.yml` includes:
- **Redis**: Message broker for events
- **Ruvon Server**: FastAPI server with WebSocket support
- **Celery Workers**: Process async tasks (retry/resume)

**Environment variables**:
```yaml
environment:
  REDIS_URL: redis://redis:6379/0
  CELERY_BROKER_URL: redis://redis:6379/0
  CELERY_RESULT_BACKEND: redis://redis:6379/0
  DATABASE_URL: postgresql://...
```

### Starting Services

```bash
# Start all services
docker-compose -f docker/docker-compose.production.yml up -d

# Check logs
docker-compose -f docker/docker-compose.production.yml logs ruvon-server
docker-compose -f docker/docker-compose.production.yml logs redis

# Test WebSocket
curl http://localhost:8000/health
# Then connect via browser to ws://localhost:8000/api/v1/workflow/{id}/subscribe
```

### Production Considerations

1. **Authentication**: Add JWT/API key auth to WebSocket endpoint
2. **Rate Limiting**: Already enabled via SlowAPI for REST endpoints
3. **CORS**: Configure for frontend domains
4. **Monitoring**: Use Prometheus metrics from EventPublisher
5. **Scaling**: Redis pub/sub scales horizontally with workers
6. **Security**: Use wss:// (WebSocket over TLS) in production

---

## UI Integration

The debug UI (`src/ruvon_server/debug_ui/static/js/app.js`) already has:

### WebSocket Connection

```javascript
// Line 668 in app.js
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${wsProtocol}//${window.location.host}${API_BASE_URL}/workflow/${workflowId}/subscribe`;
workflowSocket = new WebSocket(wsUrl);
```

### Button Handlers

- **Retry Button**: Calls `/api/v1/workflow/{id}/retry`
- **Rewind Button**: Calls `/api/v1/workflow/{id}/rewind`
- **Resume Button**: Calls `/api/v1/workflow/{id}/resume` with modal input

All handlers already exist in the UI - they just needed working endpoints!

---

## Troubleshooting

### WebSocket 403 Forbidden

**Symptom**: Browser console shows `connection rejected (403 Forbidden)`

**Solution**: Verify endpoint exists and Redis is running
```bash
# Check Redis
docker ps | grep redis

# Check endpoint registration
curl http://localhost:8000/openapi.json | jq '.paths | keys'
```

### Events Not Streaming

**Symptom**: WebSocket connects but no events received

**Solution**: Verify EventPublisher is publishing to correct channel
```bash
# Monitor Redis pub/sub
redis-cli
> SUBSCRIBE workflow:events:*

# Check if events are published
# (trigger workflow state change and watch for messages)
```

### Retry Not Working

**Symptom**: Retry returns 200 but workflow doesn't restart

**Solution**: Check Celery worker is running and task is dispatched
```bash
# Check Celery workers
docker-compose logs celery-worker

# Check task queue
redis-cli LLEN celery

# Check for task errors
docker-compose logs celery-worker | grep ERROR
```

---

## Migration from Confucius

The implementation was ported from Confucius (`confucius/src/confucius/routers.py`):

### Confucius Endpoints (Reference)

- `WS /workflow/{workflow_id}/subscribe` (line 672-741)
- `POST /workflow/{workflow_id}/retry` (line 418-441)
- `POST /workflow/{workflow_id}/rewind` (line 443-477)
- `POST /workflow/{workflow_id}/resume` (existed in Confucius)

### Differences

1. **URL Prefix**: Ruvon uses `/api/v1/workflow` vs Confucius `/workflow`
2. **Authentication**: Ruvon uses optional `X-User-ID` header
3. **Event Publisher**: Ruvon uses centralized EventPublisher class
4. **Celery Integration**: Ruvon uses `ruvon.tasks` module

### Compatibility

All endpoints are backward compatible with Confucius UI patterns. The UI required no changes - only the server endpoints were missing.

---

## Future Enhancements

1. **WebSocket Authentication**: Add JWT token validation
2. **WebSocket Multiplexing**: Support multiple workflow subscriptions per connection
3. **Event Filtering**: Allow clients to filter event types
4. **Replay Events**: Add endpoint to replay historical events
5. **Batch Retry**: Support retrying multiple workflows
6. **Step-level Rewind**: Allow rewind to specific step (not just -1)
7. **Resume Validation**: Add input schema validation for resume

---

## References

- Confucius implementation: `confucius/src/confucius/routers.py`
- Event Publisher: `src/ruvon/events.py`
- API Models: `src/ruvon_server/api_models.py`
- UI JavaScript: `src/ruvon_server/debug_ui/static/js/app.js`
- Tests: `tests/test_server_endpoints.py`
