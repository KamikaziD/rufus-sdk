# Glossary

This glossary defines key terms and concepts used throughout Rufus SDK documentation.

---

## A

### Async Step
A workflow step that executes asynchronously via the execution provider (e.g., Celery task, thread pool). The workflow pauses at the async step and resumes when the task completes. See: [Step Types](/docs/reference/step-types.md)

### Audit Log
A persistent record of workflow events (step executions, status changes, errors) stored in the database. Used for debugging, compliance, and monitoring. PostgreSQL persistence provider includes full audit logging.

---

## C

### Celery
A distributed task queue system used by Rufus's `CeleryExecutionProvider` to execute async steps and parallel tasks across multiple worker processes. See: [Execution Providers](/docs/reference/providers.md#execution-providers)

### Compensation
The process of undoing or reversing a completed workflow step when a later step fails. Used in the Saga pattern to maintain consistency. Each compensatable step defines a `compensate_function` that reverses its effects. See: [Saga Pattern](/docs/how-to-guides/saga-pattern.md)

### Config Push
The ability to update workflow definitions on edge devices without firmware updates. Rufus Edge uses ETag-based synchronization to deploy new YAML configurations from the cloud control plane. See: [Edge Deployment](/docs/tutorials/edge-deployment.md)

### Control Plane
The centralized cloud service (Rufus Server) that manages edge devices, workflow definitions, and transaction synchronization. Contrasts with the edge agent running on individual devices.

### Cron Step
A workflow step type that executes on a recurring schedule defined by a cron expression. Supports timezone-aware scheduling. See: [Step Types](/docs/reference/step-types.md#cron-scheduler)

---

## D

### Decision Step
A workflow step that implements conditional branching. Returns a condition that routes execution to different target steps. Can use explicit routes (YAML) or runtime jumps (Python). See: [Control Flow](/docs/how-to-guides/control-flow.md)

### Definition Snapshot
A complete copy of a workflow's YAML configuration stored with each workflow instance. Ensures running workflows continue using their original definition even if the YAML file is updated. See: [Workflow Versioning](/docs/explanation/versioning.md)

### Dependency
A prerequisite step that must complete before another step can execute. Defined in YAML via the `dependencies` field. Rufus enforces dependency order automatically.

### Dynamic Injection
The ability to insert workflow steps at runtime based on conditions or state. Powerful but makes workflows non-deterministic. Use sparingly. See: [Advanced Patterns](/docs/explanation/advanced-patterns.md#dynamic-injection)

---

## E

### Edge Device
A fintech terminal (POS, ATM, mobile reader, kiosk) running Rufus Edge Agent. Operates offline and synchronizes with the cloud when connected. See: [Edge Architecture](/docs/RUFUS_EDGE_FINTECH_ARCHITECTURE.md)

### ETag
An HTTP header used for cache validation. Rufus Edge uses ETags to efficiently check if workflow configurations have changed without downloading the full YAML file.

### Execution Provider
A pluggable interface (`ExecutionProvider`) that defines how workflow steps are executed. Implementations include sync (same process), thread pool, Celery (distributed), and PostgreSQL task queue. See: [Providers](/docs/reference/providers.md)

---

## F

### Fire-and-Forget Step
A workflow step that executes asynchronously without waiting for completion. The workflow immediately proceeds to the next step. Useful for logging, notifications, or non-critical operations. See: [Step Types](/docs/reference/step-types.md)

### Floor Limit
In payment processing, the maximum transaction amount that can be approved offline without network connectivity. Implemented in Rufus Edge workflows.

---

## H

### Heartbeat
A periodic signal sent by a workflow step during execution to indicate it's still running. Used by zombie detection to identify crashed workers. See: [Zombie Recovery](/docs/explanation/zombie-recovery.md)

### HTTP Step
A workflow step that makes HTTP requests to external services, enabling polyglot workflows (Python orchestration calling Go/Rust/Node.js services). See: [Polyglot Workflows](/docs/how-to-guides/polyglot-workflows.md)

### Human-in-the-Loop
A workflow pattern where execution pauses for human input or approval. Implemented via `WorkflowPauseDirective`. See: [Control Flow](/docs/how-to-guides/control-flow.md#pausing-workflows)

---

## I

### Idempotency Key
A unique identifier for a workflow or operation that prevents duplicate execution. Rufus uses workflow IDs as idempotency keys in persistence providers.

### Initial State
The starting data for a workflow instance, provided when calling `create_workflow()`. Must match the workflow's `initial_state_model` Pydantic schema.

---

## J

### Jump Directive
An exception (`WorkflowJumpDirective`) raised by step functions to branch to a different step. Alternative to explicit routes in YAML. See: [Control Flow](/docs/how-to-guides/control-flow.md#conditional-branching)

---

## L

### Loop Step
A workflow step type that iterates over a collection or repeats until a condition is met. Supports nested loops and break/continue logic. See: [Step Types](/docs/reference/step-types.md#loop-step)

---

## M

### Merge Strategy
The algorithm used to combine results from parallel tasks into workflow state. Options: `SHALLOW` (dict merge), `DEEP` (recursive merge). See: [Parallel Execution](/docs/how-to-guides/parallel-execution.md)

### Metrics
Performance measurements collected during workflow execution (duration, step count, error rate). Accessible via CLI (`rufus metrics`) or persistence provider API.

---

## O

### Observer
A pluggable interface (`WorkflowObserver`) that receives notifications about workflow events. Used for logging, monitoring, and custom integrations. See: [Observability](/docs/reference/providers.md#observer)

### Offline-First
An architectural pattern where edge devices operate independently without network connectivity, synchronizing with the cloud when available. Core design principle of Rufus Edge.

---

## P

### Parallel Step
A workflow step that executes multiple tasks concurrently. Tasks can run in threads (ThreadPoolExecutor) or distributed workers (CeleryExecutor). See: [Parallel Execution](/docs/how-to-guides/parallel-execution.md)

### PCI-DSS
Payment Card Industry Data Security Standard. Rufus Edge architecture supports PCI-DSS compliance with encryption, audit logging, and secure key management.

### Persistence Provider
A pluggable interface (`PersistenceProvider`) that defines how workflow state, audit logs, and metrics are stored. Implementations: SQLite, PostgreSQL, Redis, in-memory. See: [Providers](/docs/reference/providers.md)

### Polyglot Workflow
A workflow where Python orchestrates steps implemented in multiple programming languages (Go, Rust, Node.js, etc.) via HTTP steps. See: [Polyglot Workflows](/docs/how-to-guides/polyglot-workflows.md)

### Provider
A pluggable interface for external integrations. Rufus defines providers for persistence, execution, observation, templating, and expression evaluation. See: [Architecture](/docs/explanation/architecture.md#provider-pattern)

---

## R

### Registry
The master list of available workflow types (`config/workflow_registry.yaml`). Maps workflow types to YAML configuration files and state models.

### Route
A declarative condition-to-target mapping in decision steps. Defines which step to execute based on workflow state. Alternative to runtime jump directives. See: [Control Flow](/docs/how-to-guides/control-flow.md)

---

## S

### Saga Pattern
A distributed transaction pattern where long-running workflows maintain consistency through compensation (rollback) of completed steps when failures occur. See: [Saga Pattern](/docs/how-to-guides/saga-pattern.md)

### Snapshot
See [Definition Snapshot](#definition-snapshot).

### Standard Step
The default workflow step type - executes synchronously within the workflow process. Contrasts with async steps that dispatch to external executors. See: [Step Types](/docs/reference/step-types.md)

### State
The data associated with a workflow instance, defined by a Pydantic model. State is updated as steps execute and persisted to the database. See: [State Management](/docs/explanation/state-management.md)

### State Model
A Pydantic class defining the schema for workflow state. Provides type validation and serialization. Example: `OrderState(BaseModel)`. See: [State Models](/docs/how-to-guides/state-models.md)

### Step
A unit of work in a workflow. Each step executes a Python function (or HTTP request) and can update workflow state. See: [Step Types](/docs/reference/step-types.md)

### Step Context
An object (`StepContext`) passed to every step function providing runtime information: workflow ID, step name, previous results, loop state, etc.

### Step Function
The Python function executed by a workflow step. Must accept `(state, context, **user_input)` parameters and return a dict. See: [Writing Steps](/docs/how-to-guides/writing-steps.md)

### Store-and-Forward (SAF)
A reliability pattern where transactions are stored locally when offline and forwarded to the cloud when connectivity returns. Core feature of Rufus Edge. See: [Edge Architecture](/docs/RUFUS_EDGE_FINTECH_ARCHITECTURE.md)

### Sub-Workflow
A workflow instance created and managed by another workflow. Enables hierarchical composition and reusable workflow components. See: [Sub-Workflows](/docs/how-to-guides/sub-workflows.md)

---

## T

### Template Engine
A pluggable interface (`TemplateEngine`) for rendering dynamic content from workflow state. Default implementation uses Jinja2. Used in HTTP steps for dynamic URLs and bodies.

### TestHarness
A utility class for testing workflows with in-memory providers. Simplifies unit testing by avoiding database setup. See: [Testing](/docs/how-to-guides/testing.md)

### TMS
Terminal Management System. In fintech, the platform that manages device configurations, fraud rules, and software updates.

---

## W

### Workflow
An instance of a workflow type, representing a single execution (e.g., one order, one loan application). Has unique ID, state, status, and execution history.

### Workflow Builder
The class (`WorkflowBuilder`) responsible for loading YAML configurations, resolving Python functions, and creating workflow instances. See: [Architecture](/docs/explanation/architecture.md)

### Workflow Engine
The orchestration logic that executes workflows step-by-step, handles directives, manages state, and enforces dependencies. Implemented in `Workflow` class.

### Workflow Type
A template/class of workflow defined by YAML configuration (e.g., "OrderProcessing", "LoanApproval"). Multiple workflow instances can exist for the same type.

### Workflow Versioning
The practice of tracking workflow definition versions and snapshotting definitions with each instance. Prevents running workflows from breaking when YAML files change. See: [Workflow Versioning](/docs/explanation/versioning.md)

---

## X

### XSS (Cross-Site Scripting)
A security vulnerability where malicious scripts are injected into web applications. Rufus includes optional semantic firewall for XSS detection in step inputs. See: [Security](/docs/reference/security.md)

---

## Z

### WASI (WebAssembly System Interface)
A standard interface that gives WebAssembly modules safe, sandboxed access to system primitives (stdin, stdout, filesystem, clock). Rufus uses WASI to pass state to WASM modules via stdin and collect results from stdout.

### WASM (WebAssembly)
A portable binary instruction format that runs in a sandboxed environment. Rufus supports `WASM` as a first-class workflow step type, enabling step logic written in any language that compiles to WASM (Rust, C, Go, AssemblyScript). See: [WASM Step Type](/docs/reference/configuration/step-types.md#wasm)

### WasmBinaryResolver
A Protocol (interface) in `rufus.implementations.execution.wasm_runtime` that abstracts WASM binary lookup. Two implementations: `DiskWasmBinaryResolver` (cloud — reads from disk via `wasm_components` DB table) and `SqliteWasmBinaryResolver` (edge — reads BLOB from `device_wasm_cache`).

### WasmRuntime
The helper class in `rufus.implementations.execution.wasm_runtime` that instantiates a `wasmtime` WASI engine, executes a WASM module, and returns its JSON stdout as a dict. Injected into `Workflow` via the `wasm_runtime=` parameter.

### Zombie Workflow
A workflow stuck in `RUNNING` status because the worker process crashed without updating the database. Detected via stale heartbeats and automatically marked `FAILED_WORKER_CRASH`. See: [Zombie Recovery](/docs/explanation/zombie-recovery.md)

---

## Cross-References

For detailed explanations of these concepts, see:
- [Architecture Overview](/docs/explanation/architecture.md)
- [Core Concepts](/docs/explanation/core-concepts.md)
- [Step Types Reference](/docs/reference/step-types.md)
- [Provider Reference](/docs/reference/providers.md)
- [How-To Guides](/docs/how-to-guides/)

---

**Last Updated:** 2026-02-13
