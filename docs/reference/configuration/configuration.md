# Configuration Reference

## Overview

Ruvon configuration via environment variables, config files, and CLI options.

---

## Environment Variables

### Database Configuration

#### `DATABASE_URL`

**Type:** `string`

**Description:** Primary database connection URL.

**Format:**

- PostgreSQL: `postgresql://user:password@host:port/database`
- SQLite: `sqlite:///path/to/database.db`
- SQLite in-memory: `sqlite:///:memory:`

**Example:**

```bash
export DATABASE_URL="postgresql://ruvon:secret@localhost:5432/ruvon_cloud"
export DATABASE_URL="sqlite:///workflows.db"
```

#### `RUVON_DB_URL`

**Type:** `string`

**Description:** Override database URL for CLI commands.

**Example:**

```bash
export RUVON_DB_URL="postgresql://localhost/ruvon_test"
ruvon db stats  # Uses RUVON_DB_URL
```

---

### PostgreSQL Connection Pool

#### `POSTGRES_POOL_MIN_SIZE`

**Type:** `int`

**Default:** `10`

**Description:** Minimum connection pool size.

**Example:**

```bash
export POSTGRES_POOL_MIN_SIZE=5
```

#### `POSTGRES_POOL_MAX_SIZE`

**Type:** `int`

**Default:** `50`

**Description:** Maximum connection pool size.

**Recommended Values:**

- Low concurrency (< 10 workflows): `20`
- Medium concurrency (10-100 workflows): `50`
- High concurrency (> 100 workflows): `100`

**Example:**

```bash
export POSTGRES_POOL_MAX_SIZE=100
```

#### `POSTGRES_POOL_COMMAND_TIMEOUT`

**Type:** `int`

**Default:** `10`

**Description:** Command timeout in seconds.

**Example:**

```bash
export POSTGRES_POOL_COMMAND_TIMEOUT=30
```

#### `POSTGRES_POOL_MAX_QUERIES`

**Type:** `int`

**Default:** `50000`

**Description:** Maximum queries per connection before recycling.

**Example:**

```bash
export POSTGRES_POOL_MAX_QUERIES=100000
```

#### `POSTGRES_POOL_MAX_INACTIVE_LIFETIME`

**Type:** `int`

**Default:** `300`

**Description:** Maximum seconds a connection can be idle.

**Example:**

```bash
export POSTGRES_POOL_MAX_INACTIVE_LIFETIME=600
```

---

### Celery Configuration

#### `CELERY_BROKER_URL`

**Type:** `string`

**Description:** Celery message broker URL (Redis/RabbitMQ).

**Example:**

```bash
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_BROKER_URL="amqp://guest:guest@localhost:5672//"
```

#### `CELERY_RESULT_BACKEND`

**Type:** `string`

**Description:** Celery result backend URL.

**Example:**

```bash
export CELERY_RESULT_BACKEND="redis://localhost:6379/1"
```

---

### Performance Optimizations

#### `RUVON_USE_UVLOOP`

**Type:** `boolean`

**Default:** `true`

**Description:** Use uvloop for async I/O (2-4x faster).

**Example:**

```bash
export RUVON_USE_UVLOOP=false  # Disable for debugging
```

#### `RUVON_USE_ORJSON`

**Type:** `boolean`

**Default:** `true`

**Description:** Use orjson for JSON serialization (3-5x faster).

**Example:**

```bash
export RUVON_USE_ORJSON=false  # Use stdlib json
```

---

### CLI Configuration

#### `RUVON_CONFIG_PATH`

**Type:** `string`

**Default:** `~/.ruvon/config.yaml`

**Description:** CLI configuration file location.

**Example:**

```bash
export RUVON_CONFIG_PATH="/etc/ruvon/config.yaml"
```

#### `NO_COLOR`

**Type:** `boolean`

**Default:** `false`

**Description:** Disable colored output (for CI/CD).

**Example:**

```bash
export NO_COLOR=1
```

---

### Testing Configuration

#### `TESTING`

**Type:** `boolean`

**Default:** `false`

**Description:** Enable testing mode (run parallel tasks synchronously).

**Example:**

```bash
export TESTING=true
pytest tests/
```

---

### Security

#### `RUVON_ENCRYPTION_KEY`

**Type:** `string`

**Required:** **YES — workflows cannot be decrypted without this key**

**Description:** Fernet symmetric encryption key for workflow state encryption. Must be set before starting the server or workers. All nodes in a cluster must share the same key.

**Generate a key:**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Example:**

```bash
export RUVON_ENCRYPTION_KEY="your-base64-fernet-key-here"
```

**Key rotation:** Deploy the new key, then gradually re-encrypt existing workflows. See [Security](../advanced/security.md) for the rotation procedure.

---

### Server Extensions

#### `RUVON_CUSTOM_ROUTERS`

**Type:** `string`

**Default:** `""` (empty — no custom routers)

**Description:** Comma-separated dotted paths to FastAPI `APIRouter` objects. Routers are imported and mounted on server startup, enabling user-defined API extensions without modifying core server code.

**Example:**

```bash
export RUVON_CUSTOM_ROUTERS="myapp.routers.payments.router,myapp.routers.reports.router"
```

**Router definition:**

```python
# myapp/routers/payments.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])

@router.get("/summary")
async def payment_summary():
    return {"total_today": 42}
```

---

## CLI Configuration File

**Location:** `~/.ruvon/config.yaml` (or `$RUVON_CONFIG_PATH`)

### Format

```yaml
version: "1.0"

persistence:
  provider: string          # memory, sqlite, postgres, redis
  sqlite:
    db_path: string         # SQLite database path
  postgres:
    db_url: string          # PostgreSQL connection URL
    pool_min_size: int      # Connection pool min size
    pool_max_size: int      # Connection pool max size
  redis:
    host: string            # Redis host
    port: int               # Redis port
    db: int                 # Redis database number

execution:
  provider: string          # sync, thread_pool, celery

observability:
  provider: string          # logging, noop

defaults:
  auto_execute: boolean     # Auto-execute next step
  interactive: boolean      # Use interactive mode
  json_output: boolean      # Output as JSON
```

### Example

```yaml
version: "1.0"

persistence:
  provider: postgres
  postgres:
    db_url: postgresql://ruvon:secret@localhost:5432/ruvon_cloud
    pool_min_size: 10
    pool_max_size: 50

execution:
  provider: thread_pool

observability:
  provider: logging

defaults:
  auto_execute: false
  interactive: true
  json_output: false
```

---

## Workflow Registry Configuration

**File:** `config/workflow_registry.yaml`

### Format

```yaml
workflows:
  - type: string                  # Required
    description: string           # Optional
    config_file: string           # Required
    initial_state_model: string   # Required
    requires: list[string]        # Optional

requires: list[string]            # Optional
```

### Example

```yaml
workflows:
  - type: "OrderProcessing"
    description: "E-commerce order workflow"
    config_file: "order_processing.yaml"
    initial_state_model: "my_app.models.OrderState"
    requires:
      - ruvon-payment-gateway

  - type: "UserOnboarding"
    description: "User onboarding workflow"
    config_file: "user_onboarding.yaml"
    initial_state_model: "my_app.models.UserState"

requires:
  - ruvon-notifications
```

---

## Persistence Provider Configuration

### SQLite

```python
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider

persistence = SQLitePersistenceProvider(
    db_path="workflows.db",      # Path to database file
    timeout=5.0,                  # Lock timeout (seconds)
    check_same_thread=False       # Allow multi-threaded access
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str` | `:memory:` | Database file path or `:memory:` |
| `timeout` | `float` | `5.0` | Lock timeout in seconds |
| `check_same_thread` | `bool` | `False` | SQLite threading check |

### PostgreSQL

```python
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(
    db_url="postgresql://user:pass@host/db",
    pool_min_size=10,
    pool_max_size=50
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_url` | `str` | Required | PostgreSQL connection URL |
| `pool_min_size` | `int` | `10` | Minimum pool size |
| `pool_max_size` | `int` | `50` | Maximum pool size |

### Redis

```python
from ruvon.implementations.persistence.redis import RedisPersistenceProvider

persistence = RedisPersistenceProvider(
    redis_url="redis://localhost:6379/0"
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `redis_url` | `str` | `redis://localhost:6379/0` | Redis connection URL |

### In-Memory

```python
from ruvon.implementations.persistence.memory import MemoryPersistenceProvider

persistence = MemoryPersistenceProvider()
```

**Note:** Data lost when process exits. Testing only.

---

## Execution Provider Configuration

### Sync

```python
from ruvon.implementations.execution.sync import SyncExecutionProvider

execution = SyncExecutionProvider()
```

No configuration parameters.

### Thread Pool

```python
from ruvon.implementations.execution.thread_pool import ThreadPoolExecutionProvider

execution = ThreadPoolExecutionProvider(
    max_workers=10
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_workers` | `int` | `10` | Maximum thread pool size |

### Celery

```python
from ruvon.implementations.execution.celery import CeleryExecutor

execution = CeleryExecutor(
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/1"
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `broker_url` | `str` | Required | Celery broker URL |
| `result_backend` | `str` | Required | Result backend URL |

---

## Observer Configuration

### Logging Observer

```python
from ruvon.implementations.observability.logging import LoggingObserver

observer = LoggingObserver()
```

No configuration parameters.

### No-op Observer

```python
from ruvon.providers.observer import NoopObserver

observer = NoopObserver()
```

Disables all observability hooks.

---

## Configuration Priority

Configuration sources in order of precedence (highest to lowest):

1. **Code** - Explicit constructor parameters
2. **Environment variables** - `RUVON_*`, `DATABASE_URL`, etc.
3. **Config file** - `~/.ruvon/config.yaml`
4. **Defaults** - Built-in default values

**Example:**

```python
# Code (highest priority)
persistence = SQLitePersistenceProvider(db_path="custom.db")

# Environment variable (overrides config file)
export DATABASE_URL="sqlite:///env.db"

# Config file (lowest priority)
# ~/.ruvon/config.yaml:
# persistence:
#   sqlite:
#     db_path: "config.db"
```

---

## Production Recommendations

### PostgreSQL

```bash
export DATABASE_URL="postgresql://ruvon:secret@db-host:5432/ruvon_prod"
export POSTGRES_POOL_MIN_SIZE=20
export POSTGRES_POOL_MAX_SIZE=100
export CELERY_BROKER_URL="redis://redis-host:6379/0"
export CELERY_RESULT_BACKEND="redis://redis-host:6379/1"
```

### High Concurrency

```bash
export POSTGRES_POOL_MAX_SIZE=200
export POSTGRES_POOL_MAX_QUERIES=100000
```

### Debugging

```bash
export RUVON_USE_UVLOOP=false
export RUVON_USE_ORJSON=false
export NO_COLOR=1
```

---

## Docker Configuration

### Environment File

```bash
# .env
DATABASE_URL=postgresql://ruvon:secret@postgres:5432/ruvon_cloud
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
POSTGRES_POOL_MIN_SIZE=20
POSTGRES_POOL_MAX_SIZE=100
```

### Docker Compose

```yaml
version: "3.8"

services:
  ruvon-server:
    image: ruvon:latest
    env_file: .env
    environment:
      - RUVON_USE_UVLOOP=true
      - RUVON_USE_ORJSON=true
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: ruvon
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: ruvon_cloud

  redis:
    image: redis:7-alpine
```

---

## See Also

- [CLI Commands](cli-commands.md)
- [Database Schema](database-schema.md)
- [Providers](../api/providers.md)
