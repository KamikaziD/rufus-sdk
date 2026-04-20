# Workflow Versioning: Definition Snapshots

When you deploy a new version of a workflow YAML file, what happens to the 10,000 workflows already running in production? Workflow versioning ensures that running workflows continue using their original definition, immune to breaking changes.

## The Problem

### Scenario: Breaking Change Deployment

```yaml
# v1.0.0 (deployed Monday, 10,000 workflows running)
workflow_type: "OrderProcessing"
workflow_version: "1.0.0"
steps:
  - name: "Validate_Order"
  - name: "Human_Approval"  # Manual approval required
  - name: "Charge_Payment"
  - name: "Ship_Order"
```

Tuesday, you deploy v2.0.0 that removes the manual approval step:

```yaml
# v2.0.0 (deployed Tuesday)
workflow_type: "OrderProcessing"
workflow_version: "2.0.0"
steps:
  - name: "Validate_Order"
  # Human_Approval removed (automated now)
  - name: "Charge_Payment"
  - name: "Ship_Order"
```

**What happens to the 10,000 workflows in `WAITING_HUMAN_INPUT` at step `Human_Approval`?**

**Without versioning**:
- Workflow resumes, tries to find "Human_Approval" step
- Step not found in new YAML
- Workflow crashes
- 10,000 orders stuck, requiring manual recovery

**With versioning**:
- Workflow uses its original definition snapshot (v1.0.0)
- "Human_Approval" step still exists in the snapshot
- Workflow completes successfully
- New workflows use v2.0.0, old workflows use v1.0.0

## How Workflow Versioning Works

### 1. Definition Snapshot on Creation

When a workflow is created, Ruvon captures a complete snapshot:

```python
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"order_id": "ORD-123"}
)

# Ruvon automatically snapshots:
workflow.definition_snapshot = {
    "workflow_type": "OrderProcessing",
    "workflow_version": "1.0.0",
    "initial_state_model": "myapp.models.OrderState",
    "steps": [
        {"name": "Validate_Order", "type": "STANDARD", ...},
        {"name": "Human_Approval", "type": "STANDARD", ...},
        {"name": "Charge_Payment", "type": "STANDARD", ...},
        {"name": "Ship_Order", "type": "STANDARD", ...}
    ],
    # ... complete workflow definition
}
```

### 2. Snapshot Persistence

Snapshot stored in database alongside workflow state:

```sql
CREATE TABLE workflow_executions (
    id UUID PRIMARY KEY,
    workflow_type VARCHAR(100) NOT NULL,
    workflow_version VARCHAR(50),         -- e.g., "1.0.0"
    definition_snapshot JSONB,            -- Complete YAML as JSON
    state JSONB NOT NULL,
    status VARCHAR(50) NOT NULL,
    ...
);
```

**Storage overhead**:
- ~5-10 KB per workflow (typical)
- PostgreSQL: Compressed JSONB (efficient storage)
- SQLite: TEXT (JSON string)

### 3. Snapshot Usage on Resume

When workflow is loaded (after pause, async task, or server restart):

```python
# Load workflow from database
workflow_dict = await persistence.load_workflow(workflow_id)

# Use snapshot instead of current YAML
if workflow_dict.get('definition_snapshot'):
    # Use snapshot (version at creation time)
    workflow_config = workflow_dict['definition_snapshot']
else:
    # Fallback: Load from current YAML (backward compatibility)
    workflow_config = builder.load_yaml(workflow_dict['workflow_type'])

# Reconstruct workflow with original definition
workflow = Workflow(
    id=workflow_dict['id'],
    config=workflow_config,  # Uses snapshot!
    state=state,
    ...
)
```

**Key Point**: Workflow always uses its snapshot, never the latest YAML.

## Version Compatibility

### Explicit Versioning

Add `workflow_version` to YAML for tracking:

```yaml
workflow_type: "OrderProcessing"
workflow_version: "2.1.0"  # Semantic versioning
initial_state_model: "myapp.models.OrderState"
steps:
  - name: "Validate_Order"
  ...
```

Access version in code:

```python
workflow = await builder.create_workflow("OrderProcessing", data)
print(f"Workflow version: {workflow.workflow_version}")  # "2.1.0"
```

Query workflows by version:

```sql
SELECT id, workflow_version, status, created_at
FROM workflow_executions
WHERE workflow_type = 'OrderProcessing'
  AND workflow_version = '1.0.0'
  AND status = 'ACTIVE';
```

### Compatibility Checking (Optional)

Implement version validation when resuming workflows:

```python
def check_version_compatibility(snapshot_version: str, current_version: str) -> bool:
    """Check if workflow snapshot is compatible with current YAML."""
    if not snapshot_version or not current_version:
        return True  # No version specified

    # Parse semantic versions
    snap_major, snap_minor, _ = snapshot_version.split('.')
    curr_major, curr_minor, _ = current_version.split('.')

    # Compatible if same major version
    if snap_major != curr_major:
        return False

    # Allow minor version upgrades (backward compatible)
    return int(snap_minor) <= int(curr_minor)

# In WorkflowBuilder.load_workflow:
workflow_dict = await persistence.load_workflow(workflow_id)
snapshot_version = workflow_dict.get('workflow_version')
current_version = builder.get_current_version(workflow_dict['workflow_type'])

if not check_version_compatibility(snapshot_version, current_version):
    raise IncompatibleVersionError(
        f"Workflow version {snapshot_version} incompatible with "
        f"current version {current_version}"
    )
```

## Breaking Change Strategies

### Strategy 1: Snapshot-Only (Recommended)

Just deploy the new YAML—running workflows use their snapshot:

```yaml
# Monday: Deploy v1.0.0
workflow_version: "1.0.0"
steps:
  - name: "Human_Approval"  # Required

# Tuesday: Deploy v2.0.0 (removes Human_Approval)
workflow_version: "2.0.0"
steps:
  # Human_Approval removed
```

**Behavior**:
- Existing workflows (created Monday): Use v1.0.0 snapshot, have "Human_Approval"
- New workflows (created Tuesday): Use v2.0.0 YAML, no "Human_Approval"

**Pros**:
- Simple deployment
- No coordination needed
- Natural migration (old workflows drain, new workflows start)

**Cons**:
- May have 2 versions running for days/weeks (long-running workflows)

### Strategy 2: Side-by-Side Versions

Keep both YAML files, register as separate workflow types:

```yaml
# config/order_processing_v1.yaml
workflow_type: "OrderProcessing_v1"
workflow_version: "1.0.0"
steps:
  - name: "Human_Approval"

# config/order_processing_v2.yaml
workflow_type: "OrderProcessing_v2"
workflow_version: "2.0.0"
steps:
  # Human_Approval removed
```

Register both:
```yaml
# config/workflow_registry.yaml
workflows:
  - type: "OrderProcessing_v1"
    config_file: "order_processing_v1.yaml"
    deprecated: true

  - type: "OrderProcessing_v2"
    config_file: "order_processing_v2.yaml"
```

**Application code**:
```python
# Gradually migrate to v2
if feature_flag('use_order_processing_v2'):
    workflow_type = "OrderProcessing_v2"
else:
    workflow_type = "OrderProcessing_v1"

workflow = await builder.create_workflow(workflow_type, data)
```

**Pros**:
- Explicit versioning
- Easy to toggle between versions
- Can delete v1 YAML after all workflows complete

**Cons**:
- File duplication
- Registry clutter

### Strategy 3: Gradual Migration

Deploy new version but keep old version available:

```yaml
# config/order_processing.yaml (v2.0.0)
workflow_type: "OrderProcessing"
workflow_version: "2.0.0"
steps:
  # New definition

# config/order_processing_v1.yaml (kept for running workflows)
workflow_type: "OrderProcessing"
workflow_version: "1.0.0"
steps:
  - name: "Human_Approval"
```

**Monitoring**:
```sql
-- Check if any v1 workflows still running
SELECT COUNT(*) AS active_v1_workflows
FROM workflow_executions
WHERE workflow_type = 'OrderProcessing'
  AND workflow_version = '1.0.0'
  AND status IN ('ACTIVE', 'PENDING_ASYNC', 'WAITING_HUMAN_INPUT');

-- When count reaches 0, delete order_processing_v1.yaml
```

**Pros**:
- Safe migration
- Can monitor progress

**Cons**:
- Requires manual cleanup

## Snapshot Analysis

### Inspecting Snapshots

Check what definition a workflow is using:

```python
workflow = await persistence.load_workflow(workflow_id)
snapshot = workflow['definition_snapshot']

print(f"Workflow type: {snapshot['workflow_type']}")
print(f"Workflow version: {snapshot.get('workflow_version')}")
print(f"Steps in snapshot: {[s['name'] for s in snapshot['steps']]}")
```

### Comparing Snapshot to Current YAML

```python
def compare_definitions(snapshot, current_yaml):
    """Compare snapshot to current YAML."""
    snapshot_steps = {s['name'] for s in snapshot['steps']}
    current_steps = {s['name'] for s in current_yaml['steps']}

    added = current_steps - snapshot_steps
    removed = snapshot_steps - current_steps

    print(f"Steps added: {added}")
    print(f"Steps removed: {removed}")

# Usage
snapshot = workflow['definition_snapshot']
current = builder.load_yaml("OrderProcessing")
compare_definitions(snapshot, current)

# Output:
# Steps added: {'Automated_Approval'}
# Steps removed: {'Human_Approval'}
```

### Storage Analysis

```sql
-- Check snapshot storage usage
SELECT
    AVG(LENGTH(definition_snapshot::text)) AS avg_snapshot_size_bytes,
    MAX(LENGTH(definition_snapshot::text)) AS max_snapshot_size_bytes,
    COUNT(*) AS total_workflows
FROM workflow_executions
WHERE definition_snapshot IS NOT NULL;

-- Find workflows with large snapshots
SELECT id, workflow_type, LENGTH(definition_snapshot::text) AS snapshot_size
FROM workflow_executions
WHERE LENGTH(definition_snapshot::text) > 50000  -- > 50KB
ORDER BY snapshot_size DESC;
```

## Backward Compatibility

### Workflows Without Snapshots

Existing workflows (before versioning feature) don't have snapshots:

```sql
SELECT COUNT(*) FROM workflow_executions WHERE definition_snapshot IS NULL;
```

**Behavior**:
- Workflow loads current YAML (legacy behavior)
- May break if YAML has incompatible changes
- Recommend: Migrate to snapshot

**Migration**:
```python
# Backfill snapshots for running workflows
async def backfill_snapshots(persistence, builder):
    workflows = await persistence.list_workflows(status="ACTIVE")

    for workflow in workflows:
        if not workflow.get('definition_snapshot'):
            # Load current YAML as snapshot
            current_yaml = builder.load_yaml(workflow['workflow_type'])

            # Save snapshot
            await persistence.update_workflow(
                workflow['id'],
                {'definition_snapshot': current_yaml}
            )

            print(f"Backfilled snapshot for {workflow['id']}")
```

## Common Pitfalls

### Pitfall 1: Deleting Old YAML Files Immediately

```bash
# ❌ Bad: Delete old YAML right after deploying new version
rm config/order_processing_v1.yaml

# Existing workflows may need v1 definition for reference/debugging
```

**Best Practice**: Keep old YAMLs for 30-90 days, or until all workflows complete.

### Pitfall 2: Assuming All Workflows Use Latest Definition

```python
# ❌ Bad: Assume workflow has latest field
def my_step(state: OrderState, context: StepContext):
    # This field added in v2.0.0
    new_field = state.new_v2_field  # AttributeError for v1 workflows!

# ✅ Good: Check version or use defaults
def my_step(state: OrderState, context: StepContext):
    new_field = getattr(state, 'new_v2_field', default_value)
```

### Pitfall 3: Not Testing Migrations

```python
# ✅ Good: Test v1 → v2 migration
def test_v1_workflow_completes_after_v2_deploy():
    # Create workflow with v1 YAML
    builder_v1 = WorkflowBuilder(config_dir="config/v1/")
    workflow = builder_v1.create_workflow("OrderProcessing", data)

    # Pause workflow
    workflow.next_step(user_input={})  # Validate_Order
    workflow.next_step(user_input={})  # Human_Approval (pauses)

    # Deploy v2 YAML (removes Human_Approval)
    builder_v2 = WorkflowBuilder(config_dir="config/v2/")

    # Resume workflow (should use v1 snapshot)
    loaded_workflow = await persistence.load_workflow(workflow.id)
    assert "Human_Approval" in [s['name'] for s in loaded_workflow['definition_snapshot']['steps']]

    # Complete workflow
    workflow.resume(input={"approved": True})
    assert workflow.status == "COMPLETED"
```

## Versioning Best Practices

### 1. Use Semantic Versioning

```yaml
# Major: Breaking changes (incompatible state model)
workflow_version: "2.0.0"

# Minor: Backward-compatible features (new optional steps)
workflow_version: "1.1.0"

# Patch: Bug fixes (no definition changes)
workflow_version: "1.0.1"
```

### 2. Document Version Changes

```yaml
# config/order_processing.yaml
workflow_type: "OrderProcessing"
workflow_version: "2.0.0"

# CHANGELOG:
# v2.0.0 (2026-02-13):
#   - Removed Human_Approval step (automated)
#   - Added Fraud_Check step
#   - Changed state model: removed manual_approver field
#
# v1.0.0 (2026-01-01):
#   - Initial version
```

### 3. Monitor Version Distribution

```sql
-- Track version distribution
SELECT workflow_version, status, COUNT(*) AS count
FROM workflow_executions
WHERE workflow_type = 'OrderProcessing'
GROUP BY workflow_version, status
ORDER BY workflow_version DESC, status;

-- Output:
-- workflow_version | status               | count
-- -----------------|----------------------|-------
-- 2.0.0            | ACTIVE               | 8,500
-- 2.0.0            | COMPLETED            | 12,000
-- 1.0.0            | ACTIVE               | 1,200  ← Still running!
-- 1.0.0            | WAITING_HUMAN_INPUT  | 300    ← Still running!
-- 1.0.0            | COMPLETED            | 50,000
```

### 4. Set Deprecation Timeline

```yaml
workflows:
  - type: "OrderProcessing_v1"
    config_file: "order_processing_v1.yaml"
    deprecated: true
    deprecation_date: "2026-03-01"
    remove_after_date: "2026-04-01"  # Delete after 30 days
```

### 5. Alert on Long-Running Old Versions

```python
# Alert if v1 workflows still running after 30 days
old_workflows = await persistence.query("""
    SELECT id, workflow_version, created_at, status
    FROM workflow_executions
    WHERE workflow_type = 'OrderProcessing'
      AND workflow_version = '1.0.0'
      AND status != 'COMPLETED'
      AND created_at < NOW() - INTERVAL '30 days'
""")

if old_workflows:
    alert(f"{len(old_workflows)} old version workflows still running")
```

## What's Next

Now that you understand workflow versioning:
- [Zombie Recovery](zombie-recovery.md) - Another reliability feature
- [Workflow Lifecycle](workflow-lifecycle.md) - How versioning interacts with lifecycle states
- [State Management](state-management.md) - Version compatibility for state models
