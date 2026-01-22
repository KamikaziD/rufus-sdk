# Rufus - Workflow SDK for Python

## Project Overview

Rufus is a Python-based, SDK-first workflow orchestration engine designed for building, running, and observing complex, long-running business processes. It has evolved from a monolithic server application into a flexible and modular SDK, allowing developers to embed powerful workflow capabilities directly into their Python applications.

### Core Philosophy

*   **SDK-First:** Designed to be used as a library within your existing Python applications (Flask, Django, FastAPI, CLI tools, etc.).
*   **Pluggable Architecture:** Key components like persistence, execution, and observation are abstracted behind provider interfaces, allowing for customizable and swappable backends.
*   **Declarative Workflows:** Workflows are defined in a clean and human-readable YAML format, separating business logic from orchestration flow.
*   **Resilient & Observable:** Built-in support for saga patterns for compensation, real-time observability through event hooks, and detailed audit trails.
*   **Extensible Marketplace:** A package-based ecosystem allows for the discovery and sharing of custom workflow steps and integrations.

### Key Technologies & Concepts

*   **Pydantic:** For robust data validation and serialization of workflow state.
*   **Provider Pattern:**
    *   **`PersistenceProvider`:** For durable state management (e.g., `PostgresProvider`, `InMemoryPersistence`).
    *   **`ExecutionProvider`:** For running asynchronous tasks (e.g., `CeleryExecutor`, `ThreadPoolExecutor`, `SyncExecutor`).
    *   **`WorkflowObserver`:** For hooking into workflow events (e.g., for logging, metrics, or webhooks).
*   **YAML DSL:** A rich Domain-Specific Language for defining workflows, including features like parameterization, environment variable substitution, and template inheritance.

## Architecture

Rufus is designed as a modular, layered SDK that can be integrated into any Python application.

```
┌─────────────────────────────────────────────────┐
│        Application Layer (Your Code)            │
│  FastAPI | Flask | Django | CLI | Jupyter       │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│                   Rufus SDK                     │
│  ┌──────────────────────────────────────────┐   │
│  │             WorkflowEngine               │   │
│  │    - start_workflow()                     │   │
│  │    - get_workflow()                       │   │
│  │    - ...                                  │   │
│  └──────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────┐   │
│  │           Pluggable Providers            │   │
│  │    - PersistenceProvider (Interface)      │   │
│  │    - ExecutionProvider (Interface)        │   │
│  │    - WorkflowObserver (Interface)         │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

1.  **Core SDK (`src/rufus`):**
    *   **`WorkflowEngine` (`engine.py`):** The main public API for interacting with the workflow system.
    *   **`Workflow` (`workflow.py`):** Represents a single workflow instance, managing its state and execution.
    *   **`WorkflowBuilder` (`builder.py`):** Responsible for parsing YAML definitions and constructing workflow objects.
    *   **`models.py`:** Defines the core data structures and step types.
    *   **`providers/`:** Contains the interfaces for the pluggable provider system.

2.  **Optional Server (`src/rufus_server`):** A pre-built FastAPI application that uses the Rufus SDK to expose a REST API for workflow management.

3.  **Optional CLI (`src/rufus_cli`):** A command-line interface for validating, running, and visualizing workflows.

## Key Features

*   **Flexible Step Types:** Supports standard synchronous steps, asynchronous background tasks (`ASYNC`), parallel fan-out/fan-in (`PARALLEL`), HTTP calls (`HTTP`), and more.
*   **Saga Pattern:** Built-in support for `CompensatableStep` to enable automatic rollback on failure, ensuring data consistency across distributed systems.
*   **Dynamic Execution:** Inject new steps at runtime, define conditional branching logic in YAML, and chain steps together for automated sequences.
*   **Marketplace & Auto-Discovery:** Easily extend Rufus by installing `rufus-*` packages. The SDK automatically discovers and registers new step types provided by these packages.
*   **Developer-Friendly Testing:** The SDK-first design and `InMemoryPersistence` and `SyncExecutor` providers make it easy to write fast, reliable unit and integration tests for your workflows without external infrastructure.

## Developer Guide

### Using the SDK

The primary way to use Rufus is by importing the `WorkflowEngine` into your Python code.

```python
# Pure Python, no server required
from rufus import WorkflowEngine
from rufus.providers.persistence import InMemoryPersistence
from rufus.providers.execution import SyncExecutor

# 1. Configure the engine with your chosen providers
engine = WorkflowEngine(
    persistence=InMemoryPersistence(),
    executor=SyncExecutor(),
    # ... other providers and registry
)

# 2. Start a workflow
handle = await engine.start_workflow("MyWorkflowType", {"initial_data": "foo"})

# 3. Interact with the workflow
result = await handle.next_step()
```

### Adding New Features

1.  **Define State:** Create or update Pydantic models for your workflow's state.
2.  **Write Logic:** Implement your business logic as Python functions that accept `state` and `context` parameters.
3.  **Configure YAML:** Create or update a YAML file in your `config/` directory to define the workflow's steps and logic.
4.  **Register Workflow:** Add your new YAML file to the `workflow_registry.yaml`.

## Project Evolution

This project was formerly known as "Confucius," a monolithic FastAPI-based workflow server. It has been strategically refactored into "Rufus," a more flexible and powerful SDK-first platform, to better serve the needs of Python developers by allowing them to integrate workflow orchestration directly into their applications. This shift enables broader adoption, easier testing, and a more extensible architecture.

## IMPORTANT RULES TO FOLLOW

1.  **Embrace the SDK:** Prioritize building functionality within the core SDK (`src/rufus`) and treat the server and CLI as optional frontends.
2.  **Provider-Based Design:** When adding new integrations (e.g., for storage, messaging), follow the provider pattern to maintain the pluggable nature of the architecture.
3.  **YAML First:** The YAML DSL is a core product. Enhancements to the workflow capabilities should be reflected in the YAML schema.
4.  **Testability is Key:** All new features must be accompanied by tests. Leverage the `InMemoryPersistence` and `SyncExecutor` for fast, I/O-free unit tests.
5.  **Documentation is Critical:** Update all relevant documentation (READMEs, guides, API references) when adding or changing features.
6.  **Marketplace Compatibility:** When building new step types, consider how they might be packaged and distributed to the wider community.