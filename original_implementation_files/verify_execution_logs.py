import asyncio
import os
import uuid
import logging
from pydantic import BaseModel
from confucius.workflow import Workflow, WorkflowStep
from confucius.persistence import get_workflow_store, get_postgres_store

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a simple state model
class TestState(BaseModel):
    count: int = 0

# Define a step function
def increment(state: TestState, **kwargs):
    state.count += 1
    return {"message": "Incremented count"}

async def verify_logs():
    print("--- Starting Execution Log Verification ---")
    
    # Ensure we are using Postgres
    os.environ["WORKFLOW_STORAGE"] = "postgres"
    
    # Check if DB is available (simple check)
    try:
        store = await get_postgres_store()
        await store.initialize()
    except Exception as e:
        print(f"Skipping verification: Could not connect to Postgres: {e}")
        return

    # Create a unique workflow ID
    workflow_id = str(uuid.uuid4())
    print(f"Workflow ID: {workflow_id}")

    # Create a simple workflow programmatically
    step = WorkflowStep(name="IncrementStep", func=increment)
    
    workflow = Workflow(
        id=workflow_id,
        workflow_steps=[step],
        initial_state_model=TestState(),
        workflow_type="LogVerificationWorkflow",
        steps_config=[{"name": "IncrementStep"}],
        state_model_path="verify_execution_logs.TestState" # Fake path, but required
    )

    # Save initial state
    print("Saving initial workflow state...")
    store = get_workflow_store()
    store.save_sync(workflow_id, workflow)

    # Execute the step
    # This should trigger _log_execution -> log_execution_sync
    print("Executing step...")
    workflow.next_step({})
    
    # Save after step
    store.save_sync(workflow_id, workflow)

    # Now verify logs in DB
    print("Verifying logs in database...")
    pg_store = await get_postgres_store()
    
    async with pg_store.pool.acquire() as conn:
        # Check execution logs
        exec_logs = await conn.fetch("""
            SELECT step_name, log_level, message 
            FROM workflow_execution_logs 
            WHERE workflow_id = $1
            ORDER BY logged_at ASC
        """, workflow_id)
        
        print(f"\nExecution Logs found: {len(exec_logs)}")
        for log in exec_logs:
            print(f" - [{log['log_level']}] {log['step_name']}: {log['message']}")
            
        # Check audit logs
        audit_logs = await conn.fetch("""
            SELECT event_type, step_name 
            FROM workflow_audit_log 
            WHERE workflow_id = $1
            ORDER BY recorded_at ASC
        """, workflow_id)
        
        print(f"\nAudit Logs found: {len(audit_logs)}")
        for log in audit_logs:
            print(f" - {log['event_type']} (Step: {log['step_name']})")

    # Assertions
    if len(exec_logs) >= 2: # Start and Success
        print("\n✅ Execution logs verified.")
    else:
        print("\n❌ Execution logs missing or incomplete.")

    if len(audit_logs) >= 1: # Step Completed
        print("✅ Audit logs verified.")
    else:
        print("❌ Audit logs missing.")

if __name__ == "__main__":
    # We need to run this in an event loop to use the async verification part,
    # but the workflow execution itself uses the sync bridge.
    asyncio.run(verify_logs())
