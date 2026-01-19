from confucius.semantic_firewall import WorkflowInput
from typing import Optional
from datetime import datetime

class ScheduledReportState(WorkflowInput):
    report_id: str
    generated_at: str
    status: str = "pending"
    report_url: Optional[str] = None
