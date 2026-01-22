# Confucius: Workflow Engine Documentation

This document provides a detailed look into the configuration-driven workflow approach of this project, how it operates, and its core API.

## 1. How It Works: The Lifecycle of a Workflow

The key feature of this platform is that workflows are not defined in Python code, but in YAML files. This allows for modifying business logic without deployments. Here is the lifecycle of a typical workflow:

1.  **Loading:** When the application starts, the `WorkflowBuilder` in `workflow_loader.py` reads the master registry (`config/workflow_registry.yaml`) to understand all available workflow types.

2.  **Starting:** A user or system initiates a workflow via the API (`POST /api/v1/workflow/start`), providing a `workflow_type` and `initial_data`.
    *   The `WorkflowBuilder` finds the matching entry in the registry.
    *   It reads the corresponding workflow definition YAML (e.g., `config/loan_workflow.yaml`).
    *   It dynamically imports the specified Pydantic state model (e.g., `state_models.LoanApplicationState`).
    *   It constructs a new `Workflow` instance, populating it with the steps defined in the YAML and the initial state.
    *   The new workflow object is serialized and saved to Redis.

3.  **Executing:** The user calls the `/next` endpoint to advance the workflow.
    *   The `Workflow` object is loaded from Redis.
    *   It executes the current step's function (as defined in the YAML).
    *   The `type` of the step in the YAML determines *how* it's executed (e.g., `STANDARD`, `ASYNC`, `PARALLEL`, `HUMAN_IN_LOOP`).
    *   For `ASYNC` or `PARALLEL` steps, tasks are dispatched to Celery, and the workflow's status is set to `PENDING_ASYNC`. A callback task is chained to resume the workflow upon completion.
    *   The workflow checks for any `dynamic_injection` rules that might insert new steps based on the result of the current one.
    *   The updated workflow object (with its new state, current step, and potentially new injected steps) is saved back to Redis.

4.  **Completion:** The process repeats until the final step is executed, at which point the workflow's status is set to `COMPLETED`.

## 2. Core Workflow API

The core of the workflow engine is exposed through a FastAPI application. The API provides endpoints for managing the lifecycle of a workflow. These endpoints are provided by an importable router factory (`get_workflow_router`) within the `confucius` package.

### API Endpoints

*   **`GET /api/v1/workflows`**:
    *   **Description:** Returns a list of all available workflows defined in `config/workflow_registry.yaml`.
    *   **Response:** A JSON array of workflow objects, including `type`, `description`, and an example of the `initial_data` structure.

*   **`POST /api/v1/workflow/start`**:
    *   **Description:** Initializes and starts a new workflow based on its YAML configuration.
    *   **Request Body:**
        *   `workflow_type` (str): The type of workflow to start (e.g., "LoanApplication").
        *   `initial_data` (dict): The initial data to populate the workflow's Pydantic state model.
    *   **Response:** A JSON object with the `workflow_id`, `current_step_name`, and initial `status`.

*   **`POST /api/v1/workflow/{workflow_id}/next`**:
    *   **Description:** Advances a workflow in an `ACTIVE` state to its next step.
    *   **Request Body:** `input_data` (dict) containing any data required for the current step.
    *   **Response:** A `WorkflowStepResponse` object with the result of the step, the `next_step_name`, and the workflow's updated state and status. If the step is async, it will return a `202 Accepted` status.

*   **`GET /api/v1/workflow/{workflow_id}/current_step_info`**:
    *   **Description:** Retrieves information about the current step, including its input requirements. This is key for building dynamic user interfaces.
    *   **Response:** A JSON object containing the step `name`, its `type`, and an `input_schema` (the JSON Schema of the Pydantic model) if the step requires input.

*   **`GET /api/v1/workflow/{workflow_id}/status`**:
    *   **Description:** Retrieves the current status and state of any workflow. While useful for auditing, for real-time UI updates, the WebSocket endpoint is preferred.
    *   **Response:** A JSON object with the `workflow_id`, `status`, `current_step_name`, and the complete `state` object.

*   **`WEBSOCKET /api/v1/workflow/{workflow_id}/subscribe`**:
    *   **Description:** Opens a WebSocket connection to receive real-time state updates for a specific workflow. The server will immediately push the current state upon connection and then push a new state object every time the workflow is updated. This is the recommended way to monitor workflow progress in a UI.

*   **`POST /api/v1/workflow/{workflow_id}/resume`**:
    *   **Description:** Resumes a workflow that is paused in the `WAITING_HUMAN` state.
    *   **Request Body:** The data submitted by the human reviewer (e.g., `decision`, `reviewer_id`, `comments`).
    *   **Response:** A `WorkflowStepResponse` indicating the result of the human decision and the next step in the workflow.

*   **`POST /api/v1/workflow/{workflow_id}/retry`**:
    *   **Description:** Retries a workflow that has entered a `FAILED` state. It resets the status to `ACTIVE`, allowing the failed step to be re-run.
    *   **Response:** A `WorkflowStatusResponse` with the workflow's updated status.

## 3. Use Cases for the Workflow-Driven Approach

This section explores the application of the configuration-driven workflow approach in various sectors.

### 3.1. Finance
*   **AI-Powered Underwriting:** An advanced workflow that uses AI agents to perform credit checks and fraud detection in parallel. The workflow can then use a `DECISION` step to make an initial approval and, if necessary, use `dynamic_injection` to add a human underwriting review step. This is the example `loan_workflow.yaml` in this project.
*   **Algorithmic Trading:** A workflow that ingests real-time market data, uses an AI agent to identify trading opportunities, and executes trades.
*   **Personalized Financial Advisory:** A workflow that onboards a new client, uses an AI agent to analyze their financial goals, and generates a personalized investment plan.

### 3.2. Healthcare
*   **AI-Assisted Diagnosis:** A workflow that takes a patient's symptoms, uses an `ASYNC` step to have an AI agent analyze the data against a medical knowledge base, and provides a list of potential diagnoses to a doctor for review (`HUMAN_IN_LOOP`).
*   **Personalized Treatment Plans:** A workflow that uses an AI agent to analyze a patient's genomic data and medical history to create a personalized treatment plan.
*   **Automated Clinical Trials:** A workflow that manages a clinical trial, from recruiting patients to collecting data and monitoring for adverse events.

### 3.3. E-commerce
*   **Personalized Shopping Experience:** A workflow that uses an AI agent to analyze a customer's browsing history to provide personalized product recommendations.
*   **Dynamic Pricing:** A workflow that uses an AI agent to monitor competitor prices and demand to dynamically adjust product prices.
*   **Automated Returns Processing:** A workflow that allows a customer to initiate a return, uses an AI agent with OCR to verify the item, and automatically processes the refund.

---

## 💡 Potential Use Cases for the Platform

This platform is best suited for complex, multi-step processes that involve decision-making, external services, and human oversight.

| Domain | Use Case | Key Features Utilized | Description |
| :--- | :--- | :--- | :--- |
| **Finance & Banking** | **Loan/Mortgage Underwriting** | `DECISION`, `PARALLEL`, `HUMAN_IN_LOOP` | Orchestrates credit/fraud checks (parallel agents), runs risk models, and pauses for a human underwriter's final approval. Branches applications to different paths based on risk score. |
| **Legal & Compliance** | **Regulatory Document Review (KYC)** | `ASYNC`, `PARALLEL`, `HUMAN_IN_LOOP` | Manages the full Know Your Customer (KYC) lifecycle. Runs sanctions checks and database lookups concurrently. Requires a final compliance officer sign-off. |
| **Manufacturing & QA** | **Automated Quality Inspection** | `PARALLEL`, `DECISION`, `ASYNC` | Images from an assembly line are sent to multiple vision agents (defect, color, dimensional analysis) in parallel. If a defect is found, it branches to a human operator for manual rework notification. |
| **Healthcare & Pharma** | **Clinical Trial Data Processing** | `Pydantic`, `dynamic_injection` | Ingests raw patient data. `Pydantic` state models ensure data validity. An initial agent determines the necessary analysis and **dynamically injects** new steps into the workflow. |
| **Software Development** | **Autonomous Code Review & Deployment** | `PARALLEL`, `dynamic_injection`, `HUMAN_IN_LOOP` | On a pull request, the workflow triggers parallel agents (static analysis, security scan, test coverage). If a high-severity vulnerability is flagged, it **dynamically injects** a step forcing a human security review. |

---

## Conclusion

The platform's strength lies in its ability to **impose structure and reliability** on systems composed of independent, specialized AI agents. By managing the **state, concurrency, and decision logic** in declarative YAML files, it ensures that complex business processes are auditable, fault-tolerant, and highly adaptable.
