"""
Step functions for the Quickstart example.

Each step function receives:
- state: The workflow's state (GreetingState)
- context: Step execution context (StepContext)

And returns:
- dict: Results to merge into the workflow state
"""

from rufus.models import StepContext
from examples.quickstart.state_models import GreetingState


def generate_greeting(state: GreetingState, context: StepContext):
    """
    Generates a personalized greeting.

    This step reads the name from the state and creates a greeting message.

    Args:
        state: The workflow state containing the name
        context: Step execution context (includes workflow_id, step_name, etc.)

    Returns:
        dict: Contains the 'greeting' field to merge into state
    """
    print(f"[{context.step_name}] Generating greeting for: {state.name}")

    # Create personalized greeting
    state.greeting = f"Hello, {state.name}!"

    print(f"[{context.step_name}] Generated: {state.greeting}")

    return {"greeting": state.greeting}


def format_output(state: GreetingState, context: StepContext):
    """
    Formats the final output.

    This step takes the greeting and wraps it with decorative formatting.

    Args:
        state: The workflow state containing the greeting
        context: Step execution context

    Returns:
        dict: Contains the 'formatted_output' field to merge into state
    """
    print(f"[{context.step_name}] Formatting output...")

    # Add decorative formatting
    state.formatted_output = f">>> {state.greeting} <<<"

    print(f"[{context.step_name}] Formatted: {state.formatted_output}")

    return {"formatted_output": state.formatted_output}
