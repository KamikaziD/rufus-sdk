from typing import Dict, Any
from state_models import GearsTestState
from confucius.models import StepContext

def process_item(state: GearsTestState, context: StepContext):
    """Processes a single item in a loop."""
    item = context.loop_item
    print(f"[GEARS-TEST] Processing item: {item} in workflow {context.workflow_id}")
    state.processed_count += 1
    return {"processed_count": state.processed_count}

def check_stop_condition(state: GearsTestState, context: StepContext):
    """Checks if the loop should stop."""
    if state.processed_count >= 3:
        return {"stop_loop": True}
    return {"stop_loop": False}

def log_spawn(state: GearsTestState, context: StepContext):
    """Simple logging function."""
    message = "Final check step executed."
    print(f"[GEARS-TEST] Log: {message}")
    return {"log_message": message}

def mark_schedule_registered(state: GearsTestState, context: StepContext):
    """Updates the state to indicate schedule was registered."""
    print(f"[GEARS-TEST] Marking schedule as registered.")
    return {"schedule_registered": True}
