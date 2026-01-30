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

### 8.1 Polyglot Workflows (HTTP Steps)

HTTP steps enable **polyglot workflows** - Python-orchestrated workflows that integrate with services written in any programming language. This is the primary mechanism for multi-language support in Rufus.

#### Architecture Overview

```
┌─────────────────────────────────────────┐
│     Rufus Workflow Engine (Python)      │
│         Orchestration Layer             │
└───────────┬─────────────────────────────┘
            │ HTTP/REST
            ▼
┌─────────────────────────────────────────┐
│     External Services (Any Language)    │
│  ├─ Go microservices                    │
│  ├─ Rust ML inference                   │
│  ├─ Node.js notification services       │
│  ├─ Java enterprise APIs                │
│  └─ Any HTTP-speaking service           │
└─────────────────────────────────────────┘
```

#### Multi-Language Pipeline Example

```yaml
workflow_type: "PolyglotDataPipeline"
description: "Process data using services in multiple languages"
initial_state_model: "my_app.models.PipelineState"

steps:
  # Python: Data validation and business logic
  - name: "Validate_Input"
    type: "STANDARD"
    function: "my_app.steps.validate_input"
    automate_next: true

  # Go Service: High-performance concurrent processing
  - name: "Process_Data_Go"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://go-processor:8080/api/process"
      headers:
        Content-Type: "application/json"
        X-Request-ID: "{{state.request_id}}"
      body:
        data: "{{state.validated_data}}"
        options:
          concurrency: 100
          batch_size: 1000
      timeout: 60
    output_key: "go_processing_result"
    automate_next: true

  # Rust Service: Machine learning inference
  - name: "ML_Inference_Rust"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://rust-ml-service:8080/predict"
      headers:
        Content-Type: "application/json"
      body:
        features: "{{state.go_processing_result.features}}"
        model_version: "v2.1"
      timeout: 30
    output_key: "ml_prediction"
    automate_next: true

  # Node.js: Send real-time notifications
  - name: "Notify_User_Node"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://notification-service:3000/api/notify"
      headers:
        Content-Type: "application/json"
        Authorization: "Bearer {{secrets.NOTIFICATION_API_KEY}}"
      body:
        user_id: "{{state.user_id}}"
        channel: "email"
        template: "processing_complete"
        data:
          result: "{{state.ml_prediction.result}}"
          confidence: "{{state.ml_prediction.confidence}}"
    automate_next: true

  # Python: Final business logic and state update
  - name: "Finalize_Processing"
    type: "STANDARD"
    function: "my_app.steps.finalize_processing"
```

#### Third-Party API Integration

```yaml
steps:
  # Stripe: Payment processing
  - name: "Create_Payment_Intent"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "https://api.stripe.com/v1/payment_intents"
      headers:
        Authorization: "Bearer {{secrets.STRIPE_SECRET_KEY}}"
        Content-Type: "application/x-www-form-urlencoded"
      body:
        amount: "{{state.amount_cents}}"
        currency: "usd"
        customer: "{{state.stripe_customer_id}}"
    output_key: "stripe_payment"
    automate_next: true

  # Twilio: SMS notification
  - name: "Send_SMS"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "https://api.twilio.com/2010-04-01/Accounts/{{secrets.TWILIO_SID}}/Messages.json"
      headers:
        Authorization: "Basic {{secrets.TWILIO_AUTH_BASE64}}"
        Content-Type: "application/x-www-form-urlencoded"
      body:
        To: "{{state.customer_phone}}"
        From: "{{secrets.TWILIO_PHONE}}"
        Body: "Payment of ${{state.amount}} received. Thank you!"
    automate_next: true

  # SendGrid: Email notification
  - name: "Send_Email"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "https://api.sendgrid.com/v3/mail/send"
      headers:
        Authorization: "Bearer {{secrets.SENDGRID_API_KEY}}"
        Content-Type: "application/json"
      body:
        personalizations:
          - to:
              - email: "{{state.customer_email}}"
        from:
          email: "noreply@example.com"
        subject: "Payment Confirmation"
        content:
          - type: "text/plain"
            value: "Your payment of ${{state.amount}} has been processed."
```

#### Microservices Orchestration Pattern

```yaml
workflow_type: "OrderFulfillment"
steps:
  # Inventory Service (Go)
  - name: "Reserve_Inventory"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://inventory-service:8080/api/reserve"
      body:
        items: "{{state.order_items}}"
        reservation_id: "{{state.order_id}}"
      timeout: 10
    output_key: "inventory_reservation"
    automate_next: true

  # Pricing Service (Rust)
  - name: "Calculate_Final_Price"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://pricing-service:8080/api/calculate"
      body:
        items: "{{state.order_items}}"
        customer_id: "{{state.customer_id}}"
        promotions: "{{state.applied_promotions}}"
      timeout: 5
    output_key: "pricing_result"
    automate_next: true

  # Payment Service (Java)
  - name: "Process_Payment"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://payment-service:8080/api/charge"
      body:
        customer_id: "{{state.customer_id}}"
        amount: "{{state.pricing_result.total}}"
        payment_method: "{{state.payment_method_id}}"
        idempotency_key: "{{state.order_id}}"
      timeout: 30
    output_key: "payment_result"
    automate_next: true

  # Shipping Service (Node.js)
  - name: "Create_Shipment"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://shipping-service:3000/api/shipments"
      body:
        order_id: "{{state.order_id}}"
        items: "{{state.order_items}}"
        address: "{{state.shipping_address}}"
        carrier_preference: "{{state.carrier_preference}}"
    output_key: "shipment"
```

#### Error Handling in Polyglot Workflows

```yaml
steps:
  - name: "Call_External_Service"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://external-service/api/process"
      body: "{{state.data}}"
      timeout: 30
      retry_policy:
        max_attempts: 3
        delay_seconds: 2
        backoff_multiplier: 2
    output_key: "service_response"
    automate_next: true

  - name: "Check_Response"
    type: "DECISION"
    function: "steps.check_service_response"
    routes:
      - condition: "state.service_response.status_code >= 400"
        target: "Handle_Error"
      - condition: "state.service_response.body.status == 'failed'"
        target: "Handle_Error"
      - default: "Continue_Processing"

  - name: "Handle_Error"
    type: "STANDARD"
    function: "steps.handle_service_error"
    automate_next: false  # Manual intervention may be needed
```

#### When to Use Polyglot Workflows

**Ideal Use Cases:**
- Integrating existing microservices in different languages
- Leveraging language-specific strengths (Go for concurrency, Rust for ML)
- Third-party API integrations (Stripe, Twilio, SendGrid, etc.)
- Legacy system integration via REST APIs
- Multi-team architectures with different tech stacks

**Best Practices:**
1. **Keep orchestration in Python** - Business logic and control flow in the workflow engine
2. **Use HTTP steps for external calls** - Any language that speaks HTTP can be integrated
3. **Implement idempotency** - External services should handle duplicate requests gracefully
4. **Use service discovery** - Don't hardcode URLs in production
5. **Configure appropriate timeouts** - Different services have different latency profiles
6. **Handle errors gracefully** - Check response status codes and body for errors
7. **Use retry policies** - Transient failures are common in distributed systems

**Performance Considerations:**
- HTTP steps add network latency compared to Python steps
- Use connection pooling in high-throughput scenarios
- Consider gRPC for performance-critical polyglot calls (planned feature)
- Batch multiple operations where possible

### 8.2 JavaScript Steps (Embedded V8)

JavaScript steps provide **in-process polyglot execution** - data transformation and business logic written in JavaScript/TypeScript that runs directly within the workflow engine using an embedded V8 runtime (PyMiniRacer).

#### Architecture Overview

```
┌─────────────────────────────────────────┐
│     Rufus Workflow Engine (Python)      │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │   Embedded V8 Runtime (PyMiniRacer)  │
│  │   ├─ JavaScript execution       │    │
│  │   ├─ TypeScript transpilation   │    │
│  │   └─ Sandboxed environment      │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

**Key Benefits:**
- Zero network latency (in-process execution)
- Strong sandboxing (V8 isolates)
- TypeScript support with esbuild transpilation
- Access to workflow state and context
- Built-in utility functions (rufus.*)

#### Installation

```bash
# Install py-mini-racer for V8 JavaScript execution
pip install py-mini-racer

# Optional: Install esbuild for TypeScript support
npm install -g esbuild
# or
pip install esbuild
```

#### Basic Usage - Inline Code

```yaml
steps:
  - name: "Calculate_Discount"
    type: "JAVASCRIPT"
    js_config:
      code: |
        const items = state.items;
        const subtotal = items.reduce((sum, item) => sum + item.price * item.quantity, 0);
        const discount = subtotal > 100 ? 0.1 : 0;
        const total = subtotal * (1 - discount);
        return {
          subtotal: rufus.round(subtotal, 2),
          discount_percent: discount * 100,
          total: rufus.round(total, 2)
        };
      timeout_ms: 5000
    output_key: "pricing"
    automate_next: true
```

#### File-Based Scripts (Recommended)

**Workflow YAML:**
```yaml
steps:
  - name: "Transform_Data"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/transform.js"
      timeout_ms: 10000
      memory_limit_mb: 128
    automate_next: true
```

**scripts/transform.js:**
```javascript
// Workflow state is available as `state`
// Step context is available as `context`

const users = state.raw_users;

// Transform user data
const transformed = users.map(user => ({
  id: user.id,
  fullName: `${user.first_name} ${user.last_name}`.trim(),
  email: user.email.toLowerCase(),
  createdAt: rufus.formatDate(user.created_at, 'iso'),
  isActive: user.status === 'active'
}));

// Group by active status
const grouped = rufus.groupBy(transformed, 'isActive');

// Log for debugging (captured in workflow logs)
rufus.log(`Processed ${transformed.length} users`);

return {
  users: transformed,
  active_count: grouped.true?.length || 0,
  inactive_count: grouped.false?.length || 0
};
```

#### TypeScript Support

**Workflow YAML:**
```yaml
steps:
  - name: "Process_Order"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/process-order.ts"
      typescript: true  # Auto-detected from .ts extension
      tsconfig_path: "./tsconfig.json"  # Optional
    automate_next: true
```

**scripts/process-order.ts:**
```typescript
interface OrderItem {
  product_id: string;
  quantity: number;
  unit_price: number;
}

interface OrderState {
  items: OrderItem[];
  customer_id: string;
  discount_code?: string;
}

// Type-safe access to workflow state
const order = state as unknown as OrderState;

// Calculate totals with type safety
const calculateTotal = (items: OrderItem[]): number => {
  return items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
};

const subtotal = calculateTotal(order.items);
const discount = order.discount_code ? 0.1 : 0;
const total = subtotal * (1 - discount);

return {
  subtotal,
  discount,
  total,
  item_count: order.items.length
};
```

#### Available Context

JavaScript steps have access to:

```javascript
// Workflow state (read-only, frozen)
state.user_id       // Access state fields
state.items[0].price // Nested access

// Step context (read-only, frozen)
context.workflow_id    // Current workflow ID
context.step_name      // Current step name
context.workflow_type  // Workflow type
```

#### Built-in Utilities (rufus.*)

The `rufus` object provides common utility functions:

```javascript
// Logging (captured for audit)
rufus.log("Info message");
rufus.warn("Warning message");
rufus.error("Error message");

// Date/Time
rufus.now();          // ISO timestamp
rufus.timestamp();    // Unix timestamp
rufus.formatDate(date, 'iso|date|time');
rufus.addDays(date, 5);
rufus.diffDays(date1, date2);

// Identifiers
rufus.uuid();         // Generate UUID v4

// Math
rufus.round(3.14159, 2);   // 3.14
rufus.clamp(15, 0, 10);    // 10
rufus.sum([1, 2, 3]);      // 6
rufus.avg([1, 2, 3]);      // 2
rufus.min([1, 2, 3]);      // 1
rufus.max([1, 2, 3]);      // 3

// Strings
rufus.slugify("Hello World");   // "hello-world"
rufus.truncate("Long text", 5); // "Lo..."
rufus.capitalize("hello");      // "Hello"
rufus.camelCase("user_name");   // "userName"
rufus.snakeCase("userName");    // "user_name"

// Objects
rufus.pick(obj, ['a', 'b']);    // Pick specific keys
rufus.omit(obj, ['c']);         // Omit specific keys
rufus.get(obj, 'a.b.c', default); // Deep get with default
rufus.set(obj, 'a.b.c', value); // Deep set (returns new object)
rufus.merge(obj1, obj2);        // Shallow merge

// Arrays
rufus.unique([1, 1, 2]);        // [1, 2]
rufus.flatten([[1], [2]]);      // [1, 2]
rufus.chunk([1, 2, 3, 4], 2);   // [[1, 2], [3, 4]]
rufus.groupBy(arr, 'key');      // Group by key
rufus.sortBy(arr, 'key');       // Sort by key
rufus.first(arr, n);            // First n elements
rufus.last(arr, n);             // Last n elements
rufus.compact([0, 1, null, 2]); // [1, 2]

// Validation
rufus.isEmail("test@example.com");  // true
rufus.isURL("https://...");         // true
rufus.isUUID("...");                // true
rufus.isEmpty(value);               // true/false
rufus.isNumber(value);
rufus.isString(value);
rufus.isArray(value);
rufus.isObject(value);

// Type conversion
rufus.toNumber("42", 0);       // 42
rufus.toString(value);         // String
rufus.toBoolean(value);        // Boolean
rufus.toArray(value);          // Array

// JSON
rufus.parseJSON(str);          // Parse or null
rufus.stringify(obj, pretty);  // JSON string
```

#### Configuration Options

```yaml
js_config:
  # Script source (one required)
  script_path: "scripts/process.js"  # Path to .js or .ts file
  # OR
  code: "return { value: state.x * 2 };"  # Inline code

  # Execution limits
  timeout_ms: 5000          # Max execution time (100-300000ms)
  memory_limit_mb: 128      # Max V8 heap size (16-1024MB)

  # TypeScript options
  typescript: false         # Force TypeScript (auto-detected from .ts)
  tsconfig_path: null       # Path to tsconfig.json

  # Output
  output_key: null          # Key to store result (default: merge at root)

  # Advanced
  strict_mode: true         # JavaScript strict mode
```

#### Security

JavaScript steps run in a sandboxed V8 environment with:

1. **Blocked Globals**: `eval`, `Function`, `setTimeout`, `require`, `process`, etc.
2. **Frozen Prototypes**: Prevents prototype pollution attacks
3. **Read-Only State**: Workflow state cannot be modified directly
4. **Resource Limits**: Timeout and memory limits enforced
5. **No I/O**: No file system, network, or process access

#### Use Cases

**1. Data Transformation:**
```yaml
- name: "Transform_API_Response"
  type: "JAVASCRIPT"
  js_config:
    code: |
      const response = state.api_response;
      return {
        users: response.data.users.map(u => ({
          id: u.id,
          name: u.full_name,
          active: u.status === 'active'
        })),
        total: response.pagination.total_count
      };
```

**2. Validation Logic:**
```yaml
- name: "Validate_Order"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/validate-order.js"
  automate_next: true

- name: "Handle_Validation"
  type: "DECISION"
  routes:
    - condition: "state.validation.is_valid"
      target: "Process_Order"
    - default: "Reject_Order"
```

**3. Complex Calculations:**
```yaml
- name: "Calculate_Pricing"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/pricing-engine.ts"
    typescript: true
    timeout_ms: 10000
```

#### JavaScript vs HTTP Steps

| Feature | JavaScript Steps | HTTP Steps |
|---------|------------------|------------|
| Latency | ~5-50ms (in-process) | 50-500ms+ (network) |
| Language | JavaScript/TypeScript | Any HTTP service |
| Use Case | Data transformation, business logic | External services, APIs |
| Security | V8 sandbox | Network isolation |
| Dependencies | py-mini-racer | None |

**When to Use JavaScript Steps:**
- Data transformation and mapping
- Complex calculations
- Validation logic
- Business rules
- JSON manipulation
- When Python performance is sufficient but JS is preferred

**When to Use HTTP Steps:**
- External API calls
- Services in other languages (Go, Rust, Java)
- Third-party integrations (Stripe, Twilio)
- Long-running operations
- When you need language-specific libraries

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

## 12. Production Reliability Features

Rufus includes production-grade features to handle worker crashes and workflow definition changes.

### 12.1 Zombie Workflow Recovery

Automatically detect and recover workflows where the worker crashed during execution.

**Quick Start - CLI**:
```bash
# Scan for zombie workflows (dry-run)
rufus scan-zombies --db postgresql://localhost/rufus

# Fix zombies automatically
rufus scan-zombies --db postgresql://localhost/rufus --fix

# Run continuous monitoring daemon
rufus zombie-daemon --db postgresql://localhost/rufus --interval 60
```

**Programmatic Usage**:
```python
from rufus.zombie_scanner import ZombieScanner
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

# Setup
persistence = PostgresPersistenceProvider("postgresql://localhost/rufus")
await persistence.initialize()

scanner = ZombieScanner(persistence, stale_threshold_seconds=120)

# One-shot scan and recover
summary = await scanner.scan_and_recover(dry_run=False)
print(f"Recovered {summary['zombies_recovered']} zombie workflows")
```

**Heartbeat Configuration**:
```python
from rufus.heartbeat import HeartbeatManager

# Heartbeats are automatic via execution provider
# For custom execution logic:
async def my_step(state: MyState, context: StepContext):
    heartbeat = HeartbeatManager(
        persistence=context.persistence,
        workflow_id=context.workflow_id,
        heartbeat_interval_seconds=30
    )

    async with heartbeat:  # Auto-start and cleanup
        result = await long_running_operation()
        return {"result": result}
```

**Production Deployment**:

Option 1: Cron job (simple):
```bash
*/5 * * * * rufus scan-zombies --db $DATABASE_URL --fix >> /var/log/zombie-scanner.log 2>&1
```

Option 2: Systemd daemon (recommended):
```ini
[Unit]
Description=Rufus Zombie Scanner Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/rufus zombie-daemon --db postgresql://localhost/rufus
Restart=always

[Install]
WantedBy=multi-user.target
```

Option 3: Kubernetes CronJob:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rufus-zombie-scanner
spec:
  schedule: "*/5 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            image: myapp/rufus:latest
            command: ["rufus", "scan-zombies", "--db", "$(DATABASE_URL)", "--fix"]
```

**Configuration Guidelines**:

| Step Duration | Heartbeat Interval | Stale Threshold | Scan Interval |
|---------------|-------------------|-----------------|---------------|
| < 1 minute    | 15s               | 60s             | 30s           |
| 1-10 minutes  | 30s               | 120s            | 60s           |
| 10+ minutes   | 60s               | 300s            | 120s          |

**Key Rule**: Stale Threshold > 2 × Heartbeat Interval

### 12.2 Workflow Versioning

Protect running workflows from breaking YAML changes using automatic definition snapshots.

**How It Works**:
1. WorkflowBuilder snapshots complete YAML on workflow creation
2. Snapshot stored in database with workflow
3. Running workflows use their snapshot (immune to YAML changes)
4. New workflows use latest YAML

**Automatic (No Code Changes)**:
```python
# Snapshotting is automatic
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"order_id": "123"}
)

# Snapshot automatically stored
assert workflow.definition_snapshot is not None
```

**Explicit Versioning (Recommended)**:
```yaml
# config/order_processing.yaml
workflow_type: "OrderProcessing"
workflow_version: "2.0.0"  # Bump for breaking changes
initial_state_model: "my_app.models.OrderState"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "my_app.steps.validate"
```

**Breaking Changes Strategy**:

Option A: Update YAML in place (snapshot protects running workflows):
```yaml
# Before (v1.0.0)
steps:
  - name: "Human_Approval"  # Step exists
  - name: "Process_Payment"

# After (v2.0.0)
steps:
  # Human_Approval removed - running workflows still have it via snapshot!
  - name: "Process_Payment"
```

Running workflows created with v1.0.0:
- ✅ Still have "Human_Approval" (from snapshot)
- ✅ Complete successfully

New workflows created after deploy:
- ✅ Use v2.0.0 (no "Human_Approval")
- ✅ Follow new process

Option B: Explicit versioning with separate YAMLs:
```yaml
# config/order_processing_v1.yaml (keep for compatibility)
workflow_type: "OrderProcessing_v1"
workflow_version: "1.0.0"

# config/order_processing_v2.yaml (new deployments)
workflow_type: "OrderProcessing_v2"
workflow_version: "2.0.0"
```

**Checking Snapshots**:
```python
# Load workflow and inspect snapshot
workflow = await persistence.load_workflow(workflow_id)
snapshot = workflow['definition_snapshot']

print(f"Workflow version: {snapshot.get('workflow_version')}")
print(f"Steps: {[s['name'] for s in snapshot['steps']]}")
```

**Storage Overhead**:
- ~5-10 KB per workflow (typical)
- PostgreSQL: Compressed JSONB
- SQLite: TEXT

**Best Practices**:
- ✅ Always bump `workflow_version` for breaking changes
- ✅ Use semantic versioning (MAJOR.MINOR.PATCH)
- ✅ Test YAML changes on staging first
- ✅ Keep old YAMLs until running workflows complete (or rely on snapshots)
- ❌ Don't make breaking changes without version bump
- ❌ Don't delete workflow definitions immediately after deploy

---

## 13. Troubleshooting YAML Configuration

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