# Scaling Rufus Celery Workers with Docker

Complete guide for distributed deployment and horizontal scaling of Celery workers.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Docker Compose Deployment](#docker-compose-deployment)
3. [Kubernetes Deployment](#kubernetes-deployment)
4. [Scaling Strategies](#scaling-strategies)
5. [Monitoring](#monitoring)
6. [Production Best Practices](#production-best-practices)

---

## Quick Start

**Start the full distributed stack:**

```bash
cd docker
docker-compose -f docker-compose.production.yml up -d
```

**Scale workers to 10 instances:**

```bash
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=10
```

**View worker status:**

```bash
# Flower UI
open http://localhost:5555

# Or command line
docker-compose -f docker-compose.production.yml exec celery-worker \
    celery -A ruvon.celery_app inspect active
```

---

## Docker Compose Deployment

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Host                              │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ PostgreSQL   │  │   Redis      │  │ Flower       │      │
│  │ (Database)   │  │ (Broker)     │  │ (Monitoring) │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                 │                                  │
│         │                 │                                  │
│  ┌──────┴─────────────────┴──────────────────────┐         │
│  │         Celery Worker Pool                     │         │
│  │  ┌──────┐ ┌──────┐ ┌──────┐      ┌──────┐    │         │
│  │  │Worker│ │Worker│ │Worker│ ...  │Worker│    │         │
│  │  │  #1  │ │  #2  │ │  #3  │      │ #N   │    │         │
│  │  └──────┘ └──────┘ └──────┘      └──────┘    │         │
│  └─────────────────────────────────────────────────┘        │
│         │                                                    │
│  ┌──────┴──────────┐                                        │
│  │  Rufus Server   │                                        │
│  │  (API/UI)       │                                        │
│  └─────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Steps

**1. Configure environment:**

```bash
# Create .env file
cat > docker/.env <<EOF
POSTGRES_PASSWORD=your_secure_password
WORKER_CONCURRENCY=4
WORKER_POOL=prefork
WORKER_LOG_LEVEL=info
WORKER_REGION=us-east-1
WORKER_ZONE=zone-a
EOF
```

**2. Build images:**

```bash
cd docker
docker-compose -f docker-compose.production.yml build
```

**3. Start infrastructure (PostgreSQL + Redis):**

```bash
docker-compose -f docker-compose.production.yml up -d postgres redis
```

**4. Apply database migrations:**

```bash
docker-compose -f docker-compose.production.yml run --rm ruvon-server \
    sh -c "cd src/ruvon && alembic upgrade head"
```

**5. Start workers:**

```bash
# Start 5 workers
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=5
```

**6. Start monitoring and API:**

```bash
docker-compose -f docker-compose.production.yml up -d flower ruvon-server
```

**7. Verify deployment:**

```bash
# Check all containers
docker-compose -f docker-compose.production.yml ps

# Check worker registration in database
docker-compose -f docker-compose.production.yml exec postgres \
    psql -U ruvon -d ruvon_production -c "SELECT worker_id, region, zone, status, last_heartbeat FROM worker_nodes;"

# Check Flower dashboard
open http://localhost:5555
```

### Scaling Commands

**Scale up:**

```bash
# Add more workers
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=20

# Verify scaling
docker-compose -f docker-compose.production.yml ps celery-worker
```

**Scale down:**

```bash
# Reduce workers (graceful shutdown)
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=5
```

**Regional deployment:**

```bash
# Deploy workers in different regions
WORKER_REGION=us-west-1 WORKER_ZONE=zone-a \
    docker-compose -f docker-compose.production.yml up -d --scale celery-worker=3

WORKER_REGION=eu-west-1 WORKER_ZONE=zone-b \
    docker-compose -f docker-compose.production.yml up -d --scale celery-worker=3
```

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (v1.24+)
- kubectl configured
- Container registry access
- Helm (optional, for easier management)

### Deployment Steps

**1. Build and push images:**

```bash
# Build worker image
docker build -f docker/Dockerfile.celery-worker -t ruvondev/ruvon-celery-worker:latest .

# Build server image
docker build -f docker/Dockerfile.ruvon-server -t your-registry/ruvon-server:latest .

# Push to registry
docker push ruvondev/ruvon-celery-worker:latest
docker push your-registry/ruvon-server:latest
```

**2. Create namespace:**

```bash
kubectl create namespace rufus-production
```

**3. Create secrets:**

```bash
# Database credentials
kubectl create secret generic rufus-secrets \
    --from-literal=database-url='postgresql://user:password@postgres-host:5432/rufus' \
    -n rufus-production

# Or use a secret file
cat > secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ruvon-secrets
  namespace: rufus-production
type: Opaque
stringData:
  database-url: "postgresql://user:password@postgres-host:5432/rufus"
EOF

kubectl apply -f secret.yaml
```

**4. Deploy Redis:**

```bash
kubectl apply -f docker/kubernetes/redis-deployment.yaml -n rufus-production
```

**5. Deploy ConfigMap:**

```bash
kubectl apply -f docker/kubernetes/configmap.yaml -n rufus-production
```

**6. Deploy Celery workers:**

```bash
# Update image in celery-worker-deployment.yaml first
kubectl apply -f docker/kubernetes/celery-worker-deployment.yaml -n rufus-production
```

**7. Verify deployment:**

```bash
# Check pods
kubectl get pods -n rufus-production

# Check worker logs
kubectl logs -f -l component=celery-worker -n rufus-production

# Check autoscaling
kubectl get hpa -n rufus-production
```

### Kubernetes Scaling

**Manual scaling:**

```bash
# Scale to 10 replicas
kubectl scale deployment rufus-celery-worker --replicas=10 -n rufus-production
```

**Auto-scaling:**

The HorizontalPodAutoscaler is configured to:
- **Min replicas:** 3
- **Max replicas:** 20
- **Target CPU:** 70%
- **Target Memory:** 80%

**Monitor autoscaling:**

```bash
kubectl get hpa rufus-celery-worker-hpa -n rufus-production --watch
```

**Update HPA:**

```bash
# Change max replicas to 50
kubectl patch hpa rufus-celery-worker-hpa \
    --patch '{"spec":{"maxReplicas":50}}' \
    -n rufus-production
```

---

## Scaling Strategies

### 1. Queue-Based Scaling

**Route tasks to specific queues:**

```python
from ruvon.implementations.execution.celery import CeleryExecutionProvider

execution = CeleryExecutionProvider()

# High priority queue
execution.dispatch_async_task(
    func_path="tasks.payment",
    state_data=state,
    workflow_id=workflow_id,
    data_region="high_priority"  # Routes to high_priority queue
)
```

**Deploy queue-specific workers:**

```bash
# High priority workers (low concurrency, fast)
docker run -e CELERY_QUEUES=high_priority \
    -e WORKER_CONCURRENCY=2 \
    ruvondev/ruvon-celery-worker

# Low priority workers (high concurrency, batch)
docker run -e CELERY_QUEUES=low_priority \
    -e WORKER_CONCURRENCY=8 \
    ruvondev/ruvon-celery-worker
```

### 2. Region-Based Scaling

**Deploy workers in multiple regions:**

```yaml
# docker-compose.multi-region.yml
services:
  celery-worker-us-east:
    build: ...
    environment:
      WORKER_REGION: us-east-1
      WORKER_ZONE: zone-a
    deploy:
      replicas: 5

  celery-worker-eu-west:
    build: ...
    environment:
      WORKER_REGION: eu-west-1
      WORKER_ZONE: zone-b
    deploy:
      replicas: 5
```

**Route tasks by region:**

```python
execution.dispatch_async_task(
    func_path="tasks.payment",
    state_data=state,
    workflow_id=workflow_id,
    data_region="eu-west-1"  # Routes to EU workers
)
```

### 3. Load-Based Autoscaling

**Docker Swarm autoscaling:**

```yaml
# docker-compose.swarm.yml
services:
  celery-worker:
    deploy:
      replicas: 3
      update_config:
        parallelism: 2
        delay: 10s
      restart_policy:
        condition: on-failure
        max_attempts: 3
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
      placement:
        constraints:
          - node.role == worker
```

**Kubernetes autoscaling metrics:**

```yaml
# Custom metrics from Prometheus
- type: External
  external:
    metric:
      name: celery_queue_length
      selector:
        matchLabels:
          queue: default
    target:
      type: AverageValue
      averageValue: "100"
```

### 4. Time-Based Scaling

**Cron-based scaling for predictable load:**

```bash
# Scale up during business hours (9 AM)
0 9 * * * kubectl scale deployment rufus-celery-worker --replicas=20

# Scale down at night (6 PM)
0 18 * * * kubectl scale deployment rufus-celery-worker --replicas=5
```

---

## Monitoring

### Flower Dashboard

**Access Flower:**

```bash
# Docker Compose
open http://localhost:5555

# Kubernetes port-forward
kubectl port-forward svc/ruvon-flower 5555:5555 -n rufus-production
open http://localhost:5555
```

**Flower features:**
- Real-time worker status
- Task progress monitoring
- Queue lengths
- Worker statistics
- Task history

### Prometheus Metrics

**Celery exporter:**

```yaml
# Add to docker-compose.production.yml
celery-exporter:
  image: danihodovic/celery-exporter
  environment:
    CELERY_BROKER_URL: redis://redis:6379/0
  ports:
    - "9808:9808"
```

**Key metrics:**
- `celery_tasks_total` - Total tasks processed
- `celery_tasks_runtime_seconds` - Task execution time
- `celery_workers_total` - Active workers
- `celery_queue_length` - Tasks waiting in queue

### Database Monitoring

**Check worker health:**

```sql
-- Active workers
SELECT worker_id, region, zone, status, last_heartbeat
FROM worker_nodes
WHERE status = 'active'
  AND last_heartbeat > NOW() - INTERVAL '2 minutes';

-- Worker distribution
SELECT region, zone, COUNT(*) as worker_count
FROM worker_nodes
WHERE status = 'active'
GROUP BY region, zone;

-- Workflow throughput
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as workflows_created,
    COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed,
    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed
FROM workflow_executions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;
```

---

## Production Best Practices

### 1. Resource Limits

**Set appropriate limits:**

```yaml
# docker-compose.production.yml
celery-worker:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 2G
      reservations:
        cpus: '1'
        memory: 1G
```

**Calculate resource needs:**

- **CPU:** 1 CPU per 4 concurrent tasks (prefork pool)
- **Memory:** 256MB base + 100MB per concurrent task
- **Network:** Depends on payload size (plan for 10Mbps per worker)

### 2. Worker Pool Selection

**prefork (default):**
```bash
WORKER_POOL=prefork WORKER_CONCURRENCY=4
```
- Best for CPU-bound tasks
- Isolated processes (memory safe)
- Higher memory usage

**gevent (I/O-bound):**
```bash
WORKER_POOL=gevent WORKER_CONCURRENCY=100
```
- Best for I/O-bound tasks (HTTP, database)
- Lower memory usage
- Higher concurrency

**eventlet:**
```bash
WORKER_POOL=eventlet WORKER_CONCURRENCY=100
```
- Similar to gevent
- Better Windows support

### 3. Queue Management

**Separate queues by priority:**

```python
# High priority (payment, real-time)
-Q high_priority

# Default (normal workflows)
-Q default

# Low priority (analytics, cleanup)
-Q low_priority
```

**Rate limiting:**

```python
# Celery task configuration
@celery_app.task(rate_limit='10/m')  # 10 tasks per minute
def rate_limited_task():
    pass
```

### 4. Health Checks

**Liveness probe:**
```bash
celery -A ruvon.celery_app inspect ping -d celery@worker1
```

**Readiness probe:**
```bash
celery -A ruvon.celery_app inspect active -d celery@worker1
```

### 5. Graceful Shutdown

**Docker:**
```dockerfile
STOPSIGNAL SIGTERM
```

**Kubernetes:**
```yaml
lifecycle:
  preStop:
    exec:
      command: ["celery", "-A", "rufus.celery_app", "control", "shutdown"]
terminationGracePeriodSeconds: 60
```

### 6. Logging

**Structured logging:**

```bash
WORKER_LOG_LEVEL=info
CELERY_TASK_SERIALIZER=json
```

**Centralized logging:**

```yaml
# Use logging driver
celery-worker:
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
```

### 7. Security

**Network isolation:**

```yaml
# docker-compose.production.yml
networks:
  ruvon-network:
    driver: bridge
    internal: true  # No external access
```

**Environment secrets:**

```bash
# Use Docker secrets or Kubernetes secrets
docker secret create db_password ./db_password.txt
```

**TLS for Redis:**

```bash
CELERY_BROKER_URL=rediss://redis:6380/0  # SSL/TLS
```

---

## Troubleshooting

### Workers not connecting

```bash
# Check Redis connectivity
docker-compose exec celery-worker redis-cli -h redis ping

# Check PostgreSQL connectivity
docker-compose exec celery-worker pg_isready -h postgres -U ruvon
```

### High memory usage

```bash
# Check for memory leaks
docker stats

# Restart workers periodically
celery -A ruvon.celery_app control shutdown

# Or use max-tasks-per-child
celery -A ruvon.celery_app worker --max-tasks-per-child=1000
```

### Tasks stuck in queue

```bash
# Check queue length
celery -A ruvon.celery_app inspect active_queues

# Purge queue (DANGEROUS - only in dev)
celery -A ruvon.celery_app purge

# Check worker availability
celery -A ruvon.celery_app inspect stats
```

---

## Cost Optimization

### 1. Spot Instances (AWS)

```yaml
# Kubernetes node selector
nodeSelector:
  node.kubernetes.io/instance-type: "spot"
```

### 2. Vertical Pod Autoscaler

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: ruvon-celery-worker-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ruvon-celery-worker
  updatePolicy:
    updateMode: "Auto"
```

### 3. Cluster Autoscaler

- Scale worker nodes based on pod pending state
- Combine with HPA for full autoscaling

---

## Summary

**Docker Compose:**
- ✅ Quick local development
- ✅ Easy scaling (`--scale`)
- ✅ Good for small-medium deployments
- ❌ Limited high-availability features

**Kubernetes:**
- ✅ Production-grade orchestration
- ✅ Advanced autoscaling (HPA, VPA, Cluster Autoscaler)
- ✅ Self-healing and rolling updates
- ✅ Multi-region deployment
- ⚠️ Higher complexity

**Recommended Stack:**
- **Dev/Test:** Docker Compose
- **Production (<50 workers):** Docker Swarm or Compose
- **Production (>50 workers):** Kubernetes with managed services (RDS, ElastiCache)
