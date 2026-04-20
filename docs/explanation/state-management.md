# State Management

Workflow state is the heart of Ruvon—it's the data that flows through your workflow, persists across steps, and survives restarts. Understanding how state works is crucial to building reliable workflows.

## What is Workflow State?

Workflow state is a Pydantic model that represents all the data your workflow needs to make decisions and track progress:

```python
from pydantic import BaseModel
from typing import Optional

class OrderState(BaseModel):
    order_id: str
    customer_id: str
    items: list[dict]
    total_amount: float
    payment_status: Optional[str] = None
    shipping_address: Optional[dict] = None
    tracking_number: Optional[str] = None
```

This model is:
- **Defined once** in Python code
- **Referenced** in workflow YAML
- **Instantiated** when workflow is created
- **Mutated** by step functions
- **Persisted** after every step
- **Validated** by Pydantic on every change

## State Lifecycle

### 1. Initialization

State is created when the workflow is instantiated:

```python
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={
        "order_id": "ORD-12345",
        "customer_id": "CUST-789",
        "items": [{"sku": "WIDGET-1", "qty": 2}],
        "total_amount": 99.99
    }
)
```

Ruvon:
1. Loads the state model from `initial_state_model` in YAML
2. Validates `initial_data` against the model
3. Creates state instance: `state = OrderState(**initial_data)`
4. Serializes to JSON and saves to database

### 2. Step Execution

Each step function receives state and can modify it:

```python
def process_payment(state: OrderState, context: StepContext) -> dict:
    # Read state
    amount = state.total_amount
    customer = state.customer_id

    # Process payment
    transaction_id = charge_customer(customer, amount)

    # Return changes (merged into state)
    return {
        "payment_status": "charged",
        "transaction_id": transaction_id
    }
```

After step executes:
1. Ruvon merges return value into state: `state.payment_status = "charged"`
2. Pydantic validates the updated state
3. State is serialized to JSON
4. Persisted to database

### 3. Persistence

State is saved after every step:

```python
# PostgreSQL: Stored as JSONB
UPDATE workflow_executions
SET state = '{"order_id": "ORD-12345", "payment_status": "charged", ...}'::jsonb,
    updated_at = NOW()
WHERE id = '550e8400-e29b-41d4-a716-446655440000';

# SQLite: Stored as TEXT
UPDATE workflow_executions
SET state = '{"order_id": "ORD-12345", "payment_status": "charged", ...}',
    updated_at = datetime('now')
WHERE id = '550e8400-e29b-41d4-a716-446655440000';
```

**Performance**: Ruvon uses `orjson` for 3-5x faster serialization compared to stdlib `json`.

### 4. Loading

When workflow is resumed (after pause, async task, or restart):

```python
# Load from database
workflow_dict = await persistence.load_workflow(workflow_id)

# Deserialize state
state_class = import_from_string(workflow_dict['state_model'])
state = state_class(**workflow_dict['state'])

# Validate
assert isinstance(state, BaseModel)
```

State is reconstructed exactly as it was saved.

## State Mutation Patterns

### Pattern 1: Direct Mutation

Step function modifies state object directly:

```python
def update_address(state: OrderState, context: StepContext, **user_input) -> dict:
    # Direct mutation
    state.shipping_address = user_input['address']

    # No return value needed
    return {}
```

**When to use**: Simple field updates, no complex logic.

### Pattern 2: Return Dict (Recommended)

Step function returns a dict of changes:

```python
def calculate_shipping(state: OrderState, context: StepContext) -> dict:
    # Calculate based on current state
    cost = calculate_cost(state.shipping_address, state.items)

    # Return changes
    return {
        "shipping_cost": cost,
        "total_amount": state.total_amount + cost
    }
```

Ruvon merges the dict into state: `state.shipping_cost = cost`.

**When to use**: Preferred pattern—explicit, testable, functional style.

### Pattern 3: Hybrid

Combine both approaches:

```python
def process_order(state: OrderState, context: StepContext) -> dict:
    # Direct mutation
    state.status = "processing"

    # Return additional data
    return {
        "processed_at": datetime.utcnow().isoformat(),
        "processor_id": context.workflow_id
    }
```

**When to use**: Complex state updates with both simple and computed fields.

## State Merging

When a step returns a dict, Ruvon merges it into the state model:

```python
# Step returns
return {"payment_status": "charged", "transaction_id": "TXN-123"}

# Ruvon merges
for key, value in result.items():
    setattr(state, key, value)

# Equivalent to
state.payment_status = "charged"
state.transaction_id = "TXN-123"
```

**Merge Behavior**:
- **Shallow merge**: Top-level keys overwrite
- **No deep merge**: Nested dicts replace entirely

```python
# State before
state.metadata = {"created_by": "user1", "version": 1}

# Step returns
return {"metadata": {"updated_by": "user2"}}

# State after
state.metadata = {"updated_by": "user2"}  # created_by and version lost!
```

**Best Practice**: Use explicit fields instead of nested dicts:

```python
class OrderState(BaseModel):
    created_by: str
    updated_by: Optional[str] = None
    version: int = 1

# Now updates are explicit
return {"updated_by": "user2"}  # created_by and version preserved
```

## State Validation

Pydantic validates state on every mutation:

```python
class OrderState(BaseModel):
    order_id: str
    total_amount: float
    items: list[dict]

    @validator('total_amount')
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('total_amount must be positive')
        return v

# This will fail validation
return {"total_amount": -10.00}
# Raises: pydantic.ValidationError: total_amount must be positive
```

**When validation happens**:
- On workflow creation (initial_data)
- After every step execution (result merge)
- On manual state updates

**Why validate**: Catch data errors early, enforce business rules, prevent corruption.

## State Immutability Considerations

Workflow state is **mutable** within a step, but **versioned** across steps:

```python
def step_a(state: OrderState, context: StepContext):
    state.items.append({"sku": "EXTRA-1", "qty": 1})  # Mutates list
    return {}

def step_b(state: OrderState, context: StepContext):
    # Sees the mutation from step_a
    assert len(state.items) == 2
```

**Important**: Mutations are **not atomic**. If a step fails mid-execution, partial mutations may be saved.

**Best Practice**: Use return dicts for atomicity:

```python
def step_a(state: OrderState, context: StepContext):
    # Copy, modify, return
    new_items = state.items.copy()
    new_items.append({"sku": "EXTRA-1", "qty": 1})
    return {"items": new_items}
```

## State Context

Step functions receive a `StepContext` object with metadata:

```python
@dataclass
class StepContext:
    workflow_id: UUID
    step_name: str
    previous_step_result: Optional[Dict]
    loop_state: Optional[LoopState]
    parent_workflow_id: Optional[UUID]
```

**Why separate from state**: Context is transient (not persisted), state is durable.

```python
def my_step(state: OrderState, context: StepContext):
    # Access durable state
    order_id = state.order_id

    # Access transient context
    workflow_id = context.workflow_id
    previous_result = context.previous_step_result

    # Only state changes persist
    return {"processed": True}
```

## State Serialization

### JSON Serialization

Pydantic models serialize to JSON automatically:

```python
# Pydantic model
state = OrderState(order_id="ORD-123", total_amount=99.99)

# Serialize (using orjson for performance)
from ruvon.utils.serialization import serialize
json_str = serialize(state.dict())
# '{"order_id":"ORD-123","total_amount":99.99,...}'
```

**Custom Types**: Pydantic handles most types (datetime, UUID, Enum), but complex types need custom serializers:

```python
from pydantic import BaseModel, validator
from decimal import Decimal

class OrderState(BaseModel):
    amount: Decimal

    class Config:
        json_encoders = {
            Decimal: lambda v: str(v)  # Serialize Decimal as string
        }
```

### Database Storage

State is stored differently by backend:

**PostgreSQL**:
```sql
CREATE TABLE workflow_executions (
    id UUID PRIMARY KEY,
    state JSONB NOT NULL,  -- Native JSON type, queryable
    ...
);

-- Can query inside state
SELECT * FROM workflow_executions
WHERE state->>'payment_status' = 'charged';
```

**SQLite**:
```sql
CREATE TABLE workflow_executions (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,  -- JSON as TEXT
    ...
);

-- JSON queries require json_extract
SELECT * FROM workflow_executions
WHERE json_extract(state, '$.payment_status') = 'charged';
```

**In-Memory** (testing):
```python
# Python dict
self._workflows[workflow_id] = {
    'id': workflow_id,
    'state': state.dict(),  # Already deserialized
    ...
}
```

## State Access Patterns

### Pattern 1: Read-Only Access

Step only reads state, doesn't modify:

```python
def check_eligibility(state: OrderState, context: StepContext) -> dict:
    # Read state
    is_eligible = state.total_amount > 100 and state.customer_id.startswith("VIP")

    # Return decision (doesn't modify state)
    if is_eligible:
        raise WorkflowJumpDirective(target_step_name="VIP_Processing")
    else:
        raise WorkflowJumpDirective(target_step_name="Standard_Processing")
```

**When to use**: Decision steps, validation steps.

### Pattern 2: Incremental Updates

Step builds on previous step's output:

```python
def calculate_tax(state: OrderState, context: StepContext) -> dict:
    # Use previous step's result
    subtotal = context.previous_step_result.get('subtotal', state.total_amount)

    # Calculate tax
    tax = subtotal * 0.08

    # Return cumulative total
    return {
        "tax_amount": tax,
        "total_amount": subtotal + tax
    }
```

**When to use**: Multi-step calculations, aggregations.

### Pattern 3: Conditional Initialization

Step initializes fields if not already set:

```python
def initialize_defaults(state: OrderState, context: StepContext) -> dict:
    result = {}

    if not state.shipping_method:
        result["shipping_method"] = "standard"

    if not state.currency:
        result["currency"] = "USD"

    return result
```

**When to use**: Default value initialization, backward compatibility.

## State Debugging

### Inspecting State

```python
# Via CLI
ruvon show <workflow-id> --state

# Via API
GET /api/v1/workflows/<workflow-id>
{
  "id": "550e8400-...",
  "state": {
    "order_id": "ORD-123",
    "payment_status": "charged",
    ...
  }
}

# Programmatically
workflow_dict = await persistence.load_workflow(workflow_id)
print(workflow_dict['state'])
```

### State Evolution Over Time

Audit log tracks state changes:

```sql
SELECT step_name, event_data->'result' AS step_output, created_at
FROM workflow_audit_log
WHERE workflow_id = '550e8400-...'
ORDER BY created_at ASC;
```

Shows how state evolved step-by-step.

### State Validation Errors

If a step returns invalid data:

```python
return {"total_amount": "invalid"}  # Should be float

# Raises ValidationError
# Workflow transitions to FAILED
# Error logged to audit log
```

**Debugging**: Check audit log for validation errors.

## State Versioning

When workflow definitions change, running workflows use their **definition snapshot**:

```python
# Workflow created with v1 definition
workflow = create_workflow("OrderProcessing", data)
# workflow.definition_snapshot contains v1 YAML

# Developer deploys v2 definition (removes "loyalty_points" field)

# Existing workflow resumes
workflow_dict = await persistence.load_workflow(workflow_id)
# Uses v1 snapshot - "loyalty_points" still exists in state model
```

**Why**: Prevents breaking changes from affecting running workflows.

## State Size Limits

**PostgreSQL**: JSONB column has ~1GB theoretical limit, practical limit ~1MB
**SQLite**: TEXT column has no hard limit, but >1MB impacts performance
**Redis**: String type limited by `maxmemory` setting

**Best Practices**:
- Keep state small (<100KB typical, <1MB max)
- Store large blobs (files, images) in object storage (S3)
- Reference large data by ID, not embedding

```python
# ❌ Bad: Embed large data
state.csv_data = "..." # 10MB CSV

# ✅ Good: Reference by ID
state.csv_file_id = "s3://bucket/file.csv"
```

## What's Next

Now that you understand state management:
- [Workflow Lifecycle](workflow-lifecycle.md) - How state transitions through lifecycle
- [Parallel Execution](parallel-execution.md) - Merging state from parallel tasks
- [Sub-Workflows](sub-workflows.md) - Passing state to child workflows
