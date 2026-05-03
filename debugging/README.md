# Debugging Workflows

This directory contains test workflows for debugging and development.

## Quick Start

### Option 1: Using setup script (Easiest)

```bash
cd /Users/kim/PycharmProjects/ruvon/debugging

# Source the setup script to add this directory to PYTHONPATH
source setup_workflow.sh

# Now run your workflow
ruvon workflow start TestApplication \
  -d '{"name":"Detmar", "age": 45}' \
  --config ./test_workflow.yaml
```

### Option 2: One-liner

```bash
cd /Users/kim/PycharmProjects/ruvon/debugging
PYTHONPATH=$PWD ruvon workflow start TestApplication -d '{"name":"Detmar", "age": 45}' --config ./test_workflow.yaml
```

### Option 3: Python directly

```python
# From this directory
python << 'EOF'
import sys
import asyncio
sys.path.insert(0, '.')  # Add current directory to path

from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.execution.sync import SyncExecutionProvider

async def main():
    # Initialize providers
    persistence = SQLitePersistenceProvider(db_path="test.db")
    await persistence.initialize()

    # Create builder
    builder = WorkflowBuilder(
        config_dir=".",
        persistence_provider=persistence,
        execution_provider=SyncExecutionProvider()
    )

    # Start workflow
    workflow = await builder.create_workflow(
        workflow_type="TestApplication",
        initial_data={"name": "Detmar", "age": 45}
    )

    print(f"✅ Workflow started: {workflow.id}")
    print(f"   Status: {workflow.status}")

    # Execute next step
    await workflow.next_step()
    print(f"   After step: {workflow.status}")

    await persistence.close()

asyncio.run(main())
EOF
```

## Files

- **state_models.py** - Pydantic state models for workflows
- **workflow_functions.py** - Step function implementations
- **test_workflow.yaml** - Workflow configuration
- **workflow_registry.yaml** - Registry of available workflows
- **test.db** - SQLite database (created when you run workflows)

## Common Issues

### "No module named 'state_models'"

**Problem**: Python can't find your workflow modules.

**Solution**:
```bash
# Always run with PYTHONPATH set
cd /Users/kim/PycharmProjects/ruvon/debugging
PYTHONPATH=$PWD ruvon workflow start ...
```

### "Table workflow_executions not found"

**Problem**: Database not initialized.

**Solution**:
```bash
# Initialize the database
ruvon db init --db test.db
```

## Development Workflow

1. **Edit your workflow**:
   - Modify `state_models.py` for state structure
   - Modify `workflow_functions.py` for step logic
   - Modify `test_workflow.yaml` for workflow config

2. **Run and test**:
   ```bash
   source setup_workflow.sh
   ruvon workflow start TestApplication -d '{"name":"Test", "age": 30}' --config ./test_workflow.yaml
   ```

3. **Check logs**:
   ```bash
   ruvon logs <workflow-id>
   ```

4. **Iterate** and repeat!

## Tips

- Use `--help` to see all options: `ruvon workflow start --help`
- List workflows: `ruvon list`
- Show workflow details: `ruvon show <workflow-id>`
- Cancel workflow: `ruvon cancel <workflow-id>`
