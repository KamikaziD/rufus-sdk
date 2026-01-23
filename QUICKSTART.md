# Rufus SDK - Quickstart Guide

Get started with Rufus in 5 minutes. This guide will walk you through installing the SDK, creating your first workflow, and executing it.

## What is Rufus?

Rufus is a Python-native, SDK-first workflow engine for orchestrating complex business processes and AI pipelines. Unlike server-based workflow engines, Rufus embeds directly into your Python applications.

**Key Features:**
- **SDK-First**: Embed directly in Django, Flask, FastAPI, or any Python app
- **Declarative**: Define workflows in YAML, not code
- **Pluggable**: Swap persistence, execution, and observability providers
- **Production-Ready**: Saga patterns, parallel execution, human-in-the-loop

## Installation

### Prerequisites

- Python 3.9 or higher
- pip or poetry

### Install Rufus SDK

```bash
# Clone the repository (until PyPI release)
git clone https://github.com/your-org/rufus.git
cd rufus

# Install with pip
pip install -e .

# Or with poetry
poetry install
```

### Verify Installation

```bash
# Check CLI is available
rufus --help

# Run Python import test
python -c "from rufus.engine import WorkflowEngine; print('Rufus SDK installed successfully!')"
```

## Your First Workflow (5 Minutes)

Let's create a simple greeting workflow that demonstrates Rufus basics.

### Step 1: Create Project Structure

```bash
mkdir my_workflow_project
cd my_workflow_project
touch greeting_workflow.yaml workflow_registry.yaml state_models.py steps.py run_workflow.py
```

### Step 2: Define State Model (`state_models.py`)

State models use Pydantic for validation:

```python
from pydantic import BaseModel
from typing import Optional

class GreetingState(BaseModel):
    """State for the greeting workflow."""
    name: str
    greeting: Optional[str] = None
    formatted_output: Optional[str] = None
```

### Step 3: Implement Step Functions (`steps.py`)

Step functions receive state and context:

```python
from rufus.models import StepContext
from state_models import GreetingState

def generate_greeting(state: GreetingState, context: StepContext):
    """Generate a personalized greeting."""
    print(f"[{context.step_name}] Generating greeting for: {state.name}")
    state.greeting = f"Hello, {state.name}!"
    return {"greeting": state.greeting}

def format_output(state: GreetingState, context: StepContext):
    """Format the final output."""
    print(f"[{context.step_name}] Formatting output...")
    state.formatted_output = f">>> {state.greeting} <<<"
    return {"formatted_output": state.formatted_output}
```

### Step 4: Define Workflow (`greeting_workflow.yaml`)

Workflows are declarative YAML configurations:

```yaml
workflow_type: "GreetingWorkflow"
workflow_version: "1.0"
initial_state_model: "state_models.GreetingState"

steps:
  - name: "Generate_Greeting"
    type: "STANDARD"
    function: "steps.generate_greeting"
    automate_next: true

  - name: "Format_Output"
    type: "STANDARD"
    function: "steps.format_output"
    dependencies: ["Generate_Greeting"]
```

### Step 5: Register Workflow (`workflow_registry.yaml`)

The registry maps workflow types to their configurations:

```yaml
workflows:
  - type: "GreetingWorkflow"
    description: "Simple greeting workflow"
    config_file: "greeting_workflow.yaml"
    initial_state_model: "state_models.GreetingState"
```

### Step 6: Execute Workflow (`run_workflow.py`)

```python
import asyncio
import sys
from pathlib import Path
import yaml

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

async def main():
    # Load workflow registry
    with open("workflow_registry.yaml") as f:
        registry_config = yaml.safe_load(f)

    # Build registry dict
    workflow_registry = {}
    for workflow in registry_config["workflows"]:
        with open(workflow["config_file"]) as f:
            workflow_config = yaml.safe_load(f)
        workflow_registry[workflow["type"]] = {
            "initial_state_model_path": workflow["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version", "1.0"),
        }

    # Initialize engine with providers
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()

    # Start workflow with initial data
    initial_data = {"name": "World"}
    workflow = await engine.start_workflow(
        workflow_type="GreetingWorkflow",
        initial_data=initial_data
    )

    print(f"✓ Workflow started: {workflow.id}")
    print(f"  Status: {workflow.status}\n")

    # Execute steps
    while workflow.status == "ACTIVE":
        result = await workflow.next_step(user_input={})
        print(f"  Step completed: {result}\n")

    # Display results
    print(f"✓ Workflow completed!")
    print(f"  Final output: {workflow.state.formatted_output}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 7: Run It!

```bash
python run_workflow.py
```

**Expected Output:**

```
[SyncExecutor] Initialized.
✓ Workflow started: abc-123-def
  Status: ACTIVE

[Generate_Greeting] Generating greeting for: World
  Step completed: ({'greeting': 'Hello, World!'}, None)

[Format_Output] Formatting output...
  Step completed: ({'formatted_output': '>>> Hello, World! <<<'}, None)

✓ Workflow completed!
  Final output: >>> Hello, World! <<<
```

## Understanding the Example

### Architecture

```
Your Application (run_workflow.py)
    ↓
WorkflowEngine (orchestrator)
    ↓
Providers (pluggable components)
    ├── Persistence: InMemoryPersistence
    ├── Executor: SyncExecutor
    └── Observer: LoggingObserver
    ↓
Your Workflow (greeting_workflow.yaml)
    ├── Step 1: generate_greeting
    └── Step 2: format_output
```

### Key Concepts

1. **State Model** (`GreetingState`) - Pydantic model defining workflow data
2. **Step Functions** - Python functions that transform state
3. **Workflow Definition** - YAML file declaring step sequence
4. **WorkflowEngine** - Orchestrates execution with pluggable providers
5. **Providers** - Abstractions for persistence, execution, and observability

### Step Function Signature

All step functions follow this pattern:

```python
def step_name(state: StateModel, context: StepContext) -> Dict[str, Any]:
    # Access current state
    value = state.field_name

    # Modify state
    state.new_field = "value"

    # Return result dict (merged into state)
    return {"key": "value"}
```

The `StepContext` provides:
- `workflow_id` - Unique workflow identifier
- `step_name` - Current step name
- `validated_input` - User input (for human-in-the-loop)
- `previous_step_result` - Result from previous step

## Next Steps

### 1. Try the Complete Quickstart Example

We provide a full working example:

```bash
cd examples/quickstart
python run_quickstart.py
```

See [examples/quickstart/README.md](examples/quickstart/README.md) for details.

### 2. Explore Complex Features

Try the loan application example showcasing:
- Parallel execution
- Conditional branching
- Dynamic step injection
- Human-in-the-loop
- Saga compensation

```bash
cd examples/loan_application
python run_loan_sync.py
```

See [examples/loan_application/README.md](examples/loan_application/README.md) for details.

### 3. Customize Providers

#### Use PostgreSQL for Persistence

```python
from rufus.implementations.persistence.postgres import PostgresPersistence

persistence = PostgresPersistence(
    db_url="postgresql://user:pass@localhost/rufus_db"
)
```

#### Use Celery for Async Execution

```python
from rufus.implementations.execution.celery import CeleryExecutor
from celery import Celery

celery_app = Celery('workflows', broker='redis://localhost:6379')
executor = CeleryExecutor(celery_app=celery_app)
```

### 4. Add Workflow Features

#### Parallel Execution

```yaml
- name: "Run_Parallel_Tasks"
  type: "PARALLEL"
  automate_next: true
  tasks:
    - name: "Task_A"
      function: "steps.task_a"
    - name: "Task_B"
      function: "steps.task_b"
```

#### Conditional Branching

```python
from rufus.models import WorkflowJumpDirective

def evaluate_condition(state: MyState, context: StepContext):
    if state.score > 80:
        raise WorkflowJumpDirective(target_step_name="Approved_Path")
    else:
        raise WorkflowJumpDirective(target_step_name="Rejected_Path")
```

#### Human-in-the-Loop

```python
from rufus.models import WorkflowPauseDirective

def request_approval(state: MyState, context: StepContext):
    state.status = "PENDING_APPROVAL"
    raise WorkflowPauseDirective(result={"message": "Waiting for approval"})

def process_approval(state: MyState, context: StepContext):
    decision = context.validated_input.decision
    state.approved = (decision == "APPROVED")
    return {"approved": state.approved}
```

## Common Patterns

### Pattern 1: Multi-Step Processing Pipeline

```yaml
steps:
  - name: "Validate_Input"
    type: "STANDARD"
    function: "steps.validate"
    automate_next: true

  - name: "Transform_Data"
    type: "STANDARD"
    function: "steps.transform"
    dependencies: ["Validate_Input"]
    automate_next: true

  - name: "Save_Results"
    type: "STANDARD"
    function: "steps.save"
    dependencies: ["Transform_Data"]
```

### Pattern 2: Fork-Join Parallelism

```yaml
steps:
  - name: "Fetch_Data"
    type: "STANDARD"
    function: "steps.fetch"
    automate_next: true

  - name: "Parallel_Processing"
    type: "PARALLEL"
    dependencies: ["Fetch_Data"]
    automate_next: true
    tasks:
      - name: "Process_A"
        function: "steps.process_a"
      - name: "Process_B"
        function: "steps.process_b"

  - name: "Merge_Results"
    type: "STANDARD"
    function: "steps.merge"
    dependencies: ["Parallel_Processing"]
```

### Pattern 3: Approval Workflow

```yaml
steps:
  - name: "Submit_Request"
    type: "STANDARD"
    function: "steps.submit"
    automate_next: true

  - name: "Request_Approval"
    type: "STANDARD"
    function: "steps.request_approval"
    dependencies: ["Submit_Request"]

  - name: "Process_Decision"
    type: "STANDARD"
    function: "steps.process_decision"
    input_model: "models.ApprovalInput"
    dependencies: ["Request_Approval"]
    automate_next: true
```

## Troubleshooting

### Import Errors

**Problem:** `ModuleNotFoundError: No module named 'rufus'`

**Solution:**
```bash
pip install -e /path/to/rufus
```

### Step Function Not Found

**Problem:** `ImportError: cannot import name 'my_function'`

**Solution:** Ensure your function path in YAML matches the actual module and function:
```yaml
function: "steps.my_function"  # Must match steps.py module
```

### Workflow Won't Advance

**Problem:** Workflow status stays `ACTIVE` but doesn't progress

**Solution:** Check `automate_next: true` is set on steps that should auto-advance:
```yaml
- name: "My_Step"
  type: "STANDARD"
  function: "steps.my_step"
  automate_next: true  # ← Required for auto-advance
```

### State Not Updating

**Problem:** Step executes but state doesn't change

**Solution:** Ensure your step function modifies the state object directly:
```python
def my_step(state: MyState, context: StepContext):
    state.field = "new_value"  # ← Direct mutation
    return {"field": "new_value"}  # ← Also merged in
```

## Learn More

- **[README.md](README.md)** - Project overview and features
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)** - Architecture deep dive
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Migrating from Confucius
- **[API_REFERENCE.md](API_REFERENCE.md)** - Complete API documentation
- **[examples/](examples/)** - More working examples

## Get Help

- **Issues**: [GitHub Issues](https://github.com/your-org/rufus/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/rufus/discussions)
- **Examples**: Check `examples/` directory for working code

## What's Next?

Now that you've created your first workflow, you can:

1. **Add more steps** to build complex business logic
2. **Use parallel execution** to speed up independent operations
3. **Add human-in-the-loop** steps for approvals and reviews
4. **Switch to PostgreSQL** for durable persistence
5. **Deploy with Celery** for distributed execution
6. **Build a REST API** around your workflows with Flask/FastAPI

Happy orchestrating! 🎯
