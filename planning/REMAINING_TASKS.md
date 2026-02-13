# Remaining Tasks & Roadmap

**Last Updated**: 2026-02-09
**Status**: Post-HMAC and Delta Updates Implementation

---

## Recently Completed ✅

**High-Priority Security & Performance**:
1. ✅ **HMAC authentication on sync payloads** (2026-02-09)
   - Edge device signing with HMAC-SHA256
   - Cloud verification with constant-time comparison
   - Automatic rejection of tampered/missing HMACs
   - **Impact**: Payload integrity guaranteed

2. ✅ **Delta model updates** (2026-02-09)
   - Binary diff/patch using bsdiff algorithm
   - 80-85% bandwidth savings for typical updates
   - Automatic fallback to full download
   - Cloud-side generation tool
   - **Impact**: Cellular data savings, faster updates

3. ✅ **Load testing plan** (2026-02-09)
   - 6 test scenarios (heartbeat, SAF, config, models, commands, workflows)
   - Test infrastructure design (simulator + orchestrator)
   - Metrics & monitoring setup (Prometheus + Grafana)
   - 7.5-day implementation timeline
   - **Impact**: Validation strategy for 1000+ device scale

---

## High Priority (Should Fix Before Production)

### 1. Device Sequence Tracking
**Effort**: 4-8 hours
**Impact**: Gap detection for transaction re-sync
**Status**: ❌ Not Started

**Description**:
Add monotonic sequence counter to edge devices for detecting missed transactions during sync.

**Implementation**:
```python
# Edge device (sync_manager.py)
class SyncManager:
    def __init__(self, ...):
        self._device_sequence = 0  # Load from persistence

    async def queue_for_sync(self, transaction):
        self._device_sequence += 1
        transaction.device_sequence = self._device_sequence
        # ... queue transaction

# Cloud (device_service.py)
async def sync_transactions(self, ...):
    # Check for sequence gaps
    expected_seq = last_synced_seq + 1
    if payload["device_sequence"] != expected_seq:
        # Gap detected - request re-sync for range
        return {"status": "gap_detected", "request_range": ...}
```

**Files to Modify**:
- `src/rufus_edge/sync_manager.py` - add sequence tracking
- `src/rufus_server/device_service.py` - verify sequence, detect gaps
- `src/rufus_edge/models.py` - add `device_sequence` to SAFTransaction
- Database schema - add `device_sequence` column to `saf_transactions`

**Workaround**: Manual reconciliation via audit logs

---

### 2. Load Testing Implementation
**Effort**: 3-5 days (per plan)
**Impact**: Unknown performance at 1000+ devices
**Status**: 📋 Plan Complete, Implementation Pending

**Description**:
Implement and execute the load testing plan created in LOAD_TESTING_PLAN.md.

**Steps**:
1. **Implement device simulator** (2 days)
   - Create `tests/load/device_simulator.py`
   - Implement orchestrator
   - Add metrics collection
2. **Run baseline tests** (1 day)
   - 10-device smoke tests
   - Document baseline
3. **Scale testing** (2 days)
   - 100 → 500 → 1000 → 1500 devices
   - All 6 scenarios
4. **Optimization** (1-2 days)
   - Fix bottlenecks
   - Re-test
5. **Stability testing** (1 day)
   - 24-hour run
   - Failure scenarios

**Deliverables**:
- Device simulator code
- Performance benchmark report
- Production tuning recommendations
- Automated regression tests

**Workaround**: Start with small fleet (10-100 devices), scale gradually

---

## Medium Priority (Nice-to-Have)

### 3. CRDT for Non-Financial State
**Effort**: 1 week
**Impact**: Better offline merge for non-financial data
**Status**: ❌ Not Started

**Description**:
Implement Conflict-free Replicated Data Types for non-financial workflow state (e.g., user preferences, device settings).

**Use Cases**:
- Device config overrides (user customizations)
- Workflow state that can be eventually consistent
- Multi-device user sessions

**Implementation Approach**:
- Use LWW-Element-Set for simple fields
- Use OR-Set for collection fields
- Maintain financial transactions as-is (idempotency-first)

**Libraries**:
- `pycrdt` - Python CRDT implementation
- `automerge-py` - Automerge CRDT bindings

**Files to Create**:
- `src/rufus_edge/crdt.py` - CRDT merge strategies
- `src/rufus/models.py` - add CRDT field markers
- Tests for conflict scenarios

**Current Workaround**: LWW + idempotency-key (works for financial)

---

### 4. Prometheus Metrics Integration
**Effort**: 2-3 days
**Impact**: Production observability
**Status**: ❌ Not Started

**Description**:
Add Prometheus metrics exporter for monitoring production deployments.

**Metrics to Add**:
- Request counters (`rufus_http_requests_total`)
- Latency histograms (`rufus_request_duration_seconds`)
- SAF transaction counters (`rufus_saf_transactions_total`)
- Database connection gauge (`rufus_db_connections`)
- Workflow execution metrics (`rufus_workflow_duration_seconds`)

**Implementation**:
```python
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# In main.py
from prometheus_client import make_asgi_app
app.mount("/metrics", make_asgi_app())

# In device_service.py
saf_transactions = Counter(
    'rufus_saf_transactions_total',
    'Total SAF transactions',
    ['device_id', 'status']
)

@app.post("/api/v1/devices/{device_id}/sync")
async def sync_transactions(...):
    with request_duration.labels(method='POST', endpoint='/sync').time():
        result = await device_service.sync_transactions(...)
        saf_transactions.labels(device_id=device_id, status='accepted').inc(len(result['accepted']))
```

**Files to Modify**:
- `src/rufus_server/main.py` - add /metrics endpoint
- `src/rufus_server/device_service.py` - instrument methods
- `src/rufus_edge/agent.py` - optional edge metrics
- `prometheus.yml` - scrape config

**Deliverables**:
- Prometheus metrics endpoint
- Example Grafana dashboards (JSON)
- Alerting rules (critical thresholds)

**Current Workaround**: Webhook events + structured logging

---

### 5. Grafana Dashboards
**Effort**: 1-2 days (depends on Prometheus metrics)
**Impact**: Visual monitoring for ops teams
**Status**: ❌ Not Started

**Description**:
Create pre-built Grafana dashboards for common monitoring needs.

**Dashboards to Create**:
1. **Cloud Control Plane Overview**
   - Request rate (by endpoint)
   - Latency (p50, p95, p99)
   - Error rate
   - CPU/memory usage
2. **Database Performance**
   - Connection pool utilization
   - Query latency
   - Cache hit rate
   - Lock wait time
3. **Edge Device Fleet**
   - Heartbeat health (online/offline/zombie)
   - SAF sync backlog
   - Config version distribution
   - Model version distribution
4. **SAF Pipeline**
   - Transaction queue depth
   - Sync throughput
   - Conflict rate
   - Bandwidth usage

**Files to Create**:
- `grafana/dashboards/cloud_control_plane.json`
- `grafana/dashboards/database_performance.json`
- `grafana/dashboards/edge_fleet.json`
- `grafana/dashboards/saf_pipeline.json`

**Dependencies**: Requires Prometheus metrics (#4)

---

## Low Priority (Future)

### 6. Loop Step Edge Cases
**Effort**: 2-4 hours
**Impact**: Advanced workflow features
**Status**: ❌ Not Started

**Description**:
Handle edge cases in LOOP step execution (nested loops, break/continue).

**Current Limitation**:
- Single-level loops work
- No break/continue directives
- No nested loop support

**Enhancement**:
```python
# Add loop control directives
class WorkflowBreakDirective(Exception):
    """Break out of current loop."""

class WorkflowContinueDirective(Exception):
    """Skip to next loop iteration."""

# In workflow.py
try:
    result = await step_function(state, context)
except WorkflowBreakDirective:
    break  # Exit loop early
except WorkflowContinueDirective:
    continue  # Skip to next iteration
```

**Current Workaround**: Use DECISION steps to exit loops conditionally

---

### 7. Celery Executor Polish
**Effort**: 1-2 days
**Impact**: Distributed execution improvements
**Status**: ❌ Not Started

**Description**:
Polish the Celery executor implementation for production use.

**Enhancements**:
- Task routing (dedicated queues for critical workflows)
- Priority-based execution
- Dead letter queue (DLQ) for failed tasks
- Task result expiry configuration
- Worker autoscaling

**Files to Modify**:
- `src/rufus/implementations/execution/celery.py`
- `celeryconfig.py` - production config

**Current Workaround**: Use SyncExecutor or ThreadPoolExecutor for most workloads

---

### 8. Settlement Gateway Integration
**Effort**: Processor-specific (1-2 weeks per processor)
**Impact**: Complete payment lifecycle
**Status**: ❌ Not Started (by design - processor-specific)

**Description**:
Integrate with payment processor settlement APIs (Stripe, Adyen, FIS, etc.).

**Implementation Strategy**:
- Create processor-specific workflow steps
- Not part of core SDK (app-level integration)
- Example implementations in `examples/payment_terminal/`

**Example**:
```yaml
steps:
  - name: "Settle_Batch"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "https://api.stripe.com/v1/settlements"
      headers:
        Authorization: "Bearer {{secrets.stripe_key}}"
      body:
        transactions: "{{state.settled_transactions}}"
```

**Current Workaround**: Manual settlement reconciliation

---

### 9. Advanced Cron Scheduling
**Effort**: 2-3 days
**Impact**: Timezone-aware scheduled workflows
**Status**: ❌ Not Started

**Description**:
Add timezone support and advanced cron features to CRON_SCHEDULE steps.

**Enhancements**:
- Timezone-aware scheduling
- DST handling
- Holiday calendars
- Cron expression validation

**Current Limitation**:
- Simple cron expressions work
- No timezone support
- No holiday exclusions

**Current Workaround**: Run cron in UTC, handle timezones in step functions

---

### 10. GraphQL API
**Effort**: 1-2 weeks
**Impact**: Flexible querying for complex UIs
**Status**: ❌ Not Started (Tier 5)

**Description**:
Add GraphQL API alongside REST API for flexible querying.

**Use Cases**:
- Dashboard UIs (fetch only needed fields)
- Mobile apps (reduce bandwidth)
- Third-party integrations

**Libraries**:
- `strawberry-graphql` - Python GraphQL library for FastAPI
- `graphene` - Alternative GraphQL framework

**Endpoints to Expose**:
- Workflows (query, mutation)
- Devices (query, mutation)
- SAF transactions (query)
- Commands (mutation)

**Current Workaround**: Use REST API (works fine for most use cases)

---

## Pinned for Later (Strategic)

### Resilience Engine Reframing
**Effort**: 2-3 days
**Impact**: Strategic positioning
**Status**: 🔖 PINNED (user decision pending)

**Description**:
Reframe Rufus from "workflow orchestration" to "Resilience Engine" with new RufusEngine API wrapper.

**Changes**:
- Create `RufusEngine` class wrapping `WorkflowBuilder`
- Update all documentation with resilience messaging
- Maintain backward compatibility
- Add resilience-focused examples

**User Decision Required**: When to proceed with this strategic pivot

---

## Summary by Priority

### Must Do Before Production
1. ✅ ~~HMAC authentication~~ (COMPLETE)
2. ✅ ~~Delta model updates~~ (COMPLETE)
3. ❌ Device sequence tracking (4-8 hours)
4. ❌ Load testing implementation (3-5 days)

### Should Do for Better Production
5. ❌ Prometheus metrics (2-3 days)
6. ❌ Grafana dashboards (1-2 days)
7. ❌ CRDT for non-financial state (1 week)

### Nice to Have
8. ❌ Loop step edge cases (2-4 hours)
9. ❌ Celery executor polish (1-2 days)
10. ❌ Advanced cron scheduling (2-3 days)
11. ❌ GraphQL API (1-2 weeks)

### Application-Specific (Not SDK)
12. ❌ Settlement gateway integration (processor-specific)

### Strategic Decision Pending
13. 🔖 Resilience Engine reframing (2-3 days)

---

## Estimated Timeline

**Critical Path to Production**:
- Device sequence tracking: 1 day
- Load testing: 5 days
- **Total**: 6 days (1.2 weeks)

**Full Production Polish**:
- Critical path: 6 days
- Prometheus + Grafana: 4 days
- CRDT: 5 days
- **Total**: 15 days (3 weeks)

**Complete Roadmap** (all features):
- Full production polish: 15 days
- Loop/Celery/Cron polish: 5 days
- GraphQL API: 10 days
- **Total**: 30 days (6 weeks)

---

## Recommendation

**For POS/ATM Production Deployment** (Ready Now):
1. Implement device sequence tracking (1 day)
2. Run load testing (5 days)
3. Deploy with monitoring plan

**For Healthcare/Large Fleets** (3 weeks):
1. Complete critical path (6 days)
2. Add Prometheus + Grafana (4 days)
3. Run extended stability testing (5 days)
4. HIPAA/compliance assessment (external)

**For Long-Term Product** (6 weeks):
1. Complete full production polish (15 days)
2. Add CRDT for complex offline scenarios (5 days)
3. Polish executors and advanced features (5 days)
4. Build GraphQL API for flexible integrations (10 days)

---

## Questions to Resolve

1. **Load testing timeline**: Run now or before first large deployment?
2. **Prometheus metrics**: Add now or wait for production monitoring needs?
3. **CRDT priority**: Critical for any specific use case?
4. **GraphQL API**: Customer demand vs REST API sufficiency?
5. **Resilience Engine reframing**: Proceed with strategic pivot?

---

Last updated: 2026-02-09
