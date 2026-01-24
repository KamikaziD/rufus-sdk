# Rufus Workflow Engine - Usage Guide

This comprehensive guide will walk you through all aspects of using the Rufus workflow SDK,
from basic concepts to advanced patterns.

## Table of Contents

1. Getting Started
2. Core Concepts
3. Providers and Implementations
4. Defining Workflows in YAML
5. Implementing Step Functions
6. Running Workflows with the SDK
7. Using the CLI Tool
8. Step Types Reference
9. Advanced Features
10. Best Practices
11. Testing Workflows

## 1. Getting Started

### Prerequisites

```
Python 3.10+
pip for package installation
```
### Installation

Install the core Rufus SDK:

```bash
pip install rufus
```
For specific functionalities like a FastAPI server or Celery integration, install optional
dependencies:

```bash
# For the optional FastAPI server components (installs uvicorn, fastapi)
pip install rufus[server]
```
```bash
# If you plan to use Celery for async execution
pip install rufus[celery]
```
```bash
# For development and testing tools (installs pytest, typer, etc.)
pip install rufus[dev]
```

## 2. Core Concepts

### Workflows

A **workflow** is a series of steps that execute to accomplish a business process. Each
workflow has:

```
A unique type (e.g., "LoanApplication", "UserOnboarding").
A state - data that persists throughout execution (a Pydantic model).
A list of steps - units of work to be executed.
A status - indicates the current execution state.
```
### Workflow States

| Status                      | Description                                                  |
| :-------------------------- | :----------------------------------------------------------- |
| `ACTIVE`                    | Workflow is running and ready for the next step              |
| `PENDING_ASYNC`             | Waiting for an async task to complete                        |
| `PENDING_SUB_WORKFLOW`      | Waiting for a child workflow to complete or report a non-blocking status |
| `FAILED_CHILD_WORKFLOW`     | A child workflow failed during execution                     |
| `WAITING_CHILD_HUMAN_INPUT` | A child workflow is paused awaiting human input              |
| `WAITING_HUMAN`             | Paused, awaiting human input (e.g., via a UI)                |
| `COMPLETED`                 | All steps finished successfully                              |
| `FAILED`                    | An error occurred during execution                           |
| `FAILED_ROLLED_BACK`        | Failed and saga compensation successfully rolled back changes |

### Steps

A **step** is a single unit of work in a workflow. Steps can:

```
Execute synchronous Python functions.
Dispatch async tasks to an `ExecutionProvider`.
Run multiple tasks in parallel.
Pause for human review.
Launch sub-workflows (nested execution).
Make decisions and branch the workflow.
```
### State Management

Each workflow has a **state** , which is a Pydantic model that holds all the data for that workflow
execution. The state:

```
Is validated on every update.
Persists between step executions (managed by a `PersistenceProvider`).
Can be accessed and modified by any step.
Is serialized to JSON for storage.
```
## 3. Providers and Implementations

Rufus is built with a pluggable architecture, meaning its core logic is independent of how
persistence, execution, and observability are handled. This is achieved through **Provider
Interfaces** (defined in `rufus.providers.*`) and their **Implementations** (found in
`rufus.implementations.*`).

You inject specific provider implementations into the `WorkflowEngine` to configure its
behavior.

*   `PersistenceProvider` : Handles saving and loading workflow states.
    *   `InMemoryPersistence` (for testing/dev)
    *   `SQLitePersistenceProvider` (for development/testing/low-concurrency production)
    *   `PostgresPersistenceProvider` (for high-concurrency production)
    *   `RedisPersistenceProvider` (for caching/specific use-cases)
*   `ExecutionProvider` : Manages how workflow steps are executed (synchronously,
    asynchronously, in parallel).
    *   `SyncExecutor` (for testing/dev)
    *   `ThreadPoolExecutorProvider` (for local concurrency)
    *   `CeleryExecutor` (for distributed, scalable execution)
*   `WorkflowObserver` : Provides hooks for reacting to workflow events (logging, metrics,
    real-time updates).
    *   `LoggingObserver` (for basic console logging)
    *   `EventPublisherObserver` (for publishing events to a message broker like Redis for real-time updates)
*   `ExpressionEvaluator` : Used for evaluating conditions in `DECISION` steps or
    dynamic injection.
    *   `SimpleExpressionEvaluator`
*   `TemplateEngine` : Used for rendering dynamic content, like HTTP step bodies or
    `FireAndForget` initial data.
    *   `Jinja2TemplateEngine`
## 4. Defining Workflows in YAML

Rufus uses YAML for defining workflows. This provides a human-readable, Git-friendly, and
declarative way to describe your business processes.

### Example: Simple Welcome Workflow (config/welcome_flow.yaml)

```yaml
# config/welcome_flow.yaml
workflow_type: "WelcomeFlow"
initial_state_model: "pydantic.BaseModel" # A simple Pydantic model for initial state
description: "A simple workflow to welcome new users."

steps:
  - name: "Log_Start"
    type: "STANDARD"
    function: "my_app.workflow_steps.log_message"
    automate_next: true # Automatically proceed to the next step
  - name: "Greet_User"
    type: "STANDARD"
    function: "my_app.workflow_steps.greet_user"
    input_model: "my_app.workflow_steps.UserNameInput" # Expects specific input
```

### Workflow Registry (config/workflow_registry.yaml)

All your workflow YAML files must be registered in a central `workflow_registry.yaml` file.
This file also declares any package dependencies for auto-discovery of steps and workflows.

```yaml
# config/workflow_registry.yaml
workflows:
  - type: "WelcomeFlow"
    description: "A simple welcome workflow."
    config_file: "welcome_flow.yaml" # Relative path to the workflow YAML
    initial_state_model: "my_app.workflow_steps.WelcomeState" # Full import path to the state model
  
requires: # Optional: list of packages to auto-discover steps/workflows from
  - rufus-example-package # Rufus will look for entry points and modules in 'rufus_example_package'
  - another-workflow-extension # Can be any installed package
```
## 5. Implementing Step Functions

Step functions are standard Python callables that implement the actual business logic for
each step. They receive the current workflow state (a Pydantic model) and a context
object (containing metadata).

### Example: (my_app/workflow_steps.py)

```python
# my_app/workflow_steps.py
from pydantic import BaseModel, Field
from rufus.models import StepContext
from typing import Optional

class WelcomeState(BaseModel):
    message: str = "Default Welcome Message"
    user_name: Optional[str] = None
    greeting_sent: bool = False

class UserNameInput(BaseModel):
    name: str = Field(..., description="The user's name.")

async def log_message(state: WelcomeState, context: StepContext):
    """Logs the initial message from the state."""
    print(f"[{context.workflow_id}] Log Start: {state.message}")
    # You can return a dict to update the state, or modify 'state' directly
    return {"log_entry": f"Workflow started at {context.workflow_id}"}

async def greet_user(state: WelcomeState, context: StepContext):
    """Greets the user based on input and updates state."""
    user_name = "Guest"
    if context.validated_input and isinstance(context.validated_input, UserNameInput):
        user_name = context.validated_input.name
    state.user_name = user_name
    state.greeting_sent = True
    print(f"[{context.workflow_id}] Hello, {user_name}!")
    return {"greeting_message": f"Hello, {user_name}!"}
```
## 6. Running Workflows with the SDK

The Rufus SDK allows you to embed workflow execution directly into your Python application.

```python
# main.py or your application entry point
import os
import sys
import shutil
from pathlib import Path
import asyncio
import yaml

from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from pydantic import BaseModel # For a generic state model
from typing import Optional, Dict, Any # For type hints in dynamic functions
from rufus.models import StepContext # For StepContext in dynamic functions


async def main():
    # --- 1. Set up your workflow registry (for this example, we create it dynamically) ---
    # In a real app, you would define your workflow YAML files and a registry.yaml
    # We'll simulate a registry here.
    
    # Define a simple state model for the example
    class WelcomeState(BaseModel):
        message: str = "Default Welcome Message"
        user_name: Optional[str] = None
        greeting_sent: bool = False

    class UserNameInput(BaseModel):
        name: str = Field(..., description="The user's name.")

    # Define step functions (needs to be importable, so defining here for example)
    async def log_message(state: WelcomeState, context: StepContext) -> Dict[str, Any]:
        """Logs the initial message from the state."""
        print(f"[SDK] ({context.workflow_id}) Log Start: {state.message}")
        # You can return a dict to update the state, or modify 'state' directly
        return {"log_entry": f"Workflow started at {context.workflow_id}"}

    async def greet_user(state: WelcomeState, context: StepContext) -> Dict[str, Any]:
        """Greets the user based on input and updates state."""
        user_name = "Guest"
        if context.validated_input and isinstance(context.validated_input, UserNameInput):
            user_name = context.validated_input.name
        state.user_name = user_name
        state.greeting_sent = True
        print(f"[SDK] ({context.workflow_id}) Hello, {user_name}!")
        return {"greeting_message": f"Hello, {user_name}!"}

    # Simulate a workflow registry dictionary
    # Note: `initial_state_model_path` and `function` paths should typically be
    # importable Python modules. For this self-contained example, we use `__name__`
    # to refer to dynamically defined classes/functions in this script.
    workflow_registry_config = {
        "WelcomeFlow": {
            "initial_state_model_path": f"{__name__}.WelcomeState",
            "description": "A simple workflow to welcome new users.",
            "steps": [
                {"name": "Log_Start", "type": "STANDARD", "function": f"{__name__}.log_message", "automate_next": True},
                {"name": "Greet_User", "type": "STANDARD", "function": f"{__name__}.greet_user", "input_model": f"{__name__}.UserNameInput"}
            ]
        }
    }
    
    # --- 2. Initialize SDK Providers ---
    # Choose your desired implementations for persistence, execution, and observability
    persistence_provider = InMemoryPersistence() # For development and testing
    # persistence_provider = SQLitePersistenceProvider(db_path="workflows.db") # For development (embedded DB)
    # persistence_provider = PostgresPersistenceProvider(db_url="postgresql://user:password@host:port/db") # For production
    execution_provider = SyncExecutor() # For synchronous execution
    # execution_provider = CeleryExecutor(celery_app=my_celery_app_instance)
    workflow_observer = LoggingObserver() # Logs events to console

    # Initialize providers (important for async providers)
    await persistence_provider.initialize()
    await workflow_observer.initialize()
    # execution_provider.initialize() is called internally by WorkflowEngine if it exists

    # --- 3. Instantiate WorkflowEngine ---
    engine = WorkflowEngine(
        persistence=persistence_provider,
        executor=execution_provider,
        observer=workflow_observer,
        workflow_registry=workflow_registry_config,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    # --- 4. Create and Run a Workflow ---
    initial_state_data = {"message": "Hello from Rufus SDK!"}
    workflow_instance = await engine.start_workflow( # Use await engine.start_workflow
        workflow_type="WelcomeFlow",
        initial_data=initial_state_data
    )

    print(f"\n--- Starting Workflow: {workflow_instance.id} ---")
    print(f"Current Status: {workflow_instance.status}")
    print(f"Current Step: {workflow_instance.current_step_name}")

    # Execute steps until completion
    while workflow_instance.status not in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
        current_step_name = workflow_instance.current_step_name
        print(f"\nExecuting step: {current_step_name}")

        user_input = {}
        if current_step_name == "Greet_User":
            user_input = {"name": "Alice"} # Provide input for this step

        # next_step handles state transitions and auto-advancement
        await workflow_instance.next_step(user_input=user_input) # Use await

        print(f"Status after step: {workflow_instance.status}")
        if workflow_instance.status != "COMPLETED":
            print(f"Next step: {workflow_instance.current_step_name}")

    print(f"\n--- Workflow Finished ({workflow_instance.status}) ---")
    print(f"Final state: {workflow_instance.state.model_dump_json(indent=2)}")

    # --- 5. Clean up providers ---
    await persistence_provider.close()
    await workflow_observer.close()
    await execution_provider.close()

if __name__ == "__main__":
    asyncio.run(main())
```
## 7. Using the CLI Tool

The Rufus CLI provides convenient commands for validating and running workflows.

### Validate Workflow YAML

Check your workflow definition for syntax errors and basic structural integrity:

```bash
rufus validate config/my_workflow.yaml
```
### Run Workflow Locally

Execute a workflow from your terminal using in-memory persistence and synchronous
execution:

```bash
rufus run config/my_workflow.yaml -d '{"user_id": "U123", "amount": 100.00}'
```
This is ideal for rapid prototyping and testing during development.

### Visualize Workflow Structure

Generate a textual representation of your workflow's steps and flow:

```bash
rufus visualize config/my_workflow.yaml
```

## 8. Step Types Reference

Rufus supports a rich set of step types to cover diverse orchestration needs. For detailed
configuration options of each step type, please refer to the YAML Guide.

| Type                | Description                                                                                                                                                                                                                                                                           | `function` key required? | Example YAML Configuration                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       ```
## 9. Advanced Features

### Saga Pattern (Distributed Transactions)

Rufus implements the Saga pattern to ensure data consistency across distributed systems. If
a workflow fails after several steps, Rufus automatically executes "compensation" functions
in reverse order to undo changes.

**How to use:**

1.  **Define a `compensate_function`** in your step YAML for `CompensatableSteps`:

```yaml
steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "my_app.inventory.reserve_items"
    compensate_function: "my_app.inventory.release_items" # Function to call on rollback
  - name: "Charge_Payment"
    type: "STANDARD"
    function: "my_app.payment.charge_customer"
    compensate_function: "my_app.payment.refund_customer"
```
2.  **Enable saga mode** on your workflow instance:

```python
await workflow_instance.enable_saga_mode()
```
### Sub-Workflows (Hierarchical Composition)

Break down complex processes into smaller, reusable child workflows. The parent workflow
pauses while the child executes, with the parent's status dynamically updating to reflect the
child's state (e.g., `PENDING_SUB_WORKFLOW`, `WAITING_CHILD_HUMAN_INPUT`,
`FAILED_CHILD_WORKFLOW`). The parent resumes after the child completes, merging the
child's results into its own state.

**How to use:**

In a step function, raise a `StartSubWorkflowDirective`:

```python
# my_app/loan_steps.py
from rufus.models import StartSubWorkflowDirective, BaseModel, StepContext
# from my_app.state_models import LoanApplicationState # Replace with your actual state model

async def launch_kyc_workflow(state: BaseModel, context: StepContext):
    """Launches KYC verification as a child workflow."""
    raise StartSubWorkflowDirective(
        workflow_type="KYC_Process", # Type defined in registry
        initial_data={
            "user_id": state.applicant_profile.user_id, # Assuming state has this structure
            "document_url": state.applicant_profile.id_document_url # Assuming state has this structure
        },
        data_region="eu-west-1" # Optional: route child to specific region
    )
```
The parent workflow will automatically transition to `PENDING_SUB_WORKFLOW` status. The child workflow's status changes are
then reported back to the parent, causing the parent's status to dynamically update to reflect the child's state.

**Parent Workflow Statuses during Sub-Workflow Execution:**

*   `PENDING_SUB_WORKFLOW` : The child workflow has been dispatched and is currently active or processing.
*   `FAILED_CHILD_WORKFLOW` : The child workflow encountered an error and failed. The parent's metadata will contain
    `failed_child_id` and `failed_child_status`.
*   `WAITING_CHILD_HUMAN_INPUT` : The child workflow has paused, waiting for human input. The parent's metadata will
    contain `waiting_child_id` and `waiting_child_step`.

**Accessing Sub-Workflow Results:**

When a child workflow successfully completes, its final state (and any explicit result returned by its last step) will be merged into
the parent's state within `parent.state.sub_workflow_results`. This dictionary is keyed by the child workflow's ID.

```python
# Assuming LoanApplicationState and processing results
from pydantic import BaseModel
from rufus.models import StepContext
from typing import Dict, Any

async def process_kyc_results(state: BaseModel, context: StepContext):
    """Processes results from the completed KYC sub-workflow."""
    # Access the child's full final state
    # Replace '<child_workflow_id>' with the actual child workflow ID or derive it from context
    kyc_final_state = state.sub_workflow_results.get('<child_workflow_id>', {}).get('state', {})

    # Or, if the child returned an explicit final result from its last step:
    kyc_final_result = state.sub_workflow_results.get('<child_workflow_id>', {}).get('final_result', {})

    if kyc_final_state.get('kyc_status') == "APPROVED":
        if hasattr(state, 'kyc_approved'): # Assuming kyc_approved exists in state
            state.kyc_approved = True
        return {"message": "KYC approved."}
    else:
        if hasattr(state, 'kyc_approved'): # Assuming kyc_approved exists in state
            state.kyc_approved = False
        return {"message": "KYC review required."}
```
## 7. Dynamic Step Injection

Dynamic step injection allows you to modify the workflow's sequence of steps at runtime based on current state or business rules.

**YAML Example:**

```yaml
steps:
  - name: "Evaluate_Risk_Score"
    type: "STANDARD"
    function: "my_app.risk.evaluate"
    dynamic_injection:
      rules:
        - condition_key: "risk_level" # Path in workflow state
          value_match: "high"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert: # Steps to be injected
            - name: "Manual_Review"
              type: "HUMAN_IN_LOOP"
              function: "my_app.human.request_review"
            - name: "Notify_Fraud_Team"
              type: "FIRE_AND_FORGET"
              target_workflow_type: "FraudNotification"
```
**Rule Properties:**

*   `condition_key`: (Required) A dot-notation path within the workflow state (e.g., "user.profile.age").
*   `value_match`: (Conditional) Inject if `condition_key` equals this value.
*   `value_is_not`: (Conditional) Inject if `condition_key` does NOT equal any of these values.
*   `action`: (Required) Currently only "INSERT_AFTER_CURRENT" is supported.
*   `steps_to_insert`: (Required) A list of step configurations to insert.

## 8. HTTP Step Configuration

The HTTP step type allows your workflow to interact with any external service without writing custom Python wrappers.

```yaml
steps:
  - name: "Fetch_Product_Details"
    type: "HTTP"
    method: "GET"
    url: "https://api.ecommerce.com/products/{{state.product_id}}" # Templating with Jinja2 syntax
    headers:
      Authorization: "Bearer {{secrets.ECOMMERCE_API_TOKEN}}" # Access secrets
      Content-Type: "application/json"
    query_params: # Optional: query parameters
      locale: "en-US"
    body: # Optional: request body (will be JSON for json/application-json content types)
      some_field: "some_value"
    output_key: "product_api_response" # Key to store the response in workflow state
    includes: ["body", "status_code"] # Optional: Filter response fields to save
    retry_policy: # Optional: specific retry policy for this step
      max_attempts: 3
      delay_seconds: 5
    timeout_seconds: 30 # Optional: timeout for the HTTP request
```
**Templating:**

*   Uses Jinja2-like syntax (`{{variable}}`) for dynamic values in `url`, `headers`, `body`, and `query_params`.
*   Context for templating is the entire workflow state and available secrets.

## 9. Advanced Node Types (The "Gears")

These nodes provide high-level control flow and orchestration capabilities.

### FIRE_AND_FORGET

Spawns an independent workflow that runs in the background without pausing the current workflow. The parent workflow only
retains a reference (ID) to the spawned workflow.

```yaml
steps:
  - name: "Send_Confirmation_Email"
    type: "FIRE_AND_FORGET"
    target_workflow_type: "EmailDelivery" # Workflow to spawn
    initial_data_template: # Initial data for the spawned workflow
      user_id: "{{state.user.id}}"
      email_type: "order_confirmation"
      recipient: "{{state.user.email}}"
```
### LOOP

Executes a sequence of steps repeatedly.

**Iterate Mode (Lists)**

```yaml
steps:
  - name: "Process_Order_Items"
    type: "LOOP"
    mode: "ITERATE"
    iterate_over: "state.order_details.items" # Path to a list in the workflow state
    item_var_name: "current_item" # Variable name for each item within loop_body context
    max_iterations: 100 # Safety limit
    loop_body: # Steps to execute for each item
      - name: "Update_Inventory"
        type: "STANDARD"
        function: "my_app.inventory.update_stock"
      - name: "Apply_Discount"
        type: "STANDARD"
        function: "my_app.pricing.apply_item_discount"
```
**While Mode (Conditions)**

```yaml
steps:
  - name: "Poll_API_Until_Ready"
    type: "LOOP"
    mode: "WHILE"
    while_condition: "state.api_status != 'READY'" # Condition to continue loop
    max_iterations: 10 # Safety limit
    loop_body:
      - name: "Call_Status_Endpoint"
        type: "HTTP"
        method: "GET"
        url: "https://api.example.com/status"
        output_key: "api_status_response"
      - name: "Extract_Status"
        type: "STANDARD"
        function: "my_app.utils.extract_api_status"
```
### CRON_SCHEDULER

Registers a new recurring workflow schedule. Requires an `ExecutionProvider` that supports scheduling (e.g.,
`CeleryExecutor` integrated with Celery Beat).

```yaml
steps:
  - name: "Schedule_Weekly_Report"
    type: "CRON_SCHEDULER"
    schedule_name: "weekly_report_for_user_{{state.user_id}}" # Unique name for the schedule
    cron_expression: "0 9 * * MON" # Standard cron expression (e.g., "0 9 * * MON" for 9 AM every Monday)
    target_workflow_type: "GenerateReport" # Workflow to be triggered
    initial_data_template: # Initial data for the triggered workflow
      user_id: "{{state.user_id}}"
      report_period: "last_week"
```
## 10. Common Patterns

### Pattern 1: Approval Chain

```yaml
steps:
  - name: "Request_Manager_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.approvals.request_manager_approval"
  - name: "Check_Manager_Decision"
    type: "DECISION"
    function: "my_app.approvals.check_manager_decision"
    routes:
      - condition: "state.manager_decision == 'APPROVED'"
        next_step: "Process_Director_Approval"
      - default: "Notify_Rejection"
```
### Pattern 2: Retry with Exponential Backoff (in Async Steps)

Retry logic is typically handled within the `ExecutionProvider` or within the Celery task itself using libraries like `tenacity`.

```python
# my_app/tasks.py
from celery import shared_task
from tenacity import retry, stop_after_attempt, wait_exponential
import requests
from typing import Dict, Any

# Ensure to import any state models you are using
from pydantic import BaseModel 

@shared_task(bind=True)
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
async def call_external_api_with_retry(self, workflow_id: str, state_data: Dict[str, Any], context_data: Dict[str, Any]):
    # This function would typically load the workflow state and context within the task
    # For demonstration, we assume state_data and context_data are passed directly.
    # In a real scenario, you might re-hydrate the workflow here.
    
    # ... logic to call API ...
    response = requests.post("https://api.example.com/unreliable", json=state_data)
    response.raise_for_status()
    return response.json()
```
### Pattern 3: Scatter-Gather

```yaml
steps:
  - name: "Dispatch_To_Services"
    type: "PARALLEL"
    tasks:
      - name: "Call_Service_A"
        function: "my_app.services.call_service_a"
      - name: "Call_Service_B"
        function: "my_app.services.call_service_b"
    merge_function_path: "my_app.utils.merge_service_results" # Custom function to combine results
```
## 11. Best Practices & Critical Warnings

### ⚠️ Executor Portability - CRITICAL

**THE PROBLEM**: Step functions must be **stateless and process-isolated** to work across all execution providers.

Developers often test with `SyncExecutionProvider` (single process, shared memory) and deploy with `CeleryExecutor` (distributed, fresh process per task). Code that works locally breaks in production because:

- **SyncExecutor**: All steps run in the same Python process. Global variables, module-level state, and in-memory caches are shared.
- **CeleryExecutor/ThreadPoolExecutor**: Each step runs in a separate worker process/thread. No shared memory.

**❌ BREAKS in Distributed Execution:**

```python
# Global state lost between steps
global_cache = {}

def step_a(state: MyState, context: StepContext):
    global_cache['user_data'] = fetch_user(state.user_id)
    return {}

def step_b(state: MyState, context: StepContext):
    user_data = global_cache['user_data']  # KeyError in Celery!
    return {"name": user_data['name']}

# Module-level state lost
_connection = None

def step_c(state: MyState, context: StepContext):
    global _connection
    if _connection is None:
        _connection = create_db_connection()
    _connection.query(...)  # Different worker, _connection is None!
```

**✅ WORKS Everywhere:**

```python
# Store in workflow state - persisted to database
def step_a_correct(state: MyState, context: StepContext):
    user_data = fetch_user(state.user_id)
    state.user_data = user_data  # Persisted
    return {"user_data": user_data}

def step_b_correct(state: MyState, context: StepContext):
    user_data = state.user_data  # Loaded from database
    return {"name": user_data['name']}

# Create resources per step
def step_c_correct(state: MyState, context: StepContext):
    connection = create_db_connection()  # New connection each time
    result = connection.query(...)
    return {"query_result": result}
```

**Golden Rules**:
1. **Store everything in workflow state** - `state.field = value` persists
2. **Return data from steps** - Return dict merges into state
3. **No global variables** - Each step is isolated
4. **No module-level state** - Don't rely on `_module_var`
5. **Create resources per step** - DB connections, API clients created and cleaned up within each step

**Test for Portability**:
```python
@pytest.mark.parametrize("executor", [
    SyncExecutionProvider(),
    ThreadPoolExecutionProvider()  # Tests process isolation
])
def test_workflow_portable(executor):
    builder = WorkflowBuilder(execution_provider=executor)
    workflow = builder.create_workflow("MyWorkflow", initial_data={...})
    # Should work with both executors
```

---

### ⚠️ Dynamic Injection - USE WITH EXTREME CAUTION

**THE PROBLEM**: Dynamic step injection makes workflows **non-deterministic** and extremely hard to debug.

When workflows modify their own structure at runtime:
1. **Debugging Difficulty**: Audit logs show steps not in YAML
2. **Compensation Complexity**: Saga rollback must track injected steps
3. **Non-Determinism**: Same workflow type + different data = different execution
4. **Version Control**: Can't reconstruct execution from Git history
5. **Audit Compliance**: Harder to prove regulatory compliance

**When to Use** (Rare cases ONLY):
- Plugin systems (steps defined by external packages)
- Multi-tenant workflows (tenants provide custom logic)
- A/B testing (controlled experiments)
- Dynamic compliance (jurisdiction-specific rules)

**Recommended Alternatives** (Use these instead):

**1. DECISION Steps with Explicit Routes**:
```yaml
- name: "Check_Order_Value"
  type: "DECISION"
  function: "steps.check_order_value"
  routes:
    - condition: "state.amount > 10000"
      target: "High_Value_Review"  # Visible in YAML!
    - condition: "state.amount <= 10000"
      target: "Standard_Processing"

- name: "High_Value_Review"  # Explicit step
  type: "STANDARD"
  function: "steps.high_value_review"
```

**2. Conditional Logic Within Steps**:
```python
def process_order(state: OrderState, context: StepContext):
    if state.amount > 10000:
        perform_high_value_checks(state)
    else:
        perform_standard_checks(state)
    return {"processed": True}
```

**3. Multiple Workflow Versions**:
```yaml
# order_processing_standard.yaml
workflow_type: "OrderProcessing_Standard"

# order_processing_high_value.yaml
workflow_type: "OrderProcessing_HighValue"
```

---

### General Best Practices

**Idempotent Steps**:
Design step functions to be idempotent - they can be called multiple times without changing the result beyond the initial call. Critical for retries and recovery.

```python
def charge_payment(state: OrderState, context: StepContext):
    # Check if already charged
    if state.payment_id:
        return {"payment_id": state.payment_id, "already_charged": True}

    payment_id = payment_api.charge(state.amount, idempotency_key=context.workflow_id)
    state.payment_id = payment_id
    return {"payment_id": payment_id}
```

**Small, Focused Steps**:
Each step should do one thing well. Improves readability, testability, and reusability.

**Clear State Models**:
Define Pydantic state models clearly, ensuring they represent the evolving data accurately.

```python
class OrderState(BaseModel):
    order_id: str
    amount: Decimal
    payment_id: Optional[str] = None  # Set after payment
    shipment_id: Optional[str] = None  # Set after shipment
    status: str = "pending"
```

**Version Control YAML**:
Treat workflow YAML files as code. Store in Git, use pull requests for changes, and include in CI/CD.

**Logging and Observability**:
Integrate with WorkflowObserver to gain insights, debug issues, and monitor performance.

**Leverage Package Auto-Discovery**:
When creating reusable components, package them as `rufus-*` extensions. The SDK's auto-discovery will load them automatically.

**Validate Workflows**:
Use the CLI validator to catch errors early:

```bash
# Basic validation
rufus validate workflow.yaml

# Strict validation (includes import checks)
rufus validate workflow.yaml --strict
```

**Performance Considerations**:
- Use PostgreSQL connection pooling in production
- Enable uvloop for async I/O performance
- Use orjson for faster JSON serialization
- Cache step function imports (automatic)

---

## 12. Troubleshooting YAML Configuration

### Common Errors

*   Error: Workflow type 'MyWorkflow' not found in registry : Ensure your workflow is listed in
    `workflow_registry.yaml` and the type matches exactly.
*   ImportError: cannot import name 'my_function' : Verify the function or `input_model` paths in your YAML
    match the actual Python module structure and are importable from your application's Python path.
*   Missing 'steps' section : Ensure your workflow YAML file has a `steps` key with a list of step definitions.
*   Dynamic injection condition not triggering : Double-check `condition_key` and `value_match` (or
    `value_is_not`) for exact values and correct paths in state.

### Validation

Use the Rufus CLI to validate your YAML files:

```bash
rufus validate config/my_workflow.yaml
```
## Changelog
- **Version 0.1.0 (Initial Release)**
  - Core SDK
  - Persistence Provider
  - Execution Provider
  - Workflow Observer
  - Expression Evaluator
  - Template Engine

## Missing Features
- **API Models:** The API models used in `rufus_server/api_models.py` have not been directly reviewed for their alignment with the SDK's internal data structures. While assumed correct, a dedicated review would ensure full consistency.

## Further Considerations
- **Documentation completeness**: While the content now generally aligns, a thorough review of the newly added documentation sections (CLI, Test Harness, etc.) and cross-referencing all examples will ensure full coverage and accuracy.
- **Provider implementations**: The example code now correctly uses `PostgresPersistenceProvider` and `RedisPersistenceProvider`, as well as `CeleryExecutor` and `ThreadPoolExecutorProvider`. It's important to ensure these are consistently reflected across all documentation that refers to providers.
- **`sdk-plan.md`**: All tasks outlined in the `sdk-plan.md` regarding code migration have been completed. The remaining documentation task is being addressed incrementally.
- **Auto-discovery for marketplace packages:** The `rufus-slack` package and `cookiecutter` template have been created as examples. Ensuring that the auto-discovery mechanism correctly integrates and loads these external steps is important for the marketplace ecosystem.
- **Testing**: While `WorkflowTestHarness` has been implemented, it is recommended to ensure comprehensive test coverage for all new features and updated components to maintain stability and reliability.
- **Error Handling and Edge Cases**: A thorough review of error handling and edge cases across the entire SDK, especially in `WorkflowEngine` and provider implementations, is crucial for production readiness.

This concludes the comprehensive review of the provided `USAGE_GUIDE.md` against the current SDK.