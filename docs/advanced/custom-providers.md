# Advanced: Custom Providers

Rufus abstracts all external integrations via Python Protocol interfaces. This guide shows how to implement custom providers for persistence, execution, and observability.

---

## Provider Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Workflow Core                          │
│  (workflow.py, engine.py, builder.py)                   │
└────────────┬──────────────┬──────────────┬──────────────┘
             │              │              │
             ▼              ▼              ▼
    ┌────────────┐  ┌──────────────┐  ┌───────────┐
    │Persistence │  │  Execution   │  │ Observer  │
    │ Provider   │  │  Provider    │  │           │
    └────────────┘  └──────────────┘  └───────────┘
         │                 │                 │
         ▼                 ▼                 ▼
    PostgreSQL        Celery          Logging
    SQLite           ThreadPool       Metrics
    Redis             Sync            Tracing
    MongoDB          Custom           Custom
    Custom           ...              ...
```

---

## PersistenceProvider Interface

### Protocol Definition

```python
from typing import Protocol, Dict, Any, List, Optional
from datetime import datetime


class PersistenceProvider(Protocol):
    """
    Interface for workflow state persistence
    """

    async def initialize(self) -> None:
        """Initialize persistence (connect to database, create schema)"""
        ...

    async def close(self) -> None:
        """Close connections and cleanup resources"""
        ...

    async def save_workflow(
        self,
        workflow_id: str,
        workflow_data: Dict[str, Any]
    ) -> None:
        """Save or update workflow state"""
        ...

    async def load_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Load workflow state by ID"""
        ...

    async def list_workflows(
        self,
        workflow_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List workflows with optional filtering"""
        ...

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete workflow from persistence"""
        ...

    async def log_execution(
        self,
        workflow_id: str,
        log_level: str,
        message: str,
        step_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log workflow execution event"""
        ...

    async def record_metric(
        self,
        workflow_id: str,
        workflow_type: str,
        metric_name: str,
        metric_value: float,
        unit: Optional[str] = None,
        step_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Record workflow performance metric"""
        ...
```

---

## Example: MongoDB Persistence Provider

Let's implement a custom persistence provider for MongoDB.

```python
"""
MongoDB Persistence Provider

Stores workflow state in MongoDB.
"""

import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING


class MongoDBPersistenceProvider:
    """
    Persistence provider using MongoDB
    """

    def __init__(
        self,
        mongo_url: str = "mongodb://localhost:27017",
        database: str = "rufus",
        workflow_collection: str = "workflows",
        logs_collection: str = "execution_logs",
        metrics_collection: str = "metrics"
    ):
        self.mongo_url = mongo_url
        self.database_name = database
        self.workflow_collection_name = workflow_collection
        self.logs_collection_name = logs_collection
        self.metrics_collection_name = metrics_collection

        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.workflows = None
        self.logs = None
        self.metrics = None

    async def initialize(self) -> None:
        """Connect to MongoDB and create indexes"""
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client[self.database_name]

        # Get collections
        self.workflows = self.db[self.workflow_collection_name]
        self.logs = self.db[self.logs_collection_name]
        self.metrics = self.db[self.metrics_collection_name]

        # Create indexes
        await self.workflows.create_index("id", unique=True)
        await self.workflows.create_index("workflow_type")
        await self.workflows.create_index("status")
        await self.workflows.create_index("created_at", direction=DESCENDING)

        await self.logs.create_index("workflow_id")
        await self.logs.create_index("logged_at", direction=DESCENDING)

        await self.metrics.create_index("workflow_id")
        await self.metrics.create_index("metric_name")

    async def close(self) -> None:
        """Close MongoDB connection"""
        if self.client:
            self.client.close()

    async def save_workflow(
        self,
        workflow_id: str,
        workflow_data: Dict[str, Any]
    ) -> None:
        """Save workflow to MongoDB (upsert)"""
        workflow_data["updated_at"] = datetime.utcnow()

        if "created_at" not in workflow_data:
            workflow_data["created_at"] = datetime.utcnow()

        # Upsert (insert or update)
        await self.workflows.replace_one(
            {"id": workflow_id},
            workflow_data,
            upsert=True
        )

    async def load_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Load workflow from MongoDB"""
        workflow = await self.workflows.find_one({"id": workflow_id})

        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")

        # Remove MongoDB _id field
        workflow.pop("_id", None)

        return workflow

    async def list_workflows(
        self,
        workflow_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List workflows with filtering"""
        query = {}

        if workflow_type:
            query["workflow_type"] = workflow_type

        if status:
            query["status"] = status

        cursor = self.workflows.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)

        workflows = []
        async for workflow in cursor:
            workflow.pop("_id", None)
            workflows.append(workflow)

        return workflows

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete workflow from MongoDB"""
        result = await self.workflows.delete_one({"id": workflow_id})

        if result.deleted_count == 0:
            raise ValueError(f"Workflow not found: {workflow_id}")

        # Delete associated logs and metrics
        await self.logs.delete_many({"workflow_id": workflow_id})
        await self.metrics.delete_many({"workflow_id": workflow_id})

    async def log_execution(
        self,
        workflow_id: str,
        log_level: str,
        message: str,
        step_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log execution event to MongoDB"""
        log_entry = {
            "log_id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "log_level": log_level,
            "message": message,
            "step_name": step_name,
            "metadata": metadata or {},
            "logged_at": datetime.utcnow()
        }

        await self.logs.insert_one(log_entry)

    async def record_metric(
        self,
        workflow_id: str,
        workflow_type: str,
        metric_name: str,
        metric_value: float,
        unit: Optional[str] = None,
        step_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Record metric to MongoDB"""
        metric_entry = {
            "metric_id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "unit": unit,
            "step_name": step_name,
            "tags": tags or {},
            "recorded_at": datetime.utcnow()
        }

        await self.metrics.insert_one(metric_entry)

    # ========================================================================
    # Optional: Advanced Features
    # ========================================================================

    async def get_workflow_statistics(self) -> Dict[str, Any]:
        """Get workflow statistics"""
        pipeline = [
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }
            }
        ]

        stats = {}
        async for doc in self.workflows.aggregate(pipeline):
            stats[doc["_id"]] = doc["count"]

        return stats

    async def get_execution_logs(
        self,
        workflow_id: str,
        log_level: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get execution logs for workflow"""
        query = {"workflow_id": workflow_id}

        if log_level:
            query["log_level"] = log_level

        cursor = self.logs.find(query).sort("logged_at", ASCENDING).limit(limit)

        logs = []
        async for log in cursor:
            log.pop("_id", None)
            logs.append(log)

        return logs
```

---

## Using Custom Provider

```python
from rufus.builder import WorkflowBuilder
from my_providers.mongodb import MongoDBPersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver

async def main():
    # Initialize MongoDB persistence
    persistence = MongoDBPersistenceProvider(
        mongo_url="mongodb://localhost:27017",
        database="my_workflows"
    )
    await persistence.initialize()

    # Create workflow builder with custom provider
    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,  # Custom provider!
        execution_provider=SyncExecutor(),
        observer=LoggingObserver()
    )

    # Use normally
    workflow = builder.create_workflow(
        "MyWorkflow",
        initial_data={"user_id": "123"}
    )

    # Cleanup
    await persistence.close()
```

---

## ExecutionProvider Interface

### Protocol Definition

```python
from typing import Protocol, Dict, Any, Callable


class ExecutionProvider(Protocol):
    """
    Interface for step execution
    """

    async def execute_sync_step_function(
        self,
        func: Callable,
        state: Any,
        context: "StepContext",
        **kwargs
    ) -> Dict[str, Any]:
        """Execute synchronous step function"""
        ...

    async def dispatch_async_task(
        self,
        task_id: str,
        execution_id: str,
        step_name: str,
        function_path: str,
        state_dict: Dict[str, Any],
        context_dict: Dict[str, Any]
    ) -> None:
        """Dispatch async task to executor"""
        ...

    async def dispatch_parallel_tasks(
        self,
        tasks: List[Dict[str, Any]],
        workflow_id: str,
        timeout_seconds: int = 300
    ) -> List[Dict[str, Any]]:
        """Dispatch parallel tasks and wait for results"""
        ...
```

---

## Example: AWS Lambda Execution Provider

Execute workflow steps as Lambda functions.

```python
"""
AWS Lambda Execution Provider

Dispatches workflow steps to AWS Lambda functions.
"""

import json
import asyncio
from typing import Dict, Any, List, Callable
import boto3


class LambdaExecutionProvider:
    """
    Execution provider using AWS Lambda
    """

    def __init__(
        self,
        lambda_function_prefix: str = "rufus-step-",
        region_name: str = "us-east-1"
    ):
        self.lambda_function_prefix = lambda_function_prefix
        self.region_name = region_name
        self.lambda_client = boto3.client('lambda', region_name=region_name)

    async def execute_sync_step_function(
        self,
        func: Callable,
        state: Any,
        context: "StepContext",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute synchronous step function locally (not in Lambda)
        """
        # For STANDARD steps, execute locally
        return func(state, context, **kwargs)

    async def dispatch_async_task(
        self,
        task_id: str,
        execution_id: str,
        step_name: str,
        function_path: str,
        state_dict: Dict[str, Any],
        context_dict: Dict[str, Any]
    ) -> None:
        """
        Dispatch async task to AWS Lambda
        """
        # Build Lambda function name
        lambda_function_name = f"{self.lambda_function_prefix}{step_name.lower()}"

        # Build payload
        payload = {
            "task_id": task_id,
            "execution_id": execution_id,
            "step_name": step_name,
            "function_path": function_path,
            "state": state_dict,
            "context": context_dict
        }

        # Invoke Lambda asynchronously
        response = await asyncio.to_thread(
            self.lambda_client.invoke,
            FunctionName=lambda_function_name,
            InvocationType='Event',  # Async invocation
            Payload=json.dumps(payload)
        )

        if response['StatusCode'] not in (200, 202):
            raise RuntimeError(f"Lambda invocation failed: {response}")

    async def dispatch_parallel_tasks(
        self,
        tasks: List[Dict[str, Any]],
        workflow_id: str,
        timeout_seconds: int = 300
    ) -> List[Dict[str, Any]]:
        """
        Dispatch parallel tasks to multiple Lambda functions
        """
        # Invoke all Lambda functions concurrently
        lambda_futures = []

        for task in tasks:
            lambda_function_name = f"{self.lambda_function_prefix}{task['name'].lower()}"

            payload = {
                "task_id": task["task_id"],
                "workflow_id": workflow_id,
                "function_path": task["function_path"],
                "state": task["state"],
                "context": task["context"]
            }

            # Invoke Lambda synchronously (RequestResponse)
            future = asyncio.to_thread(
                self.lambda_client.invoke,
                FunctionName=lambda_function_name,
                InvocationType='RequestResponse',  # Sync invocation
                Payload=json.dumps(payload)
            )

            lambda_futures.append(future)

        # Wait for all Lambda invocations (with timeout)
        try:
            responses = await asyncio.wait_for(
                asyncio.gather(*lambda_futures),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Parallel tasks timed out after {timeout_seconds}s")

        # Parse results
        results = []
        for response in responses:
            if response['StatusCode'] != 200:
                raise RuntimeError(f"Lambda invocation failed: {response}")

            payload = json.loads(response['Payload'].read())
            results.append(payload.get('result', {}))

        return results
```

**Lambda Handler** (deployed to AWS Lambda):

```python
# lambda_function.py (deployed to AWS Lambda)

import json
import importlib


def lambda_handler(event, context):
    """
    AWS Lambda handler for Rufus workflow steps
    """
    # Extract task details
    task_id = event['task_id']
    function_path = event['function_path']
    state_dict = event['state']
    context_dict = event['context']

    # Import step function
    module_path, function_name = function_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    step_function = getattr(module, function_name)

    # Reconstruct state object
    state_model_path = context_dict['state_model_path']
    state_module, state_class = state_model_path.rsplit('.', 1)
    state_module = importlib.import_module(state_module)
    StateModel = getattr(state_module, state_class)

    state = StateModel(**state_dict)

    # Execute step function
    try:
        result = step_function(state, context_dict)

        return {
            'statusCode': 200,
            'result': result
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'error': str(e)
        }
```

---

## WorkflowObserver Interface

### Protocol Definition

```python
from typing import Protocol, Dict, Any


class WorkflowObserver(Protocol):
    """
    Interface for workflow event observation
    """

    async def on_workflow_started(
        self,
        workflow_id: str,
        workflow_type: str,
        initial_state: Dict[str, Any]
    ) -> None:
        """Called when workflow starts"""
        ...

    async def on_step_executed(
        self,
        workflow_id: str,
        step_name: str,
        step_result: Dict[str, Any],
        execution_time_ms: float
    ) -> None:
        """Called after each step execution"""
        ...

    async def on_workflow_completed(
        self,
        workflow_id: str,
        final_state: Dict[str, Any],
        total_execution_time_ms: float
    ) -> None:
        """Called when workflow completes successfully"""
        ...

    async def on_workflow_failed(
        self,
        workflow_id: str,
        error: Exception,
        failed_step: str
    ) -> None:
        """Called when workflow fails"""
        ...

    async def on_workflow_status_changed(
        self,
        workflow_id: str,
        old_status: str,
        new_status: str
    ) -> None:
        """Called when workflow status changes"""
        ...
```

---

## Example: Prometheus Metrics Observer

Collect metrics for Prometheus.

```python
"""
Prometheus Metrics Observer

Exports workflow metrics to Prometheus.
"""

from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge


# Prometheus metrics
workflow_started = Counter(
    'rufus_workflow_started_total',
    'Total workflows started',
    ['workflow_type']
)

workflow_completed = Counter(
    'rufus_workflow_completed_total',
    'Total workflows completed',
    ['workflow_type', 'status']
)

step_execution_time = Histogram(
    'rufus_step_execution_seconds',
    'Step execution time in seconds',
    ['workflow_type', 'step_name'],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
)

workflow_execution_time = Histogram(
    'rufus_workflow_execution_seconds',
    'Workflow execution time in seconds',
    ['workflow_type'],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0)
)

active_workflows = Gauge(
    'rufus_active_workflows',
    'Number of active workflows',
    ['workflow_type']
)


class PrometheusObserver:
    """
    Workflow observer that exports metrics to Prometheus
    """

    async def on_workflow_started(
        self,
        workflow_id: str,
        workflow_type: str,
        initial_state: Dict[str, Any]
    ) -> None:
        """Increment workflow started counter"""
        workflow_started.labels(workflow_type=workflow_type).inc()
        active_workflows.labels(workflow_type=workflow_type).inc()

    async def on_step_executed(
        self,
        workflow_id: str,
        step_name: str,
        step_result: Dict[str, Any],
        execution_time_ms: float
    ) -> None:
        """Record step execution time"""
        workflow_type = step_result.get('workflow_type', 'unknown')
        step_execution_time.labels(
            workflow_type=workflow_type,
            step_name=step_name
        ).observe(execution_time_ms / 1000.0)  # Convert to seconds

    async def on_workflow_completed(
        self,
        workflow_id: str,
        final_state: Dict[str, Any],
        total_execution_time_ms: float
    ) -> None:
        """Record workflow completion"""
        workflow_type = final_state.get('workflow_type', 'unknown')

        workflow_completed.labels(
            workflow_type=workflow_type,
            status='completed'
        ).inc()

        workflow_execution_time.labels(
            workflow_type=workflow_type
        ).observe(total_execution_time_ms / 1000.0)

        active_workflows.labels(workflow_type=workflow_type).dec()

    async def on_workflow_failed(
        self,
        workflow_id: str,
        error: Exception,
        failed_step: str
    ) -> None:
        """Record workflow failure"""
        workflow_type = getattr(error, 'workflow_type', 'unknown')

        workflow_completed.labels(
            workflow_type=workflow_type,
            status='failed'
        ).inc()

        active_workflows.labels(workflow_type=workflow_type).dec()

    async def on_workflow_status_changed(
        self,
        workflow_id: str,
        old_status: str,
        new_status: str
    ) -> None:
        """Log status change (no-op for Prometheus)"""
        pass
```

**Expose metrics endpoint:**

```python
from prometheus_client import start_http_server

# Start Prometheus metrics server
start_http_server(8000)  # Metrics at http://localhost:8000/metrics
```

---

## Testing Custom Providers

### Test PersistenceProvider

```python
import pytest
from my_providers.mongodb import MongoDBPersistenceProvider


@pytest.fixture
async def persistence():
    """Fixture for MongoDB persistence"""
    provider = MongoDBPersistenceProvider(
        mongo_url="mongodb://localhost:27017",
        database="test_rufus"
    )
    await provider.initialize()

    yield provider

    # Cleanup: drop test database
    await provider.db.client.drop_database("test_rufus")
    await provider.close()


@pytest.mark.asyncio
async def test_save_and_load_workflow(persistence):
    """Test saving and loading workflow"""
    workflow_data = {
        "id": "test-workflow-123",
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "state": {"user_id": "123"},
        "steps_config": []
    }

    # Save workflow
    await persistence.save_workflow("test-workflow-123", workflow_data)

    # Load workflow
    loaded = await persistence.load_workflow("test-workflow-123")

    assert loaded["id"] == "test-workflow-123"
    assert loaded["workflow_type"] == "TestWorkflow"
    assert loaded["state"]["user_id"] == "123"


@pytest.mark.asyncio
async def test_list_workflows(persistence):
    """Test listing workflows with filtering"""
    # Create workflows
    for i in range(5):
        await persistence.save_workflow(
            f"workflow-{i}",
            {
                "id": f"workflow-{i}",
                "workflow_type": "TestWorkflow",
                "status": "ACTIVE" if i % 2 == 0 else "COMPLETED"
            }
        )

    # List all workflows
    all_workflows = await persistence.list_workflows()
    assert len(all_workflows) == 5

    # List only ACTIVE workflows
    active_workflows = await persistence.list_workflows(status="ACTIVE")
    assert len(active_workflows) == 3
```

---

## Best Practices

### ✅ Do:

1. **Implement all protocol methods**
2. **Handle errors gracefully**
3. **Add connection pooling** for database providers
4. **Implement retry logic** for transient failures
5. **Add logging** for debugging
6. **Write comprehensive tests**

### ❌ Don't:

1. **Block async operations** (use `asyncio.to_thread` for sync libraries)
2. **Leak connections** (always close in `close()`)
3. **Ignore exceptions** (propagate or handle properly)
4. **Skip initialization** (use `initialize()` method)

---

## Summary

Custom providers allow you to integrate Rufus with any backend:

- **Persistence**: MongoDB, DynamoDB, Cassandra, etc.
- **Execution**: AWS Lambda, Google Cloud Functions, Kubernetes Jobs
- **Observability**: Prometheus, DataDog, New Relic, custom analytics

**Follow the protocol interfaces** and Rufus core remains unchanged.
