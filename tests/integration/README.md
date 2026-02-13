# Integration Tests for Celery Execution

This directory contains integration tests for Rufus's Celery-based distributed execution.

## Prerequisites

- PostgreSQL database
- Redis server
- Celery worker running
- All Celery dependencies installed

## Quick Start with Docker Compose

**1. Start test infrastructure:**
```bash
cd tests/integration
docker-compose up -d
```

This starts:
- PostgreSQL (port 5433)
- Redis (port 6380)

**2. Set environment variables:**
```bash
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5434/rufus_test"
export CELERY_BROKER_URL="redis://localhost:6380/0"
export CELERY_RESULT_BACKEND="redis://localhost:6380/0"
```

**3. Initialize database:**
```bash
cd ../../src/rufus
alembic upgrade head
```

**4. Start Celery worker (in separate terminal):**
```bash
celery -A rufus.celery_app worker --loglevel=info --concurrency=4
```

**5. Run integration tests:**
```bash
cd ../..
pytest tests/integration/test_celery_execution.py -v -s
```

**6. Cleanup:**
```bash
docker-compose down -v
```

## Manual Setup (Without Docker)

**1. Install Redis:**
```bash
# macOS
brew install redis
redis-server --port 6380

# Linux
sudo apt-get install redis-server
redis-server --port 6380

# Or use Docker for Redis only
docker run -d --name redis-test -p 6380:6379 redis:latest
```

**2. Setup PostgreSQL:**
```bash
# Create test database
createdb rufus_test

# Or use existing database
export DATABASE_URL="postgresql://localhost/rufus_test"
```

**3. Initialize database:**
```bash
cd src/rufus
export DATABASE_URL="postgresql://localhost/rufus_test"
alembic upgrade head
```

**4. Start Celery worker:**
```bash
export CELERY_BROKER_URL="redis://localhost:6380/0"
export CELERY_RESULT_BACKEND="redis://localhost:6380/0"
celery -A rufus.celery_app worker --loglevel=info
```

**5. Run tests:**
```bash
pytest tests/integration/test_celery_execution.py -v
```

## Test Coverage

### TestCeleryAsyncExecution
- ✅ `test_dispatch_async_task` - Tests async task dispatch and completion

### TestCeleryParallelExecution
- ✅ `test_dispatch_parallel_tasks` - Tests parallel task execution with merging

### TestWorkerRegistry
- ✅ `test_worker_registration` - Verifies workers register in database
- ✅ `test_worker_heartbeat` - Verifies worker heartbeat updates

### TestEventPublishing
- ✅ `test_event_stream` - Verifies events published to Redis streams

### TestFullWorkflowExecution
- ⏳ `test_complete_workflow_with_async_step` - Full end-to-end test (TODO)

## Test Structure

Each test is marked with `@pytest.mark.integration` and will be skipped if:
- Celery is not installed
- DATABASE_URL is not set
- CELERY_BROKER_URL is not set
- No Celery workers are running

## Running Specific Tests

```bash
# Run only async execution tests
pytest tests/integration/test_celery_execution.py::TestCeleryAsyncExecution -v

# Run only worker registry tests
pytest tests/integration/test_celery_execution.py::TestWorkerRegistry -v

# Run with debug output
pytest tests/integration/test_celery_execution.py -v -s --log-cli-level=DEBUG

# Run and keep containers after test
docker-compose up -d && pytest tests/integration/test_celery_execution.py -v
```

## Troubleshooting

### Workers not picking up tasks
```bash
# Check worker status
celery -A rufus.celery_app inspect active

# Check registered tasks
celery -A rufus.celery_app inspect registered

# Restart worker with debug logging
celery -A rufus.celery_app worker --loglevel=debug
```

### Database connection errors
```bash
# Verify database is accessible
psql $DATABASE_URL -c "SELECT 1"

# Check if migrations are applied
cd src/rufus && alembic current

# Apply migrations if needed
alembic upgrade head
```

### Redis connection errors
```bash
# Test Redis connection
redis-cli -p 6380 ping

# Check Redis info
redis-cli -p 6380 INFO

# Monitor Redis commands
redis-cli -p 6380 MONITOR
```

### Test timeouts
Some tests wait for task completion and may timeout if:
- Worker is not running
- Worker is overloaded
- Network latency is high

Adjust timeout in test code if needed:
```python
timeout = 30  # Increase from default 10 seconds
```

## Continuous Integration

For CI/CD pipelines:

```yaml
# .github/workflows/test-integration.yml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: rufus_test
          POSTGRES_PASSWORD: secret
        ports:
          - 5433:5432
      redis:
        image: redis:7-alpine
        ports:
          - 6380:6379

    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -e ".[celery]"
          pip install pytest pytest-asyncio

      - name: Run migrations
        env:
          DATABASE_URL: postgresql://postgres:secret@localhost:5433/rufus_test
        run: |
          cd src/rufus
          alembic upgrade head

      - name: Start Celery worker
        env:
          DATABASE_URL: postgresql://postgres:secret@localhost:5433/rufus_test
          CELERY_BROKER_URL: redis://localhost:6380/0
          CELERY_RESULT_BACKEND: redis://localhost:6380/0
        run: |
          celery -A rufus.celery_app worker --loglevel=info &
          sleep 5

      - name: Run integration tests
        env:
          DATABASE_URL: postgresql://postgres:secret@localhost:5433/rufus_test
          CELERY_BROKER_URL: redis://localhost:6380/0
          CELERY_RESULT_BACKEND: redis://localhost:6380/0
        run: pytest tests/integration/test_celery_execution.py -v
```

## Performance Benchmarks

Run performance tests to measure:
- Task dispatch latency
- Parallel execution overhead
- Worker throughput
- End-to-end workflow execution time

```bash
pytest tests/integration/test_celery_execution.py -v --benchmark-only
```

## Next Steps

1. **Add more test scenarios:**
   - Sub-workflow orchestration
   - Fire-and-forget workflows
   - HTTP step execution
   - Scheduled workflows

2. **Add performance tests:**
   - Measure task throughput
   - Test with 100+ concurrent workflows
   - Benchmark different merge strategies

3. **Add failure scenarios:**
   - Worker crashes during task
   - Redis connection loss
   - Database connection loss
   - Task timeouts

4. **Add monitoring tests:**
   - Prometheus metrics collection
   - Event stream verification
   - Worker heartbeat monitoring
