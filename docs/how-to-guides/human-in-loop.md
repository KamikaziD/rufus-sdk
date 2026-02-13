# How to implement human-in-the-loop

This guide covers pausing workflows for human input and resuming with user decisions.

## Overview

Human-in-the-loop (HITL) workflows pause execution to wait for manual approval, data entry, or decisions. The workflow persists its state and can be resumed hours or days later.

## Basic pause and resume

### Pause workflow for approval

```python
from rufus.models import StepContext, WorkflowPauseDirective
from my_app.state_models import OrderState

def await_manager_approval(state: OrderState, context: StepContext) -> dict:
    """Pause workflow for manager approval."""

    # Prepare approval request
    approval_data = {
        "order_id": state.order_id,
        "amount": state.amount,
        "customer_id": state.customer_id,
        "awaiting_approval": True
    }

    # Pause workflow - raises exception to halt execution
    raise WorkflowPauseDirective(result=approval_data)
```

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
    function: "my_app.steps.await_manager_approval"
    # No automate_next - waits for manual resume

  - name: "Process_Approved_Order"
    type: "STANDARD"
    function: "my_app.steps.process_order"
    dependencies: ["Await_Manager_Approval"]
```

### Resume with approval

```python
from rufus.builder import WorkflowBuilder

# Load paused workflow
workflow = await builder.load_workflow(workflow_id)

# Check status
assert workflow.status == "WAITING_HUMAN_INPUT"

# Resume with approval decision
await workflow.next_step(user_input={
    "approved": True,
    "approved_by": "manager@company.com",
    "approval_notes": "Verified customer credentials"
})

# Workflow continues to next step
```

## Using CLI for resume

```bash
# List paused workflows
rufus list --status WAITING_HUMAN_INPUT

# Show workflow details
rufus show <workflow-id>

# Resume with approval
rufus resume <workflow-id> --input '{"approved": true, "approved_by": "manager@company.com"}'

# View updated status
rufus show <workflow-id>
```

## Handling approval decisions

Process user input in next step:

```python
def process_approved_order(state: OrderState, context: StepContext, **user_input) -> dict:
    """Process order after approval."""

    # Access approval decision from user_input
    approved = user_input.get("approved", False)
    approved_by = user_input.get("approved_by")

    if approved:
        state.status = "approved"
        state.approved_by = approved_by

        # Continue processing
        return {"approval_processed": True}
    else:
        # Rejection logic
        state.status = "rejected"
        state.rejection_reason = user_input.get("rejection_reason")

        raise Exception(f"Order rejected: {state.rejection_reason}")
```

## Multiple approval stages

Chain multiple human steps:

```yaml
steps:
  - name: "Analyst_Review"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.await_analyst_review"

  - name: "Manager_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.await_manager_approval"
    dependencies: ["Analyst_Review"]

  - name: "Director_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.await_director_approval"
    dependencies: ["Manager_Approval"]

  - name: "Execute_Transaction"
    type: "STANDARD"
    function: "my_app.steps.execute"
    dependencies: ["Director_Approval"]
```

## Conditional approval routing

Use DECISION steps after approval:

```yaml
steps:
  - name: "Await_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.await_approval"

  - name: "Check_Approval_Decision"
    type: "DECISION"
    function: "my_app.steps.check_decision"
    dependencies: ["Await_Approval"]
    routes:
      - condition: "state.approved == True"
        target: "Process_Order"
      - condition: "state.approved == False"
        target: "Send_Rejection_Email"
```

```python
def check_decision(state: OrderState, context: StepContext, **user_input) -> dict:
    """Process approval decision."""

    approved = user_input.get("approved", False)
    state.approved = approved

    if approved:
        state.approved_by = user_input.get("approved_by")
        state.approved_at = context.execution_time
    else:
        state.rejection_reason = user_input.get("rejection_reason")

    return {
        "decision_processed": True,
        "approved": approved
    }
```

## Form data collection

Pause to collect detailed input:

```python
def collect_kyc_documents(state: ApplicationState, context: StepContext) -> dict:
    """Pause to collect KYC documents from user."""

    # Prepare form data request
    form_request = {
        "required_documents": [
            "government_id",
            "proof_of_address",
            "income_verification"
        ],
        "upload_url": f"https://app.example.com/kyc/{state.application_id}"
    }

    raise WorkflowPauseDirective(result=form_request)
```

Resume with uploaded documents:

```python
await workflow.next_step(user_input={
    "documents_uploaded": True,
    "government_id_url": "s3://bucket/id.pdf",
    "proof_of_address_url": "s3://bucket/address.pdf",
    "income_verification_url": "s3://bucket/income.pdf"
})
```

## Timeout handling

Implement approval timeouts with scheduled checks:

```python
from datetime import datetime, timedelta

def await_approval_with_timeout(state: OrderState, context: StepContext) -> dict:
    """Pause with timeout tracking."""

    # Set timeout (24 hours from now)
    timeout_at = datetime.now() + timedelta(hours=24)
    state.approval_timeout_at = timeout_at.isoformat()

    raise WorkflowPauseDirective(result={
        "awaiting_approval": True,
        "timeout_at": timeout_at.isoformat()
    })
```

Check for expired approvals:

```python
# Scheduled job (run every hour)
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

async def check_expired_approvals():
    """Check for and handle expired approval requests."""

    persistence = PostgresPersistenceProvider(db_url)
    await persistence.initialize()

    # Find workflows waiting for input
    workflows = await persistence.list_workflows(
        status="WAITING_HUMAN_INPUT",
        limit=1000
    )

    now = datetime.now()

    for wf in workflows:
        timeout_at = wf['state'].get('approval_timeout_at')
        if timeout_at and datetime.fromisoformat(timeout_at) < now:
            # Timeout expired - auto-reject or escalate
            print(f"Approval timeout for workflow {wf['id']}")

            # Option 1: Auto-reject
            workflow = await builder.load_workflow(wf['id'])
            await workflow.next_step(user_input={
                "approved": False,
                "rejection_reason": "Approval timeout"
            })
```

## Notification integration

Send notifications when paused:

```python
def await_approval(state: OrderState, context: StepContext) -> dict:
    """Pause and send notification."""

    # Send email notification
    send_approval_email(
        to=state.manager_email,
        order_id=state.order_id,
        amount=state.amount,
        approval_link=f"https://app.example.com/approve/{context.workflow_id}"
    )

    # Send Slack notification
    send_slack_message(
        channel="#approvals",
        message=f"Order {state.order_id} awaiting approval: ${state.amount}"
    )

    raise WorkflowPauseDirective(result={
        "notification_sent": True,
        "notified_at": context.execution_time
    })
```

## Web UI integration

Build approval UI with REST API:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class ApprovalRequest(BaseModel):
    approved: bool
    approved_by: str
    notes: str = None

@app.get("/approvals/pending")
async def list_pending_approvals():
    """List all workflows awaiting approval."""

    workflows = await persistence.list_workflows(
        status="WAITING_HUMAN_INPUT"
    )

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
    """Approve a workflow."""

    try:
        workflow = await builder.load_workflow(workflow_id)

        if workflow.status != "WAITING_HUMAN_INPUT":
            raise HTTPException(400, "Workflow not awaiting approval")

        # Resume with approval
        await workflow.next_step(user_input={
            "approved": request.approved,
            "approved_by": request.approved_by,
            "approval_notes": request.notes
        })

        return {
            "status": "approved",
            "workflow_id": workflow_id
        }

    except Exception as e:
        raise HTTPException(500, str(e))
```

## State persistence during pause

Workflow state is automatically persisted:

```python
# Before pause
state.order_id = "ORD-001"
state.amount = 1500.00
state.customer_id = "CUST-123"

# Pause (state saved to database)
raise WorkflowPauseDirective(result={"awaiting_approval": True})

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
    """Test workflow with approval step."""

    harness = TestHarness()

    # Start workflow
    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "amount": 1500.00
        }
    )

    # Execute until approval
    await harness.next_step(workflow.id)

    # Should be paused
    assert workflow.status == "WAITING_HUMAN_INPUT"

    # Simulate approval
    await harness.next_step(workflow.id, user_input={
        "approved": True,
        "approved_by": "test@example.com"
    })

    # Should continue processing
    assert workflow.status == "ACTIVE"
    assert workflow.state.approved == True

@pytest.mark.asyncio
async def test_rejection_workflow():
    """Test workflow rejection."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-002"}
    )

    await harness.next_step(workflow.id)

    # Reject
    await harness.next_step(workflow.id, user_input={
        "approved": False,
        "rejection_reason": "Invalid customer"
    })

    # Should fail or route to rejection handler
    assert workflow.state.approved == False
```

## Common patterns

### Multi-level approval

```python
def await_tiered_approval(state: LoanState, context: StepContext) -> dict:
    """Determine approval tier based on amount."""

    if state.amount < 10000:
        state.approval_tier = "analyst"
    elif state.amount < 100000:
        state.approval_tier = "manager"
    else:
        state.approval_tier = "director"

    raise WorkflowPauseDirective(result={
        "approval_tier": state.approval_tier,
        "amount": state.amount
    })
```

### Comment collection

```python
def collect_review_comments(state: ReviewState, context: StepContext) -> dict:
    """Pause to collect review comments."""

    raise WorkflowPauseDirective(result={
        "requesting_comments": True,
        "review_url": f"https://app.example.com/review/{state.review_id}"
    })

# Resume with comments
await workflow.next_step(user_input={
    "comments": "Looks good, approved",
    "rating": 5
})
```

### Batch approval

```python
# Approve multiple workflows at once
workflow_ids = ["wf-1", "wf-2", "wf-3"]

for workflow_id in workflow_ids:
    workflow = await builder.load_workflow(workflow_id)
    await workflow.next_step(user_input={
        "approved": True,
        "approved_by": "batch-approver@example.com"
    })
```

## Best practices

1. **Set clear expectations** - Include timeout information in pause data
2. **Send notifications** - Alert users when approval is needed
3. **Track approval metadata** - Store who approved and when
4. **Handle rejections** - Plan for both approval and rejection paths
5. **Implement timeouts** - Don't let workflows pause indefinitely
6. **Log approvals** - Audit trail for compliance
7. **Test both paths** - Test approval and rejection scenarios
8. **Validate input** - Check user input for required fields

## Next steps

- [Add decision steps](decision-steps.md)
- [Implement saga mode](saga-mode.md)
- [Deploy to production](deployment.md)

## See also

- [Create workflow guide](create-workflow.md)
- [Testing guide](testing.md)
- USAGE_GUIDE.md section 8.3 for HUMAN_IN_LOOP steps
- CLAUDE.md "Control Flow Mechanisms" section
