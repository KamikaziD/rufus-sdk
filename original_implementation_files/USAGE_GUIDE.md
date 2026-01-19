# Confucius Workflow Engine - Usage Guide

This comprehensive guide will walk you through all aspects of using the Confucius workflow orchestration engine, from basic concepts to advanced patterns.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Core Concepts](#core-concepts)
3. [Creating Your First Workflow](#creating-your-first-workflow)
4. [Step Types](#step-types)
5. [Working with State](#working-with-state)
6. [Advanced Features](#advanced-features)
7. [Real-World Examples](#real-world-examples)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

## Getting Started

### Prerequisites

- Docker and Docker Compose (Recommended)
- Python 3.10+ (if running locally without Docker)

### Installation & Running (Docker - Recommended)

The easiest way to run Confucius with all its dependencies (PostgreSQL, Redis, Celery) is using Docker Compose.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/confucius.git
    cd confucius
    ```

2.  **Start the stack:**
    ```bash
    docker-compose up --build
    ```

    This will start:
    *   **Postgres**: Primary database for workflow state (ACID compliant).
    *   **Redis**: Broker for Celery tasks and Pub/Sub events.
    *   **API**: The FastAPI backend (`http://localhost:8000`).
    *   **Celery Worker**: Processes async tasks and sub-workflows.
    *   **Migrate**: Runs database migrations on startup.

3.  **Access the UI:**
    Open `http://localhost:8000` in your browser to access the Workflow Debug UI.

### Running Locally (Development Mode)

If you prefer to run services locally:

1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    pip install -e .
    ```

2.  **Start Redis:**
    ```bash
    docker run -d -p 6379:6379 redis:alpine
    ```

3.  **Start Celery:**
    ```bash
    celery -A celery_setup worker --loglevel=info
    ```

4.  **Run the API:**
    ```bash
    uvicorn main:app --reload
    ```

## Core Concepts

### Workflows

A **workflow** is a series of steps that execute in sequence (or conditionally) to accomplish a business process. Each workflow has:

- A unique **type** (e.g., "LoanApplication", "UserOnboarding")
- A **state** - data that persists throughout execution (Pydantic model)
- A list of **steps** - units of work to be executed
- A **status** - indicates the current execution state

### Workflow States

| Status | Description |
|--------|-------------|
| `ACTIVE` | Workflow is running and ready for the next step |
| `PENDING_ASYNC` | Waiting for an async task to complete |
| `PENDING_SUB_WORKFLOW` | Waiting for a child workflow to complete |
| `WAITING_HUMAN` | Paused, awaiting human input |
| `COMPLETED` | All steps finished successfully |
| `FAILED` | An error occurred during execution |
| `FAILED_ROLLED_BACK` | Failed and saga compensation successfully rolled back changes |

### Steps

A **step** is a single unit of work in a workflow. Steps can:
- Execute synchronous Python functions
- Dispatch async tasks to Celery workers
- Run multiple tasks in parallel
- Pause for human review
- Launch sub-workflows (nested execution)
- Make decisions and branch the workflow

### State Management

Each workflow has a **state** - a Pydantic model that holds all the data for that workflow execution. The state:
- Is validated on every update
- Persists between step executions (stored in Postgres/Redis)
- Can be accessed and modified by any step
- Is serialized to JSON for storage and API responses

## Creating Your First Workflow

Let's build a simple customer onboarding workflow step by step.

### Step 1: Define the State Model

Create or edit `state_models.py`:

```python
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class CustomerOnboardingState(BaseModel):
    # Required inputs
    full_name: str = Field(..., min_length=2)
    email: EmailStr
    phone: str

    # Fields populated during workflow
    customer_id: Optional[str] = None
    account_created: bool = False
    welcome_email_sent: bool = False
    status: str = "pending"
    error_message: Optional[str] = None
```

### Step 2: Implement Step Functions

Create or edit `workflow_utils.py`:

```python
from confucius.workflow import WorkflowPauseDirective
import uuid

def validate_customer_info(state):
    """Validate the customer's basic information"""
    if len(state.phone) < 10:
        raise ValueError("Invalid phone number")
    return {"status": "validated"}

def create_customer_account(state):
    """Create the customer account in the database"""
    customer_id = f"CUST-{uuid.uuid4().hex[:8].upper()}"
    return {
        "customer_id": customer_id,
        "account_created": True,
        "status": "account_created"
    }

def request_identity_verification(state):
    """Pause workflow for identity verification"""
    # Pauses the workflow until /resume is called
    raise WorkflowPauseDirective({
        "message": f"Please verify identity for {state.full_name}",
        "customer_id": state.customer_id,
        "status": "awaiting_verification"
    })

def process_verification_result(state, decision: str, reviewer_id: str):
    """Process the verification decision"""
    if decision == "approved":
        return {
            "status": "verified",
            "verification_reviewer": reviewer_id
        }
    else:
        return {
            "status": "rejected",
            "error_message": "Identity verification failed"
        }

def send_welcome_email(state):
    """Send welcome email to customer"""
    print(f"Sending welcome email to {state.email}")
    return {
        "welcome_email_sent": True,
        "status": "completed"
    }
```

### Step 3: Define the Workflow in YAML

Create `config/customer_onboarding.yaml`:

```yaml
workflow_type: "CustomerOnboarding"
workflow_version: "1.0"
initial_state_model: "state_models.CustomerOnboardingState"

steps:
  - name: "Validate_Customer_Info"
    type: "STANDARD"
    function: "workflow_utils.validate_customer_info"
    automate_next: true  # Automatically proceed to next step

  - name: "Create_Customer_Account"
    type: "STANDARD"
    function: "workflow_utils.create_customer_account"
    automate_next: true

  - name: "Request_Identity_Verification"
    type: "HUMAN_IN_LOOP"
    function: "workflow_utils.request_identity_verification"
    # Workflow pauses here until human input

  - name: "Process_Verification_Result"
    type: "STANDARD"
    function: "workflow_utils.process_verification_result"
    automate_next: true

  - name: "Send_Welcome_Email"
    type: "STANDARD"
    function: "workflow_utils.send_welcome_email"
```

### Step 4: Register the Workflow

Edit `config/workflow_registry.yaml`:

```yaml
workflows:
  # ... existing workflows ...

  - type: "CustomerOnboarding"
    description: "Customer onboarding workflow with identity verification"
    config_file: "config/customer_onboarding.yaml"
    initial_state_model: "state_models.CustomerOnboardingState"
```

### Step 5: Execute the Workflow

#### Via REST API:

```bash
# 1. Start the workflow
curl -X POST http://localhost:8000/api/v1/workflow/start \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_type": "CustomerOnboarding",
    "initial_data": {
      "full_name": "Jane Doe",
      "email": "jane.doe@example.com",
      "phone": "555-0123"
    }
  }'

# 2. Monitor status/Advance via Debug UI (http://localhost:8000)
#    Or use the /next and /resume endpoints as needed.
```

## Step Types

### 1. STANDARD Steps
Execute synchronously. Good for simple logic, DB updates, or API calls that are fast (< 1s).

### 2. ASYNC Steps
Dispatch to Celery. Essential for long-running operations (PDF generation, heavy AI inference, slow 3rd party APIs).

### 3. PARALLEL Steps
Run multiple Celery tasks concurrently. Great for independent checks (e.g., Credit Check + Fraud Check).

### 4. DECISION Steps
Evaluate state and jump to different steps. Used for branching logic.

### 5. HUMAN_IN_LOOP Steps
Pause execution for manual approval or data entry.

### 6. SUB-WORKFLOW Steps
Launch a child workflow. The parent pauses (`PENDING_SUB_WORKFLOW`) until the child completes. Results are merged back to the parent.

### 7. HTTP Steps
Native support for calling external REST APIs. Supports templating from workflow state and response filtering.

## Working with State

Steps update the workflow state by returning a dictionary. Keys in the dictionary are merged into the state.

**Example:**
```python
def my_step(state):
    # state is a Pydantic model instance
    return {"status": "processed", "result_code": 200}
```

## Advanced Features

### 1. HTTP Integration (Polyglot Support)
Confucius allows you to orchestrate services written in any language via the `HTTP` step type.

**Example:**
```yaml
- name: "Fetch_External_Data"
  type: "HTTP"
  method: "GET"
  url: "https://api.example.com/items/{item_id}"
  headers:
    Authorization: "Bearer {auth_token}"
  includes: ["body", "status_code"] # Only save body and status
  output_key: "api_data"
```

The engine will:
1. Replace `{item_id}` and `{auth_token}` with values from the current state.
2. Execute the request in a background Celery worker.
3. Extract `body` and `status_code` from the response.
4. Save them to `state.api_data`.

### 2. Saga Pattern (Distributed Transactions)
Confucius supports the Saga pattern to handle failures in distributed systems. If a workflow fails, it can execute "compensation" functions in reverse order to undo changes.

**Enable it:** Call `workflow.enable_saga_mode()` at startup.
**Configure it:** Add `compensate_function: "path.to.undo_func"` in YAML.

### 3. Sub-Workflows (Recursive Execution)
Break complex processes into reusable components.
- **Parent:** Uses `StartSubWorkflowDirective` to launch a child.
- **Child:** Runs independently.
- **Engine:** Automatically handles pausing the parent and resuming it when the child finishes.

### 4. Dynamic Step Injection
Modify the workflow at runtime based on data.
- Use `dynamic_injection` rules in YAML to insert steps if specific conditions are met (e.g., "Risk Score > 90" -> Insert "Enhanced Due Diligence").

### 5. Automated Step Chaining
Set `automate_next: true` in YAML to make the engine automatically execute the next step upon completion. This allows for fast, multi-step execution without network round-trips for every step.

### 6. Declarative Routing
Define branching logic directly in YAML without custom Python code.

```yaml
- name: "Route_User"
  type: "DECISION"
  routes:
    - condition: "user.age >= 18 AND country == 'US'"
      next_step: "Adult_US_Flow"
    - default: "Global_Flow"
```

### 7. Scheduled Workflows (Cron)
Configure workflows to run automatically on a schedule.

1.  Add `schedule` to your workflow registry config.
2.  Define the initial data.

```yaml
# workflow_registry.yaml
workflows:
  - type: "DailyReport"
    schedule: "0 0 * * *" # Run at midnight
    initial_data:
      report_type: "full"
```

The system uses `Celery Beat` to trigger these workflows. Ensure the `celery_beat` container is running.

### 8. Worker Configuration (Hybrid Cloud)
The Worker Registry allows you to run workers in different locations (e.g., cloud regions, on-premise data centers) and assign them specific capabilities. This is crucial for data sovereignty and auditability.

You can configure a worker's identity using environment variables when you launch it:

- **`WORKER_ID`**: A unique, static name for this worker (e.g., `on-premise-worker-1`). This ensures the worker has a stable identity in the registry.
- **`WORKER_REGION`**: The geographical or logical region of the worker (e.g., `eu-central-1`, `us-gov-west`).
- **`WORKER_ZONE`**: A more specific location within a region (e.g., `secure-enclave`, `availability-zone-a`).
- **`WORKER_CAPABILITIES`**: A JSON string describing the worker's attributes (e.g., `'{"gpu": true, "pii_access": true}'`).

**Example `docker-compose.override.yml` for an on-premise worker:**
```yaml
services:
  worker-on-premise:
    build: .
    command: celery -A confucius.celery_app worker --loglevel=info -Q on-premise
    environment:
      # Connect to the central Postgres/Redis
      DATABASE_URL: "postgresql://confucius:secretpassword@<central_db_host>:5432/confucius"
      CELERY_BROKER_URL: "redis://<central_redis_host>:6379/0"
      # Define worker identity
      WORKER_ID: "on-premise-worker-gpu-1"
      WORKER_REGION: "on-premise-frankfurt"
      WORKER_ZONE: "secure-finance-cluster"
      WORKER_CAPABILITIES: '{"gpu": "true", "trained_on_pii": "false"}'
```
When this worker starts, it will register itself in the central `worker_nodes` table, providing a clear, auditable record of its existence and attributes.

## Best Practices

### Workflow Stuck in PENDING_ASYNC
*   **Cause**: Celery worker is down, queue is full, or task failed silently.
*   **Fix**: Check Celery logs (`docker-compose logs celery_worker`). Verify Redis connectivity. Use the `/retry` endpoint to restart the step.

### Workflow Stuck in PENDING_SUB_WORKFLOW
*   **Cause**: Child workflow failed or stalled.
*   **Fix**: Find the child ID (in parent's status response). Check the child's status. If child failed, retry the child. Parent will auto-resume when child completes.

### State Not Updating
*   **Cause**: Step function returned `None` or invalid keys.
*   **Fix**: Ensure your function returns a dictionary. Ensure keys match the Pydantic state model fields.

### "Another operation is in progress" (Postgres)
*   **Cause**: Concurrency issue in older versions.
*   **Fix**: We have implemented a `PostgresExecutor` to handle this. Ensure you are using the latest code (`git pull`).

---

For more details, see:
- [YAML Configuration Reference](YAML_GUIDE.md)
- [Technical Documentation](TECHNICAL_DOCUMENTATION.md)
- [API Reference](API_REFERENCE.md)