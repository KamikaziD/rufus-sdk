from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor

# Use in-memory providers for simple cases
engine = WorkflowEngine(
    persistence=InMemoryPersistence(),
    executor=SyncExecutor(),
    # ... other providers
)

# Start a workflow defined in your registry
handle = engine.start_workflow("MyWorkflowType", {"initial_data": "..."})
