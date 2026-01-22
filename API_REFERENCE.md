# API Reference

This document provides a reference for the public API of the Rufus SDK.

## `rufus.WorkflowEngine`

The main entry point for interacting with the workflow engine.

### `__init__(self, persistence, executor, observer=None, logger=None, expression_evaluator=None, templating_engine=None)`

Initializes the workflow engine with pluggable providers.

*   **`persistence`**: An instance of a `PersistenceProvider` (e.g., `InMemoryPersistence`, `PostgresPersistence`).
*   **`executor`**: An instance of an `ExecutionProvider` (e.g., `SyncExecutor`, `CeleryExecutor`).
*   **`observer`**: An optional `ObserverProvider` for metrics and logging.
*   **`logger`**: An optional custom logger.
*   **`expression_evaluator`**: An optional `ExpressionEvaluatorProvider`.
*   **`templating_engine`**: An optional `TemplatingEngineProvider`.

### `start_workflow(self, workflow_type, initial_state)`

Starts a new workflow instance.

*   **`workflow_type`** (str): The type of the workflow to start.
*   **`initial_state`** (dict): The initial data for the workflow state.
*   **Returns**: A `WorkflowHandle` object.

### `get_workflow_handle(self, instance_id)`

Retrieves a handle to an existing workflow instance.

*   **`instance_id`** (str): The unique ID of the workflow instance.
*   **Returns**: A `WorkflowHandle` object.

### `register_workflow(self, workflow_definition)`

Registers a workflow definition from a YAML string or a dictionary.

*   **`workflow_definition`** (str or dict): The workflow definition.

### `register_step_module(self, module_name, module_instance)`

Registers a Python module or class instance containing step functions.

*   **`module_name`** (str): The name to use for the module in the YAML definition.
*   **`module_instance`**: The instance of the class or module.

## `rufus.WorkflowHandle`

A handle to a specific workflow instance, used to interact with it.

### `get_state(self)`

Returns the current state of the workflow.

*   **Returns**: A dictionary representing the workflow state.

### `get_status(self)`

Returns the current status of the workflow.

*   **Returns**: A string (e.g., `RUNNING`, `COMPLETED`, `FAILED`, `PAUSED`).

### `resume(self, input_data=None)`

Resumes a paused workflow.

*   **`input_data`** (dict): Optional data to merge into the workflow state before resuming.
