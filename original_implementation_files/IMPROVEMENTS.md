# Confucius Engine - Improvement & Refactoring Plan
**Date:** January 15, 2026
**Reference:** `PROJECT_REVIEW.md`

This document outlines the plan to address the architectural and implementation feedback from the recent project review. The changes are prioritized to address developer ergonomics, critical architectural gaps, operational maturity, and future scalability.

---

## **Phase 1: Immediate Priorities (Developer Experience & Safeguards)**

This phase focuses on improving the developer experience and implementing critical safeguards before tackling larger architectural changes.

### **1. Refactor Step Function Signatures (Fix `**kwargs` Footgun)**
*   **Goal:** Prevent runtime errors by enforcing a clear, explicit signature for all step functions. Move error detection from runtime to workflow load time.
*   **Priority:** **Critical**. This is the top priority as it directly impacts developer experience and prevents a common source of errors.
*   **Steps:**
    1.  **Define `StepContext` Model:** Create a Pydantic `BaseModel` named `StepContext` in `src/confucius/models.py`. This model will encapsulate all metadata passed to steps (e.g., `workflow_id`, `step_name`, loop variables like `item`, `index`).
    2.  **Define `StepFunction` Protocol:** In a new file `src/confucius/protocols.py`, define a `StepFunction` typing `Protocol` with the signature `__call__(self, state: BaseModel, context: StepContext) -> Dict[str, Any]`.
    3.  **Implement Validator:** In `src/confucius/workflow_loader.py`, create a `_validate_step_function` utility that uses `inspect.signature()` to ensure a given function's signature matches the `StepFunction` protocol (i.e., accepts `state` and `context`).
    4.  **Integrate Validation:** Call `_validate_step_function` from within `_build_steps_from_config` for every function path loaded from YAML.
    5.  **Refactor Engine:** Modify the `Workflow.next_step` method in `workflow.py` to instantiate and pass the `StepContext` object instead of `**kwargs`.
    6.  **Update All Step Functions:** Refactor every step function in `steps/*.py` and `workflow_utils.py` to conform to the new `(state, context)` signature.
    7.  **Update Documentation:** Update `TECHNICAL_DOCUMENTATION.md` and `USAGE_GUIDE.md` to reflect the new, required signature for step functions.

### **2. Add Safety Limit to Synchronous Loops**
*   **Goal:** Prevent long-running synchronous loops from blocking a Celery worker indefinitely.
*   **Priority:** **High**. This is an immediate mitigation for a potential scalability cliff.
*   **Steps:**
    1.  **Update YAML Loader:** In `workflow_loader.py`, update the logic for `LoopStep` to read an optional `max_iterations` integer from the YAML configuration (defaulting to a safe value like 1000).
    2.  **Enforce Limit in Engine:** In `LoopStep._execute_loop` (`workflow.py`), add a counter. If `iterations > self.max_iterations`, raise a `WorkflowPauseDirective` with an informative error message.
    3.  **Document the Feature:** Update `YAML_GUIDE.md` to include the new `max_iterations` field for `LOOP` steps.

### **3. Harden Semantic Firewall**
*   **Goal:** Replace naive regex-based sanitization with industry-standard libraries to prevent XSS and other injection attacks.
*   **Priority:** **High**. This is a critical security fix.
*   **Steps:**
    1.  **Add Dependency:** Add `bleach` to `requirements.txt`.
    2.  **Refactor `WorkflowInput`:** In `src/confucius/semantic_firewall.py`, modify the `sanitize_strings` validator.
    3.  **Implement Whitelist:** Introduce a `Config` inner class on `WorkflowInput` to define `strict_fields` (for character whitelisting) and `html_fields` (for `bleach` sanitization).
    4.  **Apply `bleach`:** Use `bleach.clean()` for fields marked as `html_fields`.
    5.  **Apply Character Whitelist:** For fields in `strict_fields`, use a strict regex to allow only a safe subset of characters.
    6.  **Remove Old Regex:** Delete the `dangerous_patterns` list.

---

## **Phase 2: Hierarchical State Propagation & Recovery**

This phase addresses the critical architectural gap of propagating state changes (failures, human-in-the-loop requests) from child workflows up to the parent, making nested workflows observable and recoverable.

### **1. State Model & Database Schema**
*   **Goal:** Update the database and data models to support parent-child relationships and state bubbling.
*   **Priority:** **Critical**. This is the foundation for the entire feature.
*   **Steps:**
    1.  **Update `WorkflowStatus` Enum:** Add `WAITING_FOR_CHILD_INPUT` and `CHILD_FAILED` to the `WorkflowStatus` enum in `src/confucius/models.py`.
    2.  **Define `PendingAction` and `ChildError` Models:** Create Pydantic models to structure the data for pending inputs and bubbled-up errors.
    3.  **Create Migration `006_add_hierarchical_state.sql`:**
        - Add a nullable `parent_execution_id` (UUID) column to the `workflow_executions` table, with a foreign key to itself.
        - Add a `pending_actions` (JSONB) column to store an array of required inputs from children.
        - Add an `errors` (JSONB) column to store structured error details from failed children.
    4.  **Update Persistence Layer:** Modify `src/confucius/persistence_postgres.py` to handle the new fields during create and update operations.

### **2. Failure Bubble-Up**
*   **Goal:** Ensure a child workflow's failure is immediately and recursively reflected up to the root parent's state.
*   **Priority:** **High**.
*   **Steps:**
    1.  **Create `signal_failure_to_parent` Task:** Create a new recursive Celery task. This task will take an `execution_id` and `error_details` as input.
    2.  **Implement Recursive Signaling:** The task will:
        - Load the specified workflow execution and find its `parent_execution_id`.
        - If no parent exists, the recursion stops.
        - If a parent exists, it will update the parent's status to `CHILD_FAILED`, append the `error_details` to its `errors` field, and save it.
        - It will then call itself with the `parent_execution_id` and the same `error_details`, ensuring the failure bubbles all the way to the top.
    3.  **Modify `execute_sub_workflow` Task:** In `src/confucius/tasks.py`, wrap the core sub-workflow execution logic in a `try...except` block. On exception, it should call the new `signal_failure_to_parent` task with its own ID and the failure information.

### **3. Human-in-the-Loop (HITL) Bubble-Up**
*   **Goal:** Allow a child's request for human input to pause the parent and expose the required action.
*   **Priority:** **High**.
*   **Steps:**
    1.  **Refactor `HumanInputStep`:** In `workflow.py`, when a `HumanInputStep` executes in a child workflow, it must trigger a signal to the parent instead of just pausing.
    2.  **Create `signal_parent_for_input` Task:** This new Celery task will:
        - Be called by the `HumanInputStep` in a child.
        - Load the parent workflow.
        - Set the parent's status to `WAITING_FOR_CHILD_INPUT`.
        - Add a `PendingAction` object (with child ID and input schema) to the parent's `pending_actions` field.
        - Save the parent.
        - The child workflow itself should enter a `PAUSED` state.

### **4. Surgical Resume & Retry**
*   **Goal:** Enable resuming a workflow from the parent by proxying commands to the correct child, including retrying a specific failed node.
*   **Priority:** **Medium**. This completes the recovery loop.
*   **Steps:**
    1.  **Define `ResumeInstruction` API Model:** Create a Pydantic model for the resume/retry API payload, specifying which child and node to target, and the corrected data.
    2.  **Enhance Resume API:** In `src/confucius/routers.py`, update the resume endpoint (`/next`) to handle the new parent statuses (`CHILD_FAILED`, `WAITING_FOR_CHILD_INPUT`). It will parse the `ResumeInstruction` and proxy the command to the appropriate child.
    3.  **Implement Node Re-injection Logic:**
        - This requires a significant refactoring of the core engine (`workflow.py`).
        - Create a `resume_at_node(node_id, corrected_data)` method.
        - This method must update the status of the target node in the database, inject the new data, and re-enqueue *only that node's execution task*.
        - The engine's step traversal logic must be updated to find the next valid, uncompleted node in the DAG, rather than assuming linear execution.

---

## **Phase 3: Operational Maturity & Testing**

This phase focuses on making the engine easier to test, monitor, and operate in production.

### **1. Build a `WorkflowTestHarness`**
*   **Goal:** Enable synchronous, reliable testing of workflow logic without needing a full Celery/Redis stack.
*   **Priority:** **High**.
*   **Steps:**
    1.  Create `src/confucius/testing.py`.
    2.  Implement a `WorkflowTestHarness` class capable of loading workflows, mocking steps (with return values or exceptions), and running the workflow logic synchronously in-process.
    3.  Add support for asserting on saga rollbacks (`compensations_called`).

### **2. Integrate First-Class Observability Hooks**
*   **Goal:** Make metrics collection a core, non-optional part of the engine architecture.
*   **Priority:** **Medium**.
*   **Steps:**
    1.  Define a `MetricsCollector` protocol with methods like `record_step_success`, `record_step_failure`, etc.
    2.  Integrate the collector into the `Workflow` class and add hooks to the `next_step` method to record duration and status.

### **3. Add Explicit State Merging Strategies**
*   **Goal:** Make the result-merging behavior of async steps explicit and predictable.
*   **Priority:** **Medium**.
*   **Steps:**
    1.  Define `MergeStrategy` and `MergeConflict` enums.
    2.  Update the YAML loader to read these configurations for async steps.
    3.  Refactor the async resume tasks to implement the explicit merge logic (e.g., `DEEP`, `SHALLOW`, `REPLACE`).

---

## **Phase 4: Future-Proofing & Scale**

These are important architectural improvements for handling future growth.

### **1. Add TTL Caching to Secrets Provider**
*   **Goal:** Improve performance and reduce load on external secret management systems.
*   **Priority:** **Low**.
*   **Steps:**
    1.  Modify the `SecretsProvider` class in `src/confucius/secrets.py` to include an in-memory cache with a configurable TTL.

### **2. Create Documentation Artifacts (ADRs & Anti-Patterns)**
*   **Goal:** Improve project maintainability and knowledge sharing.
*   **Priority:** **Low**.
*   **Steps:**
    1.  Create a `docs/adr/` directory and add initial records for key decisions.
    2.  Add an "Anti-Patterns" section to `USAGE_GUIDE.md`.

---
## **Completed Improvements**

*   **Worker Registry MVP:** A passive worker registry with a `worker_nodes` table and heartbeat mechanism has been implemented. (Completed January 14, 2026)
