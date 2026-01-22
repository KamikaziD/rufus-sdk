# Technical Documentation

## Architecture

The new architecture is built around the `rufus` Python package, which can be embedded in any application.

```
┌─────────────────────────────────────────────────┐
│        Your Application (FastAPI, Django, etc.) │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│                 Rufus SDK (Core)                │
│  ┌──────────────────────────────────────────┐   │
│  │  WorkflowEngine (Public API)             │   │
│  └──────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────┐   │
│  │  Pluggable Providers                     │   │
│  │    - Persistence (Postgres, InMemory)    │   │
│  │    - Execution (Celery, Sync)            │   │
│  │    - Observer (Logging, Metrics)         │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

An optional FastAPI server (`rufus_server`) is provided as an adapter for developers who prefer a standalone API.

## Developer Guide

### Using the SDK

To get started, install the core SDK:
```bash
pip install rufus
```

You can then define and run a workflow within your Python code:
```python
from rufus import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor

# Use in-memory providers for simple cases
engine = WorkflowEngine(
    persistence=InMemoryPersistence(),
    executor=SyncExecutor(),
    # ... other providers
)

# Start a workflow defined in your registry
handle = engine.start_workflow("MyWorkflowType", {"initial_data": "..."})
```
