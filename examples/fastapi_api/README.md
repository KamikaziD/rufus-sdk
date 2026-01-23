# Rufus FastAPI Example

This example demonstrates how to embed the Rufus workflow engine into a modern FastAPI application with full async/await support and automatic API documentation.

## Features

- **Full Async/Await** - Native async support throughout
- **Automatic API Documentation** - Interactive Swagger UI and ReDoc
- **Pydantic Models** - Request/response validation with type hints
- **Dependency Injection** - Clean architecture with FastAPI dependencies
- **PostgreSQL Persistence** - Production-ready database storage
- **CORS Support** - Ready for frontend integration
- **Type Safety** - Full type hints for better IDE support

## Why FastAPI?

FastAPI is ideal for Rufus integration because:
- **Performance** - One of the fastest Python frameworks
- **Modern Python** - Built with Python 3.8+ features (async/await, type hints)
- **Auto Documentation** - Swagger UI generated automatically
- **Validation** - Pydantic models ensure data integrity
- **Production Ready** - Used by major companies worldwide

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
cd examples/fastapi_api
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
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.

## Interactive API Documentation

FastAPI automatically generates interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

You can test all endpoints directly in the browser!

## API Endpoints

### 1. Health Check

```http
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

```http
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

**Response (201 Created):**
```json
{
  "workflow_id": "abc-123-def",
  "status": "WAITING_HUMAN",
  "current_step": "Request_Approval",
  "state": {
    "order_id": "ORD-A1B2C3D4",
    "customer_id": "CUST123",
    "total_amount": 59.98,
    "order_status": "PENDING_APPROVAL"
  }
}
```

### 3. Get Workflow Status

```http
GET /workflows/{workflow_id}
```

**Response (200 OK):**
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

```http
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

**Response (200 OK):**
```json
{
  "workflow_id": "abc-123-def",
  "status": "COMPLETED",
  "current_step": null,
  "state": {
    "order_status": "SHIPPED",
    "tracking_number": "TRK123456789"
  }
}
```

### 5. List Workflows

```http
GET /workflows?status=WAITING_HUMAN&limit=10
```

**Query Parameters:**
- `status` (optional) - Filter by workflow status
- `workflow_type` (optional) - Filter by workflow type
- `limit` (optional, 1-100, default: 50) - Maximum results

**Response (200 OK):**
```json
{
  "workflows": [
    {
      "workflow_id": "abc-123-def",
      "workflow_type": "OrderProcessing",
      "status": "WAITING_HUMAN",
      "current_step": 3,
      "created_at": "2024-01-23T10:30:00"
    }
  ],
  "total": 1
}
```

### 6. Cancel a Workflow

```http
POST /workflows/{workflow_id}/cancel
```

**Response (200 OK):**
```json
{
  "workflow_id": "abc-123-def",
  "status": "CANCELLED",
  "message": "Workflow cancelled successfully"
}
```

## Example Usage with Python httpx

```python
import httpx
import asyncio

async def create_order():
    async with httpx.AsyncClient() as client:
        # Start workflow
        response = await client.post("http://localhost:8000/workflows", json={
            "workflow_type": "OrderProcessing",
            "initial_data": {
                "customer_id": "CUST123",
                "customer_email": "test@example.com",
                "items": [{
                    "product_id": "PROD001",
                    "name": "Widget",
                    "quantity": 2,
                    "price": 29.99
                }]
            }
        })
        workflow = response.json()
        workflow_id = workflow["workflow_id"]

        # Check status
        response = await client.get(f"http://localhost:8000/workflows/{workflow_id}")
        print(response.json())

        # Approve order
        response = await client.post(
            f"http://localhost:8000/workflows/{workflow_id}/resume",
            json={
                "user_input": {
                    "approved": True,
                    "approver_id": "ADMIN001",
                    "notes": "Looks good!"
                }
            }
        )
        print(response.json())

asyncio.run(create_order())
```

## Example Usage with cURL

### Start an order workflow:

```bash
curl -X POST http://localhost:8000/workflows \
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
curl http://localhost:8000/workflows/{workflow_id}
```

### Approve the order:

```bash
curl -X POST http://localhost:8000/workflows/{workflow_id}/resume \
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

### Using Uvicorn with Multiple Workers

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Using Gunicorn with Uvicorn Workers

```bash
gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Run with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t rufus-fastapi .
docker run -p 8000:8000 --env-file .env rufus-fastapi
```

## Architecture

```
┌─────────────────────┐
│   Client            │
│  (Browser/Mobile/   │
│   Other Services)   │
└──────────┬──────────┘
           │ HTTP/REST
           ▼
┌─────────────────────────────────────┐
│      FastAPI Application             │
│  ┌───────────────────────────────┐  │
│  │  Pydantic Models & Validation │  │
│  └───────────────┬───────────────┘  │
│                  │                   │
│  ┌───────────────▼───────────────┐  │
│  │     Workflow Engine            │  │
│  │  ┌──────────────────────────┐ │  │
│  │  │ PostgresPersistence      │ │  │
│  │  │ SyncExecutor             │ │  │
│  │  │ LoggingObserver          │ │  │
│  │  └──────────────────────────┘ │  │
│  └────────────────────────────────┘  │
└─────────────────┬───────────────────┘
                  │
                  ▼
           ┌──────────────┐
           │  PostgreSQL  │
           └──────────────┘
```

## FastAPI-Specific Features

### 1. Automatic Validation

Pydantic models ensure request data is valid:

```python
class WorkflowCreateRequest(BaseModel):
    workflow_type: str
    initial_data: Dict[str, Any]

@app.post("/workflows")
async def create_workflow(request: WorkflowCreateRequest):
    # request is already validated!
    pass
```

### 2. Dependency Injection

Clean architecture with reusable dependencies:

```python
def get_engine() -> WorkflowEngine:
    if workflow_engine is None:
        raise HTTPException(status_code=503)
    return workflow_engine

@app.get("/workflows/{id}")
async def get_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(get_engine)
):
    # engine is automatically injected
    workflow = await engine.get_workflow(workflow_id)
```

### 3. Async/Await Throughout

All operations are truly asynchronous:

```python
@app.post("/workflows")
async def create_workflow(request: WorkflowCreateRequest):
    workflow = await engine.start_workflow(...)
    while workflow.status == "ACTIVE":
        await workflow.next_step()
    return workflow
```

### 4. Interactive Documentation

Visit `/docs` for Swagger UI where you can:
- Browse all endpoints
- See request/response schemas
- Test endpoints directly in the browser
- Generate API client code

## Error Handling

FastAPI returns standard HTTP status codes:

- `200` - Success
- `201` - Created
- `400` - Bad Request (validation errors)
- `404` - Not Found
- `500` - Internal Server Error
- `503` - Service Unavailable

Validation errors include detailed field-level information:

```json
{
  "detail": [
    {
      "loc": ["body", "initial_data", "items", 0, "quantity"],
      "msg": "ensure this value is greater than 0",
      "type": "value_error.number.not_gt"
    }
  ]
}
```

## Testing

FastAPI includes excellent testing support:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_create_workflow():
    response = client.post("/workflows", json={
        "workflow_type": "OrderProcessing",
        "initial_data": {...}
    })
    assert response.status_code == 201
    assert "workflow_id" in response.json()
```

## Customization

### Adding Authentication

```python
from fastapi import Depends, HTTPException, Header

async def verify_token(authorization: str = Header()):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid token")
    # Verify token...
    return user

@app.post("/workflows")
async def create_workflow(
    request: WorkflowCreateRequest,
    user = Depends(verify_token)
):
    # user is authenticated
    pass
```

### Adding Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/workflows")
@limiter.limit("10/minute")
async def create_workflow(request: Request, ...):
    pass
```

### WebSocket Support for Real-Time Updates

```python
from fastapi import WebSocket

@app.websocket("/workflows/{workflow_id}/watch")
async def watch_workflow(websocket: WebSocket, workflow_id: str):
    await websocket.accept()
    while True:
        workflow = await engine.get_workflow(workflow_id)
        await websocket.send_json({
            "status": workflow.status,
            "current_step": workflow.current_step_name
        })
        await asyncio.sleep(1)
```

## Performance

FastAPI with Uvicorn is highly performant:

- **20,000+ requests/second** on modern hardware
- **Native async/await** - no thread overhead
- **Uvloop** integration for maximum performance
- **Connection pooling** for database efficiency

## Comparison: Flask vs FastAPI

| Feature | Flask | FastAPI |
|---------|-------|---------|
| Performance | Good | Excellent |
| Async Support | Via extensions | Native |
| Type Hints | Optional | Required |
| Validation | Manual/extensions | Built-in (Pydantic) |
| Documentation | Manual | Automatic |
| Python Version | 3.7+ | 3.8+ |

## Troubleshooting

### Import Errors

Make sure Rufus SDK is installed: `pip install -e ../..`

### Database Connection Issues

Check that PostgreSQL is running and `.env` has correct credentials.

### Port Already in Use

Change the port in `.env` or run: `uvicorn main:app --port 8001`

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Rufus Documentation](../../README.md)
- [QUICKSTART Guide](../../QUICKSTART.md)
- [API Reference](../../API_REFERENCE.md)
- [Pydantic Documentation](https://docs.pydantic.dev/)
