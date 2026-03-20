# Rufus Edge Load Testing Suite

Load testing infrastructure for validating Rufus Edge control plane performance at scale (1000+ devices).

---

## Quick Start

### Prerequisites

**1. Install Dependencies:**
```bash
pip install httpx psutil
```

**2. Start Services:**
```bash
# Option A: Docker Compose (recommended)
cd docker
docker compose up -d

# Option B: Local development (see Deployment Setup below)
```

**3. Database Seeding (Automatic):**

Load tests automatically seed the database if `DATABASE_URL` is set:

```bash
# Set DATABASE_URL environment variable
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"

# Load test will automatically check and seed if needed
python tests/load/run_load_test.py --scenario heartbeat --devices 10
```

**Or seed manually:**
```bash
python tools/seed_data.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud" \
  --type all
```

**Database seeding provides:**
- 4 demo workflows (completed, active, failed, waiting)
- 5 edge devices (POS terminals, ATM, kiosk, mobile reader) - PostgreSQL only

**4. Verify Setup:**
```bash
# Check services
docker compose ps
# Expected: postgres (healthy), rufus-cloud (healthy)

# Check API
curl http://localhost:8000/health
# Expected: {"status": "healthy"}

# Check seed data
python tools/seed_data.py \
  --db-url "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud" \
  --verify
# Expected: Workflows: 4, Edge Devices: 5
```

### Run a Simple Test

```bash
# Smoke test with 10 devices (heartbeat scenario)
python tests/load/run_load_test.py \
    --scenario heartbeat \
    --devices 10 \
    --duration 60

# SAF sync test with 50 devices
python tests/load/run_load_test.py \
    --scenario saf_sync \
    --devices 50

# Run all scenarios (smoke test)
python tests/load/run_load_test.py \
    --all \
    --devices 10 \
    --output-dir results/
```

---

## Test Scenarios

### Scenario 1: Concurrent Device Heartbeats
**Target**: 1,000 devices sending heartbeats every 30s

```bash
python tests/load/run_load_test.py \
    --scenario heartbeat \
    --devices 1000 \
    --duration 600
```

**Expected Performance**:
- Throughput: ~33 req/sec sustained
- Latency: p95 < 500ms
- Error rate: < 0.5%

---

### Scenario 2: Store-and-Forward Bulk Sync
**Target**: 500 devices with 100 queued transactions each

```bash
python tests/load/run_load_test.py \
    --scenario saf_sync \
    --devices 500
```

**Expected Performance**:
- Transaction throughput: 1,000-2,000 tx/sec
- Batch latency: p95 < 2s
- Success rate: > 99.5%

---

### Scenario 3: Config Polling
**Target**: 1,000 devices polling every 60s with ETag caching

```bash
python tests/load/run_load_test.py \
    --scenario config_poll \
    --devices 1000 \
    --duration 600
```

**Expected Performance**:
- ETag cache hit rate: > 95%
- Latency: p95 < 200ms
- Error rate: < 0.5%

---

### Scenario 4: Model Distribution
**Target**: 1,000 devices downloading model updates (delta or full)

```bash
python tests/load/run_load_test.py \
    --scenario model_update \
    --devices 1000
```

**Expected Performance**:
- Delta usage: > 80%
- Success rate: > 98%

---

### Scenario 5: Cloud Commands
**Target**: 1,000 devices receiving commands via heartbeat

```bash
python tests/load/run_load_test.py \
    --scenario cloud_commands \
    --devices 1000 \
    --duration 600
```

**Expected Performance**:
- Command delivery: p95 < 5s
- Acknowledgment: > 95% within 60s

---

### Scenario 6: WASM Step Execution Throughput
**Target**: 100 devices receiving `sync_wasm` commands and executing WASM steps locally

```bash
python tests/load/run_load_test.py \
    --scenario wasm_steps \
    --devices 100 \
    --duration 300
```

**What it measures**:
- **Cloud side**: `sync_wasm` command delivery throughput via heartbeat pipeline
- **Edge side**: simulated WASM step execution latency (50–400ms per step, modelling wasmtime instantiation)

**Execution model**: Each device sends heartbeats at the configured interval. On receiving a `sync_wasm` command the device executes a configurable number of simulated WASM steps. After 3 consecutive heartbeats without a cloud command, a synthetic local execution batch is injected to sustain throughput measurement even if the cloud has no pending commands.

**Expected Performance**:
- WASM step success rate: ≥ 90%
- Execution p95: < 300ms (simulated wasmtime budget)
- Heartbeat error rate: < 1%

**Targets reflect simulation**: The 2% injected failure rate and latency distribution (40% fast / 45% normal / 15% slow path) model real wasmtime behaviour. Results below 300ms p95 indicate the cloud command pipeline is not the bottleneck.

---

## Running All Scenarios

```bash
# Smoke test (10 devices)
python tests/load/run_load_test.py \
    --all \
    --devices 10 \
    --output-dir results/smoke/

# Full scale test (1000 devices)
python tests/load/run_load_test.py \
    --all \
    --devices 1000 \
    --output-dir results/scale_1000/
```

---

## Command-Line Options

```
--cloud-url URL         Cloud control plane URL (default: http://localhost:8000)
--scenario SCENARIO     Test scenario to run (see list above)
--devices N             Number of simulated devices (default: 100)
--duration SECONDS      Test duration in seconds (default: 600)
--output FILE           Output file for results (JSON)
--output-dir DIR        Output directory for all results (with --all)
--all                   Run all scenarios
--log-level LEVEL       Logging level (DEBUG|INFO|WARNING|ERROR)
```

---

## Deployment Setup

### Option 1: Docker Compose (Recommended)

```bash
# Start cloud control plane + database
docker compose up -d

# Wait for services to be ready
docker compose ps

# Run load tests
python tests/load/run_load_test.py \
    --scenario heartbeat \
    --devices 100 \
    --cloud-url http://localhost:8000
```

### Option 2: Local Development

```bash
# Terminal 1: Start database
docker run -d --name postgres-test \
    -e POSTGRES_DB=rufus_load_test \
    -p 5432:5432 \
    postgres:14

# Terminal 2: Start cloud control plane
export DATABASE_URL=postgresql://postgres@localhost/rufus_load_test
uvicorn rufus_server.main:app --reload

# Terminal 3: Run load tests
python tests/load/run_load_test.py --scenario heartbeat --devices 10
```

---

## Incremental Scaling

Start small and scale up:

```bash
# Phase 1: 10 devices (smoke test)
python tests/load/run_load_test.py --all --devices 10

# Phase 2: 100 devices
python tests/load/run_load_test.py --all --devices 100

# Phase 3: 500 devices
python tests/load/run_load_test.py --all --devices 500

# Phase 4: 1000 devices (target)
python tests/load/run_load_test.py --all --devices 1000

# Phase 5: 1500 devices (stress test)
python tests/load/run_load_test.py --all --devices 1500
```

---

## Interpreting Results

### Success Criteria

**Must Pass** (Go/No-Go):
- ✅ Error rate < 1%
- ✅ Throughput within 90% of target
- ✅ No crashes or service unavailability

**Performance Targets**:
- Heartbeat latency: p95 < 500ms
- SAF throughput: > 1000 tx/sec
- Config latency: p95 < 200ms
- Command delivery: p95 < 5s

### Example Output

```
================================================================================
LOAD TEST RESULTS - HEARTBEAT
================================================================================
Devices:              1000
Duration:             600.3s
Total Requests:       20,012
Total Errors:         23
Error Rate:           0.11%
Success Rate:         99.89%
Throughput:           33.3 req/sec

Heartbeats Sent:      20,012
Heartbeat Failures:   23
================================================================================

PERFORMANCE TARGETS:
================================================================================
Error Rate < 1%:      ✅ PASS (0.11%)
Throughput >= 33 req/s:  ✅ PASS (33.3 req/s)
================================================================================
```

### Troubleshooting

**High Error Rate**:
- Check cloud service logs
- Verify database connection pool size
- Check for rate limiting

**Low Throughput**:
- Increase database max_connections
- Check CPU/memory on cloud server
- Verify network latency

**Connection Pool Exhaustion**:
```bash
# Increase PostgreSQL pool size
export POSTGRES_POOL_MAX_SIZE=100

# Restart cloud service
```

---

## Monitoring During Tests

### Terminal 1: Load Test
```bash
python tests/load/run_load_test.py --scenario heartbeat --devices 1000
```

### Terminal 2: Cloud Logs
```bash
docker compose logs -f rufus-server
```

### Terminal 3: Database Stats
```bash
# Connection count
docker exec postgres-test psql -U postgres -c \
    "SELECT count(*) FROM pg_stat_activity WHERE datname='rufus_load_test';"

# Query performance
docker exec postgres-test psql -U postgres -c \
    "SELECT query, calls, total_time FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"
```

### Terminal 4: System Resources
```bash
# CPU/Memory
docker stats

# Network
watch -n 1 "docker exec rufus-server netstat -an | grep :8000 | wc -l"
```

---

## Results Export

Load test results are exported to JSON:

```json
{
  "scenario": "heartbeat",
  "num_devices": 1000,
  "duration_seconds": 600.3,
  "total_requests": 20012,
  "total_errors": 23,
  "error_rate": "0.11%",
  "requests_per_second": "33.3",
  "heartbeats_sent": 20012,
  "heartbeat_failures": 23,
  "success_rate": "99.89%"
}
```

Use for:
- Performance regression tracking
- Capacity planning
- SLA validation

---

## Advanced Usage

### Custom Device Configuration

```python
from tests.load.device_simulator import SimulatedEdgeDevice, DeviceConfig
from tests.load.orchestrator import LoadTestOrchestrator

# Create custom config
config = DeviceConfig(
    device_id="custom-device-001",
    cloud_url="http://localhost:8000",
    api_key="test_key",
    heartbeat_interval=15,  # Custom interval
    saf_batch_size=100  # Custom batch size
)

# Create device
device = SimulatedEdgeDevice(config)
await device.initialize()

# Run custom scenario
await device.run_scenario("heartbeat", duration_seconds=300)
```

### Programmatic Usage

```python
from tests.load.orchestrator import LoadTestOrchestrator, ScenarioRunner

async def run_custom_test():
    orchestrator = LoadTestOrchestrator(
        cloud_url="http://localhost:8000"
    )

    # Run heartbeat test
    results = await ScenarioRunner.run_heartbeat_test(
        orchestrator,
        num_devices=500,
        duration_seconds=300
    )

    # Export results
    orchestrator.export_results(results, "results.json")

    # Check if passed
    if results.error_rate < 1.0:
        print("✅ Test PASSED")
    else:
        print("❌ Test FAILED")

# Run
import asyncio
asyncio.run(run_custom_test())
```

---

## CI/CD Integration

### GitHub Actions

```yaml
name: Load Testing

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM

jobs:
  load-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Start services
        run: docker compose up -d

      - name: Wait for services
        run: sleep 30

      - name: Run load tests
        run: |
          python tests/load/run_load_test.py \
            --all \
            --devices 100 \
            --output-dir results/

      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: load-test-results
          path: results/
```

---

## FAQ

**Q: How long does a full test take?**
A: ~60 minutes for all scenarios with 1000 devices.

**Q: What hardware is needed?**
A: Cloud server: 4 vCPU, 16GB RAM. Test machine: 2 vCPU, 4GB RAM.

**Q: Can I run tests against production?**
A: No - these tests generate significant load. Use staging environment.

**Q: How do I debug failing tests?**
A: Set `--log-level DEBUG` and check `load_test.log`.

**Q: What if error rate > 1%?**
A: Check cloud logs, database connections, and system resources.

---

## Resources

- **Load Testing Plan**: [docs/LOAD_TESTING_PLAN.md](../../docs/LOAD_TESTING_PLAN.md)
- **Production Readiness**: [PRODUCTION_READINESS.md](../../PRODUCTION_READINESS.md)
- **Cloud Deployment**: See main README.md

**Questions?** File a GitHub issue or contact the DevOps team.
