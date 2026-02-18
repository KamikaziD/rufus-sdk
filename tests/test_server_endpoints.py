"""
Tests for new server endpoints: WebSocket, retry, rewind, resume.
"""

import pytest
import asyncio
import json
from uuid import uuid4
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Set environment variables before importing app
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure to use SQLite for tests
os.environ['WORKFLOW_STORAGE'] = 'sqlite'
os.environ['RUFUS_WORKFLOW_REGISTRY_PATH'] = 'tests/fixtures/test_registry.yaml'
os.environ['RUFUS_CONFIG_DIR'] = 'tests/fixtures'

from rufus_server.main import app
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.engine import WorkflowEngine
from rufus.builder import WorkflowBuilder


@pytest.fixture
def test_client():
    """Create test client for FastAPI app."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def setup_test_workflow():
    """Create a test workflow for endpoint testing."""
    persistence = InMemoryPersistence()
    await persistence.initialize()

    execution = SyncExecutor()
    observer = LoggingObserver()

    # Create minimal workflow registry
    workflow_registry = {
        "TestWorkflow": {
            "type": "TestWorkflow",
            "config_file": "test_workflow.yaml",
            "initial_state_model": "pydantic.BaseModel"
        }
    }

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        config_dir="tests/fixtures",
        persistence_provider=persistence,
        execution_provider=execution
    )

    engine = WorkflowEngine(
        workflow_builder=builder,
        persistence=persistence,
        execution=execution,
        observer=observer
    )

    # Inject into app
    import rufus_server.main as main_module
    main_module.workflow_engine = engine
    main_module.persistence_provider = persistence
    main_module.execution_provider = execution

    return engine, persistence


@pytest.mark.asyncio
async def test_retry_endpoint_success(test_client, setup_test_workflow):
    """Test retry endpoint successfully resets failed workflow."""
    engine, persistence = await setup_test_workflow

    # Create a failed workflow
    workflow_id = uuid4()
    workflow_dict = {
        "id": workflow_id,
        "workflow_type": "TestWorkflow",
        "status": "FAILED",
        "current_step": 2,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(workflow_id, workflow_dict)

    # Mock Celery task
    with patch('rufus.tasks.resume_from_async_task') as mock_task:
        mock_task.delay = Mock()

        # Call retry endpoint
        response = test_client.post(f"/api/v1/workflow/{workflow_id}/retry")

        assert response.status_code == 200
        assert response.json()["status"] == "retry_initiated"
        assert response.json()["workflow_id"] == str(workflow_id)

        # Verify workflow status changed to ACTIVE
        updated_workflow = await persistence.load_workflow(workflow_id)
        assert updated_workflow["status"] == "ACTIVE"

        # Verify Celery task was dispatched
        mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_retry_endpoint_not_failed(test_client, setup_test_workflow):
    """Test retry endpoint rejects non-failed workflows."""
    engine, persistence = await setup_test_workflow

    # Create an active workflow
    workflow_id = uuid4()
    workflow_dict = {
        "id": workflow_id,
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": 1,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(workflow_id, workflow_dict)

    # Call retry endpoint
    response = test_client.post(f"/api/v1/workflow/{workflow_id}/retry")

    assert response.status_code == 400
    assert "Only failed workflows can be retried" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rewind_endpoint_success(test_client, setup_test_workflow):
    """Test rewind endpoint decrements current_step."""
    engine, persistence = await setup_test_workflow

    # Create a workflow at step 2
    workflow_id = uuid4()
    workflow_dict = {
        "id": workflow_id,
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": 2,
        "state": {"data": "test"},
        "workflow_steps": [{"name": "Step1"}, {"name": "Step2"}, {"name": "Step3"}],
        "step_results": {"1": {"result": "data1"}, "2": {"result": "data2"}}
    }

    await persistence.save_workflow(workflow_id, workflow_dict)

    # Call rewind endpoint
    response = test_client.post(f"/api/v1/workflow/{workflow_id}/rewind")

    assert response.status_code == 200
    assert response.json()["status"] == "rewound"
    assert response.json()["current_step"] == 1

    # Verify workflow was rewound
    updated_workflow = await persistence.load_workflow(workflow_id)
    assert updated_workflow["current_step"] == 1
    assert updated_workflow["status"] == "ACTIVE"
    assert "2" not in updated_workflow.get("step_results", {})


@pytest.mark.asyncio
async def test_rewind_endpoint_at_first_step(test_client, setup_test_workflow):
    """Test rewind endpoint rejects workflows at step 0."""
    engine, persistence = await setup_test_workflow

    # Create a workflow at step 0
    workflow_id = uuid4()
    workflow_dict = {
        "id": workflow_id,
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": 0,
        "state": {"data": "test"},
        "workflow_steps": [{"name": "Step1"}],
        "step_results": {}
    }

    await persistence.save_workflow(workflow_id, workflow_dict)

    # Call rewind endpoint
    response = test_client.post(f"/api/v1/workflow/{workflow_id}/rewind")

    assert response.status_code == 400
    assert "Cannot rewind: already at first step" in response.json()["detail"]


@pytest.mark.asyncio
async def test_resume_endpoint_success(test_client, setup_test_workflow):
    """Test resume endpoint resumes paused workflow."""
    engine, persistence = await setup_test_workflow

    # Create a paused workflow
    workflow_id = uuid4()
    workflow_dict = {
        "id": workflow_id,
        "workflow_type": "TestWorkflow",
        "status": "PAUSED",
        "current_step": 1,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(workflow_id, workflow_dict)

    # Mock Celery task
    with patch('rufus.tasks.resume_from_async_task') as mock_task:
        mock_task.delay = Mock()

        # Call resume endpoint
        response = test_client.post(
            f"/api/v1/workflow/{workflow_id}/resume",
            json={"user_input": {"approved": True}}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "resume_initiated"

        # Verify Celery task was dispatched with user input
        mock_task.delay.assert_called_once_with(str(workflow_id), {"approved": True})


@pytest.mark.asyncio
async def test_resume_endpoint_not_paused(test_client, setup_test_workflow):
    """Test resume endpoint rejects non-paused workflows."""
    engine, persistence = await setup_test_workflow

    # Create an active workflow
    workflow_id = uuid4()
    workflow_dict = {
        "id": workflow_id,
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": 1,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(workflow_id, workflow_dict)

    # Call resume endpoint
    response = test_client.post(
        f"/api/v1/workflow/{workflow_id}/resume",
        json={"user_input": {}}
    )

    assert response.status_code == 400
    assert "Only paused workflows can be resumed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_websocket_subscribe():
    """Test WebSocket endpoint for real-time workflow updates."""
    # Note: Full WebSocket testing requires a running Redis instance
    # This is a basic structural test

    with TestClient(app) as client:
        workflow_id = str(uuid4())

        # Mock Redis to avoid connection errors in tests
        with patch('redis.asyncio.from_url') as mock_redis:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()

            # Setup mock
            mock_redis.return_value = mock_client
            mock_client.pubsub.return_value = mock_pubsub
            mock_pubsub.subscribe = AsyncMock()

            # Mock message stream
            async def mock_listen():
                # Simulate one message
                yield {
                    'type': 'message',
                    'data': json.dumps({
                        'event_type': 'workflow.updated',
                        'workflow_id': workflow_id,
                        'status': 'ACTIVE'
                    })
                }

            mock_pubsub.listen = mock_listen
            mock_pubsub.unsubscribe = AsyncMock()
            mock_client.close = AsyncMock()

            # Test WebSocket connection
            with client.websocket_connect(f"/api/v1/workflow/{workflow_id}/subscribe") as websocket:
                # Receive event
                data = websocket.receive_json()
                assert data['event_type'] == 'workflow.updated'
                assert data['workflow_id'] == workflow_id
                assert data['status'] == 'ACTIVE'


@pytest.mark.asyncio
async def test_invalid_workflow_id_format(test_client):
    """Test endpoints reject invalid UUID format."""
    invalid_id = "not-a-uuid"

    # Retry endpoint
    response = test_client.post(f"/api/v1/workflow/{invalid_id}/retry")
    assert response.status_code == 400
    assert "Invalid workflow ID format" in response.json()["detail"]

    # Rewind endpoint
    response = test_client.post(f"/api/v1/workflow/{invalid_id}/rewind")
    assert response.status_code == 400
    assert "Invalid workflow ID format" in response.json()["detail"]

    # Resume endpoint
    response = test_client.post(
        f"/api/v1/workflow/{invalid_id}/resume",
        json={"user_input": {}}
    )
    assert response.status_code == 400
    assert "Invalid workflow ID format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_workflow_not_found(test_client, setup_test_workflow):
    """Test endpoints handle missing workflows."""
    engine, persistence = await setup_test_workflow
    non_existent_id = uuid4()

    # Retry endpoint
    response = test_client.post(f"/api/v1/workflow/{non_existent_id}/retry")
    assert response.status_code == 404
    assert "Workflow not found" in response.json()["detail"]

    # Rewind endpoint
    response = test_client.post(f"/api/v1/workflow/{non_existent_id}/rewind")
    assert response.status_code == 404
    assert "Workflow not found" in response.json()["detail"]

    # Resume endpoint
    response = test_client.post(
        f"/api/v1/workflow/{non_existent_id}/resume",
        json={"user_input": {}}
    )
    assert response.status_code == 404
    assert "Workflow not found" in response.json()["detail"]
