# Testing Guide - Integration and Load Testing

## Overview

Comprehensive testing suite for Rufus Edge Cloud Control Plane covering:
- **Integration Tests**: End-to-end API testing
- **Load Tests**: Performance and throughput testing
- **Stress Tests**: System behavior under load

---

## Quick Start

### Prerequisites

1. **Start the server:**
```bash
uvicorn rufus_server.main:app --reload
```

2. **Set environment variables:**
```bash
export DATABASE_URL=postgresql://localhost/rufus_edge
# Or for SQLite:
export DATABASE_URL=sqlite:///rufus_edge.db
```

### Run All Tests

```bash
# Run complete test suite
./tests/run_all_tests.sh
```

### Run Specific Test Categories

```bash
# Integration tests only
pytest tests/integration/ -v

# Load tests only
python tests/load/load_test_suite.py

# Specific test file
pytest tests/integration/test_command_versioning_integration.py -v
```

---

## Integration Tests

### Command Versioning Integration Tests

**File:** `tests/integration/test_command_versioning_integration.py`

**Tests:**
- List command versions
- Get latest version
- Validate valid command data
- Validate invalid command data (oversized, wrong type)
- Missing required fields
- Enum validation
- Command creation with validation
- Version filtering
- Changelog retrieval
- Validation performance (cold/warm cache)
- Concurrent validation requests

**Run:**
```bash
pytest tests/integration/test_command_versioning_integration.py -v
```

**Expected Output:**
```
test_list_command_versions PASSED
test_get_latest_version PASSED
test_validate_valid_command PASSED
test_validate_invalid_command_oversized PASSED
test_validate_invalid_command_wrong_type PASSED
...
```

### Webhook Integration Tests

**File:** `tests/integration/test_webhook_integration.py`

**Tests:**
- Create webhook
- List webhooks
- Get webhook details
- Update webhook
- Delete webhook
- Webhook delivery with signature
- Custom headers
- Delivery history
- Delivery filtering by status
- Event dispatching (device registration, command creation)
- Concurrent webhook creation

**Run:**
```bash
pytest tests/integration/test_webhook_integration.py -v
```

**Features:**
- Includes mock webhook receiver on port 9000
- Tests HMAC signature verification
- Tests event dispatching end-to-end

### Webhook Retry Integration Tests

**File:** `tests/integration/test_webhook_retry_integration.py`

**Tests:**
- Failed webhook marking
- Retry policy configuration
- Exponential backoff calculation
- Fixed backoff calculation
- Max retries limit
- Retry worker instantiation
- Graceful shutdown
- Retry scenarios (transient/permanent failures)

**Run:**
```bash
pytest tests/integration/test_webhook_retry_integration.py -v
```

---

## Load Tests

### Load Test Suite

**File:** `tests/load/load_test_suite.py`

**Tests:**

#### Command Versioning Load Tests
1. **Validation Throughput** (1000 requests, 50 concurrent)
   - Validates command data against schema
   - Tests caching performance

2. **List Versions Throughput** (500 requests, 25 concurrent)
   - Lists all command versions
   - Tests database query performance

3. **Get Latest Version Throughput** (1000 requests, 50 concurrent)
   - Gets latest version for command type
   - Tests caching and database performance

4. **Validation Error Handling** (500 requests, 25 concurrent)
   - Validates invalid data
   - Tests error path performance

#### Webhook Load Tests
1. **List Webhooks Throughput** (500 requests, 25 concurrent)
   - Lists all webhooks
   - Tests database query performance

2. **Webhook Creation Throughput** (100 requests, 10 concurrent)
   - Creates new webhooks
   - Tests database write performance

3. **Get Webhook Throughput** (500 requests, 25 concurrent)
   - Gets webhook details
   - Tests database read performance

#### Mixed Workload Tests
1. **Mixed Workload** (1000 requests, 50 concurrent)
   - Random mix of validation, list versions, list webhooks
   - Tests realistic usage patterns

**Run:**
```bash
python tests/load/load_test_suite.py
```

**Example Output:**
```
======================================================================
  Load Test: Command Validation Throughput
======================================================================
  Total requests: 1000
  Concurrent:     50

  Progress: 50/1000 requests (50 success, 0 failed)
  Progress: 100/1000 requests (100 success, 0 failed)
  ...
  Progress: 1000/1000 requests (998 success, 2 failed)

  Results:
    Duration:       5.23s
    Success:        998/1000 (99.8%)
    Failed:         2
    Throughput:     191.20 req/s

  Latency:
    Average:        25.34ms
    p50:            23.12ms
    p95:            45.67ms
    p99:            78.90ms
    Min:            12.34ms
    Max:            120.45ms
```

---

## Performance Benchmarks

### Expected Performance

Based on typical deployment on laptop/workstation:

#### Command Versioning
| Test | Throughput | p50 Latency | p95 Latency |
|------|-----------|-------------|-------------|
| Validation (cached) | 150-300 req/s | 20-40ms | 40-80ms |
| List Versions | 100-200 req/s | 30-50ms | 60-100ms |
| Get Latest | 150-300 req/s | 20-40ms | 40-80ms |

#### Webhooks
| Test | Throughput | p50 Latency | p95 Latency |
|------|-----------|-------------|-------------|
| List Webhooks | 100-200 req/s | 30-50ms | 60-100ms |
| Create Webhook | 50-100 req/s | 50-100ms | 100-200ms |
| Get Webhook | 150-300 req/s | 20-40ms | 40-80ms |

### Performance Optimization

If performance is below expectations:

1. **Check Database Connection:**
   ```bash
   # PostgreSQL connection pooling
   export POSTGRES_POOL_MIN_SIZE=10
   export POSTGRES_POOL_MAX_SIZE=50
   ```

2. **Enable Schema Caching:**
   ```bash
   # Already enabled by default (5 min TTL)
   export VERSION_SCHEMA_CACHE_TTL=300
   ```

3. **Use uvloop:**
   ```bash
   # Already enabled by default
   export RUFUS_USE_UVLOOP=true
   ```

4. **Database Indexes:**
   ```sql
   -- Ensure indexes exist
   CREATE INDEX IF NOT EXISTS idx_webhook_active ON webhook_registrations(is_active);
   CREATE INDEX IF NOT EXISTS idx_version_active ON command_versions(is_active);
   ```

---

## Test Configuration

### Environment Variables

```bash
# Server URL (default: http://localhost:8000)
export TEST_SERVER_URL=http://localhost:8000

# Database URL
export DATABASE_URL=postgresql://localhost/rufus_edge

# Test settings
export PYTEST_TIMEOUT=30  # Test timeout in seconds
```

### Pytest Configuration

**File:** `pytest.ini` (create if needed)

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
timeout = 30
markers =
    integration: Integration tests
    load: Load tests
    slow: Slow tests
```

---

## Continuous Integration

### GitHub Actions

**File:** `.github/workflows/test.yml`

```yaml
name: Integration and Load Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: rufus_edge
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-asyncio

    - name: Start server
      run: |
        uvicorn rufus_server.main:app &
        sleep 5
      env:
        DATABASE_URL: postgresql://postgres:postgres@localhost/rufus_edge

    - name: Run integration tests
      run: |
        pytest tests/integration/ -v

    - name: Run load tests
      run: |
        python tests/load/load_test_suite.py
```

---

## Troubleshooting

### Server Not Running

**Error:**
```
✗ Server is not running!
```

**Solution:**
```bash
# Start server in terminal 1
uvicorn rufus_server.main:app --reload

# Run tests in terminal 2
pytest tests/integration/ -v
```

### Connection Refused

**Error:**
```
httpx.ConnectError: [Errno 61] Connection refused
```

**Solution:**
```bash
# Check server is running
curl http://localhost:8000/health

# Check port
lsof -i :8000

# Restart server
uvicorn rufus_server.main:app --reload
```

### Database Connection Error

**Error:**
```
asyncpg.exceptions.ConnectionDoesNotExistError
```

**Solution:**
```bash
# Check PostgreSQL is running
pg_isready

# Or use SQLite
export DATABASE_URL=sqlite:///rufus_edge.db

# Initialize database
python tools/migrate.py --db $DATABASE_URL --up
```

### Tests Timeout

**Error:**
```
pytest.timeout: Test exceeded timeout of 30 seconds
```

**Solution:**
```bash
# Increase timeout
pytest tests/integration/ -v --timeout=60

# Or disable timeout for debugging
pytest tests/integration/ -v --timeout=0
```

### Import Errors

**Error:**
```
ModuleNotFoundError: No module named 'rufus_server'
```

**Solution:**
```bash
# Run from project root
cd /Users/kim/PycharmProjects/rufus

# Or add to PYTHONPATH
export PYTHONPATH=/Users/kim/PycharmProjects/rufus/src:$PYTHONPATH
```

---

## Advanced Testing

### Custom Load Test

Create custom load test:

```python
from tests.load.load_test_suite import LoadTester

class CustomLoadTest(LoadTester):
    async def test_custom_endpoint(self):
        async with httpx.AsyncClient(base_url=self.base_url) as client:

            async def custom_request():
                response = await client.get("/api/v1/custom/endpoint")
                return response.status_code == 200

            await self.run_load_test(
                "Custom Endpoint Test",
                custom_request,
                total_requests=500,
                concurrent=25
            )

# Run
test = CustomLoadTest()
asyncio.run(test.test_custom_endpoint())
```

### Profiling

Profile specific test:

```bash
# Install profiler
pip install pytest-profiling

# Run with profiling
pytest tests/integration/test_command_versioning_integration.py --profile

# View results
snakeviz prof/combined.prof
```

### Memory Testing

Test memory usage:

```bash
# Install memory profiler
pip install memory-profiler

# Run with memory profiling
pytest tests/integration/ --memprof
```

---

## Test Data Cleanup

### Clean Test Webhooks

```bash
# List test webhooks
curl http://localhost:8000/api/v1/webhooks | jq '.webhooks[] | select(.webhook_id | startswith("load-test"))'

# Delete via API
curl -X DELETE http://localhost:8000/api/v1/webhooks/load-test-webhook-1

# Or via SQL
psql $DATABASE_URL -c "DELETE FROM webhook_registrations WHERE webhook_id LIKE 'load-test%'"
```

### Reset Database

```bash
# PostgreSQL
psql $DATABASE_URL -c "TRUNCATE webhook_registrations, webhook_deliveries CASCADE"

# SQLite
sqlite3 rufus_edge.db "DELETE FROM webhook_registrations; DELETE FROM webhook_deliveries;"

# Re-run migrations
python tools/migrate.py --db $DATABASE_URL --up
```

---

## Best Practices

1. **Always Run Against Test Database**: Never run load tests against production
2. **Clean Up After Tests**: Remove test data to avoid pollution
3. **Monitor Resource Usage**: Watch CPU, memory, database connections
4. **Start Small**: Begin with low concurrency, increase gradually
5. **Baseline First**: Establish baseline performance before changes
6. **Test Incrementally**: Test each feature separately before mixed workload
7. **Document Results**: Keep performance baselines in version control

---

## Files

### Integration Tests
- `tests/integration/test_command_versioning_integration.py` (~350 lines)
- `tests/integration/test_webhook_integration.py` (~450 lines)
- `tests/integration/test_webhook_retry_integration.py` (~250 lines)

### Load Tests
- `tests/load/load_test_suite.py` (~600 lines)

### Test Runner
- `tests/run_all_tests.sh` (executable script)

### Documentation
- `TESTING_GUIDE.md` (this file)

---

## Summary

✅ **Integration Tests:** 30+ test cases covering all features
✅ **Load Tests:** 8 comprehensive load test scenarios
✅ **Performance Benchmarks:** Baseline metrics established
✅ **Test Runner:** Automated test execution
✅ **CI/CD Ready:** GitHub Actions configuration included

**Total Test Coverage:**
- Command Versioning: 15 integration tests
- Webhooks: 12 integration tests
- Webhook Retry: 8 integration tests
- Load Tests: 8 scenarios

All tests are production-ready and can be integrated into CI/CD pipelines! 🎉
