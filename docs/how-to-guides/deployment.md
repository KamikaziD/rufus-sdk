# How to deploy Rufus

This guide covers deploying Rufus workflows to production environments.

## Overview

Rufus supports multiple deployment models:

- **Embedded SDK** - Run in your existing Python application
- **Standalone service** - Deploy as FastAPI application
- **Distributed workers** - Scale with Celery workers
- **Edge devices** - Deploy to IoT/POS terminals

## Production configuration

### Environment variables

Set these for production deployments:

```bash
# Database
export DATABASE_URL="postgresql://user:password@host:5432/rufus_prod"
export POSTGRES_POOL_MIN_SIZE=20
export POSTGRES_POOL_MAX_SIZE=100

# Celery (if using distributed execution)
export CELERY_BROKER_URL="redis://redis:6379/0"
export CELERY_RESULT_BACKEND="redis://redis:6379/0"

# Performance optimizations
export RUFUS_USE_UVLOOP=true
export RUFUS_USE_ORJSON=true

# Application settings
export ENVIRONMENT=production
export LOG_LEVEL=INFO
```

### Database setup

Initialize PostgreSQL schema:

```bash
# Apply migrations
cd src/rufus
export DATABASE_URL="postgresql://user:password@host:5432/rufus_prod"
alembic upgrade head

# Verify migration status
alembic current
```

## Deployment models

### Model 1: Embedded SDK

Embed Rufus in your existing application:

```python
# app.py
import asyncio
from fastapi import FastAPI
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.thread_pool import ThreadPoolExecutionProvider

app = FastAPI()

# Initialize Rufus
persistence = None
builder = None

@app.on_event("startup")
async def startup():
    global persistence, builder

    # Initialize providers
    persistence = PostgresPersistenceProvider(
        db_url="postgresql://user:password@host:5432/rufus_prod",
        pool_min_size=20,
        pool_max_size=100
    )
    await persistence.initialize()

    execution = ThreadPoolExecutionProvider(max_workers=20)

    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=execution
    )

@app.on_event("shutdown")
async def shutdown():
    if persistence:
        await persistence.close()

@app.post("/orders")
async def create_order(order_data: dict):
    """Create order and start workflow."""

    # Start workflow
    workflow = await builder.create_workflow(
        workflow_type="OrderProcessing",
        initial_data=order_data
    )

    return {
        "order_id": order_data["order_id"],
        "workflow_id": str(workflow.id)
    }
```

Run with uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

### Model 2: Standalone FastAPI service

Deploy Rufus server separately:

```bash
# Start Rufus server
uvicorn rufus_server.main:app --host 0.0.0.0 --port 8000
```

Use REST API from your application:

```python
import httpx

# Create workflow via API
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://rufus-server:8000/workflows/start",
        json={
            "workflow_type": "OrderProcessing",
            "initial_data": order_data
        }
    )

    workflow_id = response.json()["workflow_id"]
```

### Model 3: Distributed with Celery

Scale horizontally with Celery workers:

**Start Celery workers:**

```bash
# Worker 1
export DATABASE_URL="postgresql://..."
export CELERY_BROKER_URL="redis://..."
export CELERY_RESULT_BACKEND="redis://..."

celery -A rufus.celery_app worker \
    --loglevel=info \
    --concurrency=10 \
    --hostname=worker1@%h

# Worker 2
celery -A rufus.celery_app worker \
    --loglevel=info \
    --concurrency=10 \
    --hostname=worker2@%h
```

**Start API server:**

```bash
uvicorn rufus_server.main:app --host 0.0.0.0 --port 8000
```

## Docker deployment

### Single container

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ src/
COPY config/ config/

# Apply migrations on startup
COPY docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "rufus_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# docker-entrypoint.sh
#!/bin/bash
set -e

# Apply migrations
cd /app/src/rufus
alembic upgrade head

# Start application
cd /app
exec "$@"
```

Build and run:

```bash
docker build -t rufus:latest .

docker run -d \
    --name rufus-server \
    -p 8000:8000 \
    -e DATABASE_URL="postgresql://..." \
    rufus:latest
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: rufus
      POSTGRES_PASSWORD: rufus_secret_2024
      POSTGRES_DB: rufus_prod
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rufus"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  rufus-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://rufus:rufus_secret_2024@postgres:5432/rufus_prod
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  celery-worker:
    build: .
    command: celery -A rufus.celery_app worker --loglevel=info --concurrency=10
    environment:
      DATABASE_URL: postgresql://rufus:rufus_secret_2024@postgres:5432/rufus_prod
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: 3  # Scale workers

volumes:
  postgres_data:
```

Deploy:

```bash
docker compose up -d
docker compose ps
docker compose logs -f rufus-server
```

## Kubernetes deployment

### Deployment manifests

```yaml
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rufus-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: rufus-server
  template:
    metadata:
      labels:
        app: rufus-server
    spec:
      containers:
      - name: rufus
        image: rufus:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rufus-secrets
              key: database-url
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-worker
spec:
  replicas: 5
  selector:
    matchLabels:
      app: celery-worker
  template:
    metadata:
      labels:
        app: celery-worker
    spec:
      containers:
      - name: celery
        image: rufus:latest
        command: ["celery"]
        args:
          - "-A"
          - "rufus.celery_app"
          - "worker"
          - "--loglevel=info"
          - "--concurrency=10"
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rufus-secrets
              key: database-url
        - name: CELERY_BROKER_URL
          valueFrom:
            secretKeyRef:
              name: rufus-secrets
              key: celery-broker-url
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: rufus-server
spec:
  selector:
    app: rufus-server
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

```yaml
# kubernetes/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: rufus-secrets
type: Opaque
stringData:
  database-url: postgresql://user:password@postgres:5432/rufus_prod
  celery-broker-url: redis://redis:6379/0
  celery-result-backend: redis://redis:6379/0
```

Deploy to Kubernetes:

```bash
kubectl apply -f kubernetes/secrets.yaml
kubectl apply -f kubernetes/deployment.yaml

kubectl get pods
kubectl logs -f deployment/rufus-server
```

### Horizontal Pod Autoscaler

```yaml
# kubernetes/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rufus-server-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: rufus-server
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: celery-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: celery-worker
  minReplicas: 5
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 80
```

## Production checklist

### Before deployment

- [ ] Database migrations applied (`alembic upgrade head`)
- [ ] Environment variables configured
- [ ] Secrets stored securely (not in code)
- [ ] PostgreSQL connection pool sized appropriately
- [ ] Celery workers configured (if using distributed execution)
- [ ] Health check endpoints working
- [ ] Logging configured
- [ ] Monitoring/metrics setup

### Database

- [ ] PostgreSQL 13+ installed
- [ ] Connection pooling configured (min: 20, max: 100 for production)
- [ ] Backups configured
- [ ] SSL/TLS enabled for connections
- [ ] Read replicas setup (for read-heavy workloads)

### Security

- [ ] Database credentials in environment variables or secrets manager
- [ ] API authentication enabled (if exposing REST API)
- [ ] Network security groups configured
- [ ] SSL/TLS certificates installed
- [ ] Rate limiting enabled

### Monitoring

- [ ] Application logs forwarded to centralized logging
- [ ] Metrics exported (Prometheus/Datadog/CloudWatch)
- [ ] Alerts configured for failures
- [ ] Performance dashboards created

### High availability

- [ ] Multiple server replicas (3+ recommended)
- [ ] Load balancer configured
- [ ] Database replication setup
- [ ] Redis cluster (if using Celery)
- [ ] Automated failover configured

## Monitoring and observability

### Health check endpoint

```python
# In your FastAPI app
@app.get("/health")
async def health_check():
    """Health check endpoint for load balancer."""

    try:
        # Check database connection
        await persistence.list_workflows(limit=1)

        return {"status": "healthy"}

    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### Prometheus metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
workflows_started = Counter(
    'workflows_started_total',
    'Total workflows started',
    ['workflow_type']
)

workflow_duration = Histogram(
    'workflow_duration_seconds',
    'Workflow execution duration',
    ['workflow_type']
)

active_workflows = Gauge(
    'active_workflows',
    'Number of active workflows'
)

# Export endpoint
from prometheus_client import generate_latest

@app.get("/metrics")
async def metrics():
    return Response(
        generate_latest(),
        media_type="text/plain"
    )
```

### Logging

Configure structured logging:

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name
        }
        return json.dumps(log_obj)

# Configure logging
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())

logger = logging.getLogger("rufus")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

## Scaling strategies

### Vertical scaling

Increase resources per instance:

- Increase PostgreSQL connection pool size
- Increase Celery worker concurrency
- Increase server memory/CPU

### Horizontal scaling

Add more instances:

- Deploy multiple FastAPI server replicas
- Deploy multiple Celery workers
- Use database read replicas for read-heavy workloads

### Database scaling

- Enable connection pooling (pgBouncer)
- Setup read replicas
- Partition large tables
- Add database indexes

## Troubleshooting production issues

### Database connection errors

```bash
# Check connection pool exhaustion
kubectl logs deployment/rufus-server | grep "pool exhausted"

# Increase pool size
export POSTGRES_POOL_MAX_SIZE=200
```

### High memory usage

```bash
# Check for memory leaks
kubectl top pods

# Restart pods
kubectl rollout restart deployment/rufus-server
```

### Slow workflow execution

```bash
# Check database performance
# Query slow queries log

# Check Celery queue backlog
celery -A rufus.celery_app inspect active
```

## Next steps

- [Configure monitoring](troubleshooting.md)
- [Optimize performance](configuration.md)
- [Test in production](testing.md)

## See also

- [Configuration guide](configuration.md)
- [Troubleshooting guide](troubleshooting.md)
- CLAUDE.md for migration and database setup
- Docker Compose files in `docker/` directory
