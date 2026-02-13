# Load Testing Plan - 1000+ Device Scale Validation

**Status**: 📋 Planning Complete (2026-02-09)
**Effort**: 3-5 days implementation + testing
**Priority**: High (before large-scale production deployment)

---

## Executive Summary

This document outlines a comprehensive load testing strategy to validate Rufus Edge system performance at scale (1000+ concurrent edge devices).

**Goals**:
1. Validate system handles 1000+ concurrent devices
2. Identify bottlenecks in cloud control plane
3. Verify Store-and-Forward sync under load
4. Measure database performance (PostgreSQL vs SQLite)
5. Establish baseline performance metrics for monitoring

---

## Test Scenarios

### Scenario 1: Concurrent Device Heartbeats
**Objective**: Validate cloud can handle 1000+ devices reporting heartbeats simultaneously.

**Configuration**:
- **Devices**: 1,000 simulated edge devices
- **Heartbeat interval**: 30 seconds
- **Duration**: 10 minutes
- **Metrics**: CPU/RAM/disk from each device

**Expected Performance**:
- **Throughput**: 1,000 heartbeats / 30s = 33 req/sec sustained
- **Latency**: p50 < 100ms, p95 < 500ms, p99 < 1000ms
- **Success rate**: > 99.5%
- **Cloud CPU**: < 70% utilization
- **Database connections**: < 50 concurrent

**Pass Criteria**:
- ✅ All devices successfully report heartbeats
- ✅ Latency within thresholds
- ✅ No connection pool exhaustion
- ✅ No memory leaks over 10 minutes

---

### Scenario 2: Store-and-Forward Bulk Sync
**Objective**: Validate SAF pipeline handles mass offline → online transitions.

**Configuration**:
- **Devices**: 500 devices
- **Transactions per device**: 100 queued (offline period)
- **Total transactions**: 50,000
- **Sync strategy**: All devices come online simultaneously
- **Batch size**: 50 transactions per request

**Expected Performance**:
- **Sync throughput**: 1,000-2,000 transactions/sec
- **Cloud latency**: p95 < 2s per batch
- **Idempotency deduplication**: 100% accuracy
- **Conflict resolution**: < 1% conflicts, all resolved correctly

**Pass Criteria**:
- ✅ All 50,000 transactions synced successfully
- ✅ No duplicate transactions in database
- ✅ Conflict resolution logs show correct LWW strategy
- ✅ Database write queue doesn't back up (< 5s lag)

---

### Scenario 3: Config Rollout (Gradual Deployment)
**Objective**: Validate ETag-based config push to large fleet with gradual rollout.

**Configuration**:
- **Devices**: 1,000 devices
- **Rollout strategy**: CANARY (5% → 25% → 100%)
- **Config polling interval**: 60 seconds
- **Config size**: 10 KB (fraud rules + workflow updates)

**Expected Performance**:
- **Initial batch (50 devices)**: All receive config within 60s
- **Second batch (250 devices)**: All receive config within 120s
- **Final batch (700 devices)**: All receive config within 180s
- **Cloud bandwidth**: < 10 MB/s sustained (1000 devices × 10KB)
- **ETag cache hit rate**: > 95% (unchanged devices)

**Pass Criteria**:
- ✅ Gradual rollout respects policy percentages
- ✅ No devices receive wrong config version
- ✅ ETag conditional requests reduce bandwidth (304 responses)
- ✅ No config rollout failures

---

### Scenario 4: Model Distribution at Scale
**Objective**: Validate model updates (with delta patches) to large fleet.

**Configuration**:
- **Devices**: 1,000 devices
- **Model size**: 50 MB (full), 8 MB (delta)
- **Update strategy**: Delta updates (80% devices have v1, update to v2)
- **Concurrent downloads**: 200 devices/minute (rate limited)

**Expected Performance**:
- **Delta download time**: < 30s per device @ 2Mbps bandwidth
- **Full download time**: < 3 minutes per device (fallback cases)
- **Bandwidth usage**: 80% use delta (8MB), 20% full (50MB)
- **Total bandwidth**: (800 × 8MB) + (200 × 50MB) = 6.4GB + 10GB = 16.4GB
- **CDN hit rate**: > 99% (cached deltas)

**Pass Criteria**:
- ✅ 80%+ devices successfully use delta updates
- ✅ Automatic fallback works for failed deltas
- ✅ All devices end up with correct model hash
- ✅ No CDN bandwidth limit exceeded

---

### Scenario 5: Cloud Command Distribution
**Objective**: Validate cloud-to-device command system under load.

**Configuration**:
- **Devices**: 1,000 devices
- **Command types**: force_sync (40%), reload_config (40%), update_model (20%)
- **Command rate**: 100 commands/minute
- **Delivery mechanism**: Heartbeat response

**Expected Performance**:
- **Command queue latency**: p95 < 5s (time to device)
- **Command acknowledgment**: > 95% within 60s
- **Retry policy**: Exponential backoff works correctly
- **Failed command rate**: < 1%

**Pass Criteria**:
- ✅ All commands delivered within 60s
- ✅ Retry mechanism works for failed commands
- ✅ No command queue backlog
- ✅ Webhook notifications fired for all command lifecycle events

---

### Scenario 6: Concurrent Workflow Execution (Edge + Cloud)
**Objective**: Validate workflow engine handles mixed edge/cloud execution.

**Configuration**:
- **Edge devices**: 100 devices
- **Workflows per device**: 10 concurrent workflows
- **Total concurrent workflows**: 1,000
- **Workflow type**: Payment processing (3-5 steps each)
- **Execution mix**: 70% edge-only, 30% edge + cloud sync

**Expected Performance**:
- **Workflow start latency**: p95 < 200ms
- **Workflow completion**: p95 < 5s (edge-only), p95 < 10s (with sync)
- **Database load**: < 80% connection pool utilization
- **Saga compensation**: 100% accuracy for failed workflows

**Pass Criteria**:
- ✅ 1,000 concurrent workflows execute successfully
- ✅ No workflow state corruption
- ✅ Sub-workflow status bubbling works correctly
- ✅ Saga compensation executes in reverse order for failures

---

## Test Infrastructure

### Simulated Edge Devices

**Device Simulator** (`tests/load/device_simulator.py`):
```python
class SimulatedEdgeDevice:
    """
    Simulates edge device behavior for load testing.
    """
    def __init__(self, device_id, cloud_url, api_key):
        self.device_id = device_id
        self.cloud_url = cloud_url
        self.api_key = api_key
        self._http_client = httpx.AsyncClient()

    async def run_scenario(self, scenario: str):
        """Run specific test scenario."""
        if scenario == "heartbeat":
            await self._heartbeat_loop()
        elif scenario == "saf_sync":
            await self._saf_sync_scenario()
        elif scenario == "config_poll":
            await self._config_polling_loop()
        # ... etc

    async def _heartbeat_loop(self):
        """Send heartbeats every 30s."""
        while True:
            await self._send_heartbeat()
            await asyncio.sleep(30)

    async def _saf_sync_scenario(self):
        """Queue 100 transactions, then sync."""
        # Generate offline transactions
        transactions = [self._generate_transaction() for _ in range(100)]

        # Sync to cloud
        await self._sync_transactions(transactions)
```

**Load Test Orchestrator** (`tests/load/orchestrator.py`):
```python
class LoadTestOrchestrator:
    """
    Orchestrates simulated devices for load testing.
    """
    async def run_scenario(
        self,
        scenario: str,
        num_devices: int,
        duration_seconds: int
    ):
        """Spawn devices and run scenario."""
        devices = [
            SimulatedEdgeDevice(f"sim-{i}", CLOUD_URL, API_KEY)
            for i in range(num_devices)
        ]

        # Run scenario concurrently
        tasks = [device.run_scenario(scenario) for device in devices]
        await asyncio.gather(*tasks, timeout=duration_seconds)
```

---

### Cloud Infrastructure

**Recommended Setup**:
- **Compute**: 4 vCPU, 16GB RAM (scaled up for testing)
- **Database**: PostgreSQL 14+ with 100 max_connections
- **Connection pool**: Min=20, Max=80
- **CDN**: CloudFlare or AWS CloudFront for model distribution

**Docker Compose** for isolated testing:
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: rufus_load_test
      POSTGRES_MAX_CONNECTIONS: 100
    volumes:
      - postgres_data:/var/lib/postgresql/data

  rufus-server:
    build: .
    environment:
      DATABASE_URL: postgresql://postgres@postgres/rufus_load_test
      POSTGRES_POOL_MIN_SIZE: 20
      POSTGRES_POOL_MAX_SIZE: 80
    ports:
      - "8000:8000"
    depends_on:
      - postgres

  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
```

---

## Metrics & Monitoring

### Performance Metrics

**Cloud Control Plane**:
| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Request latency (p95) | < 500ms | < 1s |
| Request latency (p99) | < 1s | < 2s |
| Throughput | 100 req/sec | 50 req/sec |
| Error rate | < 0.5% | < 1% |
| CPU utilization | < 70% | < 85% |
| Memory usage | < 80% | < 90% |
| DB connection pool | < 60% | < 80% |

**Database (PostgreSQL)**:
| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Query latency (p95) | < 50ms | < 200ms |
| Active connections | < 60 | < 80 |
| Transaction throughput | 1000 tx/sec | 500 tx/sec |
| Lock wait time | < 10ms | < 100ms |
| Cache hit rate | > 95% | > 90% |

**Edge Devices** (simulated):
| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Heartbeat success rate | > 99% | > 95% |
| SAF sync success rate | > 99.5% | > 98% |
| Config download success | > 99% | > 95% |
| Model update success | > 98% | > 90% |

---

### Monitoring Stack

**Prometheus Metrics** (to be instrumented):
```python
from prometheus_client import Counter, Histogram, Gauge

# Request metrics
http_requests_total = Counter(
    'rufus_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

request_duration = Histogram(
    'rufus_request_duration_seconds',
    'Request duration',
    ['method', 'endpoint']
)

# SAF metrics
saf_transactions_total = Counter(
    'rufus_saf_transactions_total',
    'Total SAF transactions',
    ['device_id', 'status']  # status: accepted, rejected, duplicate
)

saf_sync_duration = Histogram(
    'rufus_saf_sync_duration_seconds',
    'SAF sync duration',
    ['device_id']
)

# Database metrics
db_connections = Gauge(
    'rufus_db_connections',
    'Active database connections'
)

db_query_duration = Histogram(
    'rufus_db_query_duration_seconds',
    'Database query duration',
    ['query_type']
)
```

**Grafana Dashboards**:
1. **Cloud Control Plane** - request rates, latencies, error rates
2. **Database Performance** - connection pool, query latency, cache hit rate
3. **Edge Device Fleet** - heartbeat health, sync status, command delivery
4. **SAF Pipeline** - transaction queue depth, sync throughput, conflicts

---

## Test Execution Plan

### Phase 1: Baseline (1 day)

**Objective**: Establish baseline performance with current implementation.

**Steps**:
1. Deploy cloud control plane to test environment
2. Run each scenario with 10 devices (smoke test)
3. Verify metrics collection works
4. Document baseline performance

**Deliverables**:
- Baseline metrics document
- Identified bottlenecks (if any)

---

### Phase 2: Scale Testing (2 days)

**Objective**: Incrementally scale to 1000+ devices.

**Steps**:
1. **100 devices**: Run all 6 scenarios
   - Verify performance within targets
   - Identify any issues early
2. **500 devices**: Run scenarios 1, 2, 3
   - Monitor database connection pool
   - Check for memory leaks
3. **1000 devices**: Run all scenarios
   - Full load test
   - Sustained for 30 minutes each
4. **1500 devices**: Stress test (beyond target)
   - Find breaking point
   - Measure graceful degradation

**Deliverables**:
- Performance report for each scale
- Identified bottlenecks and fixes
- Updated performance targets

---

### Phase 3: Optimization (1-2 days)

**Objective**: Fix identified bottlenecks and re-test.

**Common Bottlenecks & Fixes**:
| Bottleneck | Fix | Re-test |
|------------|-----|---------|
| Connection pool exhaustion | Increase `POSTGRES_POOL_MAX_SIZE` | ✓ |
| Slow SAF queries | Add index on `(device_id, status)` | ✓ |
| High heartbeat latency | Batch INSERT heartbeats | ✓ |
| Config polling storm | Add jitter to polling interval | ✓ |
| Memory leak | Fix async resource cleanup | ✓ |

**Deliverables**:
- Optimized configuration
- Updated performance benchmarks
- Production tuning recommendations

---

### Phase 4: Long-Running Stability (1 day)

**Objective**: Verify system stability over extended period.

**Steps**:
1. Run 1000-device load test for 24 hours
2. Monitor for:
   - Memory leaks
   - Connection leaks
   - Gradual performance degradation
   - Database bloat
3. Simulate failures:
   - Kill random devices (churn)
   - Restart cloud service (recovery)
   - Database connection loss (retry logic)

**Pass Criteria**:
- ✅ No memory growth over 24h
- ✅ Performance stays within 10% of baseline
- ✅ System recovers gracefully from failures
- ✅ No data loss during failures

---

## Tools & Frameworks

### Load Testing Tools

**Option 1: Custom Python Simulator** (Recommended)
```bash
# Install dependencies
pip install asyncio httpx faker prometheus-client

# Run load test
python tests/load/run_load_test.py \
    --scenario heartbeat \
    --devices 1000 \
    --duration 600  # 10 minutes
```

**Pros**:
- Full control over device behavior
- Can simulate complex scenarios (SAF, workflows)
- Easy to extend and debug

**Cons**:
- Requires implementation (3-4 days)

---

**Option 2: Locust** (Alternative)
```python
from locust import HttpUser, task, between

class EdgeDevice(HttpUser):
    wait_time = between(30, 35)  # Heartbeat interval

    @task
    def heartbeat(self):
        self.client.post(
            f"/api/v1/devices/{self.device_id}/heartbeat",
            headers={"X-API-Key": self.api_key},
            json={"status": "online", "metrics": {...}}
        )

    @task(weight=0.1)  # Less frequent
    def saf_sync(self):
        self.client.post(
            f"/api/v1/devices/{self.device_id}/sync",
            headers={"X-API-Key": self.api_key},
            json={"transactions": [...]}
        )
```

**Pros**:
- Mature framework with web UI
- Built-in metrics and reporting
- Easy to write simple scenarios

**Cons**:
- Less control over device lifecycle
- Harder to simulate SAF workflow logic

---

**Option 3: K6** (Alternative)
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
  vus: 1000,  // Virtual users (devices)
  duration: '10m',
};

export default function() {
  // Heartbeat
  let res = http.post(
    `${__ENV.CLOUD_URL}/api/v1/devices/${__VU}/heartbeat`,
    JSON.stringify({status: 'online'}),
    {headers: {'X-API-Key': __ENV.API_KEY}}
  );

  check(res, {'status 200': (r) => r.status === 200});
  sleep(30);  // 30s interval
}
```

**Pros**:
- High performance (written in Go)
- Good for HTTP load testing
- Built-in metrics

**Cons**:
- JavaScript-based (less Python integration)
- Harder to simulate complex device logic

---

**Recommendation**: Use **Custom Python Simulator** for comprehensive testing with fallback to **Locust** for quick HTTP load validation.

---

## Success Criteria

### Must-Have (Go/No-Go for Production)

- ✅ **1000+ concurrent devices** supported
- ✅ **Heartbeat latency** p95 < 500ms
- ✅ **SAF sync throughput** > 1000 tx/sec
- ✅ **Error rate** < 1% across all scenarios
- ✅ **24-hour stability** test passes
- ✅ **No memory leaks** detected
- ✅ **Database performance** within targets

### Nice-to-Have

- ⭐ **1500+ devices** supported (headroom)
- ⭐ **Config rollout** < 3 minutes for 1000 devices
- ⭐ **Model updates** < 5 minutes for 1000 devices (with deltas)
- ⭐ **Automated performance regression tests** in CI/CD

---

## Risks & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Connection pool exhaustion | High | Medium | Increase pool size, add connection queuing |
| Database write bottleneck | High | Medium | Add read replicas, optimize queries |
| Memory leak in async code | High | Low | Comprehensive leak testing, profiling |
| CDN rate limiting | Medium | Low | Use dedicated CDN tier, pre-warm cache |
| Test environment != production | Medium | High | Use production-like infrastructure for testing |

---

## Implementation Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **Simulator Development** | 2 days | Custom device simulator, orchestrator |
| **Baseline Testing** | 1 day | Baseline metrics, smoke tests |
| **Scale Testing** | 2 days | 100/500/1000/1500 device results |
| **Optimization** | 1-2 days | Bottleneck fixes, re-test |
| **Stability Testing** | 1 day | 24-hour run, failure scenarios |
| **Documentation** | 0.5 days | Final report, production recommendations |
| **TOTAL** | **7.5 days** | **Production-ready load test suite** |

**Estimated effort**: 3-5 days (optimistic) to 7.5 days (comprehensive)

---

## Next Steps

1. **Review this plan** with team
2. **Provision test infrastructure** (cloud + database)
3. **Implement device simulator** (2 days)
4. **Run Phase 1 baseline tests** (1 day)
5. **Execute scale testing phases** (2-3 days)
6. **Document results and recommendations**

---

## Resources

- **Load Testing Best Practices**: https://grafana.com/blog/2020/12/22/performance-testing-best-practices/
- **PostgreSQL Performance Tuning**: https://wiki.postgresql.org/wiki/Performance_Optimization
- **Python async profiling**: https://github.com/agronholm/asyncio-perf

**Questions?** Contact DevOps team or file a GitHub issue.
