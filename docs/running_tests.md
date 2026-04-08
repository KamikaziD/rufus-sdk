# Running Tests

All commands run from the repo root: `/Users/kim/PycharmProjects/ruvon`

---

## Prerequisites

```bash
# Install all dev dependencies
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/ruvon-edge[edge]"
pip install -e "packages/ruvon-server[server,celery,auth]"

# Optional extras used by benchmarks / load tests
pip install cryptography uvloop orjson httpx psutil python-dotenv
```

---

## Unit & Integration Tests (pytest)

```bash
# Run everything
pytest

# Verbose output
pytest -v

# Single module
pytest tests/sdk/test_engine.py

# Single test
pytest tests/sdk/test_workflow.py::test_name

# SDK tests only
pytest tests/sdk/

# Edge tests only
pytest tests/edge/

# CLI tests only
pytest tests/cli/

# Provider compliance tests
pytest tests/providers/

# Server tests only
pytest tests/server/

# Integration tests only
pytest tests/integration/

# Skip integration tests (faster — no Docker required)
pytest -m "not integration"

# With coverage report
pytest --cov=src --cov-report=term-missing
```

---

## Benchmarks

No Docker required. All run in-process.

### SDK Performance (serialization, import caching, async overhead, workflow throughput)

```bash
# Full suite (~60 seconds)
python tests/benchmarks/benchmark_suite.py

# Quick smoke test (~8 seconds — 10% of default iterations)
python tests/benchmarks/benchmark_suite.py --quick

# Skip security sections (if cryptography not installed)
python tests/benchmarks/benchmark_suite.py --quick --no-security

# Machine-readable output
python tests/benchmarks/benchmark_suite.py --quick --output json

# Override iteration count
python tests/benchmarks/benchmark_suite.py --iterations 500
```

### Workflow Performance (throughput, latency percentiles)

```bash
python tests/benchmarks/workflow_performance.py
```

### Persistence Layer (SQLite vs PostgreSQL)

```bash
# SQLite only (no server needed)
python tests/benchmarks/persistence_benchmark.py

# With PostgreSQL comparison
python tests/benchmarks/persistence_benchmark.py \
    --postgres "postgresql://myapp:change_me_in_production@localhost:5432/my_app_db"

# Via environment variable
export RUVON_POSTGRES_URL="postgresql://myapp:change_me_in_production@localhost:5432/my_app_db"
python tests/benchmarks/persistence_benchmark.py

# Custom iteration count
python tests/benchmarks/persistence_benchmark.py --iterations 500
```

---

## Load Tests

Requires the Docker stack running at `http://localhost:8000`.

```bash
# Start the stack (from ruvon_test directory)
docker compose -f /Users/kim/PycharmProjects/ruvon_test/docker-compose.test-async.yml up -d
```

### Single scenario

```bash
# Heartbeat — 1000 devices, 10 minutes
python tests/load/run_load_test.py --scenario heartbeat --devices 1000 --duration 600

# SAF sync — 500 devices
python tests/load/run_load_test.py --scenario saf_sync --devices 500

# Config polling — 1000 devices
python tests/load/run_load_test.py --scenario config_poll --devices 1000

# Model update — 200 devices
python tests/load/run_load_test.py --scenario model_update --devices 200

# Cloud commands — 500 devices
python tests/load/run_load_test.py --scenario cloud_commands --devices 500

# Workflow execution — 100 devices
python tests/load/run_load_test.py --scenario workflow_execution --devices 100
```

### Thundering herd (synchronized SAF burst)

```bash
# 1000 devices all sync simultaneously
python tests/load/run_load_test.py --scenario thundering_herd --devices 1000

# 10,000 devices — stress test (ensure max_connections=500 and pool max=100 in docker-compose)
python tests/load/run_load_test.py --scenario thundering_herd --devices 10000
```

### All scenarios in sequence (shared devices, one setup/teardown)

```bash
python tests/load/run_load_test.py --all --devices 100

# Save results to files
python tests/load/run_load_test.py --all --devices 100 --output-dir /tmp/load_results
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--devices N` | 100 | Number of simulated devices |
| `--duration N` | 600 | Test duration in seconds |
| `--cloud-url URL` | `http://localhost:8000` | Control plane URL |
| `--db-url URL` | `$DATABASE_URL` | Postgres URL for seed data check |
| `--output FILE` | — | Save results as JSON |
| `--output-dir DIR` | — | Save all scenario results (with `--all`) |
| `--log-level LEVEL` | INFO | DEBUG / INFO / WARNING / ERROR |

---

## Docker Stack Management

```bash
# Start all services
docker compose -f /Users/kim/PycharmProjects/ruvon_test/docker-compose.test-async.yml up -d

# Stop all services
docker compose -f /Users/kim/PycharmProjects/ruvon_test/docker-compose.test-async.yml down

# Restart server only (after code changes — hot-reload is off in 4-worker mode)
docker compose -f /Users/kim/PycharmProjects/ruvon_test/docker-compose.test-async.yml \
    restart ruvon-server

# Tail server logs
docker logs test-ruvon-server -f

# Tail all logs
docker compose -f /Users/kim/PycharmProjects/ruvon_test/docker-compose.test-async.yml logs -f

# Check service health
docker compose -f /Users/kim/PycharmProjects/ruvon_test/docker-compose.test-async.yml ps
```
