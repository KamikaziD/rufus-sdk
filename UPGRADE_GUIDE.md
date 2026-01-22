# Upgrade Guide

This guide provides instructions for upgrading between major versions of the Rufus SDK.

## Upgrading from Confucius (Pre-SDK) to Rufus 1.0

The transition from the monolithic Confucius server to the embeddable Rufus SDK is a significant architectural change. There is no direct upgrade path. You will need to refactor your existing Confucius implementation to use the new SDK-first approach.

### Key Changes

1.  **Engine Instantiation:** Instead of running a standalone server, you now instantiate the `WorkflowEngine` directly within your application.
2.  **Provider Configuration:** Persistence, execution, and other backends are now configured programmatically by passing provider instances to the `WorkflowEngine` constructor.
3.  **Step Registration:** Step functions are registered using `engine.register_step_module()` instead of relying on file-based discovery in a `steps/` directory.
4.  **API vs. SDK:** Instead of interacting with a REST API, you now call methods directly on the `WorkflowEngine` and `WorkflowHandle` objects.

### Example Refactoring

**Old (Confucius `main.py`):**
```python
# Confucius automatically discovered workflows and steps
app = create_fastapi_app()
# ... FastAPI startup logic ...
```

**New (Your Application):**
```python
from rufus import WorkflowEngine
from rufus.implementations.persistence.postgres import PostgresPersistence
from rufus.implementations.execution.celery import CeleryExecutor
import my_project.steps as my_steps

# Instantiate and configure the engine
engine = WorkflowEngine(
    persistence=PostgresPersistence(db_url="..."),
    executor=CeleryExecutor(broker_url="...")
)

# Register your step functions
engine.register_step_module("my_steps", my_steps)

# Register your workflows
engine.register_workflow(my_workflow_yaml)

# Now you can use the engine to start workflows
handle = engine.start_workflow("MyWorkflow", {})
```
