from typing import Any
from state_models import SuperWorkflowState
from confucius.models import StepContext

# --- Super Workflow / General Steps ---

def record_name(state: SuperWorkflowState, context: StepContext):
    """First step, records the name provided by the user."""
    # In this new model, the name would typically be set during workflow creation
    # or via a step with a validated input model.
    # We assume 'state.name' is already populated.
    print(f"SuperWorkflow: Recorded name '{state.name}'.")
    return {"greeting": f"Hello, {state.name}!"}

def generate_greeting(state: SuperWorkflowState, context: StepContext):
    """Second step, automatically chained. Generates a greeting."""
    greeting = context.previous_step_result.get("greeting")
    state.greeting = greeting
    print(f"SuperWorkflow: Generated greeting: '{greeting}'.")
    return {"greeting_length": len(greeting)}

def analyze_greeting(state: SuperWorkflowState, context: StepContext):
    """Third step, automatically chained. Analyzes the greeting length."""
    greeting_length = context.previous_step_result.get("greeting_length")
    state.greeting_length = greeting_length
    decision = "LONG" if greeting_length > 15 else "SHORT"
    state.analysis_decision = decision
    print(f"SuperWorkflow: Analyzed greeting. Length is {greeting_length}, which is '{decision}'.")
    return {"message": f"Analysis complete. Decision was '{decision}'."}

def finalize_workflow(state: SuperWorkflowState, context: StepContext):
    """Final step, summarizes the automated chain."""
    state.final_message = f"Workflow for {state.name} finished. The greeting '{state.greeting}' was deemed {state.analysis_decision}."
    print(f"SuperWorkflow: Finalizing. Message: {state.final_message}")
    return {"final_message": state.final_message}

def noop(state: Any, context: StepContext):
    """A no-op function that does nothing."""
    return {}

def send_notification_step(state: Any, context: StepContext):
    """Simulates sending a notification."""
    print(f"[NOTIFICATION] Sending to {state.recipient}: {state.message}")
    return {"status": "sent"}
