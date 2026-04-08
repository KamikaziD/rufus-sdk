# Production Deployment Guide

This guide explains how to deploy Ruvon using pre-built Docker images from Docker Hub.

## Overview

**Pre-built Images:**
- `yourname/ruvon-server:latest` - REST API server
- `yourname/ruvon-worker:latest` - Celery workers
- `yourname/ruvon-flower:latest` - Monitoring UI

**Your Project:**
- Custom workflow definitions (YAML)
- Custom step functions (Python)
- Custom state models (Pydantic)

---

## For Ruvon Maintainers: Building and Publishing Images

### Step 1: Build Production Images

```bash
cd /Users/kim/PycharmProjects/ruvon/docker

# Build images (PyPI version for testing)
./build-production-images.sh 0.3.5 yourname

# Or specify custom version and registry
./build-production-images.sh 0.3.5 your-docker-hub-username
```

This creates:
- `yourname/ruvon-server:0.3.5` and `:latest`
- `yourname/ruvon-worker:0.3.5` and `:latest`
- `yourname/ruvon-flower:0.3.5` and `:latest`

### Step 2: Test Locally

```bash
# Update docker-compose.user-deployment.yml with your username
sed -i '' 's/yourname/your-docker-hub-username/g' docker-compose.user-deployment.yml

# Create test project
mkdir -p ../examples/my-test-app/my_app
mkdir -p ../examples/my-test-app/config

# Copy docker-compose to test project
cp docker-compose.user-deployment.yml ../examples/my-test-app/docker-compose.yml

# Test the images
cd ../examples/my-test-app
docker-compose up -d
```

### Step 3: Push to Docker Hub

```bash
# Login to Docker Hub
docker login

# Build and push
cd /Users/kim/PycharmProjects/ruvon/docker
./build-production-images.sh 0.3.5 your-docker-hub-username true
```

### Step 4: Switch to Production PyPI (When Published)

Edit the three Dockerfiles and uncomment the production PyPI lines:

```dockerfile
# Comment out PyPI:
# RUN pip install --no-cache-dir \
#     --index-url https://pypi.org/simple/ \
#     --extra-index-url https://pypi.org/simple/ \
#     'ruvon-sdk[all]==0.3.5'

# Uncomment production PyPI:
RUN pip install --no-cache-dir 'ruvon-sdk[all]'
```

Then rebuild and push:
```bash
./build-production-images.sh 1.0.0 your-docker-hub-username true
```

---

## For End Users: Using Pre-built Images

### Quick Start

1. **Create your project structure:**

```bash
mkdir my-payment-app
cd my-payment-app

# Create directory structure
mkdir -p my_app config

# Download docker-compose template
curl -O https://raw.githubusercontent.com/your-org/ruvon-sdk/main/docker/docker-compose.user-deployment.yml
mv docker-compose.user-deployment.yml docker-compose.yml

# Update image registry in docker-compose.yml
sed -i 's/yourname/actual-docker-hub-username/g' docker-compose.yml
```

2. **Define your state models** (`my_app/models.py`):

```python
from pydantic import BaseModel
from typing import Optional

class PaymentState(BaseModel):
    user_id: str
    amount: float
    status: Optional[str] = None
    transaction_id: Optional[str] = None
```

3. **Implement step functions** (`my_app/steps.py`):

```python
from ruvon.models import StepContext
from my_app.models import PaymentState

def validate_payment(state: PaymentState, context: StepContext) -> dict:
    if state.amount <= 0:
        raise ValueError("Invalid amount")
    return {"status": "validated"}

def process_payment(state: PaymentState, context: StepContext) -> dict:
    # Your payment processing logic
    transaction_id = f"txn_{state.user_id}_{state.amount}"
    return {
        "transaction_id": transaction_id,
        "status": "completed"
    }
```

4. **Create workflow definition** (`config/payment.yaml`):

```yaml
workflow_type: "PaymentProcessing"
initial_state_model: "my_app.models.PaymentState"

steps:
  - name: "Validate_Payment"
    type: "STANDARD"
    function: "my_app.steps.validate_payment"
    automate_next: true

  - name: "Process_Payment"
    type: "ASYNC"
    function: "my_app.steps.process_payment"
```

5. **Create `__init__.py`:**

```bash
touch my_app/__init__.py
```

6. **Deploy:**

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f ruvon-worker

# Access services
open http://localhost:8000/docs   # API
open http://localhost:5555        # Flower
```

7. **Create a workflow:**

```bash
curl -X POST http://localhost:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_type": "PaymentProcessing",
    "initial_data": {
      "user_id": "user123",
      "amount": 99.99
    }
  }'
```

---

## Project Structure

```
my-payment-app/
├── docker-compose.yml       ← Uses pre-built images
├── .env                     ← Database passwords, etc.
├── my_app/                  ← YOUR business logic
│   ├── __init__.py
│   ├── models.py           ← Pydantic state models
│   └── steps.py            ← Step functions
└── config/                  ← YOUR workflow definitions
    ├── payment.yaml
    └── fraud_check.yaml
```

---

## Scaling Workers

```bash
# Scale to 10 workers
docker-compose up -d --scale ruvon-worker=10

# Scale down to 2
docker-compose up -d --scale ruvon-worker=2
```

---

## Troubleshooting

### Workers can't find my code

**Problem:** `ModuleNotFoundError: No module named 'my_app'`

**Solution:** Check volume mounts in docker-compose.yml:
```yaml
volumes:
  - ./my_app:/app/my_app  # ✅ Correct path
  - ./config:/app/config  # ✅ Correct path
```

### Workflows not loading

**Problem:** "Workflow type 'MyWorkflow' not found"

**Solution:**
1. Check `config/*.yaml` files are mounted
2. Verify PYTHONPATH includes `/app`
3. Restart containers: `docker-compose restart`

### Database connection errors

**Problem:** "connection refused" or "database does not exist"

**Solution:**
```bash
# Check database is running
docker-compose ps postgres

# Create database if needed
docker-compose exec postgres createdb -U myapp my_app_db
```

---

## Environment Variables

Create `.env` file:

```bash
# Database
POSTGRES_DB=my_app_db
POSTGRES_USER=myapp
POSTGRES_PASSWORD=super_secret_password

# Workers
WORKER_CONCURRENCY=4
WORKER_POOL=prefork
WORKER_LOG_LEVEL=info
```

---

## Next Steps

- Read the [API Documentation](http://localhost:8000/docs)
- Monitor workers with [Flower](http://localhost:5555)
- See [examples/](../examples/) for more complex workflows
- Read [CLAUDE.md](../CLAUDE.md) for architecture details
