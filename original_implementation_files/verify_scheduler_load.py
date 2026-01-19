import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), 'src')))

from confucius.workflow_loader import WorkflowBuilder

def test_load_scheduler_workflow():
    print("Testing loading of TestScheduler via Registry...")
    registry_path = "config/workflow_registry.yaml"
    
    builder = WorkflowBuilder(registry_path=registry_path)
    
    try:
        workflow = builder.create_workflow(
            workflow_type="TestScheduler",
            initial_data={"report_id": "TEST", "generated_at": "now"}
        )
        print(f"Successfully loaded workflow: {workflow.workflow_type}")
        print(f"Steps: {[s.name for s in workflow.workflow_steps]}")
        
        for step in workflow.workflow_steps:
             if hasattr(step, 'func') and step.func:
                print(f"Step {step.name} resolved function: {step.func.__module__}.{step.func.__name__}")
    
    except Exception as e:
        print(f"FAILED to load workflow: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_load_scheduler_workflow()