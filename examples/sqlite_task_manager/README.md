# SQLite Task Manager Example

A simple task management workflow using Rufus SDK with SQLite persistence.

## Overview

This example demonstrates:
- Using SQLite for workflow persistence (no PostgreSQL required!)
- Creating and executing a multi-step workflow
- Workflow state management
- Human-in-the-loop approval steps
- Sub-workflow composition

## Features

**Workflow**: TaskApprovalWorkflow
1. **Create Task** - Initialize task with details
2. **Assign Task** - Auto-assign to available team member
3. **Request Approval** - Pause for manager approval
4. **Complete Task** - Mark task as done
5. **Send Notification** - Notify stakeholders

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Initialize Database

The example uses an SQLite database file (`tasks.db`) that will be created automatically on first run.

```bash
# No additional setup needed! SQLite creates the database file automatically
```

## Usage

### Run the Example

```bash
python examples/sqlite_task_manager/main.py
```

### Run with In-Memory Database (for testing)

```bash
python examples/sqlite_task_manager/main.py --in-memory
```

## Workflow Execution

The example creates a task approval workflow with the following steps:

1. Creates a new task workflow
2. Assigns the task automatically
3. Pauses for approval
4. Resumes after approval
5. Completes the task
6. Sends notifications

## Key Files

- `main.py` - Main application entry point
- `workflows/task_approval.yaml` - Workflow definition
- `steps.py` - Step function implementations
- `models.py` - State models

## Benefits of SQLite

✅ **No Server Required** - SQLite is embedded, no PostgreSQL needed
✅ **Fast Setup** - Database file created automatically
✅ **Perfect for Development** - Quick iteration and testing
✅ **Portable** - Single file database, easy to backup/move
✅ **Production-Ready** - Suitable for single-server deployments

## Switching to PostgreSQL

To use PostgreSQL instead (for production):

```python
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(
    db_url="postgresql://user:pass@localhost/rufus"
)
```

No code changes required - just swap the persistence provider!

## Performance

SQLite performance (based on benchmarks):
- **Save workflow**: ~9,000 ops/sec
- **Load workflow**: ~6,500 ops/sec
- **Create task**: ~7,800 ops/sec
- **Log execution**: ~9,000 ops/sec

Perfect for development, testing, and moderate production workloads.
