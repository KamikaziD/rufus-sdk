# Sub-Workflows: Hierarchical Composition

Sub-workflows allow you to compose complex workflows from simpler, reusable workflows. A parent workflow can spawn child workflows, wait for them to complete, and incorporate their results.

## Why Sub-Workflows?

### Problem 1: Workflow Complexity

A monolithic workflow with 50 steps is hard to understand, test, and maintain:

```yaml
# ❌ Bad: Monolithic workflow
workflow_type: "CompleteOrderProcessing"
steps:
  - name: "Validate_Customer"
  - name: "Check_Fraud"
  - name: "Allocate_Inventory_Item_1"
  - name: "Allocate_Inventory_Item_2"
  # ... 20 more inventory steps
  - name: "Calculate_Base_Price"
  - name: "Apply_Discount_1"
  # ... 10 more pricing steps
  - name: "Charge_Payment"
  # ... 15 more steps
```

### Problem 2: Code Reuse

Different workflows need the same logic (e.g., inventory allocation):

```yaml
# OrderProcessing needs inventory allocation
# ReturnProcessing needs inventory allocation
# TransferProcessing needs inventory allocation
# Copy-paste the same 20 steps? No!
```

### Solution: Sub-Workflows

Break complex workflows into composable pieces:

```yaml
# Parent workflow
workflow_type: "OrderProcessing"
steps:
  - name: "Validate_Customer"
    type: "STANDARD"
    function: "steps.validate"

  - name: "Allocate_Inventory"
    type: "STANDARD"
    function: "steps.allocate"  # Spawns InventoryAllocation sub-workflow

  - name: "Calculate_Pricing"
    type: "STANDARD"
    function: "steps.calculate"  # Spawns PricingCalculation sub-workflow

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "steps.charge"

# Child workflow (reusable)
workflow_type: "InventoryAllocation"
steps:
  - name: "Check_Stock"
  - name: "Reserve_Items"
  - name: "Update_Ledger"
```

**Benefits**:
- **Modularity**: Each workflow has single responsibility
- **Reusability**: InventoryAllocation used by multiple parents
- **Testability**: Test child workflows independently
- **Clarity**: Easier to understand 3 workflows of 10 steps than 1 workflow of 30 steps

## How Sub-Workflows Work

### 1. Triggering a Sub-Workflow

A step function raises `StartSubWorkflowDirective`:

```python
from rufus.models import StartSubWorkflowDirective

def allocate_inventory(state: OrderState, context: StepContext) -> dict:
    """Step that spawns inventory allocation sub-workflow."""

    # Raise directive to start child workflow
    raise StartSubWorkflowDirective(
        workflow_type="InventoryAllocation",
        initial_data={
            "order_id": state.order_id,
            "items": state.items
        },
        owner_id=state.owner_id,
        data_region=state.data_region
    )
```

### 2. Parent-Child Relationship

```
Parent Workflow: OrderProcessing (ID: P123)
├── Status: PENDING_SUB_WORKFLOW
├── Current Step: "Allocate_Inventory"
└── Waiting for child: InventoryAllocation (ID: C456)
    │
    └── Child Workflow: InventoryAllocation (ID: C456)
        ├── Parent ID: P123
        ├── Status: ACTIVE
        ├── Executing steps independently
        └── Result: {"allocated": True, "warehouse_id": "WH-1"}
```

### 3. Status Propagation

Child workflows report their status to parents:

```
Child Status         → Parent Status
─────────────────      ───────────────────────────
ACTIVE              → PENDING_SUB_WORKFLOW
PENDING_ASYNC       → PENDING_SUB_WORKFLOW
WAITING_HUMAN_INPUT → WAITING_CHILD_HUMAN_INPUT
COMPLETED           → ACTIVE (parent resumes)
FAILED              → FAILED_CHILD_WORKFLOW
```

**Key Point**: Parent status reflects child status, allowing monitoring at the top level.

### 4. Result Merging

When child completes, parent receives results:

```python
# Child workflow completes with:
{
    "allocated": True,
    "warehouse_id": "WH-1",
    "items_reserved": [{"sku": "WIDGET-1", "qty": 2}]
}

# Parent workflow state updated:
state.sub_workflow_results = {
    "InventoryAllocation": {
        "allocated": True,
        "warehouse_id": "WH-1",
        "items_reserved": [...]
    }
}

# Parent resumes with next step
```

Results are stored in `state.sub_workflow_results[workflow_type]`.

## Sub-Workflow Lifecycle

### Happy Path

```
1. Parent creates child workflow
   Parent: PENDING_SUB_WORKFLOW
   Child: ACTIVE

2. Child executes steps
   Parent: PENDING_SUB_WORKFLOW (idle)
   Child: ACTIVE → PENDING_ASYNC → ACTIVE → ...

3. Child completes
   Parent: ACTIVE (resumes)
   Child: COMPLETED

4. Parent continues
   Parent: ACTIVE → next step
```

### Child Pauses for Human Input

```
1. Parent creates child
   Parent: PENDING_SUB_WORKFLOW
   Child: ACTIVE

2. Child pauses (needs approval)
   Parent: WAITING_CHILD_HUMAN_INPUT
   Child: WAITING_HUMAN_INPUT

3. User provides input to child
   Child: ACTIVE (resumes)
   Parent: PENDING_SUB_WORKFLOW (still waiting)

4. Child completes
   Parent: ACTIVE (resumes)
   Child: COMPLETED
```

**Key Point**: Parent status changes to `WAITING_CHILD_HUMAN_INPUT` so you can filter for "workflows blocked on human input" at any level.

### Child Fails

```
1. Parent creates child
   Parent: PENDING_SUB_WORKFLOW
   Child: ACTIVE

2. Child encounters error
   Child: FAILED

3. Parent detects child failure
   Parent: FAILED_CHILD_WORKFLOW

4. Both workflows are failed
   Parent: FAILED_CHILD_WORKFLOW (terminal)
   Child: FAILED (terminal)
```

**Recovery**: Retry the parent workflow, which will re-create the child.

## Nested Sub-Workflows

Sub-workflows can spawn their own sub-workflows:

```
Grandparent: OrderProcessing
└── Child: InventoryAllocation
    └── Grandchild: WarehouseSelection
        └── Great-grandchild: ShippingCostCalculation
```

**Depth Limit**: Rufus supports arbitrary nesting depth, but practical limit is 3-4 levels (beyond that, consider refactoring).

**Status Propagation**: Bubbles up through all levels:

```
Great-grandchild: WAITING_HUMAN_INPUT
    ↓
Grandchild: PENDING_SUB_WORKFLOW
    ↓
Child: PENDING_SUB_WORKFLOW
    ↓
Grandparent: WAITING_CHILD_HUMAN_INPUT
```

Top-level view: "OrderProcessing is waiting for human input somewhere in the tree."

## Data Flow Patterns

### Pattern 1: Pass Initial Data

Parent provides data when creating child:

```python
raise StartSubWorkflowDirective(
    workflow_type="InventoryAllocation",
    initial_data={
        "order_id": state.order_id,
        "items": state.items,
        "warehouse_preference": state.customer_warehouse
    }
)
```

Child receives this data in its state model:

```python
class InventoryAllocationState(BaseModel):
    order_id: str
    items: list[dict]
    warehouse_preference: Optional[str] = None
```

### Pattern 2: Retrieve Results

Parent accesses child results after completion:

```python
def after_inventory_allocation(state: OrderState, context: StepContext) -> dict:
    # Get child workflow results
    inventory_result = state.sub_workflow_results.get("InventoryAllocation", {})

    warehouse_id = inventory_result.get("warehouse_id")
    allocated = inventory_result.get("allocated")

    if not allocated:
        raise WorkflowJumpDirective(target_step_name="Handle_Allocation_Failure")

    return {"warehouse_id": warehouse_id}
```

### Pattern 3: Shared Owner and Region

Child workflows inherit multi-tenancy metadata:

```python
raise StartSubWorkflowDirective(
    workflow_type="InventoryAllocation",
    initial_data={...},
    owner_id=state.owner_id,      # Same tenant
    data_region=state.data_region  # Same region (GDPR compliance)
)
```

**Why**: Ensures child workflows respect tenant isolation and data locality.

## Sub-Workflow Error Handling

### Automatic Failure Propagation

If child fails, parent fails:

```python
# Parent step
def allocate_inventory(state, context):
    raise StartSubWorkflowDirective(workflow_type="InventoryAllocation", ...)

# Child workflow fails during execution
# → Parent transitions to FAILED_CHILD_WORKFLOW
```

### Manual Error Handling (Future Enhancement)

Currently, Rufus does not support catching child failures. Planned for future:

```yaml
# Planned (not yet implemented)
- name: "Allocate_Inventory"
  type: "SUB_WORKFLOW"
  sub_workflow_type: "InventoryAllocation"
  on_failure:
    target_step: "Handle_Allocation_Failure"
```

**Workaround**: Implement error handling inside child workflow:

```yaml
# Child workflow (InventoryAllocation)
steps:
  - name: "Reserve_Items"
    type: "STANDARD"
    function: "steps.reserve"

  - name: "Handle_Errors"  # Error handling within child
    type: "DECISION"
    routes:
      - condition: "state.reservation_failed"
        target: "Notify_Parent_Of_Failure"
      - default: "Complete_Successfully"
```

## Sub-Workflows with Saga Pattern

Both parent and child can have saga mode enabled:

```python
# Parent workflow
parent = await builder.create_workflow("OrderProcessing", data)
parent.enable_saga_mode()

# Parent spawns child
# Child also has saga mode (defined in its YAML)
child = await builder.create_workflow("InventoryAllocation", child_data)
# Child already has saga enabled from its definition
```

**Compensation Behavior**:

1. If child fails, child's saga runs first (compensates child steps)
2. Then parent's saga runs (compensates parent steps, including the sub-workflow spawn)

```
Parent: Reserve_Flight → Allocate_Inventory (child) → Charge_Payment
                              ↓
Child: Check_Stock → Reserve_Items → Update_Ledger (FAILS)

Compensation Order:
1. Child: Undo Update_Ledger (no-op, failed before execution)
2. Child: Undo Reserve_Items
3. Child: Undo Check_Stock
4. Parent: Compensate "Allocate_Inventory" step
5. Parent: Compensate "Reserve_Flight" step
```

**Best Practice**: Design child compensations to be independent of parent compensations.

## Querying Sub-Workflows

### Find All Child Workflows

```python
# List workflows by parent ID
children = await persistence.list_workflows(parent_workflow_id=parent_id)

for child in children:
    print(f"Child: {child['id']}, Type: {child['workflow_type']}, Status: {child['status']}")
```

### Find Workflows Waiting on Children

```python
# Find workflows blocked by child workflows
blocked_workflows = await persistence.list_workflows(
    status="PENDING_SUB_WORKFLOW"
)

# Or waiting for child human input
blocked_workflows = await persistence.list_workflows(
    status="WAITING_CHILD_HUMAN_INPUT"
)
```

### Workflow Hierarchy Visualization

```python
async def print_workflow_tree(workflow_id, persistence, indent=0):
    """Recursively print workflow and its children."""
    workflow = await persistence.load_workflow(workflow_id)

    print("  " * indent + f"└─ {workflow['workflow_type']} ({workflow['status']})")

    # Find children
    children = await persistence.list_workflows(parent_workflow_id=workflow_id)

    for child in children:
        await print_workflow_tree(child['id'], persistence, indent + 1)

# Usage
await print_workflow_tree(parent_id, persistence)

# Output:
# └─ OrderProcessing (PENDING_SUB_WORKFLOW)
#   └─ InventoryAllocation (ACTIVE)
#     └─ WarehouseSelection (COMPLETED)
```

## Performance Considerations

### Sub-Workflow Overhead

Each sub-workflow creates a new database record and workflow instance:

- **Database writes**: Create + N step executions + Complete = ~(N + 2) writes
- **Memory**: Each workflow instance ~5MB
- **Latency**: Sub-workflow spawn ~10-50ms

**Trade-off**: Modularity vs overhead.

**Guideline**:
- **Use sub-workflows**: For complex, reusable logic (10+ steps)
- **Don't use**: For trivial logic (1-2 steps, just inline it)

### Parallel Sub-Workflows

You can spawn multiple sub-workflows in parallel:

```yaml
- name: "Process_Items"
  type: "PARALLEL"
  tasks:
    - name: "allocate_inventory"
      function_path: "steps.spawn_inventory_workflow"

    - name: "calculate_pricing"
      function_path: "steps.spawn_pricing_workflow"

    - name: "check_fraud"
      function_path: "steps.spawn_fraud_workflow"
```

Each task spawns a sub-workflow:

```python
def spawn_inventory_workflow(state, context):
    raise StartSubWorkflowDirective(workflow_type="InventoryAllocation", ...)

def spawn_pricing_workflow(state, context):
    raise StartSubWorkflowDirective(workflow_type="PricingCalculation", ...)
```

**Result**: 3 sub-workflows executing in parallel!

## Common Patterns

### Pattern 1: Decompose by Domain

```
OrderProcessing (orchestrator)
├── InventoryAllocation (inventory domain)
├── PricingCalculation (pricing domain)
├── PaymentProcessing (payment domain)
└── ShippingArrangement (shipping domain)
```

Each child workflow is owned by a different team/service.

### Pattern 2: Reusable Workflows

```
InventoryAllocation (reused by):
├── OrderProcessing
├── ReturnProcessing
├── TransferProcessing
└── ReservationProcessing
```

One workflow definition, many parents.

### Pattern 3: User Task Workflows

```
LoanApproval (main workflow)
└── ManagerApprovalTask (sub-workflow)
    ├── Sends email to manager
    ├── Waits for approval (WAITING_HUMAN_INPUT)
    └── Returns decision
```

Child workflow encapsulates entire approval process.

## Best Practices

### 1. Design for Idempotency

Sub-workflow may be spawned multiple times (retries):

```python
def allocate_inventory(state, context):
    # Check if already allocated
    if state.inventory_allocated:
        return {"already_allocated": True}

    # Spawn sub-workflow
    raise StartSubWorkflowDirective(
        workflow_type="InventoryAllocation",
        initial_data={...}
    )
```

### 2. Pass Minimal Data

Don't pass entire parent state to child:

```python
# ❌ Bad: Passes entire state
raise StartSubWorkflowDirective(
    workflow_type="InventoryAllocation",
    initial_data=state.dict()  # 1MB of data!
)

# ✅ Good: Passes only what child needs
raise StartSubWorkflowDirective(
    workflow_type="InventoryAllocation",
    initial_data={
        "order_id": state.order_id,
        "items": state.items
    }  # <1KB
)
```

### 3. Document Parent-Child Contract

```python
class InventoryAllocationState(BaseModel):
    """
    State model for InventoryAllocation sub-workflow.

    **Required Input** (from parent):
    - order_id: str - Unique order identifier
    - items: list[dict] - Items to allocate

    **Output** (to parent):
    - allocated: bool - Whether allocation succeeded
    - warehouse_id: str - Warehouse where items allocated
    - items_reserved: list[dict] - Reserved items with quantities
    """
    order_id: str
    items: list[dict]
```

### 4. Handle Child Timeouts

Monitor long-running children:

```python
# Check if child is taking too long
workflow = await persistence.load_workflow(parent_id)

if workflow['status'] == 'PENDING_SUB_WORKFLOW':
    time_waiting = datetime.utcnow() - workflow['updated_at']

    if time_waiting > timedelta(hours=1):
        # Alert: Child workflow stuck
        alert_ops_team(f"Child workflow stuck for {time_waiting}")
```

## What's Next

Now that you understand sub-workflows:
- [Workflow Lifecycle](workflow-lifecycle.md) - Sub-workflow status states
- [Saga Pattern](saga-pattern.md) - Compensating sub-workflows
- [State Management](state-management.md) - How child results merge into parent state
