from confucius.workflow_loader import WorkflowBuilder
import os
import sys

def test_load_todo_workflow():
    print("Testing loading of todo_workflow.yaml via Registry...")
    registry_path = "config/workflow_registry.yaml"
    
    if not os.path.exists(registry_path):
        print(f"Registry not found: {registry_path}")
        return

    builder = WorkflowBuilder(registry_path=registry_path)
    
    try:
        workflow = builder.create_workflow(
            workflow_type="TodoProcessingWorkflow",
            initial_data={}
        )
        print(f"Successfully loaded workflow: {workflow.workflow_type}")
        print(f"Steps: {[s.name for s in workflow.workflow_steps]}")
        
        # Verify step functions
        for step in workflow.workflow_steps:
             if hasattr(step, 'func') and step.func:
                print(f"Step {step.name} resolved function: {step.func.__module__}.{step.func.__name__}")
             elif hasattr(step, 'func_path') and step.func_path:
                 print(f"Step {step.name} has func_path: {step.func_path}")

    except Exception as e:
        print(f"FAILED to load workflow: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_load_todo_workflow()