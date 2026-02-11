# Rufus Docker Deployment

Complete guide for running Rufus Edge Cloud Platform with Docker Compose.

## Overview

This Docker setup provides a complete Rufus Edge control plane environment:

- **PostgreSQL Database** - Persistent storage for workflows and edge device state
- **Rufus API Server** - FastAPI-based control plane for device management
- **Automatic Schema** - Database initialized on first start
- **Seed Data** - Demo workflows and edge devices pre-loaded
- **Health Checks** - Container health monitoring
- **Volume Persistence** - Data survives container restarts

---

## Quick Start (2 minutes)

### 1. Start Services

```bash
cd docker
docker compose up -d
```

### 2. Verify Services

```bash
# Check container status
docker compose ps

# Expected output:
# NAME             STATUS                    PORTS
# rufus-postgres   Up (healthy)              0.0.0.0:5433->5432/tcp
# rufus-cloud      Up (healthy)              0.0.0.0:8000->8000/tcp

# Check API health
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

### 3. Access Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **Rufus API** | http://localhost:8000 | N/A |
| **API Docs** | http://localhost:8000/docs | N/A |
| **PostgreSQL** | localhost:5433 | rufus / rufus_secret_2024 |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Docker Compose                     │
│  ┌──────────────────┐      ┌───────────────────┐  │
│  │  rufus-postgres  │      │   rufus-cloud     │  │
│  │  (PostgreSQL)    │      │   (FastAPI)       │  │
│  │                  │      │                   │  │
│  │  Port: 5433      │◄─────┤  Port: 8000       │  │
│  │  Health: ✓       │      │  Health: ✓        │  │
│  └────────┬─────────┘      └───────────────────┘  │
│           │                                        │
│           ▼                                        │
│  ┌──────────────────┐      ┌───────────────────┐  │
│  │ postgres_data    │      │ artifacts_data    │  │
│  │ (Volume)         │      │ (Volume)          │  │
│  └──────────────────┘      └───────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## Services

### PostgreSQL Database

**Container:** `rufus-postgres`
**Image:** `postgres:15-alpine`
**Port:** `5433` → `5432` (host → container)
**Volume:** `postgres_data` → `/var/lib/postgresql/data`

**Configuration:**
- Max connections: 1000
- Shared buffers: 512MB
- Max WAL size: 2GB

**Initialization:**
- Schema auto-applied from `docker/init-db.sql` on first start
- Includes all workflow and edge tables
- Optimized for high concurrency

**Health Check:**
```bash
docker exec rufus-postgres pg_isready -U rufus -d rufus_cloud
```

### Rufus API Server

**Container:** `rufus-cloud`
**Image:** Built from `docker/Dockerfile.server`
**Port:** `8000` → `8000` (host → container)
**Volume:** `artifacts_data` → `/app/artifacts`

**Features:**
- FastAPI control plane
- Device registration and management
- Workflow execution API
- Store-and-Forward (SAF) sync
- ETag-based config distribution

**Health Check:**
```bash
curl http://localhost:8000/health
```

**API Documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Configuration

### Environment Variables

Configuration is managed via `.env` file or environment variables.

**Create .env file:**
```bash
cp .env.example .env
# Edit .env with your settings
```

**Key variables:**

```bash
# Database Credentials
POSTGRES_USER=rufus
POSTGRES_PASSWORD=rufus_secret_2024  # Change in production!
POSTGRES_DB=rufus_cloud
POSTGRES_PORT=5433

# Server Configuration
RUFUS_SERVER_PORT=8000
RUFUS_REGISTRATION_KEY=demo-registration-key-2024  # Change in production!

# Connection Pool (High Concurrency)
POSTGRES_POOL_MIN_SIZE=50
POSTGRES_POOL_MAX_SIZE=500
POSTGRES_POOL_COMMAND_TIMEOUT=60

# Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

**See `.env.example` for complete configuration options.**

### Production Hardening

For production deployments:

1. **Change default passwords:**
   ```bash
   POSTGRES_PASSWORD=<strong-random-password>
   RUFUS_REGISTRATION_KEY=<secure-random-string>
   ```

2. **Enable encryption at rest:**
   ```bash
   ENABLE_ENCRYPTION_AT_REST=true
   RUFUS_ENCRYPTION_KEY=<256-bit-hex-key>
   ```

3. **Adjust connection pool:**
   ```bash
   # For 10-100 concurrent workflows
   POSTGRES_POOL_MIN_SIZE=50
   POSTGRES_POOL_MAX_SIZE=200

   # For 100+ concurrent workflows
   POSTGRES_POOL_MIN_SIZE=100
   POSTGRES_POOL_MAX_SIZE=500
   ```

4. **Restrict network access:**
   ```yaml
   # docker-compose.yml
   postgres:
     ports:
       - "127.0.0.1:5433:5432"  # Localhost only
   ```

---

## Data Management

### Seed Data

The database is automatically seeded on first start with:

- **4 demo workflows** (completed, active, failed, waiting)
- **5 edge devices** (POS terminals, ATM, kiosk, mobile reader)

**Manual seeding:**
```bash
python tools/seed_data.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud" \
  --type all
```

### Database Cleanup

Reset database to clean state with seed data:

```bash
python tools/cleanup_database.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"

# Options:
# --mode delete-all        - Delete everything and re-seed (default)
# --mode load-test-only    - Delete only load test devices
# --no-seed                - Skip re-seeding
# --yes                    - Skip confirmation
```

### Database Backups

**Backup:**
```bash
docker exec rufus-postgres pg_dump -U rufus rufus_cloud > backup.sql
```

**Restore:**
```bash
docker exec -i rufus-postgres psql -U rufus rufus_cloud < backup.sql
```

**Automated backups:**
```bash
# Add to crontab for daily backups
0 2 * * * docker exec rufus-postgres pg_dump -U rufus rufus_cloud | gzip > /backups/rufus_$(date +\%Y\%m\%d).sql.gz
```

---

## Common Operations

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f rufus-cloud
docker compose logs -f postgres

# Last 100 lines
docker compose logs --tail=100
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart rufus-cloud

# Rebuild and restart (after code changes)
docker compose up -d --build
```

### Stop Services

```bash
# Stop but keep volumes
docker compose down

# Stop and remove volumes (DESTRUCTIVE)
docker compose down -v
```

### Database Access

**psql CLI:**
```bash
docker exec -it rufus-postgres psql -U rufus -d rufus_cloud
```

**From host machine:**
```bash
psql "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
```

**List tables:**
```sql
\dt

-- Expected tables:
-- workflow_executions
-- workflow_audit_log
-- workflow_metrics
-- workflow_heartbeats
-- edge_devices
-- device_commands
-- ... (20+ tables)
```

### Container Shell Access

```bash
# PostgreSQL container
docker exec -it rufus-postgres /bin/sh

# Rufus server container
docker exec -it rufus-cloud /bin/bash
```

---

## Development Workflow

### Local Development

1. **Start services:**
   ```bash
   docker compose up -d
   ```

2. **Make code changes** (local files)

3. **Rebuild and restart:**
   ```bash
   docker compose up -d --build rufus-cloud
   ```

4. **View logs:**
   ```bash
   docker compose logs -f rufus-cloud
   ```

### Database Schema Changes

1. **Update schema:**
   ```bash
   # Edit docker/init-db.sql
   vim docker/init-db.sql
   ```

2. **Recreate database:**
   ```bash
   docker compose down -v  # WARNING: Deletes all data
   docker compose up -d
   ```

3. **Verify schema:**
   ```bash
   docker exec rufus-postgres psql -U rufus -d rufus_cloud -c "\d workflow_executions"
   ```

---

## Troubleshooting

### Services Won't Start

**Check container logs:**
```bash
docker compose logs postgres
docker compose logs rufus-cloud
```

**Common issues:**
- Port already in use: Change `POSTGRES_PORT` or `RUFUS_SERVER_PORT` in `.env`
- Database initialization failed: Check `init-db.sql` syntax
- Dependency issues: Rebuild with `docker compose build --no-cache`

### Database Connection Errors

**Verify PostgreSQL is running:**
```bash
docker compose ps postgres
# Should show "Up (healthy)"
```

**Test connection:**
```bash
docker exec rufus-postgres pg_isready -U rufus -d rufus_cloud
```

**Check credentials:**
```bash
# Verify .env matches docker-compose.yml
grep POSTGRES .env
```

### API Not Responding

**Check server health:**
```bash
docker compose ps rufus-cloud
# Should show "Up (healthy)"
```

**View server logs:**
```bash
docker compose logs --tail=50 rufus-cloud
```

**Test endpoint:**
```bash
curl -v http://localhost:8000/health
```

### Out of Disk Space

**Check Docker disk usage:**
```bash
docker system df
```

**Clean up:**
```bash
# Remove stopped containers
docker compose down

# Remove unused images
docker image prune -a

# Remove unused volumes (careful!)
docker volume prune
```

---

## Performance Tuning

### PostgreSQL Connection Pool

Adjust based on workload:

```bash
# Low concurrency (<10 workflows)
POSTGRES_POOL_MIN_SIZE=10
POSTGRES_POOL_MAX_SIZE=50

# Medium concurrency (10-100 workflows)
POSTGRES_POOL_MIN_SIZE=50
POSTGRES_POOL_MAX_SIZE=200

# High concurrency (>100 workflows)
POSTGRES_POOL_MIN_SIZE=100
POSTGRES_POOL_MAX_SIZE=500
```

### PostgreSQL Server Settings

Edit `docker-compose.yml`:

```yaml
postgres:
  command: >
    postgres
    -c max_connections=2000
    -c shared_buffers=1GB
    -c effective_cache_size=3GB
    -c maintenance_work_mem=256MB
    -c work_mem=10MB
```

---

## Security

### Production Checklist

- [ ] Change `POSTGRES_PASSWORD` to strong password
- [ ] Change `RUFUS_REGISTRATION_KEY` to secure random string
- [ ] Enable encryption at rest (`ENABLE_ENCRYPTION_AT_REST=true`)
- [ ] Restrict PostgreSQL port to localhost (`127.0.0.1:5433:5432`)
- [ ] Use HTTPS for API (add reverse proxy like nginx)
- [ ] Enable firewall rules (only allow necessary ports)
- [ ] Regular database backups configured
- [ ] Log monitoring and alerts set up
- [ ] Docker images from trusted sources
- [ ] Vulnerability scanning enabled

### Network Security

**Restrict to localhost:**
```yaml
postgres:
  ports:
    - "127.0.0.1:5433:5432"

rufus-server:
  ports:
    - "127.0.0.1:8000:8000"
```

**Use reverse proxy:**
```bash
# Add nginx for HTTPS termination
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Monitoring

### Health Checks

```bash
# Container health
docker compose ps

# API health endpoint
curl http://localhost:8000/health

# Database health
docker exec rufus-postgres pg_isready -U rufus -d rufus_cloud
```

### Metrics

**Database metrics:**
```sql
-- Connection count
SELECT count(*) FROM pg_stat_activity WHERE datname = 'rufus_cloud';

-- Table sizes
SELECT schemaname,tablename,pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Workflow statistics
SELECT status, COUNT(*) FROM workflow_executions GROUP BY status;
```

**Container metrics:**
```bash
docker stats rufus-postgres rufus-cloud
```

---

## Additional Resources

- **API Documentation:** http://localhost:8000/docs
- **CLAUDE.md** - Development guidelines and architecture
- **QUICKSTART.md** - Getting started guide
- **tools/cleanup_database.py** - Database cleanup script
- **tools/seed_data.py** - Database seeding script

---

**Last Updated:** 2026-02-11
