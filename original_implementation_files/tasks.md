# Implementation Plan

This file tracks the incremental implementation of the new workflow features.

## Phase 1: Project Restructuring and Core Concepts

- [x] **Task 1: Create `tasks.md` file.**
- [x] **Task 2: Restructure the project.**
    - [x] Create `database.py`, `celery_worker.py`, `workflow.py`, `state_models.py`, `workflow_utils.py`, `workflow_definitions.py`, and `models.py`.
    - [x] Create `templates` directory with `index.html`.
    - [x] Move existing code to the new files.
- [x] **Task 3: Implement Typed State Management.**
    - [x] Create Pydantic models in `state_models.py` and `models.py`.
    - [x] Update `workflow.py` to use Pydantic models for state.
- [x] **Task 4: Implement Persistence.**
    - [x] Create `database.py` for Redis-based state persistence.
    - [x] Update `main.py` and `workflow.py` to use the persistence layer.

## Phase 2: Asynchronous Execution

- [x] **Task 5: Implement Asynchronous Task Execution.**
    - [x] Set up `celery_worker.py`.
    - [x] Implement `@async_step` decorator.
    - [x] Update `workflow.py` and `main.py` to handle async tasks.

## Phase 3: Advanced Workflow Features

- [x] **Task 6: Implement Conditional Branching.**
- [x] **Task 7: Implement Parallel Execution.**
- [x] **Task 8: Implement Nested Workflows.**
- [x] **Task 9: Implement Human-in-the-Loop.**

## Phase 4: Frontend

- [x] **Task 10: Implement the Web Interface.**
    - [x] Create the HTML and JavaScript for the frontend.
    - [x] Update `main.py` to serve the web interface.
