# Usage Guide

This guide explains how to use the Rufus SDK to build and run workflows.

## Installation

Install the core SDK from PyPI:

```bash
pip install rufus
```

## Basic Workflow

Here is a simple example of how to define and run a workflow:

```python
from rufus import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor

# 1. Create an engine instance with in-memory providers
engine = WorkflowEngine(
    persistence=InMemoryPersistence(),
    executor=SyncExecutor(),
)

# 2. Define a workflow in YAML
workflow_yaml = """
workflow_type: MyWorkflow
steps:
  - name: Start
    type: STANDARD
    function: my_steps.start_process
    next_step: End
  - name: End
    type: STANDARD
    function: my_steps.end_process
"""

# 3. Register the workflow
engine.register_workflow(workflow_yaml)

# 4. Define your step functions
class MySteps:
    def start_process(self, state):
        print("Starting the process...")
        state["message"] = "Hello from Rufus!"
        return state

    def end_process(self, state):
        print("Ending the process.")
        print(f"Final message: {state.get('message')}")
        return state

# 5. Register the step functions
engine.register_step_module("my_steps", MySteps())

# 6. Start the workflow
handle = engine.start_workflow("MyWorkflow", {"initial_data": "some_value"})

# The SyncExecutor will run the workflow to completion immediately.
```
