# YAML Guide

This guide provides a reference for the Rufus workflow YAML format.

## Top-Level Keys

| Key             | Type   | Description                               |
| --------------- | ------ | ----------------------------------------- |
| `workflow_type` | String | **Required.** The unique name for this workflow definition. |
| `steps`         | Array  | **Required.** A list of step objects that define the workflow. |
| `data_regions`    | Object | Optional. Defines data regions for state isolation. |

## Step Object

Each object in the `steps` array defines a single unit of work.

| Key                   | Type   | Description                                                                                                                             |
| --------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                | String | **Required.** A unique name for the step within the workflow.                                                                            |
| `type`                | String | **Required.** The type of the step. See "Step Types" below.                                                                            |
| `function`            | String | The function to execute for this step, in the format `module_name.function_name`. Required for most step types.                         |
| `next_step`           | String | The name of the next step to execute upon successful completion.                                                                        |
| `compensate_function` | String | The function to execute if a Saga rollback is triggered.                                                                                |
| `input_model`         | String | The Pydantic model to use for validating the step's input state.                                                                        |
| `output_model`        | String | The Pydantic model to use for validating the step's output state.                                                                       |
| `routes`              | Array  | For `DECISION` steps, a list of routing rules.                                                                                           |
| `workflow`            | String | For `SUB_WORKFLOW` steps, the `workflow_type` of the child workflow to execute.                                                          |
| `items`               | String | For `PARALLEL` steps, a reference to a list in the workflow state to iterate over (e.g., `{state.my_list}`).                             |
| `timeout`             | Number | For `PARALLEL` steps, the maximum time in seconds to wait for all child tasks to complete.                                              |
| `on_timeout`          | String | For `PARALLEL` steps, the action to take on timeout (`fail` or `proceed`).                                                              |
| `merge_function`      | String | For `PARALLEL` steps, an optional custom function to merge results from parallel branches.                                               |

## Step Types

| Type           | Description                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------------- |
| `STANDARD`     | A synchronous step that executes a Python function.                                                      |
| `DECISION`     | A step that routes the workflow to a different next step based on conditions.                              |
| `SUB_WORKFLOW` | A step that executes a child workflow and merges the result back into the parent.                        |
| `PARALLEL`     | A step that executes a function concurrently for each item in a list.                                    |
| `ASYNC`        | A step that executes a long-running task in the background using an async executor like Celery.              |
| `HTTP`         | A step that makes an HTTP request to an external service.                                                |
| `PAUSE`        | A step that pauses the workflow for human-in-the-loop (HITL) intervention.                                 |
| `LOOP`         | A step that repeatedly executes a block of steps until a condition is met.                                 |
| `CRON`         | A step that schedules a workflow to run at a specific time or interval.                                  |
| `FIRE_FORGET`  | A step that triggers an action without waiting for a response.                                           |
