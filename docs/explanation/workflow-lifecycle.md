# Workflow Lifecycle

A workflow in Ruvon goes through a series of states from creation to completion. Understanding this lifecycle helps you predict behavior, debug issues, and design robust workflows.

## Lifecycle States

Every workflow exists in one of these states:

```
PENDING_ASYNC → WAITING_HUMAN_INPUT → PENDING_SUB_WORKFLOW
     ↓                 ↓                      ↓
   ACTIVE ←────────────┴──────────────────────┘
     ↓
     ├─→ COMPLETED (success)
     ├─→ FAILED (unhandled exception)
     ├─→ FAILED_ROLLED_BACK (saga compensation completed)
     ├─→ FAILED_WORKER_CRASH (zombie detection)
     ├─→ FAILED_CHILD_WORKFLOW (sub-workflow failed)
     └─→ CANCELLED (user-initiated)
```

Let's explore each state and what it means.

## State Definitions

### PENDING_ASYNC

**Meaning**: An async step has been dispatched to a worker and is executing in the background.

**Triggers**:
- Workflow executes an `ASYNC` type step
- Execution provider (e.g., Celery) dispatches task to worker
- Workflow saves state and returns control to caller

**What's happening**:
- Worker process is executing the step function
- Main workflow process is idle (not blocked)
- State is persisted to database

**Next state**:
- `ACTIVE` when worker completes the task and reports back
- `FAILED` if worker encounters an unhandled exception

**Duration**: Seconds to hours, depending on step logic

**Example scenario**: Sending 10,000 emails in an async step

### WAITING_HUMAN_INPUT

**Meaning**: Workflow is paused, waiting for external input (human approval, API callback, etc.).

**Triggers**:
- Step function raises `WorkflowPauseDirective`
- Typically used for approvals, manual review, or external events

**What's happening**:
- Workflow is effectively "suspended"
- No worker is actively processing
- Waiting for external system or user to call `resume_workflow()`

**Next state**:
- `ACTIVE` when `resume_workflow()` is called with required input
- `CANCELLED` if user cancels the workflow

**Duration**: Minutes to days, depending on business process

**Example scenario**: Waiting for manager approval on a large purchase order

### PENDING_SUB_WORKFLOW

**Meaning**: Workflow has spawned a child workflow and is waiting for it to complete.

**Triggers**:
- Step function raises `StartSubWorkflowDirective`
- Parent workflow creates child workflow
- Parent saves state and returns control

**What's happening**:
- Child workflow is executing independently
- Parent is idle, checking child status periodically
- Child can be in any state (ACTIVE, WAITING_HUMAN_INPUT, etc.)

**Next state**:
- `ACTIVE` when child completes successfully
- `WAITING_CHILD_HUMAN_INPUT` if child pauses for input
- `FAILED_CHILD_WORKFLOW` if child fails

**Duration**: Varies based on child workflow complexity

**Example scenario**: Order workflow spawns inventory allocation sub-workflow

### ACTIVE

**Meaning**: Workflow is actively executing or ready to execute the next step.

**Triggers**:
- Workflow is created with `create_workflow()`
- Async task completes
- Human input is provided via `resume_workflow()`
- Sub-workflow completes
- Any transition that makes the workflow ready to proceed

**What's happening**:
- Workflow is in a runnable state
- Next call to `next_step(user_input={})` will process a step
- Step may execute immediately or transition to another state

**Next state**:
- `PENDING_ASYNC` if next step is async
- `WAITING_HUMAN_INPUT` if next step pauses
- `PENDING_SUB_WORKFLOW` if next step spawns child
- `COMPLETED` if no more steps
- `FAILED` on unhandled exception

**Duration**: Milliseconds to seconds per step

**Example scenario**: Processing an order through validation, payment, and fulfillment steps

### COMPLETED

**Meaning**: Workflow has successfully executed all steps.

**Triggers**:
- Final step completes without errors
- No more steps to execute (end of workflow reached)

**What's happening**:
- All steps executed successfully
- Final state is persisted
- Workflow is immutable (no further execution)

**Next state**: Terminal state (no further transitions)

**Duration**: Permanent

**Example scenario**: Order shipped, payment settled, customer notified

### FAILED

**Meaning**: An unhandled exception occurred during step execution.

**Triggers**:
- Step function raises an exception (not a directive)
- Validation error on input or output
- Network timeout, database error, etc.

**What's happening**:
- Exception is logged to audit log
- Workflow state captured at point of failure
- Error message and stack trace stored

**Next state**:
- `ACTIVE` if user calls `retry_workflow()`
- Otherwise terminal (manual intervention required)

**Duration**: Permanent unless retried

**Example scenario**: Payment gateway timeout during charge step

### FAILED_ROLLED_BACK

**Meaning**: Workflow failed and saga compensation successfully executed.

**Triggers**:
- Saga mode is enabled (`workflow.enable_saga_mode()`)
- Step fails during execution
- All compensatable steps execute in reverse order
- All compensations complete successfully

**What's happening**:
- Failed step identified
- Compensation functions execute in reverse (LIFO)
- Each compensation attempts to undo its step's side effects
- All compensations succeed

**Next state**: Terminal state (workflow cannot continue)

**Duration**: Permanent

**Example scenario**: Payment charged, inventory allocated, then shipping fails. Compensation releases inventory and refunds payment.

### FAILED_WORKER_CRASH

**Meaning**: Worker process crashed while executing an async step, detected by zombie scanner.

**Triggers**:
- Worker sends heartbeats while processing step
- Worker crashes (OOM, hardware failure, SIGKILL)
- Heartbeat stops updating
- Zombie scanner detects stale heartbeat (threshold: 120s default)

**What's happening**:
- Workflow stuck in `PENDING_ASYNC` state
- No worker is actually processing the step
- Zombie scanner marks workflow as crashed

**Next state**:
- `ACTIVE` if user calls `retry_workflow(from_step=...)`
- Otherwise terminal (manual intervention required)

**Duration**: Permanent unless retried

**Example scenario**: Celery worker killed by OOM killer while processing large file upload

### FAILED_CHILD_WORKFLOW

**Meaning**: A child workflow failed, causing the parent to fail.

**Triggers**:
- Parent spawns child via `StartSubWorkflowDirective`
- Child workflow encounters unhandled exception
- Child transitions to `FAILED` or `FAILED_ROLLED_BACK`
- Parent checks child status and propagates failure

**What's happening**:
- Child workflow is in failed state
- Parent workflow cannot proceed (child's result is required)
- Parent transitions to failed state

**Next state**: Terminal state (both parent and child failed)

**Duration**: Permanent

**Example scenario**: Order workflow spawns payment workflow, payment fails due to invalid card

### CANCELLED

**Meaning**: User explicitly cancelled the workflow.

**Triggers**:
- User calls `cancel_workflow(workflow_id)`
- Optional: User provides cancellation reason

**What's happening**:
- Workflow execution halted immediately
- If async step was running, worker continues but result is ignored
- Cancellation reason logged to audit log

**Next state**: Terminal state (workflow cannot continue)

**Duration**: Permanent

**Example scenario**: Customer cancels order before it ships

## State Transition Examples

### Happy Path: Simple Workflow

```
1. create_workflow("OrderProcessing", data)
   → State: ACTIVE

2. next_step(user_input={})  # Validate_Order (STANDARD step)
   → Executes inline
   → State: ACTIVE (ready for next step)

3. next_step(user_input={})  # Charge_Payment (STANDARD step)
   → Executes inline
   → State: ACTIVE

4. next_step(user_input={})  # Ship_Order (STANDARD step)
   → Executes inline
   → No more steps
   → State: COMPLETED
```

### Async Step Workflow

```
1. create_workflow("EmailCampaign", data)
   → State: ACTIVE

2. next_step(user_input={})  # Send_Emails (ASYNC step)
   → Dispatch to Celery worker
   → State: PENDING_ASYNC

   [Worker executes Send_Emails in background]

3. Worker completes task, calls complete_async_task()
   → State: ACTIVE

4. next_step(user_input={})  # Track_Results (STANDARD step)
   → Executes inline
   → State: COMPLETED
```

### Human-in-the-Loop Workflow

```
1. create_workflow("LoanApproval", data)
   → State: ACTIVE

2. next_step(user_input={})  # Calculate_Risk (STANDARD step)
   → Executes inline, calculates risk score
   → State: ACTIVE

3. next_step(user_input={})  # Manager_Approval (STANDARD step)
   → Raises WorkflowPauseDirective(result={"awaiting_approval": True})
   → State: WAITING_HUMAN_INPUT

   [Hours/days pass while manager reviews]

4. resume_workflow(workflow_id, input={"approved": True})
   → State: ACTIVE

5. next_step(user_input={})  # Disburse_Loan (STANDARD step)
   → Executes inline
   → State: COMPLETED
```

### Sub-Workflow Example

```
1. create_workflow("OrderProcessing", data)
   → State: ACTIVE

2. next_step(user_input={})  # Allocate_Inventory (triggers sub-workflow)
   → Raises StartSubWorkflowDirective(workflow_type="InventoryAllocation")
   → Creates child workflow
   → State: PENDING_SUB_WORKFLOW

3. [Child workflow executes independently]
   → Child state: ACTIVE → PENDING_ASYNC → ACTIVE → COMPLETED

4. Parent checks child status, finds COMPLETED
   → Merges child results into parent state
   → State: ACTIVE

5. next_step(user_input={})  # Ship_Order
   → State: COMPLETED
```

### Saga Compensation Example

```
1. create_workflow("BookingWorkflow", data)
   → Enable saga mode
   → State: ACTIVE

2. next_step(user_input={})  # Reserve_Flight (compensatable)
   → Executes inline, reserves seat
   → State: ACTIVE

3. next_step(user_input={})  # Reserve_Hotel (compensatable)
   → Executes inline, reserves room
   → State: ACTIVE

4. next_step(user_input={})  # Charge_Payment (compensatable)
   → Fails! Card declined
   → Saga triggered
   → State: Executing compensation...

5. Compensation: Cancel_Payment (no-op, payment never charged)
6. Compensation: Release_Hotel (cancels hotel reservation)
7. Compensation: Cancel_Flight (releases flight seat)

   → State: FAILED_ROLLED_BACK
```

## Persistent vs Transient State

### Persistent State

Saved to database via `PersistenceProvider.save_workflow()`:
- Workflow ID
- Workflow type and version
- Current status
- Current step name
- Workflow state (Pydantic model serialized to JSON)
- Created/updated timestamps
- Owner ID, data region (multi-tenancy)
- Definition snapshot (for version isolation)

**When saved**:
- After every step execution
- Before async dispatch
- On pause, cancel, or failure

### Transient State

Exists only in memory during execution:
- Step function local variables
- Intermediate calculation results
- Loop iteration state (current index, etc.)

**Why separate**: Persistent state is durable across restarts, transient state is ephemeral and reconstructed on resume.

## Lifecycle Hooks (via WorkflowObserver)

The `WorkflowObserver` provider allows you to hook into lifecycle events:

```python
class MyObserver(WorkflowObserver):
    def on_workflow_started(self, workflow_id, workflow_type):
        # Called when workflow created
        pass

    def on_workflow_status_changed(self, workflow_id, old_status, new_status):
        # Called on every state transition
        if new_status == "COMPLETED":
            send_notification(workflow_id)

    def on_step_executed(self, workflow_id, step_name, result):
        # Called after each step
        record_metric(step_name, duration=result.get('duration'))

    def on_workflow_failed(self, workflow_id, error):
        # Called on failure
        log_error(workflow_id, error)
        alert_ops_team(workflow_id)
```

## Querying Workflow State

The persistence provider exposes methods to query workflows by state:

```python
# List all active workflows
active_workflows = await persistence.list_workflows(status="ACTIVE")

# List workflows waiting for human input
paused_workflows = await persistence.list_workflows(status="WAITING_HUMAN_INPUT")

# List failed workflows for manual review
failed_workflows = await persistence.list_workflows(
    status="FAILED",
    limit=100
)
```

## What's Next

Now that you understand the lifecycle:
- [State Management](state-management.md) - How state flows through the lifecycle
- [Saga Pattern](saga-pattern.md) - Compensation on failure
- [Zombie Recovery](zombie-recovery.md) - Detecting and recovering from worker crashes
