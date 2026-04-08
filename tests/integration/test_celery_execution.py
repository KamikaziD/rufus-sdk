"""
Integration tests for Celery execution provider.

These tests require:
- PostgreSQL database
- Redis server
- Celery worker running

Setup:
    docker run -d --name redis-test -p 6380:6379 redis:latest
    export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_test"
    export CELERY_BROKER_URL="redis://localhost:6380/0"
    export CELERY_RESULT_BACKEND="redis://localhost:6380/0"

Run tests:
    pytest tests/integration/test_celery_execution.py -v
"""
import pytest
import asyncio
import time
import os
from typing import Dict, Any

# Skip all tests if Celery not installed
pytest.importorskip("celery")
pytest.importorskip("redis")

from ruvon.implementations.execution.celery import CeleryExecutionProvider
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
from ruvon.implementations.observability.logging import LoggingObserver
from ruvon.builder import WorkflowBuilder
from ruvon.models import StepContext, BaseModel
from ruvon.celery_app import celery_app
from pydantic import Field


# Test state models
class AsyncTestState(BaseModel):
    """State model for async execution tests."""
    user_id: str
    amount: float = 0.0
    transaction_id: str = ""
    status: str = "pending"
    async_result: Dict[str, Any] = Field(default_factory=dict)


class ParallelTestState(BaseModel):
    """State model for parallel execution tests."""
    order_id: str
    credit_check: Dict[str, Any] = Field(default_factory=dict)
    inventory_check: Dict[str, Any] = Field(default_factory=dict)
    fraud_check: Dict[str, Any] = Field(default_factory=dict)


class SubWorkflowTestState(BaseModel):
    """State model for sub-workflow tests."""
    user_id: str
    kyc_status: str = "pending"
    sub_workflow_results: Dict[str, Any] = Field(default_factory=dict)


# Test Celery tasks
@celery_app.task
def async_payment_task(state: dict, workflow_id: str):
    """Simulates async payment processing."""
    import time
    time.sleep(2)  # Simulate processing
    return {
        "transaction_id": "tx_123456",
        "status": "approved",
        "amount": state.get("amount", 0) * 1.1  # Add processing fee
    }


@celery_app.task
def credit_check_task(state: dict, workflow_id: str):
    """Parallel task: credit check."""
    time.sleep(1)
    return {"credit_score": 750, "approved": True}


@celery_app.task
def inventory_check_task(state: dict, workflow_id: str):
    """Parallel task: inventory check."""
    time.sleep(1)
    return {"in_stock": True, "quantity": 50}


@celery_app.task
def fraud_check_task(state: dict, workflow_id: str):
    """Parallel task: fraud check."""
    time.sleep(1)
    return {"fraud_score": 0.05, "risk_level": "low"}


@pytest.fixture
async def db_url():
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def persistence(db_url):
    """Create and initialize PostgreSQL persistence provider."""
    provider = PostgresPersistenceProvider(db_url=db_url)
    await provider.initialize()
    yield provider
    await provider.close()


@pytest.fixture
async def celery_execution():
    """Create Celery execution provider."""
    provider = CeleryExecutionProvider()
    # Mock engine for testing
    class MockEngine:
        class MockBuilder:
            @staticmethod
            def _import_from_string(path: str):
                """Import function from string path."""
                import importlib
                module_path, func_name = path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                return getattr(module, func_name)

        workflow_builder = MockBuilder()

    await provider.initialize(MockEngine())
    yield provider
    await provider.close()


@pytest.fixture
def celery_worker_running():
    """Check if Celery worker is running."""
    # Try to ping Celery workers
    inspect = celery_app.control.inspect()
    active_workers = inspect.active()

    if not active_workers:
        pytest.skip(
            "No Celery workers running. Start worker with: "
            "celery -A rufus.celery_app worker --loglevel=info"
        )
    return True


@pytest.mark.asyncio
@pytest.mark.integration
class TestCeleryAsyncExecution:
    """Test async task execution with Celery."""

    async def test_dispatch_async_task(self, persistence, celery_execution, celery_worker_running):
        """Test dispatching an async task to Celery worker."""
        workflow_id = "test-async-workflow-001"
        state_data = {
            "user_id": "user123",
            "amount": 100.0
        }

        # Dispatch async task
        task_id = celery_execution.dispatch_async_task(
            func_path="tests.integration.test_celery_execution.async_payment_task",
            state_data=state_data,
            workflow_id=workflow_id,
            current_step_index=0
        )

        assert task_id is not None
        print(f"Dispatched task: {task_id}")

        # Wait for task to complete (with timeout)
        from celery.result import AsyncResult
        result = AsyncResult(task_id, app=celery_app)

        timeout = 10
        start_time = time.time()
        while not result.ready() and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.5)

        assert result.ready(), "Task did not complete within timeout"
        assert result.successful(), f"Task failed: {result.info}"

        task_result = result.get()
        assert "transaction_id" in task_result
        assert task_result["status"] == "approved"
        print(f"Task result: {task_result}")


@pytest.mark.asyncio
@pytest.mark.integration
class TestCeleryParallelExecution:
    """Test parallel task execution with Celery."""

    async def test_dispatch_parallel_tasks(self, persistence, celery_execution, celery_worker_running):
        """Test parallel execution of multiple tasks."""
        workflow_id = "test-parallel-workflow-001"
        state_data = {"order_id": "order123"}

        # Define parallel tasks
        from ruvon.models import ParallelExecutionTask
        tasks = [
            ParallelExecutionTask(
                name="credit_check",
                function_path="tests.integration.test_celery_execution.credit_check_task"
            ),
            ParallelExecutionTask(
                name="inventory_check",
                function_path="tests.integration.test_celery_execution.inventory_check_task"
            ),
            ParallelExecutionTask(
                name="fraud_check",
                function_path="tests.integration.test_celery_execution.fraud_check_task"
            )
        ]

        # Dispatch parallel tasks
        group_id = celery_execution.dispatch_parallel_tasks(
            tasks=tasks,
            state_data=state_data,
            workflow_id=workflow_id,
            current_step_index=0,
            merge_function_path=None
        )

        assert group_id is not None
        print(f"Dispatched parallel group: {group_id}")

        # Wait for all tasks to complete
        from celery.result import GroupResult
        group_result = GroupResult.restore(group_id, app=celery_app)

        timeout = 15
        start_time = time.time()
        while not group_result.ready() and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.5)

        assert group_result.ready(), "Parallel tasks did not complete within timeout"
        assert group_result.successful(), "Some parallel tasks failed"

        results = group_result.get()
        print(f"Parallel results: {results}")

        # Verify all tasks returned results
        assert len(results) == 3


@pytest.mark.asyncio
@pytest.mark.integration
class TestWorkerRegistry:
    """Test Celery worker registry functionality."""

    async def test_worker_registration(self, persistence):
        """Test that workers register in database."""
        # Query worker_nodes table
        async with persistence.pool.acquire() as conn:
            workers = await conn.fetch("""
                SELECT worker_id, hostname, region, status, last_heartbeat
                FROM worker_nodes
                WHERE status = 'online'
                ORDER BY last_heartbeat DESC
            """)

        # Should have at least one worker if Celery is running
        if workers:
            print(f"Active workers: {len(workers)}")
            for worker in workers:
                print(f"  - {worker['worker_id']} @ {worker['hostname']} ({worker['region']})")
        else:
            pytest.skip("No active workers found in database")

    async def test_worker_heartbeat(self, persistence):
        """Test that worker heartbeats are updating."""
        # Get initial heartbeat
        async with persistence.pool.acquire() as conn:
            initial = await conn.fetchrow("""
                SELECT worker_id, last_heartbeat
                FROM worker_nodes
                WHERE status = 'online'
                ORDER BY last_heartbeat DESC
                LIMIT 1
            """)

        if not initial:
            pytest.skip("No active workers found")

        print(f"Initial heartbeat: {initial['last_heartbeat']}")

        # Wait for heartbeat update (workers send every 30s)
        await asyncio.sleep(35)

        # Check updated heartbeat
        async with persistence.pool.acquire() as conn:
            updated = await conn.fetchrow("""
                SELECT last_heartbeat
                FROM worker_nodes
                WHERE worker_id = $1
            """, initial['worker_id'])

        assert updated['last_heartbeat'] > initial['last_heartbeat'], \
            "Worker heartbeat did not update"
        print(f"Updated heartbeat: {updated['last_heartbeat']}")


@pytest.mark.asyncio
@pytest.mark.integration
class TestEventPublishing:
    """Test Redis event publishing."""

    async def test_event_stream(self, celery_worker_running):
        """Test that events are published to Redis streams."""
        import redis.asyncio as redis

        redis_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        # Read recent events from workflow:persistence stream
        events = await r.xread({'workflow:persistence': '0'}, count=10)

        await r.close()

        if events:
            print(f"Found {len(events)} event streams")
            for stream_name, messages in events:
                print(f"Stream: {stream_name}, Messages: {len(messages)}")
        else:
            print("No events found in Redis streams (this is OK for fresh setup)")


@pytest.mark.asyncio
@pytest.mark.integration
class TestFullWorkflowExecution:
    """Integration test for complete workflow execution with Celery."""

    async def test_complete_workflow_with_async_step(
        self,
        persistence,
        celery_worker_running,
        tmp_path
    ):
        """Test a complete workflow with async execution."""
        # This is a placeholder for a full end-to-end test
        # In a real scenario, you would:
        # 1. Create a workflow YAML with async steps
        # 2. Use WorkflowBuilder to load it
        # 3. Execute the workflow
        # 4. Verify it transitions through states correctly
        # 5. Verify the final result

        # For now, we'll just verify the components work together
        pytest.skip("Full workflow integration test requires complete setup - implement in Phase 3")


# Pytest markers
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL") or not os.environ.get("CELERY_BROKER_URL"),
        reason="DATABASE_URL and CELERY_BROKER_URL must be set for integration tests"
    )
]
