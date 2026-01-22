# Rufus - Technical Documentation

This document delves into the architecture, design principles, and technical
implementation details of the Rufus SDK. It's intended for developers looking to
understand, extend, or contribute to Rufus.

## Core Philosophy

Rufus is built upon a set of core philosophies that drive its design and functionality:

```
SDK-First : Designed to be embedded directly into Python applications (Django,
Flask, FastAPI, etc.) without requiring a separate server for basic operation.
Declarative : Workflows are defined in YAML, not code, promoting separation of
concerns and easier collaboration.
Durable : State is persisted via pluggable PersistenceProvider implementations,
supporting ACID-compliant PostgreSQL or simple in-memory storage.
Observable : Real-time visibility and audit logging via the WorkflowObserver
interface, enabling integration with monitoring tools.
Resilient : Built-in Saga pattern for distributed transactions and rollbacks, enhanced
by robust parallel execution with conflict detection, ensuring data consistency
across distributed services.
Scalable : Async execution via pluggable ExecutionProvider implementations
(e.g., Celery workers) with atomic task claiming, and improved sub-workflow
management for clearer status propagation, enabling more complex and scalable
orchestrations.
Pluggable : All external dependencies (DB, task queue, messaging) are abstracted
behind interfaces, allowing developers to "bring their own" or use provided
implementations.
```
## Architecture Overview

Rufus is designed as a highly modular and extensible SDK, built around a core
WorkflowEngine and a set of pluggable provider interfaces. This design ensures that the
core logic is decoupled from specific technologies for persistence, execution, and
observability.

### Conceptual Architecture Diagram

#### ┌─────────────────────────────────────────────────────────────────┐

```
│ Your Application (FastAPI, Django, etc.) │
├─────────────────────────────────────────────────────────────────┤
│ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Rufus SDK (Core) │ │
```

#### │ │ ┌───────────────────────────────────────────────────────┐ │ │

```
│ │ │ WorkflowEngine (Orchestrator) │ │ │
│ │ │ (rufus/engine.py) │ │ │
│ │ │ │ │ │
│ │ │ Manages state, delegates steps, handles directives │ │ │
│ │ │ Saga, Sub-workflows, Dynamic Injection, Routing │ │ │
│ │ └───────────────▲─────────────────▲─────────────────────┘ │ │
│ │ │ │ │
│ │ ┌────────────────┴───────────────┐ │ ┌───────────────────┐ │ │
│ │ │ rufus/models.py │ │ │ rufus/builder.py │ │
│ │ │ (Data Structures & Directives) │ │ │ (Workflow Assembly) │
│ │ └────────────────────────────────┘ │ └───────────────────┘ │ │
│ └───────────────────┬───────────────────────────────────────────┘
│ │
│ ┌───────────────────▼───────────────────────────────────────────┐
│ │ Pluggable Provider Interfaces │
│ │ ┌─────────────────────────────────────────────────────────┐ │
│ │ │ PersistenceProvider (rufus/providers/persistence.py) ├───┐
│ │ ├─────────────────────────────────────────────────────────┤ │
│ │ │ ExecutionProvider (rufus/providers/execution.py) ├───┼
│ │ ├─────────────────────────────────────────────────────────┤ │
│ │ │ WorkflowObserver (rufus/providers/observer.py) ├───┘
│ │ ├─────────────────────────────────────────────────────────┤ │
│ │ │ ExpressionEvaluator (rufus/providers/expression_evaluator.p
│ │ ├─────────────────────────────────────────────────────────┤ │
│ │ │ TemplateEngine (rufus/providers/template_engine.py) │ │
│ │ └───────────────────┬─────────────────────────────────────┘ │
│ └───────────────────────┴───────────────────────────────────────┘
│ │
│ ┌───────────────────────▼─────────────────────────────────────┐
│ │ Default Implementations │
│ │ (rufus/implementations/*/) │
│ └─────────────────────────────────────────────────────────────┘
│
│ ┌─────────────────────────────────────────────────────────────┐
│ │ rufus_server/ (Optional FastAPI API Wrapper) │
│ ├─────────────────────────────────────────────────────────────┤
│ │ rufus_cli/ (Optional Command Line Tool) │
│ └─────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────┘
```
### Key Components Explained with Code References

**1. rufus/models.py (The Data Layer)**


This module defines the fundamental data structures and directives that orchestrate
workflows using Pydantic for strong typing, validation, and serialization.

```
StepContext : Provides contextual information to step functions during execution,
including workflow ID, step name, validated input, and previous step results.
```
```
# rufus/models.py
class StepContext(BaseModel):
workflow_id: str
step_name: str
validated_input: Optional[BaseModel] = None
previous_step_result: Optional[Dict[str, Any]] = None
loop_item: Optional[Any] = None
loop_index: Optional[int] = None
```
```
WorkflowStep and Subclasses : The base for all steps, with specialized types for
various execution patterns.
CompensatableStep: Extends WorkflowStep with a compensate_func for
Saga pattern rollbacks.
AsyncWorkflowStep, HttpWorkflowStep: For non-blocking, often long-
running, operations delegated to an ExecutionProvider.
ParallelWorkflowStep: Executes multiple tasks concurrently. Enhanced
with features for reliability:
```
```
# rufus/models.py
class ParallelWorkflowStep(WorkflowStep):
def __init__(self, name: str, tasks: List[ParallelExec
super().__init__(name=name, func=self.dispatch_para
self.tasks = tasks
self.merge_function_path = merge_function_path
self.timeout_seconds = timeout_seconds # Max durati
self.allow_partial_success = allow_partial_success
```
```
FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep:
For independent workflow spawning, iterative processing, and scheduling.
Workflow Directives (as Exceptions) : Special exceptions that alter the
workflow's flow control, caught by the WorkflowEngine.
WorkflowJumpDirective, WorkflowPauseDirective,
StartSubWorkflowDirective, SagaWorkflowException.
```
**2. rufus/engine.py (The Orchestrator - WorkflowEngine)**


The WorkflowEngine is the central controller responsible for managing the workflow's
lifecycle, state transitions, and delegating step execution. It is designed to be highly
extensible through dependency injection.

```
Dependency Injection (__init__) : The constructor requires all external
capabilities (persistence, execution, building, observability, expression evaluation,
templating) to be injected, making the engine testable and adaptable.
```
```
# rufus/engine.py (simplified __init__)
class WorkflowEngine:
def __init__(self,
workflow_id: str = None,
initial_state_model: BaseModel = None,
workflow_type: str = None,
persistence_provider: PersistenceProvider = No
execution_provider: ExecutionProvider = None,
workflow_builder: 'WorkflowBuilder' = None,
expression_evaluator_cls: Type[ExpressionEvalu
template_engine_cls: Type[TemplateEngine] = No
workflow_observer: WorkflowObserver = None
):
# ... initialization ...
self.persistence: PersistenceProvider = persistence_pro
self.execution: ExecutionProvider = execution_provider
self.builder: 'WorkflowBuilder' = workflow_builder
self.expression_evaluator_cls = expression_evaluator_cl
self.template_engine_cls = template_engine_cls
self.observer: WorkflowObserver = workflow_observer
```
```
Flow of Control (next_step method) : This is the heart of the engine, responsible
for advancing the workflow one step at a time.
Input Validation : Uses step.input_schema (a Pydantic model) to validate
user_input.
Step Type Delegation : Determines the step type and delegates execution:
Synchronous steps (STANDARD, DECISION) are executed directly via
self.execution.execute_sync_step_function.
Asynchronous steps (ASYNC, HTTP) are dispatched via
self.execution.dispatch_async_task.
ParallelWorkflowStep tasks are dispatched via
self.execution.dispatch_parallel_tasks.
Other special steps (FireAndForget, Loop, CronSchedule) have
their logic handled, often involving the builder or execution provider.
Directive Handling : Catches Workflow Directives (exceptions) to
implement complex control flow (jumps, pauses, sub-workflow initiation).
```

```
Sub-workflow Status Bubbling (_notify_status_change) : This helper
centralizes status updates and ensures child workflows report their status to parents
via the ExecutionProvider.
```
```
# rufus/engine.py
def _notify_status_change(self, old_status: str, new_status: st
"""Helper to centralize status change notifications."""
self.observer.on_workflow_status_changed(self.id, old_statu
if self.parent_execution_id:
# If this is a child workflow, report its status change
self.execution.report_child_status_to_parent(
child_id=self.id,
parent_id=self.parent_execution_id,
child_new_status=new_status,
child_current_step_name=current_step_name,
child_result=final_result # Only relevant if status
)
```
```
Saga Pattern : The enable_saga_mode method and _execute_saga_rollback
handle transactional integrity by executing compensation functions.
Dynamic Execution : _process_dynamic_injection allows runtime modification
of the workflow step sequence based on conditions evaluated by the
ExpressionEvaluator.
```
**3. rufus/providers/ (The Extension Points)**

These modules define Python Protocols that establish clear contracts for integrating
external services, making Rufus highly pluggable.

```
PersistenceProvider (rufus/providers/persistence.py) : Defines how
workflow states are saved and loaded, and how audit logs and task records are
managed.
ExecutionProvider (rufus/providers/execution.py) : Abstracts the
underlying execution environment for all non-synchronous operations.
```
```
# rufus/providers/execution.py (simplified)
class ExecutionProvider(Protocol):
def dispatch_async_task(self, func_path: str, state_data: D
def dispatch_parallel_tasks(self, tasks: List[ParallelExecu
def dispatch_sub_workflow(self, child_workflow_id: str, par
def report_child_status_to_parent(self, child_id: str, pare
def execute_sync_step_function(self, func: Callable, state:
```

```
Note the methods for parallel task dispatch with new timeout_seconds and
allow_partial_success parameters, and report_child_status_to_parent
for sub-workflow status bubbling.
WorkflowObserver (rufus/providers/observer.py) : Provides hooks for
external systems to observe workflow events (start, step execution, completion,
failure, rollback, status changes).
ExpressionEvaluator (rufus/providers/expression_evaluator.py) :
Defines an interface for evaluating conditions, allowing for pluggable expression
languages.
TemplateEngine (rufus/providers/template_engine.py) : Provides an
interface for rendering dynamic content from workflow state, used in HTTP steps or
FireAndForget initial data.
```
**4. rufus/builder.py (The Workflow Assembler)**

The WorkflowBuilder is responsible for loading workflow configurations (from YAML)
and assembling them into executable WorkflowEngine instances. It handles dynamic
module imports for step functions and state models, and auto-discovery of steps from
installed rufus-* packages.

**5. rufus/implementations/ (Default Concrete Implementations)**

This directory contains default, production-ready implementations of the provider
interfaces.

```
rufus/implementations/persistence/postgres.py : A robust PostgreSQL-
based persistence provider leveraging JSONB and FOR UPDATE SKIP LOCKED.
rufus/implementations/execution/sync.py : A synchronous executor for
simple scenarios and testing, executing steps directly in the current process. It
implements dispatch_parallel_tasks using ThreadPoolExecutor for local
concurrency and handling timeouts/partial success.
rufus/implementations/execution/celery.py : A CeleryExecutor that
dispatches tasks to a Celery cluster for distributed asynchronous and parallel
execution. It uses Celery's group and chain primitives, and dispatches the
merge_and_resume_parallel_tasks and report_child_workflow_status
Celery tasks for robust handling of parallel step results and sub-workflow status
propagation.
rufus/implementations/execution/celery_tasks.py : Contains the actual
Celery tasks (resume_workflow_from_celery,
merge_and_resume_parallel_tasks, report_child_workflow_status,
execute_sub_workflow, etc.) that execute on Celery workers.
merge_and_resume_parallel_tasks: Collects results from parallel Celery
tasks, performs merging (with conflict logging), respects
allow_partial_success, and then resumes the main workflow.
```

```
report_child_workflow_status: Receives status updates from child
workflows and updates the parent workflow's status accordingly
(FAILED_CHILD_WORKFLOW, WAITING_CHILD_HUMAN_INPUT, etc.), and
triggers parent resumption if the child completes.
rufus/implementations/observability/logging.py : A basic
WorkflowObserver that logs workflow events to the console.
```
## Key Features (Technical Deep Dive)

### Workflow Primitives

Rufus supports a rich set of step types, each handled uniquely by the WorkflowEngine
and its ExecutionProvider:

```
Standard/Decision Steps : Executed synchronously via
ExecutionProvider.execute_sync_step_function. Decision steps leverage
the ExpressionEvaluator for routing.
Async/HTTP Steps : Dispatched to the ExecutionProvider via
dispatch_async_task, which typically queues them for background processing
(e.g., Celery).
Parallel Steps : Tasks are dispatched as a group via
ExecutionProvider.dispatch_parallel_tasks. Results are collected and
merged by a dedicated callback mechanism (e.g.,
merge_and_resume_parallel_tasks in Celery), incorporating configurable
timeout_seconds and allow_partial_success.
Sub-Workflows : Initiated by StartSubWorkflowDirective. The parent workflow
pauses, and a child workflow is executed (via
ExecutionProvider.dispatch_sub_workflow). Status changes of the child are
actively reported back to the parent.
```
### Saga Pattern

The WorkflowEngine facilitates distributed transactions using the Saga pattern.
CompensatableSteps define compensate_funcs. If a SagaWorkflowException is
raised, _execute_saga_rollback systematically executes these compensation
functions in reverse order of completion.

### Dynamic Execution

The _process_dynamic_injection method within WorkflowEngine allows for highly
flexible workflows. Based on rules defined in YAML and evaluated against the current state
using ExpressionEvaluator, new steps can be inserted into the workflow's execution
path at runtime.

### Sub-Workflow Management


Rufus implements robust status bubbling for sub-workflows. When a child workflow
changes its status, its WorkflowEngine (via _notify_status_change) calls
ExecutionProvider.report_child_status_to_parent. This, in turn, dispatches a
Celery task (report_child_workflow_status) that updates the parent workflow's
status to reflect the child's state (e.g., PENDING_SUB_WORKFLOW,
WAITING_CHILD_HUMAN_INPUT, FAILED_CHILD_WORKFLOW). This provides real-time
visibility and enables the parent to react appropriately.

### Parallel Execution Enhancements

The ParallelWorkflowStep and its handling in ExecutionProvider implementations
(SyncExecutor, CeleryExecutor) are significantly enhanced:

```
Conflict Detection : During default merges of parallel task results, Rufus logs
warnings when key collisions occur, ensuring developers are aware of potential data
overwrites.
Timeouts : Individual parallel tasks can have timeout_seconds defined, preventing
indefinite blocking.
Partial Success : The allow_partial_success flag enables workflows to proceed
even if some parallel tasks fail or timeout, providing greater flexibility for non-critical
operations.
Improved Custom Merge : Custom merge functions now receive a dictionary
mapping task names to their results, along with the current workflow state, allowing
for more informed and robust aggregation logic.
```
## Key Technologies

Rufus leverages a modern Python ecosystem for robustness, performance, and developer
experience.

```
Pydantic : Robust data validation and serialization for workflow state and step
inputs.
YAML : Domain Specific Language (DSL) for declarative workflow definitions.
FastAPI (for rufus-server) : High-performance, asynchronous REST APIs and
WebSocket handling.
Celery (for CeleryExecutor) : Distributed task queuing and asynchronous/parallel
execution.
PostgreSQL (for PostgresProvider) : Primary persistence layer with JSONB state
storage and FOR UPDATE SKIP LOCKED.
Redis : Message broker for Celery and Pub/Sub functionality.
Typer (for rufus-cli) : Intuitive and robust CLI tools.
```
## Configuration & Extensibility

Workflows are defined in YAML files and registered in a central
workflow_registry.yaml. Rufus's architecture, built around provider interfaces, makes


it highly extensible. Developers can swap out default implementations with custom ones to
integrate with their specific technology stack.

## Developer Guide

### Extending Rufus (Adding New Features & Logic)

1. **Define State Models** : Update or create Pydantic BaseModel classes for your
    workflow's state (rufus.models or your application's models).
2. **Implement Step Functions** : Write Python functions for your workflow steps. These
    should accept (state: BaseModel, context: StepContext). Place them in
    well-organized Python modules within your application.
3. **Configure Workflows** : Create or update YAML files in your config/ directory,
    referencing your new state models and step functions.
4. **Register Workflows** : Update workflow_registry.yaml to include your new
    workflow types and their configuration files.
5. **Implement Custom Providers** : If default PersistenceProvider or
    ExecutionProvider implementations don't meet your needs, create custom
    classes that adhere to the rufus.providers interfaces.

### Important Considerations for Contributors

1. Break complex tasks down into smaller manageable steps.
2. Prioritize API stability for the SDK. Changes to core interfaces should be carefully
    considered.
3. Ensure updates don't break existing workflows or default implementations.
4. Research for up-to-date libraries and documentation.
5. Update all relevant project documentation (README.md,
    TECHNICAL_DOCUMENTATION.md, USAGE_GUIDE.md, YAML_GUIDE.md,
    API_REFERENCE.md) after changes.
6. Maintain comprehensive test coverage.
