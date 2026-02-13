# Rufus Distributed Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT APPLICATIONS                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │   Web App    │  │   Mobile     │  │   CLI Tool   │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
└─────────┼─────────────────┼─────────────────┼───────────────────────┘
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                            ▼
          ┌──────────────────────────────────────────┐
          │       Rufus API Server (FastAPI)         │
          │  - Workflow Management REST API          │
          │  - Workflow creation & resumption        │
          │  - Status monitoring                     │
          └──────────────────┬───────────────────────┘
                             │
          ┌──────────────────┴───────────────────┐
          │                                      │
          ▼                                      ▼
┌─────────────────────┐              ┌─────────────────────┐
│   PostgreSQL DB     │              │   Redis Broker      │
│  - Workflow state   │              │  - Task queue       │
│  - Worker registry  │              │  - Result backend   │
│  - Audit logs       │              │  - Pub/Sub events   │
│  - Metrics          │              │                     │
└─────────┬───────────┘              └──────────┬──────────┘
          │                                     │
          │         ┌───────────────────────────┘
          │         │
          ▼         ▼
┌─────────────────────────────────────────────────────────────┐
│                     CELERY WORKER POOL                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │  │ Worker N │     │
│  │ (Zone A) │  │ (Zone A) │  │ (Zone B) │  │ (Zone C) │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│       │             │             │             │           │
│  ┌────┴─────────────┴─────────────┴─────────────┴────┐      │
│  │         WorkflowBuilder + Execution Engine        │      │
│  │  - Async task execution                           │      │
│  │  - Parallel task orchestration                    │      │
│  │  - Sub-workflow management                        │      │
│  │  - HTTP step execution                            │      │
│  │  - Worker heartbeat                               │      │
│  └───────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────┐
          │    Flower Monitoring Dashboard       │
          │  - Real-time worker status           │
          │  - Task execution monitoring         │
          │  - Queue depth visualization         │
          │  http://localhost:5555               │
          └──────────────────────────────────────┘
```

---

## Component Details

### 1. API Server (FastAPI)

**Responsibilities:**
- Accept workflow start requests
- Resume paused workflows (HITL)
- Query workflow status
- Stream workflow events
- Manage workflow lifecycle

**Container:** `rufus-server`
**Port:** 8000
**Dependencies:** PostgreSQL, Redis

---

### 2. PostgreSQL Database

**Schema:**
- `workflow_executions` - Main workflow state
- `workflow_audit_log` - Event history
- `workflow_metrics` - Performance data
- `workflow_heartbeats` - Zombie detection
- `worker_nodes` - Worker fleet registry

**Container:** `rufus-postgres`
**Port:** 5432
**Persistence:** Docker volume `postgres_data`

---

### 3. Redis Message Broker

**Purpose:**
- Task queue (Celery broker)
- Result backend (task results)
- Pub/Sub (real-time events)
- Streams (workflow events)

**Container:** `rufus-redis`
**Port:** 6379
**Persistence:** Docker volume `redis_data`
**Configuration:**
- AOF enabled for durability
- 2GB max memory with LRU eviction

---

### 4. Celery Workers

**Responsibilities:**
- Execute ASYNC workflow steps
- Execute PARALLEL tasks
- Orchestrate sub-workflows
- Execute HTTP steps
- Send heartbeats to database

**Container:** `celery-worker` (horizontally scalable)
**Scaling:** `docker-compose up -d --scale celery-worker=N`
**Queues:**
- `default` - Standard priority
- `high_priority` - Real-time tasks
- `low_priority` - Batch jobs

**Worker Types:**

1. **Standard Workers** (default queue)
   - Concurrency: 4 (configurable)
   - Pool: prefork (process-based)
   - Use: General workflow execution

2. **High-Priority Workers** (high_priority queue)
   - Concurrency: 2 (low latency)
   - Pool: prefork
   - Use: Payment processing, real-time tasks

3. **I/O-Bound Workers** (optional, gevent pool)
   - Concurrency: 100 (greenlet-based)
   - Pool: gevent
   - Use: HTTP calls, database queries

---

### 5. Flower Dashboard

**Features:**
- Real-time worker monitoring
- Task execution history
- Queue depth graphs
- Worker resource usage
- Task routing visualization

**Container:** `flower`
**Port:** 5555
**Access:** http://localhost:5555

---

## Data Flow

### Workflow Creation

```
1. Client → API Server
   POST /workflows {"type": "OrderProcessing", "data": {...}}

2. API Server → PostgreSQL
   INSERT INTO workflow_executions (...)

3. API Server → Redis (Pub/Sub)
   PUBLISH workflow:events:123 '{"event": "created"}'

4. Client ← API Server
   {"workflow_id": "abc-123", "status": "RUNNING"}
```

### Async Task Execution

```
1. Workflow Engine → Redis (Queue)
   LPUSH celery '{"task": "process_payment", ...}'

2. Redis → Celery Worker (Broker)
   Worker pulls task from queue

3. Celery Worker → Task Function
   execute_task(state, context, **inputs)

4. Celery Worker → PostgreSQL
   UPDATE workflow_executions SET state = ...

5. Celery Worker → Redis (Result Backend)
   SET celery-task-result:123 '{"result": ...}'

6. Celery Worker → Redis (Pub/Sub)
   PUBLISH workflow:events:abc-123 '{"event": "step_completed"}'
```

### Parallel Task Execution

```
1. Workflow Engine → Celery (Group)
   celery.group([task1.s(), task2.s(), task3.s()])

2. Celery → Redis (Queue)
   LPUSH celery task1, task2, task3

3. Worker Pool → Task Execution
   Worker 1: task1
   Worker 2: task2
   Worker 3: task3

4. Celery → Results Collection
   Wait for all tasks to complete

5. Workflow Engine → Merge Results
   merge_strategy: SHALLOW/DEEP
   Handle conflicts: PREFER_NEW/PREFER_OLD

6. Workflow Engine → Next Step
   Continue workflow execution
```

---

## Deployment Topologies

### Single Host (Development)

```
┌─────────────────────────────────────┐
│         Docker Host                 │
│  ┌────────┐ ┌────────┐ ┌────────┐  │
│  │Postgres│ │ Redis  │ │ Flower │  │
│  └────────┘ └────────┘ └────────┘  │
│  ┌─────────────────────────────┐   │
│  │    3-5 Celery Workers       │   │
│  └─────────────────────────────┘   │
│  ┌────────┐                        │
│  │API Svr │                        │
│  └────────┘                        │
└─────────────────────────────────────┘
```

### Multi-Host (Production - Docker Swarm)

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Manager Node    │  │  Worker Node 1   │  │  Worker Node 2   │
│  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │
│  │ PostgreSQL │  │  │  │ Worker 1-5 │  │  │  │ Worker 6-10│  │
│  │ Redis      │  │  │  └────────────┘  │  │  └────────────┘  │
│  │ API Server │  │  │                  │  │                  │
│  │ Flower     │  │  │                  │  │                  │
│  └────────────┘  │  │                  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
         │                    │                     │
         └────────────────────┴─────────────────────┘
                    Overlay Network
```

### Kubernetes (Production - Multi-Region)

```
┌─────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                       │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────┐    │
│  │   Namespace:     │  │   Namespace:     │  │ Namespace: │    │
│  │   us-east-1      │  │   eu-west-1      │  │  shared    │    │
│  │                  │  │                  │  │            │    │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌────────┐ │    │
│  │ │ Deployment   │ │  │ │ Deployment   │ │  │ │RDS PG  │ │    │
│  │ │ celery-worker│ │  │ │ celery-worker│ │  │ │(AWS)   │ │    │
│  │ │ replicas: 10 │ │  │ │ replicas: 10 │ │  │ └────────┘ │    │
│  │ └──────────────┘ │  │ └──────────────┘ │  │            │    │
│  │                  │  │                  │  │ ┌────────┐ │    │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ │Elasti- │ │    │
│  │ │     HPA      │ │  │ │     HPA      │ │  │ │Cache   │ │    │
│  │ │  min: 3      │ │  │ │  min: 3      │ │  │ │Redis   │ │    │
│  │ │  max: 20     │ │  │ │  max: 20     │ │  │ │(AWS)   │ │    │
│  │ └──────────────┘ │  │ └──────────────┘ │  │ └────────┘ │    │
│  └──────────────────┘  └──────────────────┘  └────────────┘    │
│                                                                  │
│         └────────────────┬────────────────┘                     │
│                          │                                       │
│            ┌─────────────┴──────────────┐                       │
│            │    Ingress Controller      │                       │
│            │  (Load Balancer + TLS)     │                       │
│            └────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Worker Pool Configurations

### CPU-Bound Workloads (prefork)

```yaml
environment:
  WORKER_POOL: prefork
  WORKER_CONCURRENCY: 4
resources:
  limits:
    cpus: '4'
    memory: 4G
```

**Best for:**
- Data processing
- Image/video manipulation
- Encryption/hashing
- Complex calculations

### I/O-Bound Workloads (gevent)

```yaml
environment:
  WORKER_POOL: gevent
  WORKER_CONCURRENCY: 100
resources:
  limits:
    cpus: '2'
    memory: 2G
```

**Best for:**
- HTTP API calls
- Database queries
- File I/O
- Network operations

### Mixed Workload (hybrid)

```yaml
# Deploy both types
services:
  celery-worker-cpu:
    environment:
      WORKER_POOL: prefork
      WORKER_CONCURRENCY: 4
    deploy:
      replicas: 5

  celery-worker-io:
    environment:
      WORKER_POOL: gevent
      WORKER_CONCURRENCY: 100
    deploy:
      replicas: 2
```

---

## Network Architecture

### Docker Compose

```
rufus-network (bridge)
│
├── postgres (postgres:5432)
├── redis (redis:6379)
├── celery-worker-1 (ephemeral)
├── celery-worker-2 (ephemeral)
├── celery-worker-3 (ephemeral)
├── flower (flower:5555)
└── rufus-server (rufus-server:8000)
```

**Exposed Ports:**
- 5432 → PostgreSQL (host:5432)
- 6379 → Redis (host:6379)
- 5555 → Flower (host:5555)
- 8000 → API Server (host:8000)

### Kubernetes

```
Service Mesh
│
├── Service: postgres-svc (ClusterIP)
│   └── Endpoints: postgres pod(s)
│
├── Service: redis-svc (ClusterIP)
│   └── Endpoints: redis pod(s)
│
├── Service: rufus-api (LoadBalancer)
│   └── Endpoints: rufus-server pod(s)
│
└── Service: flower (LoadBalancer)
    └── Endpoints: flower pod(s)
```

---

## Failure Scenarios & Recovery

### Worker Crash

**Detection:**
- Heartbeat missing for >120 seconds
- ZombieScanner marks workflow as `FAILED_WORKER_CRASH`

**Recovery:**
- Kubernetes: Pod restarted automatically
- Docker Compose: Container restarted via health check
- Workflow: Retried or marked for manual intervention

### Database Outage

**Impact:**
- Workflows cannot save state
- Workers cannot update heartbeats
- New workflows cannot start

**Mitigation:**
- Use managed database (AWS RDS) with auto-failover
- Read replicas for high availability
- Connection pool retries

### Redis Outage

**Impact:**
- No new tasks can be queued
- Workers cannot receive tasks
- Results cannot be stored

**Mitigation:**
- Redis Sentinel (master-replica)
- Redis Cluster (sharding)
- Managed service (AWS ElastiCache)

### Network Partition

**Impact:**
- Workers in one zone isolated from database/Redis
- Tasks may be executed twice

**Mitigation:**
- Idempotent task design
- At-least-once delivery guarantees
- Distributed consensus (Raft, Paxos)

---

## Performance Tuning

### Worker Tuning

```bash
# CPU-bound: Match core count
WORKER_CONCURRENCY=$(nproc)

# I/O-bound: Oversubscribe 10-20x
WORKER_CONCURRENCY=$(($(nproc) * 20))

# Memory limit per task
WORKER_MAX_MEMORY_PER_CHILD=500000  # 500MB
WORKER_MAX_TASKS_PER_CHILD=1000     # Restart after 1000 tasks
```

### PostgreSQL Tuning

```sql
-- Connection pool
max_connections = 200
shared_buffers = 4GB
effective_cache_size = 12GB

-- Query performance
work_mem = 64MB
maintenance_work_mem = 512MB

-- Write performance
wal_buffers = 16MB
checkpoint_completion_target = 0.9
```

### Redis Tuning

```bash
# Memory
maxmemory 2gb
maxmemory-policy allkeys-lru

# Persistence
appendonly yes
appendfsync everysec

# Network
tcp-backlog 511
timeout 0
```

---

## Security Architecture

### Network Segmentation

```
┌──────────────────────────────────────────────┐
│  Public Internet                             │
└────────────────┬─────────────────────────────┘
                 │
         ┌───────▼──────────┐
         │  Load Balancer   │
         │  (TLS/443)       │
         └───────┬──────────┘
                 │
┌────────────────▼────────────────────────────┐
│  DMZ Zone                                   │
│  ┌──────────────────┐                       │
│  │  API Server      │                       │
│  │  (Port 8000)     │                       │
│  └──────┬───────────┘                       │
└─────────┼──────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────┐
│  Application Zone (Private)                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ Workers  │  │  Redis   │  │ Postgres │ │
│  │ (No ext  │  │ (6379)   │  │ (5432)   │ │
│  │  access) │  │          │  │          │ │
│  └──────────┘  └──────────┘  └──────────┘ │
└────────────────────────────────────────────┘
```

### Secrets Management

- Docker Secrets (Swarm)
- Kubernetes Secrets (K8s)
- HashiCorp Vault
- AWS Secrets Manager

### TLS/SSL

- API Server: TLS 1.3
- Redis: TLS (rediss://)
- PostgreSQL: SSL mode required
- Internal traffic: mTLS (service mesh)

---

## Cost Optimization

### Spot Instances (AWS)

```yaml
# Use spot instances for workers (70% cost savings)
nodeSelector:
  node.kubernetes.io/instance-type: "spot"
tolerations:
- key: "spot"
  operator: "Equal"
  value: "true"
  effect: "NoSchedule"
```

### Auto-Scaling

- Scale down during off-peak hours
- Use HPA for demand-based scaling
- Cluster Autoscaler for node scaling

### Resource Reservation

```yaml
# Reserve minimum resources, allow bursting
resources:
  requests:
    cpu: 1
    memory: 1G
  limits:
    cpu: 2
    memory: 2G
```

---

For implementation details, see:
- [README.md](README.md) - Quick start guide
- [SCALING.md](SCALING.md) - Comprehensive scaling strategies
