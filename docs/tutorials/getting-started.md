# Getting Started with Rufus

**Time:** 5 minutes
**Goal:** Create and run your first workflow

## What You'll Learn

In this tutorial, you'll:
1. Install Rufus
2. Create a simple workflow
3. Run it and see results
4. Understand the basics of workflow execution

## Prerequisites

- Python 3.9 or higher
- Basic Python knowledge
- 5 minutes of your time

## Step 1: Install Rufus

```bash
pip install -r requirements.txt
```

That's it! Rufus includes SQLite support by default, so no database setup is needed for this tutorial.

## Step 2: Create Your First Workflow

Create a new file called `hello_workflow.yaml`:

```yaml
# hello_workflow.yaml
workflow_type: "HelloWorkflow"
workflow_version: "1.0.0"
description: "My first Rufus workflow"
initial_state_model: "builtins.dict"

steps:
  - name: "Greet_User"
    type: "STANDARD"
    function: "hello_steps.greet_user"
    automate_next: true

  - name: "Say_Goodbye"
    type: "STANDARD"
    function: "hello_steps.say_goodbye"
```

**What this does:**
- Defines a workflow called "HelloWorkflow"
- Has two steps: greet and say goodbye
- Each step runs synchronously (`type: STANDARD`)
- Steps run automatically one after another (`automate_next: true`)

## Step 3: Write Step Functions

Create `hello_steps.py` in the same directory:

```python
# hello_steps.py
from rufus.models import StepContext

def greet_user(state: dict, context: StepContext, name: str = "World") -> dict:
    """Greet the user."""
    greeting = f"Hello, {name}!"
    print(f"Step {context.step_name}: {greeting}")
    return {"greeting": greeting}

def say_goodbye(state: dict, context: StepContext) -> dict:
    """Say goodbye to the user."""
    name = state.get("name", "World")
    farewell = f"Goodbye, {name}! See you next time."
    print(f"Step {context.step_name}: {farewell}")
    return {"farewell": farewell}
```

**Key concepts:**
- Step functions receive `state` (workflow data) and `context` (execution info)
- Return a dict that gets merged into workflow state
- Functions are just regular Python - nothing magic!

## Step 4: Register the Workflow

Create or update `config/workflow_registry.yaml`:

```yaml
workflows:
  - type: "HelloWorkflow"
    description: "My first workflow"
    config_file: "hello_workflow.yaml"
    initial_state_model: "builtins.dict"
```

## Step 5: Run It!

### Option A: Using the CLI (Recommended)

```bash
# Start the workflow
rufus start HelloWorkflow --data '{"name": "Alice"}'

# Output:
# ✅ Workflow started: <workflow-id>
# Step Greet_User: Hello, Alice!
# Step Say_Goodbye: Goodbye, Alice! See you next time.
```

### Option B: Using Python Code

```python
# run_workflow.py
import asyncio
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.implementations.observability.logging import LoggingObserver

async def main():
    # Create persistence (in-memory SQLite)
    persistence = SQLitePersistenceProvider(db_path=":memory:")
    await persistence.initialize()

    # Create builder
    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=SyncExecutionProvider(),
        observer=LoggingObserver()
    )

    # Start workflow
    workflow = await builder.create_workflow(
        workflow_type="HelloWorkflow",
        initial_data={"name": "Alice"}
    )

    # Execute all steps
    while workflow.status == "ACTIVE":
        await workflow.execute_next_step()

    print(f"Workflow completed! Final state: {workflow.state}")

    await persistence.close()

if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python run_workflow.py

# Output:
# Step Greet_User: Hello, Alice!
# Step Say_Goodbye: Goodbye, Alice! See you next time.
# Workflow completed! Final state: {'name': 'Alice', 'greeting': 'Hello, Alice!', 'farewell': 'Goodbye, Alice! See you next time.'}
```

## Step 6: Check the Results

You just ran your first Rufus workflow! Let's understand what happened:

1. **Workflow Created**: Rufus loaded the YAML definition and created a workflow instance
2. **Step 1 Executed**: `greet_user()` ran, returned data, merged into state
3. **Step 2 Auto-Started**: Because `automate_next: true`, the next step ran immediately
4. **Step 2 Executed**: `say_goodbye()` ran with the updated state
5. **Workflow Completed**: No more steps, status changed to "COMPLETED"

## What You've Learned

✅ **Install Rufus** - Single pip command
✅ **Define Workflows** - Simple YAML files
✅ **Write Step Functions** - Regular Python functions
✅ **Register Workflows** - Central registry file
✅ **Execute Workflows** - CLI or Python API

## What's Next?

Now that you've mastered the basics, explore:

- **[Build a Task Manager](build-task-manager.md)** - A complete practical project
- **[Adding Decision Steps](../how-to-guides/decision-steps.md)** - Conditional branching
- **[Workflow State Management](../explanation/state-management.md)** - How state flows through workflows

## Common Issues

**"Module not found: hello_steps"**
- Make sure `hello_steps.py` is in your Python path
- Try adding `sys.path.insert(0, '.')` to your script

**"Workflow type not found"**
- Check that `config/workflow_registry.yaml` exists
- Verify the `type` matches exactly

**"Step function not found"**
- Check the `function` path in YAML matches your Python module
- Use the full module path: `my_module.hello_steps.greet_user`

## Pro Tips

💡 **Use automate_next** - Chain steps together automatically
💡 **Return dicts** - Step results merge into workflow state
💡 **Print for debugging** - Simple prints work great for learning
💡 **Start simple** - Master basics before adding complexity

---

**Next Tutorial:** [Build a Task Manager](build-task-manager.md) - A complete practical project

**Need help?** Check the [Troubleshooting Guide](../how-to-guides/troubleshooting.md)
