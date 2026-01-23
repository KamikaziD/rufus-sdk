# Rufus Quickstart Example

This example demonstrates the basics of Rufus in under 5 minutes. You'll learn how to define workflows, write step functions, and execute them with the Rufus SDK.

## What You'll Build

A simple greeting workflow that:
1. Takes a name as input
2. Generates a personalized greeting
3. Formats the output with decorative styling

## Prerequisites

```bash
pip install rufus
```

Or if you're in the development environment:
```bash
cd /path/to/rufus
pip install -e .
```

## Quick Start

```bash
python run_quickstart.py
```

Expected output:
```
============================================================
Rufus SDK Quickstart Example
============================================================

Step 1: Loading workflow registry...
✓ Loaded 1 workflow(s)

Step 2: Initializing WorkflowEngine...
✓ Engine initialized

Step 3: Starting GreetingWorkflow...
✓ Workflow started

Step 4: Executing workflow steps...
--- Step 1: Generate_Greeting ---
[Generate_Greeting] Generating greeting for: World
[Generate_Greeting] Generated: Hello, World!
[Format_Output] Formatting output...
[Format_Output] Formatted: >>> Hello, World! <<<

============================================================
Workflow Complete!
============================================================
Final Status: COMPLETED
Final Output: >>> Hello, World! <<<
```

## File Structure

```
quickstart/
├── state_models.py           # Defines workflow state
├── steps.py                  # Implements step functions
├── greeting_workflow.yaml    # Workflow definition
├── workflow_registry.yaml    # Registers workflows
├── run_quickstart.py         # Runs the workflow
└── README.md                 # This file
```

## How It Works

### 1. Define State Model (`state_models.py`)

The state holds all data throughout the workflow execution:

```python
from pydantic import BaseModel
from typing import Optional

class GreetingState(BaseModel):
    """State for the greeting workflow."""
    name: str                          # Input: person's name
    greeting: Optional[str] = None     # Generated greeting
    formatted_output: Optional[str] = None  # Final output
```

**Key Points:**
- Uses Pydantic for validation and type safety
- Fields marked `Optional` are set by workflow steps
- State is automatically persisted after each step

### 2. Implement Step Functions (`steps.py`)

Each step is a Python function that receives state and context:

```python
from rufus.models import StepContext
from state_models import GreetingState

def generate_greeting(state: GreetingState, context: StepContext):
    """Generates a personalized greeting."""
    state.greeting = f"Hello, {state.name}!"
    return {"greeting": state.greeting}

def format_output(state: GreetingState, context: StepContext):
    """Formats the final output."""
    state.formatted_output = f">>> {state.greeting} <<<"
    return {"formatted_output": state.formatted_output}
```

**Key Points:**
- All step functions must accept `(state, context)` parameters
- `state` is your Pydantic model instance
- `context` provides workflow metadata (workflow_id, step_name, etc.)
- Return a dict to merge results into state (optional)
- Modifying state directly also works

### 3. Define Workflow in YAML (`greeting_workflow.yaml`)

YAML defines the execution flow:

```yaml
workflow_type: "GreetingWorkflow"
workflow_version: "1.0"
initial_state_model: "state_models.GreetingState"

steps:
  - name: "Generate_Greeting"
    type: "STANDARD"                  # Synchronous execution
    function: "steps.generate_greeting"  # Python function path
    automate_next: true               # Auto-proceed to next step
    dependencies: []

  - name: "Format_Output"
    type: "STANDARD"
    function: "steps.format_output"
    dependencies: ["Generate_Greeting"]  # Waits for previous step
```

**Key Points:**
- `workflow_type` must match registry entry
- `initial_state_model` is the Python import path
- `type: STANDARD` runs synchronously
- `automate_next: true` chains steps automatically
- `dependencies` controls execution order

### 4. Register Workflow (`workflow_registry.yaml`)

```yaml
workflows:
  - type: "GreetingWorkflow"
    description: "A simple greeting workflow"
    config_file: "greeting_workflow.yaml"
    initial_state_model: "state_models.GreetingState"
```

### 5. Run with SDK (`run_quickstart.py`)

```python
import asyncio
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
# ... other imports

async def main():
    # Initialize engine
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),  # No database required
        executor=SyncExecutor(),            # Synchronous execution
        observer=LoggingObserver(),         # Console logging
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()

    # Start workflow
    workflow = await engine.start_workflow(
        workflow_type="GreetingWorkflow",
        initial_data={"name": "World"}
    )

    # Execute steps
    while workflow.status == "ACTIVE":
        result = await workflow.next_step(user_input={})

    print(f"Final Output: {workflow.state.formatted_output}")

asyncio.run(main())
```

**Key Points:**
- `InMemoryPersistence()` - no database setup required
- `SyncExecutor()` - runs in single process, perfect for testing
- `engine.initialize()` must be called before use
- `workflow.next_step()` advances the workflow one step
- Loop until `workflow.status != "ACTIVE"`

## Customization

### Try Different Names

Edit `run_quickstart.py`:
```python
initial_data = {"name": "Alice"}  # Change from "World" to "Alice"
```

### Add a New Step

1. Add function to `steps.py`:
```python
def add_timestamp(state: GreetingState, context: StepContext):
    """Adds a timestamp to the greeting."""
    from datetime import datetime
    state.formatted_output = f"{state.formatted_output} at {datetime.now()}"
    return {"formatted_output": state.formatted_output}
```

2. Add step to `greeting_workflow.yaml`:
```yaml
  - name: "Add_Timestamp"
    type: "STANDARD"
    function: "steps.add_timestamp"
    dependencies: ["Format_Output"]
```

3. Run again:
```bash
python run_quickstart.py
```

## Next Steps

### Explore Advanced Features

- **Complex Example**: See `../loan_application/` for:
  - Parallel execution
  - Decision steps (conditional branching)
  - Sub-workflows (nested execution)
  - Human-in-the-loop (manual approval)
  - Saga pattern (automatic rollback)
  - Async execution with Celery

- **Integration Examples**:
  - Flask: `../flask_app/`
  - Django: `../django_app/`
  - Jupyter: `../notebooks/`

### Read the Documentation

- [Full Quickstart Guide](../../docs/QUICKSTART.md) - Detailed tutorial
- [YAML Reference](../../YAML_GUIDE.md) - Complete YAML syntax
- [API Reference](../../API_REFERENCE.md) - SDK API documentation
- [Usage Guide](../../USAGE_GUIDE.md) - Comprehensive guide

## Common Issues

### Import Error: "No module named 'rufus'"

**Solution**: Install the package:
```bash
pip install rufus
# OR for development:
pip install -e /path/to/rufus
```

### Import Error: "No module named 'state_models'"

**Solution**: Run the script from the quickstart directory:
```bash
cd examples/quickstart
python run_quickstart.py
```

### AttributeError in Jinja2TemplateEngine

**Solution**: Make sure you're running the latest version. The `render_string_template` method was added recently.

## Understanding the Output

```
[Generate_Greeting] Generating greeting for: World
```
- Brackets show which step is executing
- Prints from within step functions appear here

```
✓ Step completed
  Result: ({'greeting': 'Hello, World!'}, None)
```
- Shows the return value from the step function
- Tuple format: (result_dict, directive)

```
State: name='World' greeting='Hello, World!' formatted_output=None
```
- Shows current workflow state after each step
- Watch how fields get populated as workflow progresses

## Tips for Learning

1. **Start Simple**: Run the example as-is first
2. **Modify Incrementally**: Change one thing at a time
3. **Check State**: Print `workflow.state` to see what's happening
4. **Add Logging**: Use `print()` in your step functions
5. **Experiment**: Try breaking things to learn how errors work

## Questions?

- Read the [Usage Guide](../../USAGE_GUIDE.md)
- Check the [YAML Guide](../../YAML_GUIDE.md)
- Explore other examples in `../`

---

**Congratulations!** You've completed the Rufus quickstart. You now know how to:
- ✅ Define workflow state with Pydantic
- ✅ Write step functions
- ✅ Configure workflows in YAML
- ✅ Run workflows with the SDK

Ready for more? Check out the [loan application example](../loan_application/) to see advanced features in action!
