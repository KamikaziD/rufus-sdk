import os
import sys

# Add the project root to the Python path
# This might need to be adapted depending on how the project is run
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.confucius.celery_app import celery_app
from src.confucius.tasks import resume_workflow_from_celery
from src.confucius.persistence import load_workflow_state

from state_models import KYCState
from workflow_utils import verify_id_agent, sanctions_screen_agent, generate_kyc_report


@celery_app.task
def run_child_workflow_task(parent_workflow_id: str, child_workflow_id: str, child_workflow_type: str, parent_current_step_index: int):
    """
    Celery task to execute a child workflow synchronously and resume the parent.
    """
    print(f"Running child workflow {child_workflow_id} for parent {parent_workflow_id}...")

    child_workflow = load_workflow_state(child_workflow_id)
    if not child_workflow:
        # Ideally, we should handle this error by failing the parent workflow
        print(f"ERROR: Child workflow {child_workflow_id} not found!")
        # For now, just resuming with an error message
        error_result = {"error": f"Child workflow {child_workflow_id} not found"}
        resume_workflow_from_celery(parent_workflow_id, error_result, parent_current_step_index + 1)
        return error_result

    # Execute the child workflow steps.
    # Since the KYC workflow steps are simple and don't involve further async calls within them,
    # we can run them sequentially here.
    # The KYC agent functions expect a dictionary and modify it in place.
    state_as_dict = child_workflow.state.model_dump()

    # Step 1: Verify ID
    verify_id_agent(state_as_dict)

    # Step 2: Sanctions Screening
    sanctions_screen_agent(state_as_dict)

    # Update the Pydantic model with the modified state
    child_workflow.state = KYCState(**state_as_dict)

    # Step 3: Generate the final report
    # This step returns the dictionary that should be passed to the parent.
    final_result = generate_kyc_report(child_workflow.state)

    print(f"Child workflow {child_workflow_id} completed. Resuming parent {parent_workflow_id}.")

    # Resume the parent workflow with the results
    resume_workflow_from_celery(parent_workflow_id, final_result, parent_current_step_index + 1)

    return final_result