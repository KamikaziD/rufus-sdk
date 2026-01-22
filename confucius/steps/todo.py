import random
from confucius.workflow import WorkflowPauseDirective
from confucius.models import StepContext
from todo_state_models import TodoProcessingState

def select_random_todo(state: TodoProcessingState, context: StepContext):
    """Selects a random todo item from the fetched list."""
    todos = state.todo_list_response.get('body', [])
    if not todos or not isinstance(todos, list):
        raise ValueError("No todos found in response")
    
    selected = random.choice(todos)
    print(f"Selected Todo ID {selected['id']}: {selected['title']}")
    
    state.selected_todo = selected
    return {"selected_todo": selected}

def fake_process_item(state: TodoProcessingState, context: StepContext):
    """Simulates processing the item."""
    selected_todo = state.selected_todo
    if selected_todo is None:
        raise ValueError("No selected_todo found in state.")
        
    print(f"Processing Todo {selected_todo['id']}...")
    state.processing_status = "processed"
    return {"processing_status": "processed"}

def request_manual_completion(state: TodoProcessingState, context: StepContext):
    """Pause for human to mark complete/incomplete."""
    todo = state.selected_todo
    raise WorkflowPauseDirective({
        "message": f"Please review Todo #{todo['id']}: '{todo['title']}'",
        "current_status": "completed" if todo['completed'] else "incomplete"
    })

def finalize_item(state: TodoProcessingState, context: StepContext):
    """Finalize based on human input."""
    input_data = context.validated_input
    if not input_data:
        raise ValueError("Finalize input is missing from the context.")

    decision = input_data.decision
    comments = input_data.comments
    
    print(f"Human decision: {decision}")
    state.human_review_decision = decision
    state.reviewer_comments = comments
    state.final_item_status = decision
    return {
        "human_review_decision": decision, 
        "reviewer_comments": comments,
        "final_item_status": decision
    }
