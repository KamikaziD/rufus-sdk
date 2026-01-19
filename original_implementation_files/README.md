# Confucius Workflow Orchestration Engine

Confucius is a powerful, production-ready workflow orchestration engine built with Python, designed for building complex, stateful business processes with ease. It combines the flexibility of YAML configuration with the robustness of Python and PostgreSQL, making it ideal for financial services, compliance workflows, and any domain requiring reliable, auditable process automation.

The engine is built on a modern stack, using FastAPI for its API layer, Celery for asynchronous tasks, and dual persistence backends (Redis for development, PostgreSQL for production). This project includes the core `confucius` library and a complete example application demonstrating its use.

## Key Features

### Core Capabilities
*   **Multiple Step Types**: Standard, Async, Parallel, Decision, Human-in-Loop, Sub-Workflow, and HTTP steps
*   **Saga Pattern Support**: Automatic rollback with compensation functions for distributed transactions
*   **Sub-Workflow Orchestration**: Parent-child workflow execution with state merging
*   **Polyglot Integration**: Orchestrate non-Python microservices (Node.js, Go, etc.) via native HTTP steps with templating
*   **Dynamic Step Injection**: Conditionally inject steps at runtime based on workflow state
*   **Declarative Routing**: Expression-based decision logic directly in YAML
*   **State Management**: Type-safe state with Pydantic validation
*   **Automated Step Chaining**: Configure steps to automatically execute in sequence

### Advanced Control Flow (The Gears)
*   **Loops**: Native `ITERATE` (for-each) and `WHILE` loops in YAML for batch processing
*   **Fire-and-Forget**: Spawn independent background workflows without blocking the parent
*   **Dynamic Scheduling**: Register new cron-based schedules dynamically from within a workflow step

### Persistence & Scalability
*   **Dual Persistence Backends**: Redis (development) and PostgreSQL (production)
*   **ACID Compliance**: PostgreSQL backend provides full transactional guarantees
*   **Worker Registry**: Passive registry for tracking worker nodes, their capabilities, and regions, enabling auditable hybrid-cloud deployments.
*   **Distributed Execution**: Celery-based async task processing with atomic task claiming
*   **Real-time Updates**: WebSocket support for live workflow monitoring
*   **Audit Trail**: Complete execution logging and compensation tracking
*   **Data Region Support**: Regional data sovereignty for compliance

### Developer Experience
*   **YAML Configuration**: Define workflows declaratively without code
*   **FastAPI Integration**: Modern async REST API with OpenAPI docs
*   **Type Safety**: Full Pydantic validation for inputs and state
*   **Debug UI**: Built-in web interface for workflow visualization
*   **Extensible**: Easy to add custom step types and behaviors
*   **Production-Ready**: Idempotency keys, metrics, and error recovery

## Getting Started

The project is structured as a Python package (`confucius`) located in the `src/` directory, with a surrounding example application. You will need Python 3.10+, Redis, and Celery.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/confucius.git
    cd confucius
    ```

2.  **Install the dependencies and the core package in editable mode:**
    This makes the `confucius` package importable by the example application.
    ```bash
    pip install -r requirements.txt
    pip install -e .
    ```

3.  **Start Redis:** (Using Docker is recommended)
    ```bash
    docker run -d --name redis-server -p 6379:6379 redis
    ```

4.  **Start the Celery Worker:**
    The worker is now started using the `celery_setup.py` file, which correctly configures the worker to discover tasks from both the core library and the example app.
    ```bash
    celery -A celery_setup worker --loglevel=info
    ```

5.  **Run the Example FastAPI Application:**
    ```bash
    uvicorn main:app --reload
    ```

## How to Use the Demo UI

Once the application is running, open your browser and navigate to `http://127.0.0.1:8000`. The redesigned UI provides a comprehensive interface for exploring the engine's features:

*   **Start a Workflow:** Use the central card to select a workflow, edit its initial JSON data, and click "Start Workflow". The UI will then transition to the main workflow interaction view.
*   **Workflow Monitoring (Top Section):**
    *   **Workflow Steps (Left):** This pane visually displays all steps in the workflow, highlighting the current step and marking completed ones.
    *   **Tabs (Right):** Switch between the "Real-time Log" (a live feed of events from the engine via WebSockets) and "Full State" (a raw JSON view of the entire workflow data object).
*   **Workflow Control (Bottom Section):** This persistent panel allows you to drive the workflow.
    *   It displays the workflow's ID and current status.
    *   The current step's name is shown, along with a dynamically generated form (if input is required), built directly from the step's Pydantic model.
    *   Action buttons like "Next Step" or "Submit Review" appear here.
    *   A "Retry Failed Step" button becomes visible if the workflow enters a `FAILED` state, allowing for easy debugging and re-attempts.
    *   The "Start New" button in the header allows you to return to the workflow selection at any time.

## Project Structure

The project is divided into two main parts: the core `confucius` library and the example application that uses it.

### Core Library (`src/confucius/`)

This is the reusable, installable package containing the workflow engine.

*   **`workflow.py`**: Contains the core classes for the workflow engine (`Workflow`, `WorkflowStep`, etc.).
*   **`workflow_loader.py`**: The `WorkflowBuilder` class, which reads and parses YAML files to build `Workflow` objects.
*   **`persistence.py`**: Handles saving and loading workflow state to Redis.
*   **`routers.py`**: A factory function (`get_workflow_router`) that returns a pre-built FastAPI router for the workflow API.
*   **`tasks.py`**: Core Celery tasks for resuming workflows after async/parallel steps.
*   **`contrib/`**: Contains optional add-ons, such as the importable debug UI.

### Example Application (Root Directory)

These files demonstrate how to use the `confucius` library.

*   **`main.py`**: A minimal FastAPI application that initializes the `WorkflowBuilder`, and imports and includes the API and debug UI routers from the `confucius` package.
*   **`workflow_utils.py`**: A collection of functions that represent the actual "work" to be done at each step (e.g., `run_credit_check_agent`). These are the functions referenced in the YAML files.
*   **`celery_worker.py`**: Defines any application-specific Celery tasks.
*   **`state_models.py`**: Defines the Pydantic models for the state of each example workflow.
*   **`config/`**: The directory containing all YAML workflow definitions for the example application.

## Adding a New Workflow to the Example App

1.  **Define the State (if new):** Create a new Pydantic `BaseModel` in `state_models.py`.
2.  **Implement Step Functions:** Add the business logic functions for your new workflow in `workflow_utils.py`. If they are long-running, make them Celery tasks.
3.  **Create the Workflow YAML:** Create a new file in the `config/` directory and define its steps, referencing the functions from `workflow_utils.py`.
4.  **Register the Workflow:** Add your new workflow to `config/workflow_registry.yaml`.

The engine will automatically discover and make the new workflow available through the API and the debug UI.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Application                      │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────┐             │
│  │  REST API  │  │  WebSocket  │  │   Debug UI   │             │
│  └────────────┘  └─────────────┘  └──────────────┘             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────────┐
│                    Workflow Engine Core                          │
│  ┌─────────────────┐    ┌──────────────────┐                   │
│  │ Workflow.py     │───▶│ WorkflowLoader   │                   │
│  │ - Step Execution│    │ - YAML Parser    │                   │
│  │ - State Mgmt    │    │ - Step Builder   │                   │
│  │ - Saga Logic    │    └──────────────────┘                   │
│  └─────────────────┘                                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────────┐
│                    Persistence Layer                             │
│  ┌──────────┐                        ┌──────────────┐           │
│  │  Redis   │  (Development)         │ PostgreSQL   │           │
│  │  - Fast  │                        │ - ACID       │           │
│  │  - Simple│                        │ - Audit Log  │           │
│  └──────────┘                        │ - Metrics    │           │
│                                      └──────────────┘           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────────┐
│                    Async Execution Layer                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Celery Workers (with Redis/RabbitMQ broker)            │   │
│  │  - Async Steps    - Parallel Steps    - Sub-Workflows   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Advanced Features

### Saga Pattern
Automatic compensation on failure for distributed transactions:

```yaml
steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "inventory.reserve_items"
    compensate_function: "inventory.release_items"  # Runs on rollback
```

### Sub-Workflows
Launch child workflows that pause the parent until completion:

```python
from confucius.workflow import StartSubWorkflowDirective

def launch_kyc(state):
    raise StartSubWorkflowDirective(
        workflow_type="KYC",
        initial_data={"user_name": state.applicant_name}
    )
```

### Dynamic Step Injection
Conditionally add steps based on runtime state:

```yaml
dynamic_injection:
  rules:
    - condition_key: "risk_level"
      value_match: "high"
      action: "INSERT_AFTER_CURRENT"
      steps_to_insert:
        - name: "Additional_Verification"
          type: "ASYNC"
          function: "verification.enhanced_check"
```

## Production Deployment

### PostgreSQL Setup

```bash
# Run migrations
psql $DATABASE_URL < migrations/001_init_postgresql_schema.sql

# Set environment variable
export WORKFLOW_STORAGE=postgres
export DATABASE_URL=postgresql://user:pass@localhost:5432/workflows

# Migrate existing workflows from Redis (optional)
python -c "from confucius.persistence import migrate_redis_to_postgres; migrate_redis_to_postgres()"
```

### Docker Deployment

A `docker-compose.yml` file is provided to run the entire stack.

```yaml
# docker-compose.yml (simplified)
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: confucius
      POSTGRES_USER: confucius
      POSTGRES_PASSWORD: secretpassword
    ports:
      - "5432:5432"

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  api:
    build: .
    depends_on: [postgres, redis]
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://confucius:secretpassword@postgres:5432/confucius
      - CELERY_BROKER_URL=redis://redis:6379/0
      # ... and other env vars

  celery_worker:
    build: .
    depends_on: [postgres, redis]
    command: celery -A confucius.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://confucius:secretpassword@postgres:5432/confucius
      - CELERY_BROKER_URL=redis://redis:6379/0
      - WORKER_ID=default-worker-1 # For worker registry
      # ... and other env vars
```

## Documentation

- **[Usage Guide](USAGE_GUIDE.md)** - Comprehensive tutorial with real-world examples
- **[YAML Configuration Reference](YAML_GUIDE.md)** - Complete YAML syntax documentation
- **[Technical Documentation](TECHNICAL_DOCUMENTATION.md)** - Architecture deep-dive and internals
- **[API Reference](API_REFERENCE.md)** - REST API and Python API documentation

## Use Cases

- **Financial Services**: Loan applications, KYC verification, compliance reviews
- **Customer Onboarding**: Multi-step signup with approvals and document verification
- **Order Processing**: E-commerce orders with inventory, payment, and fulfillment
- **Content Moderation**: AI-powered review with human escalation
- **Data Pipelines**: ETL workflows with error recovery and compensation

## Contributing

Contributions are welcome! Please see our contributing guidelines.

## License

MIT License - see LICENSE file for details

---

Built with Python, FastAPI, PostgreSQL, Celery, and Redis.