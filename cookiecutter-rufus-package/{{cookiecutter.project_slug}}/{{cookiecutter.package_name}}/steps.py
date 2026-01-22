from typing import Any, Dict
from pydantic import BaseModel
from rufus.models import WorkflowStep, StepContext

# Define an input model for your step if it has specific inputs
class MySampleStepInput(BaseModel):
    input_value: str
    optional_setting: bool = False

class MySampleStep(WorkflowStep):
    """
    A sample custom workflow step for the Rufus marketplace.
    This step demonstrates how to define a step with custom logic and an input model.
    """
    # This attribute registers the step type name for auto-discovery
    STEP_TYPE_NAME = "{{ cookiecutter.step_type_name_example }}"

    # Add any specific fields your custom step needs beyond the base WorkflowStep
    # For example, if your step needs an API key or a specific configuration
    my_custom_config: str = "default_config"

    async def execute(self, state: BaseModel, context: StepContext) -> Dict[str, Any]:
        """
        Executes the logic for MySampleStep.
        
        Args:
            state: The current state of the workflow.
            context: The context of the current step execution.
        
        Returns:
            A dictionary of results to be merged back into the workflow state.
        """
        # Example: Accessing validated input
        step_input: MySampleStepInput = context.validated_input

        # Example: Performing some operation
        processed_value = f"Processed: {step_input.input_value.upper()}"
        
        print(f"Executing MySampleStep: {self.name}")
        print(f"  Workflow ID: {context.workflow_id}")
        print(f"  Input Value: {step_input.input_value}")
        print(f"  Custom Config: {self.my_custom_config}")

        # Update the state (or return values to be merged into the state)
        if hasattr(state, 'my_sample_output'):
            state.my_sample_output = processed_value
        
        return {
            "my_sample_output": processed_value,
            "step_status": "success",
            "executed_by": "MySampleStep"
        }

    # You can also define a compensate method if this is a compensatable step
    # async def compensate(self, state: BaseModel, context: StepContext) -> Dict[str, Any]:
    #     print(f"Compensating MySampleStep: {self.name}")
    #     return {"my_sample_compensation_status": "compensated"}
