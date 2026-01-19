# Confucius REST API Reference

This document provides a reference for the REST API endpoints exposed by the Confucius workflow engine.

## Authentication

The API can be configured to use token-based authentication. When enabled, requests must include the following headers:
- `X-User-ID`: The ID of the user making the request.
- `X-Org-ID`: (Optional) The ID of the user's organization for multi-tenancy.

## Endpoints

### Workflow Management

#### `POST /api/v1/workflow/start`
Starts a new workflow instance.

**Request Body:**
```json
{
  "workflow_type": "LoanApplication",
  "initial_data": {
    "application_id": "L12345",
    "requested_amount": 15000.50
  },
  "data_region": "eu-west-1"
}
```
- `workflow_type` (string, required): The type of workflow to start, as defined in the registry.
- `initial_data` (object, required): The initial state data for the workflow.
- `data_region` (string, optional): The data region to assign to this workflow for data sovereignty.

**Response (200 OK):**
```json
{
  "workflow_id": "...",
  "current_step_name": "Collect_Data",
  "status": "ACTIVE"
}
```

#### `POST /api/v1/workflow/{workflow_id}/next`
Executes the next step of an active workflow.

**Request Body:**
```json
{
  "input_data": {
    "social_security_number": "..."
  }
}
```
- `input_data` (object, optional): Data required by the current step.

**Responses:**
- **200 OK**: The step executed synchronously.
- **202 Accepted**: The step was an `ASYNC` or `PARALLEL` step and has been dispatched to a Celery worker.

**Response Body (200 OK):**
```json
{
  "workflow_id": "...",
  "current_step_name": "Collect_Data",
  "next_step_name": "Run_Credit_Check",
  "status": "ACTIVE",
  "state": { ... },
  "result": { "message": "Data collected" }
}
```

#### `POST /api/v1/workflow/{workflow_id}/resume`
Resumes a workflow that is in the `WAITING_HUMAN` state.

**Request Body:**
```json
{
  "decision": "approved",
  "reviewer_id": "admin-01",
  "notes": "Looks good."
}
```
- The body should contain the data expected by the step following the human-in-the-loop pause.

**Response (200 OK):**
- Same as `/next`.

#### `POST /api/v1/workflow/{workflow_id}/retry`
Retries a workflow that is in the `FAILED` state.

**Response (200 OK):**
- Returns the new status of the workflow.

#### `GET /api/v1/workflow/{workflow_id}/status`
Retrieves the current status and state of a workflow.

**Response (200 OK):**
```json
{
  "workflow_id": "...",
  "workflow_type": "LoanApplication",
  "status": "ACTIVE",
  "current_step_name": "Run_Credit_Check",
  "parent_execution_id": null,
  "blocked_on_child_id": null,
  "state": { ... }
}
```

### Workflow Information

#### `GET /api/v1/workflows`
Returns a list of all available workflow types from the registry, including sample initial data.

#### `GET /api/v1/workflow/{workflow_id}/current_step_info`
Returns information about the current step, including its name, type, and the JSON schema for its required input.

### Administration & Observability

These endpoints require the PostgreSQL backend.

#### `GET /api/v1/admin/workers`
Lists all registered worker nodes from the `worker_nodes` table.

**Query Parameters:**
- `limit` (int, optional, default: 100): Maximum number of workers to return.

**Response (200 OK):**
```json
[
  {
    "worker_id": "onsite-london-1",
    "hostname": "worker-container-2",
    "region": "onsite-london",
    "zone": "secure-zone-1",
    "capabilities": {
      "gpu": true,
      "pii_access": true
    },
    "status": "online",
    "last_heartbeat": "2026-01-14T12:00:00Z",
    "updated_at": "2026-01-14T12:00:00Z"
  },
  {
    "worker_id": "default-worker-1",
    "hostname": "worker-container-1",
    "region": "default",
    "zone": "default",
    "capabilities": {},
    "status": "online",
    "last_heartbeat": "2026-01-14T12:00:05Z",
    "updated_at": "2026-01-14T12:00:05Z"
  }
]
```

#### `GET /api/v1/workflow/{workflow_id}/audit`
Retrieves the audit trail for a specific workflow execution.

#### `GET /api/v1/workflow/{workflow_id}/logs`
Retrieves execution logs for a specific workflow execution.

#### `GET /api/v1/workflow/{workflow_id}/metrics`
Retrieves performance metrics for a specific workflow execution.

#### `GET /api/v1/workflows/executions`
Lists recent workflow executions, with optional filtering by status.

#### `GET /api/v1/metrics/summary`
Returns an aggregated summary of workflow executions over a given time period.
