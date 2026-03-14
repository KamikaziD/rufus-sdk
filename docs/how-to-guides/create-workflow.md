# How to create a workflow

This guide walks through creating a workflow from scratch.

## Overview

A Rufus workflow consists of three parts:

1. **State model** - Pydantic model defining workflow data
2. **Step functions** - Python functions implementing business logic
3. **Workflow YAML** - Declarative configuration linking everything together

## Step 1: Define state model

Create a Pydantic model for your workflow's state:

```python
# my_workflow/state_models.py
from pydantic import BaseModel, Field
from typing import Optional

class OrderState(BaseModel):
    """State for order processing workflow."""

    # Required fields
    order_id: str
    customer_id: str
    amount: float

    # Optional fields (populated during execution)
    status: Optional[str] = None
    payment_id: Optional[str] = None
    shipping_id: Optional[str] = None
    error_message: Optional[str] = None
```

**Key points:**
- Use Pydantic for automatic validation
- Mark optional fields with `Optional[...]` and default values
- State is automatically serialized to database
- All fields must be JSON-serializable

## Step 2: Implement step functions

Create Python functions for each workflow step:

```python
# my_workflow/steps.py
from rufus.models import StepContext
from .state_models import OrderState

def validate_order(state: OrderState, context: StepContext) -> dict:
    """Validate order details."""

    # Access workflow state
    if state.amount <= 0:
        raise ValueError("Order amount must be positive")

    if state.amount > 10000:
        state.status = "requires_approval"
    else:
        state.status = "validated"

    # Return dict to update state
    from datetime import datetime
    return {
        "status": state.status,
        "validated_at": datetime.utcnow().isoformat()
    }

def process_payment(state: OrderState, context: StepContext) -> dict:
    """Process payment for order."""

    # Simulate payment processing
    payment_id = f"PAY-{state.order_id}"
    state.payment_id = payment_id

    return {
        "payment_id": payment_id,
        "payment_status": "completed"
    }

def ship_order(state: OrderState, context: StepContext) -> dict:
    """Arrange order shipping."""

    shipping_id = f"SHIP-{state.order_id}"
    state.shipping_id = shipping_id

    return {
        "shipping_id": shipping_id,
        "status": "shipped"
    }
```

**Step function signature:**

```python
def step_name(state: YourStateModel, context: StepContext, **user_input) -> dict:
    """
    Args:
        state: Workflow state (Pydantic model) - modify directly
        context: StepContext with workflow_id, step_name, etc.
        **user_input: Additional inputs from resume/next_step calls

    Returns:
        dict: Data to merge into workflow state
    """
    pass
```

**Available in context:**
- `context.workflow_id` - Workflow UUID
- `context.step_name` - Current step name
- `context.previous_step_result` - Result from previous step
- `context.loop_item` - Current item in a LOOP step iteration
- `context.loop_index` - Current index in a LOOP step iteration

## Step 3: Create workflow YAML

Define workflow structure declaratively:

```yaml
# my_workflow/order_processing.yaml
workflow_type: "OrderProcessing"
workflow_version: "1.0.0"
initial_state_model: "my_workflow.state_models.OrderState"
description: "Process customer orders"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "my_workflow.steps.validate_order"
    automate_next: true

  - name: "Process_Payment"
    type: "STANDARD"
    function: "my_workflow.steps.process_payment"
    dependencies: ["Validate_Order"]
    automate_next: true

  - name: "Ship_Order"
    type: "STANDARD"
    function: "my_workflow.steps.ship_order"
    dependencies: ["Process_Payment"]
```

**Key YAML fields:**

- `workflow_type` - Unique identifier for this workflow
- `workflow_version` - Optional version string
- `initial_state_model` - Python path to state Pydantic model
- `description` - Human-readable description
- `steps` - List of step definitions

**Step configuration:**

- `name` - Unique step identifier (use PascalCase with underscores)
- `type` - Step type (STANDARD, ASYNC, DECISION, PARALLEL, etc.)
- `function` - Python path to step function
- `automate_next` - Auto-execute next step after completion
- `dependencies` - List of prerequisite step names

## Step 4: Register workflow

Add your workflow to the registry:

```yaml
# config/workflow_registry.yaml
workflows:
  - type: "OrderProcessing"
    description: "Process customer orders"
    config_file: "order_processing.yaml"
    initial_state_model: "my_workflow.state_models.OrderState"
```

## Step 5: Execute workflow

Create and run your workflow:

```python
# my_workflow/run.py
import asyncio
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

async def main():
    # Initialize providers
    persistence = SQLitePersistenceProvider(db_path=":memory:")
    await persistence.initialize()

    execution = SyncExecutor()
    observer = LoggingObserver()

    # Create builder (providers are NOT constructor args — passed per-workflow below)
    workflow_registry = {
        "OrderProcessing": {
            "config_file": "order_processing.yaml",
            "initial_state_model_path": "my_workflow.state_models.OrderState",
        }
    }
    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        config_dir="my_workflow/",
    )

    # Start workflow
    workflow = await builder.create_workflow(
        workflow_type="OrderProcessing",
        persistence_provider=persistence,
        execution_provider=execution,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        initial_data={
            "order_id": "ORD-001",
            "customer_id": "CUST-123",
            "amount": 99.99
        }
    )

    print(f"Workflow created: {workflow.id}")
    print(f"Initial status: {workflow.status}")

    # Execute steps (automate_next handles progression)
    await workflow.next_step()

    print(f"Final status: {workflow.status}")
    print(f"Final state: {workflow.state}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Step 6: Test your workflow

```bash
python my_workflow/run.py
```

Expected output:

```
Workflow created: a1b2c3d4-...
Initial status: ACTIVE
[INFO] Executing step: Validate_Order
[INFO] Executing step: Process_Payment
[INFO] Executing step: Ship_Order
Final status: COMPLETED
Final state: OrderState(
    order_id='ORD-001',
    customer_id='CUST-123',
    amount=99.99,
    status='shipped',
    payment_id='PAY-ORD-001',
    shipping_id='SHIP-ORD-001',
    error_message=None
)
```

## Common patterns

### Conditional branching

Use DECISION steps for conditional logic:

```yaml
- name: "Check_Amount"
  type: "DECISION"
  function: "my_workflow.steps.check_amount"
  routes:
    - condition: "state.amount > 10000"
      target: "Manual_Approval"
    - condition: "state.amount <= 10000"
      target: "Auto_Approve"
```

```python
def check_amount(state: OrderState, context: StepContext) -> dict:
    """Check order amount for approval routing."""
    return {"amount_checked": True}
```

### Error handling

Handle errors gracefully in step functions:

```python
def process_payment(state: OrderState, context: StepContext) -> dict:
    """Process payment with error handling."""

    try:
        # Payment processing logic
        payment_id = charge_payment(state.amount)
        return {"payment_id": payment_id}

    except PaymentException as e:
        # Update state with error
        state.error_message = str(e)
        raise  # Re-raise to mark workflow as FAILED
```

### Data validation

Use Pydantic validation in state models:

```python
from pydantic import BaseModel, Field, field_validator

class OrderState(BaseModel):
    order_id: str
    amount: float = Field(gt=0, description="Order amount (must be positive)")

    @field_validator('order_id')
    @classmethod
    def validate_order_id(cls, v):
        if not v.startswith('ORD-'):
            raise ValueError('Order ID must start with ORD-')
        return v
```

## Project structure

Organize your workflow code:

```
my_workflow/
├── __init__.py
├── state_models.py       # Pydantic state models
├── steps.py              # Step function implementations
├── order_processing.yaml # Workflow definition
└── run.py                # Execution script
```

Or for larger projects:

```
my_app/
├── workflows/
│   ├── order_processing/
│   │   ├── state_models.py
│   │   ├── steps.py
│   │   └── workflow.yaml
│   └── user_onboarding/
│       ├── state_models.py
│       ├── steps.py
│       └── workflow.yaml
├── config/
│   └── workflow_registry.yaml
└── run_workflows.py
```

## Next steps

- [Add decision steps](decision-steps.md)
- [Implement parallel execution](http-steps.md)
- [Add human-in-the-loop](human-in-loop.md)
- [Enable saga mode](saga-mode.md)

## See also

- [Configuration guide](configuration.md)
- [Testing guide](testing.md)
- USAGE_GUIDE.md for complete workflow patterns
- YAML_GUIDE.md for YAML reference
