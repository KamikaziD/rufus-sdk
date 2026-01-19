# Technical Documentation: Example Application

This document provides a detailed overview of the technical aspects of the example application built using the **Confucius workflow engine library**.

## 1. Introduction

This project demonstrates how to use the `confucius` library to build a powerful, configuration-driven application. Its core principle is to separate the business logic (the "how") from the process definition (the "what" and "when"). The business process is defined in YAML files, while the underlying orchestration is handled by the imported `confucius` engine.

The system is built on a modern stack, including FastAPI for the web API, Celery for asynchronous tasks, and Redis for state persistence and messaging.

## 2. Tech Stack

The project utilizes a combination of technologies to provide a robust and scalable platform:

| Category | Technology/Framework | Description |
| :--- | :--- | :--- |
| **Workflow Engine** | `confucius` (This Library) | For core workflow orchestration, persistence, and API routing. |
| **Web Framework** | FastAPI, Uvicorn | For building the high-performance asynchronous web API. |
| **Workflow Configuration** | YAML | To define the structure, sequence, and logic of all workflows. |
| **Data Validation** | Pydantic | For defining the schemas for workflow states. |
| **Asynchronous Tasks** | Celery | For running background tasks, such as calling AI agents or external services. |
| **In-Memory Store** | Redis | Acts as the message broker for Celery and the persistence layer for workflow states. |

## 3. Example Application Architecture

The application's architecture demonstrates a clean separation of concerns between the reusable, imported workflow engine and the application-specific business logic.

### 3.1. Core Workflow Engine (`confucius` package)

This is the heart of the platform, imported as a library from `src/`. It provides all the core functionality for workflow orchestration.

*   **`confucius.workflow` & `confucius.workflow_loader`**: These modules contain the runtime engine (`Workflow` class) and the configuration parser (`WorkflowBuilder`). The builder is instantiated in the application (`main.py`) with a path to the application's configuration files.
*   **`confucius.routers`**: This module provides a `get_workflow_router` factory function. The main application calls this to get a pre-configured FastAPI router that exposes all the necessary API endpoints (e.g., `/start`, `/next`).
*   **`confucius.tasks`**: Contains the core Celery tasks required by the engine to resume workflows after asynchronous or parallel steps complete.

### 3.2. Application Entrypoint (`main.py`)

This is the main entry point of the example application. It is responsible for:
1.  Instantiating the `WorkflowBuilder` with the path to the application's `config/` directory.
2.  Importing the API router from `confucius.routers`.
3.  Including the workflow router in the main FastAPI application.
4.  Optionally importing and including the debug UI router from `confucius.contrib.debug_ui`.

### 3.3. Business Logic (`workflow_utils.py`)

This file contains the collection of Python functions that perform the actual work at each step (e.g., `run_credit_check_agent`, `send_welcome_email`). The YAML configuration files reference these functions by their string path.

### 3.4. Workflow Definitions (`config/` directory)

This directory holds the YAML files that define the business processes.
*   **`config/workflow_registry.yaml`**: The master file that maps a `workflow_type` to its corresponding YAML definition file and the Pydantic state model it uses (from `state_models.py`).
*   **Workflow Definition Files (e.g., `config/loan_workflow.yaml`)**: Each file defines the sequence of steps, their types (`STANDARD`, `ASYNC`, `PARALLEL`, etc.), the business logic function to execute, and the `input_model` for step-specific validation.

### 3.5. State Models (`state_models.py`)

This file contains all the Pydantic models that define the structure and schema for the state of each workflow in the example application.

## 4. Methodology

The primary methodology is to separate the process definition from the execution logic.
- **Process Definition (YAML):** Defines the "what" and "when". It is easy for non-developers to read and modify.
- **Execution Logic (Python):** The functions in `workflow_utils.py` define the "how". This is the code that performs the actual work.

The `confucius` library handles the orchestration, persistence, and API, allowing the application developer to focus solely on the business logic and its configuration.
