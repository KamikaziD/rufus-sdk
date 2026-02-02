# Rufus Tech Stack

This document outlines the primary technologies and architectural concepts used in the Rufus workflow orchestration engine.

## Project Overview

Rufus is a Python-based, SDK-first workflow orchestration engine designed for building, running, and observing complex, long-running business processes. It allows developers to embed powerful workflow capabilities directly into their Python applications (e.g., FastAPI, Flask, Django, CLI tools).

The core philosophy is to provide a flexible, pluggable, and declarative system for managing workflows, separating the business logic from the orchestration flow using clean, human-readable YAML files.

## Core Technologies

-   **Language:** **Python** (3.8+)
-   **Data Validation & Serialization:** **Pydantic** is used extensively for robust data modeling, validation, and serialization of workflow state and configuration.
-   **Workflow Definition:** **YAML** is the Domain-Specific Language (DSL) for defining workflow structures, steps, and logic.

## Pluggable Architecture (Provider Pattern)

Rufus is built on a provider pattern, allowing key components to be swapped out to fit different environments and requirements.

-   **Persistence Providers:** Responsible for durable state management.
    -   `InMemoryPersistence`: For development, testing, and lightweight use cases.
    -   `PostgresProvider`: For production-grade, durable persistence using PostgreSQL.
    -   `SqliteProvider`: For simple, file-based persistence.

-   **Execution Providers:** Responsible for running asynchronous tasks and managing concurrency.
    -   `SyncExecutor`: Executes tasks synchronously in the same process; ideal for testing and simple applications.
    -   `ThreadPoolExecutor`: Executes tasks in a local thread pool for parallel execution.
    -   `CeleryExecutor`: Integrates with Celery for distributed, scalable task execution.

-   **Observation Providers (`WorkflowObserver`):** Allows for hooking into workflow lifecycle events for monitoring, logging, and metrics.

## Optional Components

-   **REST API Server:** A pre-built **FastAPI** application (`rufus_server`) is provided to expose workflow management functionality over a REST API.
-   **Command-Line Interface (CLI):** A `rufus_cli` tool for validating, running, and visualizing workflows from the command line.

## Historical Context (Formerly "Confucius")

The project evolved from a monolithic application named "Confucius," which used a more rigid stack. Understanding this context can be helpful when navigating older parts of the codebase.

-   **Original API Framework:** FastAPI
-   **Original Task Queue:** Celery
-   **Original Message Broker:** Redis
-   **Original Persistence:** Primarily PostgreSQL, with Redis used for some development cases.
