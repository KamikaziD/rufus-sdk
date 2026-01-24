"""
Step functions for task management workflow
"""

from datetime import datetime
from examples.sqlite_task_manager.models import TaskState
from rufus.models import StepContext, WorkflowPauseDirective


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
