# Control Flow Directives Reference

## Overview

Directives are exceptions raised by step functions to control workflow execution flow.

**Module:** `rufus.models`

## WorkflowJumpDirective

Jump to a specific step by name.

### Definition

```python
class WorkflowJumpDirective(Exception):
    def __init__(
        self,
        target_step_name: str,
        result: Optional[dict] = None
    ):
        self.target_step_name = target_step_name
        self.result = result or {}
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target_step_name` | `str` | Yes | Name of step to jump to |
| `result` | `dict` | No | Result data to merge into state |

### Usage

```python
from rufus.models import WorkflowJumpDirective, StepContext
from pydantic import BaseModel

def decision_step(state: BaseModel, context: StepContext) -> dict:
    if state.amount > 10000:
        raise WorkflowJumpDirective(
            target_step_name="High_Value_Review",
            result={"flagged_for_review": True}
        )
    else:
        raise WorkflowJumpDirective(
            target_step_name="Standard_Processing",
            result={"auto_approved": True}
        )
```

### Behavior

1. Result dictionary merged into workflow state
2. Workflow jumps to target step (by name)
3. Step execution continues from target
4. Original step order preserved in audit log

### Notes

- Target step must exist in workflow definition
- Can jump forward or backward
- Use for conditional branching logic
- Prefer declarative routes in YAML for simple cases

---

## WorkflowPauseDirective

Pause workflow execution and wait for external input.

### Definition

```python
class WorkflowPauseDirective(Exception):
    def __init__(
        self,
        result: Optional[dict] = None,
        waiting_for: Optional[str] = None
    ):
        self.result = result or {}
        self.waiting_for = waiting_for
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `result` | `dict` | No | Result data to merge into state |
| `waiting_for` | `str` | No | Description of what workflow is waiting for |

### Usage

```python
from rufus.models import WorkflowPauseDirective, StepContext
from pydantic import BaseModel

def approval_step(state: BaseModel, context: StepContext) -> dict:
    # Request approval
    send_approval_request(state.manager_email, context.workflow_id)

    # Pause workflow
    raise WorkflowPauseDirective(
        result={"approval_requested_at": datetime.utcnow().isoformat()},
        waiting_for="manager_approval"
    )
```

### Resuming Paused Workflows

```python
# Via API or CLI
workflow = await builder.load_workflow(workflow_id)
result = await workflow.next_step(
    user_input={"approved": True, "manager_notes": "Looks good"}
)
```

### Behavior

1. Result dictionary merged into workflow state
2. Workflow status → `PAUSED` (or `WAITING_HUMAN_INPUT`)
3. No further steps execute until resume
4. Resume continues from next step with user_input

### Notes

- Use for human-in-the-loop workflows
- Common for approvals, manual reviews, data entry
- Workflow persisted while paused
- No timeout by default (implement externally if needed)

---

## StartSubWorkflowDirective

Launch a child workflow and wait for completion.

### Definition

```python
class StartSubWorkflowDirective(Exception):
    def __init__(
        self,
        workflow_type: str,
        initial_data: dict,
        owner_id: Optional[str] = None,
        data_region: Optional[str] = None
    ):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.owner_id = owner_id
        self.data_region = data_region
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workflow_type` | `str` | Yes | Child workflow type from registry |
| `initial_data` | `dict` | Yes | Initial state data for child |
| `owner_id` | `str` | No | Owner identifier (inherits from parent) |
| `data_region` | `str` | No | Data region (inherits from parent) |

### Usage

```python
from rufus.models import StartSubWorkflowDirective, StepContext
from pydantic import BaseModel

def launch_kyc(state: BaseModel, context: StepContext) -> dict:
    # Launch KYC verification as sub-workflow
    raise StartSubWorkflowDirective(
        workflow_type="KYC_Verification",
        initial_data={
            "user_id": state.user_id,
            "document_url": state.id_document_url,
            "verification_level": "standard"
        },
        data_region="eu-west-1"
    )
```

### Behavior

1. Child workflow created and started
2. Parent status → `PENDING_SUB_WORKFLOW`
3. Parent pauses until child completes
4. Child status changes bubble to parent:
   - Child paused → Parent status → `WAITING_CHILD_HUMAN_INPUT`
   - Child failed → Parent status → `FAILED_CHILD_WORKFLOW`
5. Child completes → Parent resumes automatically
6. Child results merged into parent state

### Accessing Child Results

```python
def process_kyc_results(state: BaseModel, context: StepContext) -> dict:
    # Access child workflow results
    child_results = state.sub_workflow_results

    # Iterate through children (keyed by workflow_id)
    for child_id, child_data in child_results.items():
        kyc_status = child_data['state']['status']
        kyc_score = child_data['final_result']['risk_score']

        if kyc_status == "APPROVED":
            state.kyc_approved = True
            state.risk_score = kyc_score

    return {"kyc_processing_complete": True}
```

### Notes

- Child workflow must be registered in workflow_registry.yaml
- Parent and child share persistence and execution providers
- Supports nested sub-workflows (grandchildren)
- Use for hierarchical workflow composition
- Child failures propagate to parent unless handled

---

## SagaWorkflowException

Signal workflow failure with automatic compensation.

### Definition

```python
class SagaWorkflowException(Exception):
    def __init__(
        self,
        message: str,
        original_exception: Optional[Exception] = None
    ):
        self.message = message
        self.original_exception = original_exception
        super().__init__(message)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | `str` | Yes | Error message |
| `original_exception` | `Exception` | No | Wrapped exception |

### Usage

```python
from rufus.models import SagaWorkflowException, StepContext
from pydantic import BaseModel

def charge_payment(state: BaseModel, context: StepContext) -> dict:
    try:
        transaction_id = payment_gateway.charge(
            amount=state.amount,
            customer_id=state.customer_id
        )

        state.transaction_id = transaction_id
        return {"transaction_id": transaction_id}

    except PaymentGatewayError as e:
        # Trigger Saga rollback
        raise SagaWorkflowException(
            message=f"Payment failed: {e.message}",
            original_exception=e
        )
```

### Compensation Function

```python
def refund_payment(state: BaseModel, context: StepContext) -> dict:
    """Compensation function - reverses charge_payment"""
    if state.transaction_id:
        payment_gateway.refund(state.transaction_id)
        return {"refunded": True}

    return {"refund_skipped": "no transaction"}
```

### YAML Configuration

```yaml
steps:
  - name: "Charge_Payment"
    type: "STANDARD"
    function: "my_app.steps.charge_payment"
    compensate_function: "my_app.steps.refund_payment"
```

### Behavior

1. Exception raised in step function
2. Workflow enters compensation mode (if Saga enabled)
3. Compensation functions execute in reverse order
4. Each compensation receives original step's state
5. Workflow status → `FAILED_ROLLED_BACK`
6. Original exception preserved in audit log

### Notes

- Requires `workflow.enable_saga_mode()` to be called
- Only steps with `compensate_function` are compensated
- Compensation failures logged but don't halt rollback
- Use for distributed transaction patterns
- Common in payment, inventory, multi-service workflows

---

## Comparison Table

| Directive | Purpose | Workflow Status | Resumes Automatically |
|-----------|---------|-----------------|----------------------|
| `WorkflowJumpDirective` | Conditional branching | Unchanged | Yes (immediately) |
| `WorkflowPauseDirective` | Wait for input | `PAUSED` | No (manual resume) |
| `StartSubWorkflowDirective` | Launch child workflow | `PENDING_SUB_WORKFLOW` | Yes (when child completes) |
| `SagaWorkflowException` | Trigger rollback | `FAILED_ROLLED_BACK` | No (workflow failed) |

## Related Types

- [Workflow](workflow.md)
- [StepContext](step-context.md)
- [Step Types](../configuration/step-types.md)

## See Also

- [Control Flow Guide](../../how-to-guides/control-flow.md)
- [Saga Pattern](../../how-to-guides/saga-pattern.md)
- [Sub-Workflows](../../how-to-guides/sub-workflows.md)
