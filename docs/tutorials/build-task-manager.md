# Tutorial: Build a Task Manager with Ruvon

**Learning Objectives:**
- Create a complete workflow application from scratch
- Define workflow state with Pydantic models
- Implement step functions with business logic
- Handle human-in-the-loop workflows with pauses
- Use SQLite for development persistence
- Run and test your workflow

**Prerequisites:**
- Python 3.10+ installed
- Basic understanding of Python and async/await
- Completed [Getting Started](../getting-started.md)

**Time:** 30 minutes

---

## What We're Building

We'll build a **task approval workflow** that automates task assignment and approval. The workflow will:

1. Create a new task with details
2. Auto-assign the task to a team member based on priority
3. Pause for manager approval (human-in-the-loop)
4. Complete the task after approval
5. Send a notification

This demonstrates real-world patterns like automated decision-making, human approval gates, and notification systems.

---

## Step 1: Set Up Your Project

Let's create a new directory for our task manager:

```bash
mkdir ruvon-task-manager
cd ruvon-task-manager
```

Create a Python virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

Install Ruvon SDK:

```bash
pip install ruvon
```

Create the project structure:

```bash
mkdir -p task_manager config
touch task_manager/__init__.py
touch task_manager/models.py
touch task_manager/steps.py
touch main.py
```

Your structure should look like:

```
ruvon-task-manager/
├── task_manager/
│   ├── __init__.py
│   ├── models.py     # State models
│   └── steps.py      # Step functions
├── config/
│   └── workflow.yaml # Workflow definition
└── main.py           # Application entry point
```

---

## Step 2: Define the State Model

The workflow state is the data that persists throughout workflow execution. Let's create our `TaskState` model.

Open `task_manager/models.py`:

```python
"""
State models for task management workflow
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TaskState(BaseModel):
    """State model for task approval workflow"""

    # Task details
    task_id: str
    title: str
    description: str
    priority: str = "medium"  # low, medium, high
    category: str = "general"

    # Assignment
    assigned_to: Optional[str] = None
    assigned_at: Optional[datetime] = None

    # Approval
    requires_approval: bool = True
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_notes: Optional[str] = None

    # Completion
    completed: bool = False
    completed_at: Optional[datetime] = None

    # Notifications
    notification_sent: bool = False

    # Metadata
    created_at: Optional[datetime] = None
    workflow_status: str = "pending"  # pending, assigned, approved, completed
```

**What's happening here:**
- We use Pydantic's `BaseModel` for automatic validation and serialization
- All workflow data lives in this state object
- Optional fields use `Optional[type]` (can be `None`)
- We track the entire lifecycle: creation → assignment → approval → completion

---

## Step 3: Implement Step Functions

Now let's implement the business logic for each step. Open `task_manager/steps.py`:

```python
"""
Step functions for task management workflow
"""

from datetime import datetime
from task_manager.models import TaskState
from ruvon.models import StepContext, WorkflowPauseDirective


def create_task(state: TaskState, context: StepContext, **user_input) -> dict:
    """
    Initialize the task with details from user input
    """
    print(f"📝 Creating task: {state.title}")

    # Set creation timestamp
    state.created_at = datetime.utcnow()
    state.workflow_status = "pending"

    print(f"   Priority: {state.priority}")
    print(f"   Category: {state.category}")

    return {
        "step": "create_task",
        "status": "created",
        "created_at": state.created_at.isoformat()
    }


def assign_task(state: TaskState, context: StepContext, **user_input) -> dict:
    """
    Auto-assign task to available team member based on priority
    """
    print(f"\n👤 Assigning task: {state.task_id}")

    # Simple assignment logic based on priority
    assignment_map = {
        "high": "senior_engineer",
        "medium": "engineer",
        "low": "junior_engineer"
    }

    assignee = assignment_map.get(state.priority, "engineer")
    state.assigned_to = assignee
    state.assigned_at = datetime.utcnow()
    state.workflow_status = "assigned"

    print(f"   Assigned to: {assignee}")
    print(f"   Assigned at: {state.assigned_at.strftime('%Y-%m-%d %H:%M:%S')}")

    return {
        "step": "assign_task",
        "status": "assigned",
        "assigned_to": assignee
    }


def request_approval(state: TaskState, context: StepContext, **user_input) -> dict:
    """
    Pause workflow for manager approval (human-in-the-loop)
    """
    print(f"\n✋ Requesting approval for task: {state.task_id}")
    print(f"   Assigned to: {state.assigned_to}")
    print(f"   Priority: {state.priority}")

    if not state.requires_approval:
        print("   ⏭️  Approval not required, skipping...")
        state.approved_by = "auto_approved"
        state.approved_at = datetime.utcnow()
        return {
            "step": "request_approval",
            "status": "auto_approved"
        }

    print("   Workflow paused, awaiting approval...")

    # Pause workflow for human approval
    raise WorkflowPauseDirective(
        result={
            "step": "request_approval",
            "status": "pending_approval",
            "message": "Workflow paused for manager approval"
        }
    )


def complete_task(state: TaskState, context: StepContext, **user_input) -> dict:
    """
    Mark task as completed
    """
    print(f"\n✅ Completing task: {state.task_id}")

    # Get approval info from user input (provided when resuming workflow)
    approved_by = user_input.get("approved_by", "manager")
    approval_notes = user_input.get("approval_notes", "")

    state.approved_by = approved_by
    state.approved_at = datetime.utcnow()
    state.approval_notes = approval_notes

    # Mark as completed
    state.completed = True
    state.completed_at = datetime.utcnow()
    state.workflow_status = "completed"

    print(f"   Approved by: {approved_by}")
    if approval_notes:
        print(f"   Notes: {approval_notes}")
    print(f"   Completed at: {state.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")

    return {
        "step": "complete_task",
        "status": "completed",
        "approved_by": approved_by,
        "completed_at": state.completed_at.isoformat()
    }


def send_notification(state: TaskState, context: StepContext, **user_input) -> dict:
    """
    Send notification about task completion
    """
    print(f"\n📧 Sending completion notification")
    print(f"   Task: {state.title}")
    print(f"   Assigned to: {state.assigned_to}")
    print(f"   Approved by: {state.approved_by}")
    print(f"   Status: {state.workflow_status}")

    state.notification_sent = True

    # In a real application, this would send emails/slack messages
    print("   ✓ Notification sent successfully")

    return {
        "step": "send_notification",
        "status": "sent",
        "notification_sent": True
    }
```

**Key Patterns:**

1. **Step Function Signature**: All steps accept `(state, context, **user_input)`
2. **State Modification**: Directly modify the state object: `state.field = value`
3. **Return Results**: Return a dict that merges into the workflow state
4. **Pause Directive**: Raise `WorkflowPauseDirective` to pause for human input
5. **StepContext**: Contains workflow metadata (workflow_id, step_name, etc.)

---

## Step 4: Define the Workflow in YAML

Create `config/workflow.yaml`:

```yaml
workflow_type: "TaskApprovalWorkflow"
workflow_version: "1.0.0"
initial_state_model: "task_manager.models.TaskState"
description: "Task approval workflow with human-in-the-loop"

steps:
  - name: "Create_Task"
    type: "STANDARD"
    function: "task_manager.steps.create_task"
    automate_next: true
    description: "Initialize task with details"

  - name: "Assign_Task"
    type: "STANDARD"
    function: "task_manager.steps.assign_task"
    automate_next: true
    description: "Auto-assign task based on priority"

  - name: "Request_Approval"
    type: "STANDARD"
    function: "task_manager.steps.request_approval"
    automate_next: false
    description: "Pause for manager approval"

  - name: "Complete_Task"
    type: "STANDARD"
    function: "task_manager.steps.complete_task"
    automate_next: true
    description: "Mark task as completed after approval"

  - name: "Send_Notification"
    type: "STANDARD"
    function: "task_manager.steps.send_notification"
    automate_next: false
    description: "Notify team about task completion"
```

**YAML Breakdown:**

- `workflow_type`: Unique identifier for this workflow
- `initial_state_model`: Python path to your state model
- `steps`: List of steps to execute
- `automate_next: true`: Automatically proceed to next step after completion
- `automate_next: false`: Stop and wait for manual trigger

---

## Step 5: Build the Application

Now let's wire everything together. Open `main.py`:

```python
"""
Task Manager Application

Demonstrates a complete Ruvon workflow with SQLite persistence.
"""

import asyncio
from pathlib import Path

from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.observability.logging import LoggingObserver
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


async def initialize_database(db_path: str):
    """Initialize SQLite database with schema"""
    persistence = SQLitePersistenceProvider(db_path=db_path)
    await persistence.initialize()

    # Create minimal schema
    await persistence.conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_type TEXT NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT '{}',
            steps_config TEXT NOT NULL DEFAULT '[]',
            state_model_path TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS workflow_execution_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            step_name TEXT,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    return persistence


async def main():
    print("="*70)
    print("  RUFUS TASK MANAGER")
    print("="*70)

    # Initialize persistence
    print("\n🗄️  Initializing SQLite database...")
    persistence = await initialize_database("tasks.db")
    print("✓ Database ready\n")

    # Create workflow builder
    builder = WorkflowBuilder(
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    print("✓ Workflow loaded\n")

    # Create a new task workflow
    print("="*70)
    print("  CREATING NEW TASK")
    print("="*70 + "\n")

    initial_data = {
        "task_id": "TASK-001",
        "title": "Implement new feature",
        "description": "Add user authentication to the platform",
        "priority": "high",
        "category": "development",
        "requires_approval": True,
    }

    workflow = await builder.create_workflow(
        workflow_type="TaskApprovalWorkflow",
        persistence_provider=persistence,
        execution_provider=SyncExecutor(),
        workflow_observer=LoggingObserver(),
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        initial_data=initial_data,
    )

    print(f"✓ Workflow created: {workflow.id}\n")

    # Execute automated steps
    print("="*70)
    print("  EXECUTING AUTOMATED STEPS")
    print("="*70)

    step_count = 0
    while workflow.status == "ACTIVE" and step_count < 10:
        result = await workflow.next_step()
        step_count += 1

        if workflow.status == "PAUSED":
            print("\n⏸️  Workflow paused for approval")
            break

    # Simulate approval
    print("\n" + "="*70)
    print("  MANAGER APPROVAL")
    print("="*70 + "\n")

    print("🔍 Manager reviewing task...")
    print("✓ Task approved!\n")

    # Resume workflow
    print("="*70)
    print("  RESUMING WORKFLOW")
    print("="*70)

    approval_input = {
        "approved_by": "alice_manager",
        "approval_notes": "Looks good, proceed with implementation"
    }

    while workflow.status in ("ACTIVE", "PAUSED"):
        result = await workflow.next_step(user_input=approval_input)
        if workflow.status == "COMPLETED":
            break

    # Show final status
    print("\n" + "="*70)
    print("  WORKFLOW COMPLETED")
    print("="*70 + "\n")

    print(f"Workflow ID: {workflow.id}")
    print(f"Status: {workflow.status}")
    print(f"\nTask Details:")
    print(f"  Task ID: {workflow.state.task_id}")
    print(f"  Title: {workflow.state.title}")
    print(f"  Assigned To: {workflow.state.assigned_to}")
    print(f"  Approved By: {workflow.state.approved_by}")
    print(f"  Status: {workflow.state.workflow_status}")
    print(f"  Notification Sent: {workflow.state.notification_sent}")

    # Cleanup
    await persistence.close()

    print("\n✅ Application completed successfully!\n")


if __name__ == '__main__':
    asyncio.run(main())
```

---

## Step 6: Run Your Application

Now let's run it!

```bash
python main.py
```

You should see output like:

```
======================================================================
  RUFUS TASK MANAGER
======================================================================

🗄️  Initializing SQLite database...
✓ Database ready

✓ Workflow loaded

======================================================================
  CREATING NEW TASK
======================================================================

✓ Workflow created: 550e8400-e29b-41d4-a716-446655440000

======================================================================
  EXECUTING AUTOMATED STEPS
======================================================================
📝 Creating task: Implement new feature
   Priority: high
   Category: development

👤 Assigning task: TASK-001
   Assigned to: senior_engineer
   Assigned at: 2026-02-13 10:30:15

✋ Requesting approval for task: TASK-001
   Assigned to: senior_engineer
   Priority: high
   Workflow paused, awaiting approval...

⏸️  Workflow paused for approval

======================================================================
  MANAGER APPROVAL
======================================================================

🔍 Manager reviewing task...
✓ Task approved!

======================================================================
  RESUMING WORKFLOW
======================================================================

✅ Completing task: TASK-001
   Approved by: alice_manager
   Notes: Looks good, proceed with implementation
   Completed at: 2026-02-13 10:30:16

📧 Sending completion notification
   Task: Implement new feature
   Assigned to: senior_engineer
   Approved by: alice_manager
   Status: completed
   ✓ Notification sent successfully

======================================================================
  WORKFLOW COMPLETED
======================================================================

Workflow ID: 550e8400-e29b-41d4-a716-446655440000
Status: COMPLETED

Task Details:
  Task ID: TASK-001
  Title: Implement new feature
  Assigned To: senior_engineer
  Approved By: alice_manager
  Status: completed
  Notification Sent: True

✅ Application completed successfully!
```

---

## What You've Learned

Congratulations! You just built a complete workflow application. Let's recap what you learned:

1. **State Models**: Define workflow data with Pydantic
2. **Step Functions**: Implement business logic in Python functions
3. **Workflow YAML**: Declare your workflow structure
4. **Automated Execution**: Use `automate_next` for automatic progression
5. **Human-in-the-Loop**: Use `WorkflowPauseDirective` for approval gates
6. **SQLite Persistence**: No server required for development
7. **WorkflowBuilder**: Wire everything together

---

## Next Steps

Now that you have a working workflow, try these enhancements:

1. **Add Error Handling**: What if assignment fails? Add try/except blocks
2. **Add Validation**: Use Pydantic validators in `TaskState`
3. **Add Decision Steps**: Route high-priority tasks differently
4. **Add Metrics**: Track approval times with `persistence.record_metric()`
5. **Add Tests**: Create unit tests for step functions

**Recommended Next Tutorial:**
- [Parallel Execution](./parallel-execution.md) - Add concurrent task processing
- [Saga Pattern](./saga-pattern.md) - Add compensation for failures

---

## Troubleshooting

**Error: "No module named 'task_manager'"**
- Make sure you have `task_manager/__init__.py` (even if empty)
- Run from the project root directory

**Error: "Database is locked"**
- Close any other processes accessing `tasks.db`
- Delete `tasks.db` and restart

**Workflow doesn't pause:**
- Check that `automate_next: false` on the "Request_Approval" step
- Verify `WorkflowPauseDirective` is raised in `request_approval()`

**State changes not persisted:**
- Make sure you're modifying the `state` object, not creating a new one
- Return a dict to merge additional data

---

## Full Code

The complete working example is available in the Ruvon repository:
```
examples/sqlite_task_manager/
```

You can run it directly:
```bash
python examples/sqlite_task_manager/main.py
```
