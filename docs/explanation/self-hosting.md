# Rufus Orchestrates Itself

## The Self-Hosting Insight

Most workflow orchestration systems require a separate orchestration tier — a control plane that is architecturally distinct from the workloads it manages. Rufus takes a different approach.

**The Rufus control plane runs on Rufus.**

The same SDK that runs on a POS terminal processing offline payments also powers the cloud server managing that terminal's configuration, commands, and audit log. Configuration rollout, audit aggregation, and policy enforcement are themselves Rufus workflows — they use the same step types, the same saga pattern, the same provider abstractions.

This is not a coincidence. It is a deliberate architectural choice.

---

## Three Roles, One Runtime

```
┌────────────────────────────────────────────────────────────────┐
│                         Rufus SDK (Core)                       │
│         WorkflowBuilder · Workflow · Providers · Steps         │
└─────────────┬──────────────────┬──────────────────┬───────────┘
              │                  │                  │
   ┌──────────▼──────┐  ┌───────▼────────┐  ┌─────▼──────────┐
   │  Device Runtime  │  │  Cloud Worker  │  │ Control Plane  │
   │                  │  │                │  │                │
   │  SQLite / WAL    │  │  PostgreSQL    │  │  PostgreSQL    │
   │  SyncExecution   │  │  Celery        │  │  Celery        │
   │  Offline-first   │  │  Horizontal    │  │  Fleet API     │
   └──────────────────┘  └────────────────┘  └────────────────┘
```

The only differences between these three roles are the **persistence backend** and **execution backend** passed to `WorkflowBuilder`. The YAML step definitions, the Python step functions, the saga compensation logic, the zombie recovery system — all identical.

```python
# Device Runtime (offline-first, SQLite)
builder = WorkflowBuilder(
    persistence_provider=SQLitePersistenceProvider("device.db"),
    execution_provider=SyncExecutionProvider(),
)

# Cloud Worker (distributed, PostgreSQL + Celery)
builder = WorkflowBuilder(
    persistence_provider=PostgresPersistenceProvider(db_url=DATABASE_URL),
    execution_provider=CeleryExecutionProvider(broker_url=REDIS_URL),
)

# Both run the same YAML workflow definitions.
```

---

## What This Means

### No Magic Paths

In other orchestration platforms, the control plane is a separate system with its own APIs, its own state management, its own failure modes. Debugging a workflow failure in the control plane requires understanding a completely different codebase.

In Rufus, there are no magic paths. Everything is either:
- A Rufus workflow (uses `WorkflowBuilder`, `Workflow`, step functions, providers)
- A provider implementation (implements a Python Protocol interface)

If you understand how a payment workflow runs on a device, you understand how the configuration rollout workflow runs on the control plane.

### Battle-Tested by Its Own Use

The control plane validates the SDK by running it in production at scale. A crash bug in ASYNC step execution, a deadlock in the saga compensation path, a heartbeat timing issue — these surface in the control plane's own workflows before they reach users. The SDK is continuously tested against itself.

### Consistent Semantics

Saga rollback works identically whether it's rolling back a failed payment on a POS terminal or rolling back a failed firmware push on a fleet of 10,000 devices. Zombie detection fires the same way. Workflow versioning protects running workflows the same way.

This consistency is only possible because there is one SDK, not two.

---

## The Recursive Pattern in Practice

Here is an example of the self-hosting pattern at work:

**Device configuration rollout** — when a new fraud rule set needs to be pushed to 10,000 devices:

1. An operator calls `POST /api/v1/config/rollout` on the control plane
2. The `ConfigRollout` workflow runs with five steps:
   - `Validate_Config` — rejects malformed config before anything is written
   - `Create_Config_Version` — persists the new config to the database (compensatable)
   - `Broadcast_To_Fleet` — sends an `update_config` command to all matching devices (compensatable)
   - `Monitor_Broadcast` — a **LOOP/WHILE** step that polls broadcast progress until all devices acknowledge or a timeout is reached
   - `Finalize_Rollout` — evaluates the failure rate against the circuit-breaker threshold; raises if exceeded (triggering saga compensation)
3. If `Finalize_Rollout` raises (too many device failures), saga compensation runs in reverse: broadcast is cancelled, config version is deactivated, and the previous version is restored
4. The entire rollout is auditable via `workflow_audit_log` — same table used by device-side workflows

**That `ConfigRollout` workflow is a Rufus workflow.** It runs on the control plane with PostgreSQL + Celery, but it is defined in YAML exactly like the payment workflow running on the device.

Similarly, `PolicyRollout` wraps the fraud-rule write path in the same pattern: `Validate_Policy` → `Persist_Policy` (compensatable: deletes from DB + in-memory cache on rollback) → `Finalize_Policy_Rollout`. High-stakes policy writes get durable persistence and automatic compensation; read and evaluate operations remain direct calls on the hot path.

---

## Comparisons

Other systems that self-host include:

- **GCC** — compiled by GCC (bootstrapping compiler)
- **Docker** — Docker build infrastructure runs in Docker containers
- **Kubernetes** — kube-apiserver is a Kubernetes workload in production

The pattern is called **bootstrapping** or **dogfooding**. It is a strong signal of architectural integrity: the authors trust their system enough to run their most critical infrastructure on it.

Rufus applies this pattern to workflow orchestration: "A recursive, offline-first orchestration system that proves its own correctness by running itself."

---

## What This Means for Architecture Decisions

The self-hosting model imposes discipline:

1. **Provider abstractions must be clean** — if they were leaky, the control plane workflows would fail differently from device workflows
2. **Error handling must be correct** — the control plane cannot paper over SDK bugs with workarounds that don't exist on the device
3. **Performance characteristics must be predictable** — the control plane has the same throughput constraints as user workloads

These constraints produce a better SDK for everyone.

---

## See Also

- [Architecture Overview](architecture.md) — Three-role diagram and component details
- [Provider Pattern](provider-pattern.md) — How pluggable backends work
- [Edge Architecture](edge-architecture.md) — Device-side design details
- [Zombie Recovery](zombie-recovery.md) — Crash resilience (same on device and cloud)
