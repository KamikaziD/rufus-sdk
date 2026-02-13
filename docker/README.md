# Rufus Docker Deployment

Complete Docker and Kubernetes deployment for Rufus workflow engine with distributed Celery workers.

## 📁 Directory Structure

```
docker/
├── README.md                          # This file
├── SCALING.md                         # Comprehensive scaling guide
├── Dockerfile.celery-worker           # Celery worker image
├── Dockerfile.rufus-server            # API server image
├── docker-compose.production.yml      # Production deployment
├── .env.example                       # Environment template
├── quick-start.sh                     # One-command deployment
└── kubernetes/                        # Kubernetes manifests
    ├── celery-worker-deployment.yaml  # Worker deployment + HPA
    ├── configmap.yaml                 # Configuration
    └── redis-deployment.yaml          # Redis (for non-managed)
```

---

## 🚀 Quick Start

### Option 1: One-Command Deployment

```bash
cd docker
./quick-start.sh 5  # Deploy with 5 workers
```

### Option 2: Manual Deployment

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start infrastructure and workers
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=5

# 3. Access Flower dashboard
open http://localhost:5555
```

---

## 🎯 Access Points

| Service | URL | Description |
|---------|-----|-------------|
| **Flower Dashboard** | http://localhost:5555 | Real-time worker monitoring |
| **API Server** | http://localhost:8000 | REST API |
| **PostgreSQL** | localhost:5432 | Database |
| **Redis** | localhost:6379 | Message broker |

---

## 📊 Scaling

**Scale to 10 workers:**
```bash
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=10
```

**View worker status:**
```bash
docker-compose -f docker-compose.production.yml ps celery-worker
```

See [SCALING.md](SCALING.md) for comprehensive scaling guide.

---

## 🛠️ Common Commands

```bash
# View logs
docker-compose -f docker-compose.production.yml logs -f celery-worker

# Restart workers
docker-compose -f docker-compose.production.yml restart celery-worker

# Stop all
docker-compose -f docker-compose.production.yml down

# Database backup
docker-compose -f docker-compose.production.yml exec postgres \
    pg_dump -U rufus rufus_production > backup.sql
```

---

For detailed documentation, see [SCALING.md](SCALING.md).
