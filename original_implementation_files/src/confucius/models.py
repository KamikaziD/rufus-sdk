from pydantic import BaseModel
from typing import Dict, Any, Optional

class WorkflowStartRequest(BaseModel):
    workflow_type: str
    initial_data: Dict[str, Any] = {}
    data_region: Optional[str] = None

class WorkflowStartResponse(BaseModel):
    workflow_id: str
    current_step_name: str
    status: str

class WorkflowStepRequest(BaseModel):
    input_data: Dict[str, Any]

class WorkflowStepResponse(BaseModel):
    workflow_id: str
    current_step_name: Optional[str]
    next_step_name: Optional[str]
    status: str
    state: Dict[str, Any]
    result: Dict[str, Any]

class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str
    current_step_name: Optional[str]
    state: Dict[str, Any]
    workflow_type: Optional[str] = None
    parent_execution_id: Optional[str] = None
    blocked_on_child_id: Optional[str] = None

class ResumeWorkflowRequest(BaseModel):
    decision: str
    reviewer_id: str
    comments: Optional[str] = None

class RetryWorkflowRequest(BaseModel):
    workflow_id: str
    step_index: int
    retry_count: int

class StepContext(BaseModel):

    """

    Encapsulates metadata and context for a single step execution.

    This object is passed to every step function.

    """

    workflow_id: str

    step_name: str

    validated_input: Optional[BaseModel] = None

    previous_step_result: Optional[Dict[str, Any]] = None



    # Optional fields for loop context

    loop_item: Optional[Any] = None

    loop_index: Optional[int] = None


