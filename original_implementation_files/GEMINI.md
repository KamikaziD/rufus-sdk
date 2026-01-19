# Confucius - AI Workflow Orchestration Platform

## Project Overview

Confucius is a production-grade, configuration-driven workflow engine built in Python. It orchestrates complex business processes using a declarative YAML-based approach, decoupling business logic from execution flow.

### Core Philosophy
*   **Declarative:** Workflows are defined in YAML, not code.
*   **Durable:** State is persisted in ACID-compliant PostgreSQL (production) or Redis (development).
*   **Observable:** Real-time visibility via WebSockets and audit logs.
*   **Resilient:** Built-in Saga pattern for distributed transactions and rollbacks.
*   **Scalable:** Async execution via Celery workers with atomic task claiming.

### Key Technologies
*   **FastAPI:** Async REST API and WebSocket handling.
*   **Celery:** Distributed task queue for async/parallel execution.
*   **PostgreSQL:** Primary persistence layer with JSONB state storage and `FOR UPDATE SKIP LOCKED` task queueing.
*   **Redis:** Message broker for Celery and Pub/Sub for real-time UI updates.
*   **Pydantic:** Robust data validation and serialization for workflow state.

## Architecture

The system is designed as a layered architecture:

1.  **API Layer (`routers.py`)**: Handles HTTP requests, input validation via Pydantic, and WebSocket connections. It delegates execution to the `Workflow` core.
2.  **Engine Layer (`workflow.py`)**: The brain of the system. Manages state transitions, executes steps, handles directives (Jump, Pause, Sub-Workflow), and orchestrates Sagas.
3.  **Persistence Layer (`persistence_postgres.py`)**: A robust factory-based persistence system. The PostgreSQL backend uses `asyncpg` with a dedicated `PostgresExecutor` thread to ensure safe, non-blocking database operations even within synchronous Celery tasks.
4.  **Execution Layer (`tasks.py`)**: Celery tasks that handle long-running operations (`ASYNC`), concurrent execution (`PARALLEL`), and sub-workflow management.

## Key Features

### 1. Workflow Primitives
*   **Standard Steps:** Synchronous execution.
*   **Async Steps:** Long-running background tasks.
*   **Parallel Steps:** Concurrent fan-out/fan-in.
*   **Decision Steps:** Conditional branching logic.
*   **Human-in-the-Loop:** Pauses for manual approval/input.
*   **Sub-Workflows:** Parent-child orchestration with state merging.
*   **HTTP Steps:** Native polyglot integration with external APIs.

### 2. Saga Pattern (Distributed Transactions)
Automatic rollback mechanism for ensuring data consistency across distributed services.
*   **Compensation:** Each step can define a `compensate_function`.
*   **Rollback:** On failure, the engine executes compensations in reverse order for all completed steps.
*   **Audit:** Detailed `compensation_log` tracks all rollback actions.

### 3. Dynamic Execution
*   **Dynamic Step Injection:** Inject new steps at runtime based on data conditions (e.g., "If risk > 90, insert Enhanced Due Diligence").
*   **Automated Chaining:** Steps configured with `automate_next: true` execute in rapid sequence without network round-trips.
*   **Declarative Routing:** Define complex branching logic (`credit > 700 AND risk == 'low'`) directly in YAML.
*   **HTTP Templating:** Inject state variables into URL, headers, and body using `{var.path}` syntax.

### 4. Observability
*   **Real-time Updates:** WebSocket push notifications for state changes.
*   **Audit Logging:** Comprehensive event log for compliance.
*   **Debug UI:** A rich web interface for visualizing steps, inspecting state, and driving workflows manually.

## Configuration

Workflows are defined in `config/` and registered in `workflow_registry.yaml`.

**Example Workflow:**
```yaml
workflow_type: "LoanApplication"
steps:
  - name: "Collect_Data"
    type: "STANDARD"
    function: "loan.collect"
    input_model: "state_models.LoanInput"

  - name: "Check_Credit"
    type: "ASYNC"
    function: "credit.check"
    compensate_function: "credit.void_check"

  - name: "Evaluate_Risk"
    type: "DECISION"
    routes:
      - condition: "credit_score > 700"
        next_step: "Approve"
      - default: "Reject"
```

## Developer Guide

### Running the System
The project is containerized using Docker Compose:
```bash
docker-compose up --build
```
This spins up API, Celery Worker, Redis, and Postgres.

### Running Tests
End-to-end tests validate the entire stack:
```bash
# Requires running stack
python tests/test_end_to_end.py
```

### Adding New Features
1.  **State:** Update `state_models.py`.
2.  **Logic:** Add functions to `workflow_utils.py` (or new modules).
3.  **Config:** Create/Update YAML in `config/`.
4.  **Register:** Update `workflow_registry.yaml`.

## Recent Updates (January 2026)
*   **Postgres Backend:** Replaced Redis as primary store for durability.
*   **Saga Support:** Added `CompensatableStep` and rollback logic.
*   **Sub-Workflow Fixes:** Resolved event loop conflicts in Celery using `PostgresExecutor`.
*   **Semantic Firewall:** Added input sanitization for XSS/SQLi protection.
*   **Intelligent Execution:** Added YAML-based declarative routing.
*   **Phase 8 - The Gears:** Added Loop Node, Fire-and-Forget Node, and Cron Scheduler Node.


## IMPORTANT RULES TO FOLLOW

1. Break complex task down into smaller manageable steps.
2. Please execute actions one by one, do not run tools in parallel.
3. Thing carefully about the task at hand.
4. If you change anything on the database make sure to check previous migrations and keep building on top of each other. If we need to drop the database because of structural changes then ask me for permission first.
5. Always check what the implication will be to the core workflow modules and persistence layer.
6. Always make sure updates don't break existing workflows. If a workflow breaks then implement the fix based on the new implementation.
7. If something is going to break because of a new implementation then let the user know before implementing.
8. Always research for the most up-to-date libraries and packages and documentation for correctness of implementation and staying on top of dependencies.
9. After we complete a feature or task, all related project documentation should be updated. (README.md, TECHNICAL_DOCUMENTATION.md, USAGE_GUIDE.md, YAML_GUIDE.md, API_REFERENCE.md, Project_Status_Audit.md)
10. Always update all tests to make sure nothing is broken.
