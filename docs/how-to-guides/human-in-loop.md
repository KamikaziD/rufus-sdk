# How to implement human-in-the-loop

This guide covers pausing workflows for human input and resuming with user decisions.

## Overview

Human-in-the-loop (HITL) workflows pause execution to wait for manual approval, data entry, or decisions. The workflow persists its state and can be resumed hours or days later.

## Self-contained HITL step (recommended)

The `HUMAN_IN_LOOP` step type is self-contained. On first call it auto-pauses and exposes its
`input_model` schema to the API. On resume it calls the step function with `**user_input` and
advances automatically.

### Define in YAML

```yaml
workflow_type: "OrderProcessing"
initial_state_model: "my_app.state_models.OrderState"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "my_app.steps.validate_order"
    automate_next: true

  - name: "Await_Manager_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.process_approval"
    input_model: "my_app.models.ApprovalInput"  # validated on resume; schema exposed to API

  - name: "Process_Approved_Order"
    type: "STANDARD"
    function: "my_app.steps.process_order"
```

### Implement the step function

```python
from rufus.models import StepContext, WorkflowJumpDirective
from my_app.state_models import OrderState

# Works for decisions (approval/rejection routing):
def process_approval(state: OrderState, context: StepContext, **user_input) -> dict:
    if not user_input.get("approved"):
        raise WorkflowJumpDirective("Send_Rejection_Email")
    return {"approved_by": user_input["reviewer"]}

# Works for pure data collection (no routing needed):
def collect_customer_info(state: OrderState, context: StepContext, **user_input) -> dict:
    return {"customer_name": user_input["name"], "email": user_input["email"]}
```

`func` is optional — if omitted, `user_input` is merged directly into state on resume.

### Resume with approval

```python
# Load paused workflow
workflow = await builder.load_workflow(workflow_id)

# Check status
assert workflow.status == "WAITING_HUMAN"

# Resume with approval decision
await workflow.next_step(user_input={
    "approved": True,
    "reviewer": "manager@company.com",
    "approval_notes": "Verified customer credentials"
})

# Workflow continues to next step
```

## Using CLI for resume

```bash
# List paused workflows
rufus list --status WAITING_HUMAN

# Show workflow details
rufus show <workflow-id>

# Resume with approval
rufus resume <workflow-id> --input '{"approved": true, "reviewer": "manager@company.com"}'

# View updated status
rufus show <workflow-id>
```

## Input validation with input_model

Define a Pydantic model for the expected user input and reference it via `input_model`:

```python
from pydantic import BaseModel

class ApprovalInput(BaseModel):
    approved: bool
    reviewer: str
    approval_notes: str = ""
```

```yaml
- name: "Await_Approval"
  type: "HUMAN_IN_LOOP"
  function: "my_app.steps.process_approval"
  input_model: "my_app.models.ApprovalInput"
```

The schema is exposed via `GET /api/v1/workflow/{id}/current_step_info` when the workflow is
`WAITING_HUMAN`. Invalid input raises a `ValueError` with field-level errors.

## Multiple approval stages

Chain multiple HITL steps:

```yaml
steps:
  - name: "Analyst_Review"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.process_analyst_review"

  - name: "Manager_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.process_manager_approval"

  - name: "Director_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.process_director_approval"

  - name: "Execute_Transaction"
    type: "STANDARD"
    function: "my_app.steps.execute"
```

## Conditional approval routing

Use `WorkflowJumpDirective` inside the HITL step function for branching:

```yaml
steps:
  - name: "Await_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.process_approval_with_routing"

  - name: "Process_Order"
    type: "STANDARD"
    function: "my_app.steps.process_order"

  - name: "Send_Rejection_Email"
    type: "STANDARD"
    function: "my_app.steps.send_rejection"
```

```python
def process_approval_with_routing(state: OrderState, context: StepContext, **user_input) -> dict:
    approved = user_input.get("approved", False)
    state.approved = approved

    if not approved:
        state.rejection_reason = user_input.get("rejection_reason")
        raise WorkflowJumpDirective("Send_Rejection_Email")

    state.approved_by = user_input.get("reviewer")
    return {"decision_processed": True, "approved": approved}
```

## Funcless HITL (pure data collection)

When `function` is omitted, `user_input` is merged directly into the workflow state:

```yaml
- name: "Collect_Customer_Info"
  type: "HUMAN_IN_LOOP"
  input_model: "my_app.models.CustomerInfoInput"
  # No function key — user_input is merged into state automatically
```

## Timeout handling

Implement approval timeouts with scheduled checks:

```python
from datetime import datetime, timedelta

def await_approval_with_timeout(state: OrderState, context: StepContext, **user_input) -> dict:
    approved = user_input.get("approved", False)
    state.approved = approved

    if not approved:
        raise WorkflowJumpDirective("Handle_Rejection")

    state.approved_by = user_input.get("reviewer")
    state.approved_at = datetime.now().isoformat()
    return {"approved": True}
```

Check for expired approvals:

```python
# Scheduled job (run every hour)
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

async def check_expired_approvals():
    persistence = PostgresPersistenceProvider(db_url)
    await persistence.initialize()

    # Find workflows waiting for input
    workflows = await persistence.list_workflows(
        status="WAITING_HUMAN",
        limit=1000
    )

    now = datetime.now()

    for wf in workflows:
        timeout_at = wf['state'].get('approval_timeout_at')
        if timeout_at and datetime.fromisoformat(timeout_at) < now:
            workflow = await builder.load_workflow(wf['id'])
            await workflow.next_step(user_input={
                "approved": False,
                "rejection_reason": "Approval timeout"
            })
```

## Notification integration

Send notifications when the step auto-pauses by using a STANDARD step before the HITL step:

```python
def send_approval_notification(state: OrderState, context: StepContext) -> dict:
    send_email(
        to=state.manager_email,
        subject=f"Order {state.order_id} awaiting approval",
        approval_link=f"https://app.example.com/approve/{context.workflow_id}"
    )
    send_slack_message(
        channel="#approvals",
        message=f"Order {state.order_id} awaiting approval: ${state.amount}"
    )
    return {"notification_sent": True}
```

```yaml
steps:
  - name: "Send_Notification"
    type: "STANDARD"
    function: "my_app.steps.send_approval_notification"
    automate_next: true

  - name: "Await_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.process_approval"
```

## Web UI integration

Build approval UI with REST API:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class ApprovalRequest(BaseModel):
    approved: bool
    reviewer: str
    notes: str = ""

@app.get("/approvals/pending")
async def list_pending_approvals():
    workflows = await persistence.list_workflows(status="WAITING_HUMAN")
    return {
        "pending_approvals": [
            {
                "workflow_id": str(wf['id']),
                "order_id": wf['state']['order_id'],
                "amount": wf['state']['amount'],
                "created_at": wf['created_at']
            }
            for wf in workflows
        ]
    }

@app.post("/approvals/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, request: ApprovalRequest):
    try:
        workflow = await builder.load_workflow(workflow_id)

        if workflow.status != "WAITING_HUMAN":
            raise HTTPException(400, "Workflow not awaiting approval")

        await workflow.next_step(user_input={
            "approved": request.approved,
            "reviewer": request.reviewer,
            "approval_notes": request.notes
        })

        return {"status": "approved", "workflow_id": workflow_id}

    except Exception as e:
        raise HTTPException(500, str(e))
```

## State persistence during pause

Workflow state is automatically persisted:

```python
# Before pause (first call auto-pauses; state is already correct)
state.order_id = "ORD-001"
state.amount = 1500.00

# ... minutes, hours, or days later ...

# Resume (state loaded from database)
workflow = await builder.load_workflow(workflow_id)
assert workflow.state.order_id == "ORD-001"
assert workflow.state.amount == 1500.00
```

## Testing human-in-the-loop

```python
import pytest
from rufus.testing.harness import TestHarness

@pytest.mark.asyncio
async def test_approval_workflow():
    harness = TestHarness()

    # Start workflow
    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-001", "amount": 1500.00}
    )

    # Execute until HITL step auto-pauses
    try:
        await harness.next_step(workflow.id, user_input={})
    except WorkflowPauseDirective:
        pass

    # Should be paused
    assert workflow.status == "WAITING_HUMAN"

    # Simulate approval
    await harness.next_step(workflow.id, user_input={
        "approved": True,
        "reviewer": "test@example.com"
    })

    # Should continue processing
    assert workflow.status in ("ACTIVE", "COMPLETED")
    assert workflow.state.approved_by == "test@example.com"

@pytest.mark.asyncio
async def test_rejection_workflow():
    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-002"}
    )

    try:
        await harness.next_step(workflow.id, user_input={})
    except WorkflowPauseDirective:
        pass

    # Reject
    await harness.next_step(workflow.id, user_input={
        "approved": False,
        "rejection_reason": "Invalid customer"
    })

    assert workflow.state.approved == False
```

## Legacy migration note

Before v0.6.1, HITL required a 2-step pattern: a STANDARD step that raised
`WorkflowPauseDirective`, plus a separate STANDARD step that received `user_input` on resume.
This pattern still works (backward compatible) but the self-contained `HUMAN_IN_LOOP` type is
simpler and preferred for all new workflows.

Old pattern (still supported):
```yaml
- name: "Pause_For_Approval"   # STANDARD step raises WorkflowPauseDirective
  type: "STANDARD"
  function: "my_app.steps.pause_step"

- name: "Process_After_Approval"  # Next STANDARD step receives user_input via context
  type: "STANDARD"
  function: "my_app.steps.process_step"
  input_model: "my_app.models.ApprovalInput"
```

## Best practices

1. **Set clear input_model** — Validates input and powers auto-generated UI forms
2. **Send notifications** — Use a STANDARD step before the HITL step for notifications
3. **Track approval metadata** — Return approved_by/approved_at from the step function
4. **Handle rejections** — Raise `WorkflowJumpDirective` to route to a rejection step
5. **Implement timeouts** — Poll `WAITING_HUMAN` workflows and auto-reject expired ones
6. **Log approvals** — The step execution is automatically audit-logged
7. **Test both paths** — Test approval and rejection scenarios in unit tests
8. **Validate input** — Use `input_model` for required-field enforcement

## Next steps

- [Add decision steps](decision-steps.md)
- [Implement saga mode](saga-mode.md)
- [Deploy to production](deployment.md)

## See also

- [Create workflow guide](create-workflow.md)
- [Testing guide](testing.md)
- CLAUDE.md "Control Flow Mechanisms" section
