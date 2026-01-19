from confucius.semantic_firewall import WorkflowInput
from typing import Optional, List, Dict, Any

class TodoProcessingState(WorkflowInput):
    # Initial state
    todo_list_url: str = "https://jsonplaceholder.typicode.com/todos"
    
    # HTTP Results
    todo_list_response: Optional[Dict[str, Any]] = None
    selected_todo: Optional[Dict[str, Any]] = None
    
    # Processing
    processing_status: str = "pending"
    
    # Manual Review
    human_review_decision: Optional[str] = None # "COMPLETE", "INCOMPLETE"
    reviewer_comments: Optional[str] = None
    
    # Final Result
    final_item_status: Optional[str] = None

    # Spawned Workflows
    spawned_workflows: Optional[List[Dict[str, Any]]] = None

class FinalizeTodoInput(WorkflowInput):
    decision: str
    comments: Optional[str] = None
