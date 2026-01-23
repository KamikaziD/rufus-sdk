# Rufus Flask API Example

This example demonstrates how to embed the Rufus workflow engine into a Flask REST API application, providing HTTP endpoints for workflow management.

## Features

- **REST API Endpoints** for workflow operations
- **PostgreSQL Persistence** for production-ready storage
- **Human-in-the-Loop** workflows with pause/resume
- **Order Processing Workflow** demonstrating e-commerce use case
- **Saga Pattern** with compensation functions
- **CORS Support** for frontend integration

## Performance Optimizations

This example includes **Phase 1 performance optimizations** for production workloads:

- **uvloop Event Loop** (2-4x faster async I/O) - Automatically enabled
- **orjson Serialization** (3-5x faster JSON) - Used for all API responses and state persistence
- **Optimized PostgreSQL Pool** - Tuned for high concurrency (10-50 connections)
- **Import Caching** - 162x speedup for repeated step function imports

### Benchmark Results

```
JSON Serialization: 2.4M ops/sec (orjson)
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
Expected Throughput: 1,000+ workflows/sec
```

### Performance Configuration

Tune via `.env` file:
```bash
# PostgreSQL connection pool (tune based on your workload)
POSTGRES_POOL_MIN_SIZE=10  # Default
POSTGRES_POOL_MAX_SIZE=50  # Default

# Performance features (enabled by default)
RUFUS_USE_UVLOOP=true
RUFUS_USE_ORJSON=true
```

## Workflow: Order Processing

The example implements an order processing workflow with:

1. **Initialize Order** - Create order ID and calculate total
2. **Reserve Inventory** - Reserve items from stock
3. **Process Payment** - Charge customer's payment method
4. **Request Approval** - Pause for manual approval (high-value orders)
5. **Process Approval Decision** - Handle approval/rejection
6. **Create Shipment** - Generate shipping label and tracking
7. **Send Confirmation Email** - Notify customer

## Prerequisites

- Python 3.9+
- PostgreSQL 12+ (running and accessible)
- Rufus SDK installed

## Installation

### 1. Install Dependencies

```bash
cd examples/flask_api
pip install -r requirements.txt
```

### 2. Install Rufus SDK

```bash
# From the repository root
pip install -e ../..
```

### 3. Set Up PostgreSQL

Create a database and user:

```sql
CREATE DATABASE rufus_db;
CREATE USER rufus_user WITH PASSWORD 'rufus_password';
GRANT ALL PRIVILEGES ON DATABASE rufus_db TO rufus_user;
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your database credentials
```

### 5. Run the Application

```bash
python app.py
```

The API will be available at `http://localhost:5000`.

## API Endpoints

### 1. Health Check

```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "rufus-workflow-api"
}
```

### 2. Start a Workflow

```bash
POST /workflows
Content-Type: application/json

{
  "workflow_type": "OrderProcessing",
  "initial_data": {
    "customer_id": "CUST123",
    "customer_email": "customer@example.com",
    "items": [
      {
        "product_id": "PROD001",
        "name": "Widget",
        "quantity": 2,
        "price": 29.99
      }
    ]
  }
}
```

**Response:**
```json
{
  "workflow_id": "abc-123-def",
  "status": "WAITING_HUMAN",
  "current_step": "Request_Approval",
  "state": {
    "order_id": "ORD-A1B2C3D4",
    "customer_id": "CUST123",
    "total_amount": 59.98,
    "order_status": "PENDING_APPROVAL",
    ...
  }
}
```

### 3. Get Workflow Status

```bash
GET /workflows/{workflow_id}
```

**Response:**
```json
{
  "workflow_id": "abc-123-def",
  "workflow_type": "OrderProcessing",
  "status": "WAITING_HUMAN",
  "current_step": "Request_Approval",
  "current_step_index": 3,
  "total_steps": 7,
  "state": { ... }
}
```

### 4. Resume a Paused Workflow

```bash
POST /workflows/{workflow_id}/resume
Content-Type: application/json

{
  "user_input": {
    "approved": true,
    "approver_id": "ADMIN001",
    "notes": "Approved for processing"
  }
}
```

**Response:**
```json
{
  "workflow_id": "abc-123-def",
  "status": "COMPLETED",
  "current_step": null,
  "state": {
    "order_status": "SHIPPED",
    "tracking_number": "TRK123456789",
    ...
  }
}
```

### 5. List Workflows

```bash
GET /workflows?status=WAITING_HUMAN&limit=10
```

**Query Parameters:**
- `status` - Filter by workflow status
- `workflow_type` - Filter by workflow type
- `limit` - Maximum results (default: 50)

**Response:**
```json
{
  "workflows": [
    {
      "workflow_id": "abc-123-def",
      "workflow_type": "OrderProcessing",
      "status": "WAITING_HUMAN",
      "current_step": "Request_Approval",
      "created_at": "2024-01-23T10:30:00"
    }
  ],
  "total": 1
}
```

### 6. Cancel a Workflow

```bash
POST /workflows/{workflow_id}/cancel
```

**Response:**
```json
{
  "workflow_id": "abc-123-def",
  "status": "CANCELLED",
  "message": "Workflow cancelled successfully"
}
```

## Example Usage with cURL

### Start an order workflow:

```bash
curl -X POST http://localhost:5000/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_type": "OrderProcessing",
    "initial_data": {
      "customer_id": "CUST123",
      "customer_email": "test@example.com",
      "items": [
        {
          "product_id": "PROD001",
          "name": "Widget",
          "quantity": 2,
          "price": 29.99
        }
      ]
    }
  }'
```

### Check workflow status:

```bash
curl http://localhost:5000/workflows/{workflow_id}
```

### Approve the order:

```bash
curl -X POST http://localhost:5000/workflows/{workflow_id}/resume \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": {
      "approved": true,
      "approver_id": "ADMIN001",
      "notes": "Order approved"
    }
  }'
```

## Production Deployment

### Using Gunicorn

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Using Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

## Architecture

```
┌─────────────┐
│   Client    │
│  (Browser/  │
│   Mobile)   │
└──────┬──────┘
       │ HTTP
       ▼
┌─────────────────────────────────┐
│      Flask REST API              │
│  ┌────────────────────────────┐ │
│  │  Workflow Engine            │ │
│  │  ┌──────────────────────┐  │ │
│  │  │ PostgresPersistence  │  │ │
│  │  │ SyncExecutor         │  │ │
│  │  │ LoggingObserver      │  │ │
│  │  └──────────────────────┘  │ │
│  └────────────────────────────┘ │
└─────────────┬───────────────────┘
              │
              ▼
       ┌──────────────┐
       │  PostgreSQL  │
       └──────────────┘
```

## Error Handling

The API returns appropriate HTTP status codes:

- `200` - Success
- `201` - Created (workflow started)
- `400` - Bad Request (invalid input)
- `404` - Not Found (workflow doesn't exist)
- `500` - Internal Server Error

## Customization

### Adding New Workflows

1. Create state model in `state_models.py`
2. Define step functions in `steps.py`
3. Create YAML workflow definition
4. Register in `workflow_registry.yaml`

### Using Async Executors

For production async workflows, replace `SyncExecutor` with `CeleryExecutor`:

```python
from rufus.implementations.execution.celery import CeleryExecutor
from celery import Celery

celery_app = Celery('workflows', broker='redis://localhost:6379')
executor = CeleryExecutor(celery_app=celery_app)
```

## Troubleshooting

### Database Connection Errors

Ensure PostgreSQL is running and credentials in `.env` are correct.

### Import Errors

Make sure Rufus SDK is installed: `pip install -e ../..`

### Workflow Not Advancing

Check that `automate_next: true` is set in workflow YAML for steps that should auto-advance.

## Further Reading

- [Rufus Documentation](../../README.md)
- [QUICKSTART Guide](../../QUICKSTART.md)
- [API Reference](../../API_REFERENCE.md)
