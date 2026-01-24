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
    completion_notes: Optional[str] = None

    # Notifications
    notification_sent: bool = False

    # Metadata
    created_at: Optional[datetime] = None
    workflow_status: str = "pending"  # pending, in_progress, approved, completed
