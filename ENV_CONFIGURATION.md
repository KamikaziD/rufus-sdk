# Environment Configuration Guide

## Overview

All Rufus components (server, tests, edge agent) now read configuration from environment variables. This provides a unified way to configure the system across different environments.

## Files

- **`.env`** - Your local configuration (not committed to git)
- **`.env.example`** - Template with all available variables and documentation
- **`docker-compose.yml`** - Docker environment overrides production defaults

## How It Works

### 1. Load Order (Priority)

Configuration is loaded in this order (later overrides earlier):

1. **Default values** in code (fallback)
2. **`.env` file** (local development)
3. **System environment variables** (CI/CD, production)
4. **Docker Compose overrides** (when using `docker compose up`)

### 2. Automatic Loading

#### Server (FastAPI)
The server automatically loads `.env` on startup via `python-dotenv`.

#### Tests (pytest)
Tests now automatically load `.env` via:
```python
from dotenv import load_dotenv
load_dotenv()
```

This is already configured in `tests/load/run_load_test.py`.

#### Manual Testing
When running tests manually:
```bash
# .env is automatically loaded
python tests/load/run_load_test.py --all --devices 500
```

## Key Variables for Load Testing

### Database Connection
```bash
# Local development
DATABASE_URL=postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud

# Docker (uses internal hostname)
DATABASE_URL=postgresql://rufus:rufus_secret_2024@postgres:5432/rufus_cloud
```

### Connection Pool Sizing

Adjust based on expected load:

```bash
# For 100 devices
POSTGRES_POOL_MIN_SIZE=20
POSTGRES_POOL_MAX_SIZE=200

# For 500 devices (current)
POSTGRES_POOL_MIN_SIZE=50
POSTGRES_POOL_MAX_SIZE=500

# For 1000+ devices
POSTGRES_POOL_MIN_SIZE=100
POSTGRES_POOL_MAX_SIZE=1000
```

### Retry Configuration

Control client-side retry behavior:

```bash
# Conservative (fewer retries, faster failure)
MAX_RETRIES=2
INITIAL_BACKOFF=0.5
MAX_BACKOFF=5.0
BACKOFF_MULTIPLIER=2.0

# Aggressive (more retries, tolerates transient issues)
MAX_RETRIES=5
INITIAL_BACKOFF=1.0
MAX_BACKOFF=30.0
BACKOFF_MULTIPLIER=2.0
```

### Load Test Defaults

Set default values for load tests:

```bash
CLOUD_URL=http://localhost:8000
LOAD_TEST_DEVICES=500
LOAD_TEST_DURATION=600
```

Then run without flags:
```bash
# Uses values from .env
python tests/load/run_load_test.py --all
```

Or override via CLI:
```bash
# CLI overrides .env
python tests/load/run_load_test.py --all --devices 1000
```

## Environment-Specific Configuration

### Development (`.env`)
```bash
DATABASE_URL=postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud
LOG_LEVEL=DEBUG
RATE_LIMIT_ENABLED=false
```

### CI/CD (GitHub Actions, etc.)
```yaml
env:
  DATABASE_URL: postgresql://user:pass@ci-db:5432/test_db
  TESTING: true
  LOG_LEVEL: WARNING
```

### Production (Kubernetes, Docker)
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rufus-config
data:
  DATABASE_URL: postgresql://user:pass@prod-db:5432/prod_db
  LOG_LEVEL: ERROR
  RATE_LIMIT_ENABLED: true
  POSTGRES_POOL_MAX_SIZE: "1000"
```

## Using Variables in Code

### Reading Environment Variables

```python
import os

# With default fallback
max_retries = int(os.getenv("MAX_RETRIES", "3"))

# Required variable (raises if missing)
db_url = os.environ["DATABASE_URL"]

# Optional variable
api_key = os.getenv("RUFUS_API_KEY", "")
```

### Device Simulator Example

The simulator now reads retry settings from `.env`:

```python
# tests/load/device_simulator.py
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
INITIAL_BACKOFF = float(os.getenv("INITIAL_BACKOFF", "1.0"))
MAX_BACKOFF = float(os.getenv("MAX_BACKOFF", "10.0"))
BACKOFF_MULTIPLIER = float(os.getenv("BACKOFF_MULTIPLIER", "2.0"))
```

To change retry behavior:
```bash
# Edit .env
MAX_RETRIES=5
INITIAL_BACKOFF=2.0

# Run tests - automatically uses new values
python tests/load/run_load_test.py --all --devices 500
```

## Docker Compose Integration

When using Docker:

1. **`.env` is automatically loaded** by Docker Compose
2. **Values override** `docker-compose.yml` defaults
3. **Test from host** still uses `.env`

Example workflow:

```bash
# Edit .env for your environment
vim .env

# Start services (uses .env)
cd docker
docker compose up -d

# Run tests from host (uses .env)
cd ..
python tests/load/run_load_test.py --all --devices 500
```

## Variable Categories

### Core System
- `DATABASE_URL` - PostgreSQL connection string
- `WORKFLOW_STORAGE` - Storage backend (postgres, sqlite, redis)
- `LOG_LEVEL` - Logging verbosity

### Performance
- `RUFUS_USE_UVLOOP` - Enable uvloop for faster async
- `RUFUS_USE_ORJSON` - Enable orjson for faster JSON
- `POSTGRES_POOL_*` - Connection pool settings

### Security
- `RUFUS_REGISTRATION_KEY` - Device enrollment key
- `RUFUS_ENCRYPTION_KEY` - Data encryption key
- `RATE_LIMIT_*` - Rate limiting configuration

### Testing
- `CLOUD_URL` - Server URL for tests
- `LOAD_TEST_*` - Default load test parameters
- `MAX_RETRIES` - Client retry configuration

### Optional
- `REDIS_*` - Redis configuration (for Celery)
- `WEBHOOK_*` - Webhook retry settings
- `ARTIFACTS_DIR` - ML model storage path

## Best Practices

### 1. Never Commit `.env`
```bash
# .gitignore already includes
.env
.env.local
.env.*.local
```

### 2. Keep `.env.example` Updated
When adding new variables:
```bash
# Add to .env.example with documentation
NEW_FEATURE_ENABLED=false  # Enable new feature (default: false)

# Update ENV_CONFIGURATION.md
```

### 3. Use Sensible Defaults
```python
# Good - has fallback
timeout = int(os.getenv("TIMEOUT", "30"))

# Bad - fails if not set
timeout = int(os.environ["TIMEOUT"])
```

### 4. Validate Critical Variables
```python
db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise ValueError("DATABASE_URL environment variable is required")
```

### 5. Document Units
```bash
# Good - units in comment
TIMEOUT=30  # seconds

# Bad - ambiguous
TIMEOUT=30
```

## Troubleshooting

### Variable Not Loading

**Problem**: Changes to `.env` not reflected

**Solutions**:
```bash
# 1. Restart services
docker compose down && docker compose up -d

# 2. Check .env syntax (no spaces around =)
KEY=value  # Correct
KEY = value  # Incorrect

# 3. Verify file is in correct location
ls -la .env  # Should be in project root

# 4. Check load order
python -c "import os; print(os.getenv('YOUR_VAR'))"
```

### Docker Not Using .env

**Problem**: Docker containers not seeing `.env` values

**Solutions**:
```bash
# 1. Check docker-compose.yml has env_file directive
# services:
#   rufus-server:
#     env_file: ../.env

# 2. Explicitly pass variables
docker compose -f docker-compose.yml --env-file ../.env up

# 3. Check Docker Compose version
docker compose version  # Should be v2.0+
```

### Test Not Using .env

**Problem**: Tests not reading `.env` values

**Solutions**:
```bash
# 1. Verify dotenv is installed
pip install python-dotenv

# 2. Check .env is in project root
pwd  # Should be /path/to/rufus
ls .env

# 3. Manually load in test
from dotenv import load_dotenv
load_dotenv()
```

## Migration from Hardcoded Values

If you have hardcoded configuration:

### Before
```python
# config.py
DB_URL = "postgresql://rufus:secret@localhost:5433/rufus_cloud"
MAX_RETRIES = 3
```

### After
```python
# config.py
import os
DB_URL = os.getenv("DATABASE_URL", "postgresql://rufus:secret@localhost:5433/rufus_cloud")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
```

```bash
# .env
DATABASE_URL=postgresql://rufus:secret@localhost:5433/rufus_cloud
MAX_RETRIES=3
```

## Quick Reference

```bash
# View current environment
env | grep RUFUS
env | grep POSTGRES

# Test with custom values (doesn't modify .env)
MAX_RETRIES=5 python tests/load/run_load_test.py --all

# Load .env in Python
from dotenv import load_dotenv
load_dotenv()

# Check if variable is set
echo $DATABASE_URL  # Shell
python -c "import os; print(os.getenv('DATABASE_URL'))"  # Python
```

---

**See Also:**
- `.env.example` - Complete list of available variables
- `LOAD_TEST_FIXES.md` - Load testing configuration guide
- `docker/docker-compose.yml` - Docker environment configuration
