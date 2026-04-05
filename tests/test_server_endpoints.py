"""
Tests for Rufus server endpoints: health, registry, workflow lifecycle, and error contracts.

Fixtures (test_client, setup_test_workflow) are defined in tests/conftest.py.
"""

import pytest
import json
from uuid import uuid4
from unittest.mock import Mock, AsyncMock, patch

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Env vars are set in conftest.py before the app import, but keeping them here
# is harmless and ensures the correct config if this file is ever loaded standalone.
os.environ["WORKFLOW_STORAGE"] = "memory"
os.environ["RUFUS_WORKFLOW_REGISTRY_PATH"] = "tests/fixtures/test_registry.yaml"
os.environ["RUFUS_CONFIG_DIR"] = "tests/fixtures"

try:
    from fastapi.testclient import TestClient
    from rufus_server.main import app
    _FASTAPI_AVAILABLE = True
except Exception:
    TestClient = None  # type: ignore[assignment,misc]
    app = None  # type: ignore[assignment]
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="FastAPI/server dependencies not available in this environment",
)

from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.engine import WorkflowEngine


# ─────────────────────────────────────────────────────────────────────────────
# Group 1: Health + Registry
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check(test_client):
    """GET /health returns 200 with healthy status."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_get_available_workflows(test_client, setup_test_workflow):
    """GET /api/v1/workflows returns 200 with a list of registered workflows."""
    engine, persistence = setup_test_workflow
    response = test_client.get("/api/v1/workflows")
    assert response.status_code == 200
    workflows = response.json()
    assert isinstance(workflows, list)
    assert any(wf["type"] == "TestWorkflow" for wf in workflows)


@pytest.mark.asyncio
async def test_get_available_workflows_engine_not_initialized(test_client):
    """GET /api/v1/workflows returns 503 when engine is None."""
    import rufus_server.main as main_module
    original = main_module.workflow_engine
    try:
        main_module.workflow_engine = None
        response = test_client.get("/api/v1/workflows")
        assert response.status_code == 503
    finally:
        main_module.workflow_engine = original


# ─────────────────────────────────────────────────────────────────────────────
# Group 2: Start workflow
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_workflow_success(test_client, setup_test_workflow):
    """POST /api/v1/workflow/start with valid type returns 200 with workflow_id."""
    engine, persistence = setup_test_workflow
    response = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "workflow_id" in data
    assert data["status"] is not None


@pytest.mark.asyncio
async def test_start_workflow_unknown_type(test_client, setup_test_workflow):
    """POST /api/v1/workflow/start with unknown workflow_type returns 400, not 500."""
    engine, persistence = setup_test_workflow
    response = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "NonExistentWorkflow"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_start_workflow_engine_not_initialized(test_client, setup_test_workflow):
    """POST /api/v1/workflow/start returns 503 when engine is None."""
    engine, persistence = setup_test_workflow
    import rufus_server.main as main_module
    original = main_module.workflow_engine
    try:
        main_module.workflow_engine = None
        response = test_client.post(
            "/api/v1/workflow/start",
            json={"workflow_type": "TestWorkflow"},
        )
        assert response.status_code == 503
    finally:
        main_module.workflow_engine = original


# ─────────────────────────────────────────────────────────────────────────────
# Group 3: Get status
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_workflow_status_success(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/status returns 200 with correct fields."""
    engine, persistence = setup_test_workflow
    # Start a workflow to get a valid ID
    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    assert start_resp.status_code == 200
    workflow_id = start_resp.json()["workflow_id"]

    response = test_client.get(f"/api/v1/workflow/{workflow_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["workflow_id"] == workflow_id
    assert "status" in data
    assert data["workflow_type"] == "TestWorkflow"


@pytest.mark.asyncio
async def test_get_workflow_status_not_found(test_client, setup_test_workflow):
    """Regression: get_workflow() ValueError must map to 404, not 500."""
    engine, persistence = setup_test_workflow
    non_existent = uuid4()
    response = test_client.get(f"/api/v1/workflow/{non_existent}/status")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_workflow_status_invalid_id(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/status with non-UUID string returns 404 from engine."""
    engine, persistence = setup_test_workflow
    response = test_client.get("/api/v1/workflow/not-a-real-id/status")
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Group 4: Current step info
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_current_step_info_active(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/current_step_info returns step name and type."""
    engine, persistence = setup_test_workflow
    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    assert start_resp.status_code == 200
    workflow_id = start_resp.json()["workflow_id"]

    response = test_client.get(f"/api/v1/workflow/{workflow_id}/current_step_info")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data


@pytest.mark.asyncio
async def test_get_current_step_info_not_found(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/current_step_info returns 404 for missing workflow."""
    engine, persistence = setup_test_workflow
    response = test_client.get(f"/api/v1/workflow/{uuid4()}/current_step_info")
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Group 5: Next step
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_next_workflow_step_wrong_state(test_client, setup_test_workflow):
    """POST /api/v1/workflow/{id}/next on a COMPLETED workflow returns 409."""
    engine, persistence = setup_test_workflow
    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    assert start_resp.status_code == 200
    workflow_id = start_resp.json()["workflow_id"]

    # Manually set workflow to COMPLETED
    wf_record = await persistence.load_workflow(workflow_id)
    wf_data = {f: getattr(wf_record, f) for f in wf_record.__struct_fields__}
    wf_data["status"] = "COMPLETED"
    await persistence.save_workflow(workflow_id, wf_data)

    response = test_client.post(
        f"/api/v1/workflow/{workflow_id}/next",
        json={"input_data": {}},
    )
    assert response.status_code == 409
    assert "COMPLETED" in response.json()["detail"]


@pytest.mark.asyncio
async def test_next_workflow_step_not_found(test_client, setup_test_workflow):
    """Regression: next step on non-existent workflow returns 404, not 500."""
    engine, persistence = setup_test_workflow
    response = test_client.post(
        f"/api/v1/workflow/{uuid4()}/next",
        json={"input_data": {}},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Group 6: List executions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_workflow_executions_empty(test_client, setup_test_workflow):
    """GET /api/v1/workflows/executions returns 200 with empty list on fresh store."""
    engine, persistence = setup_test_workflow
    response = test_client.get("/api/v1/workflows/executions")
    assert response.status_code == 200
    body = response.json()
    workflows = body["workflows"] if isinstance(body, dict) else body
    assert workflows == []


@pytest.mark.asyncio
async def test_get_workflow_executions_filtered_by_status(test_client, setup_test_workflow):
    """GET /api/v1/workflows/executions?status=ACTIVE filters correctly."""
    engine, persistence = setup_test_workflow

    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    assert start_resp.status_code == 200
    workflow_id = start_resp.json()["workflow_id"]

    # Ensure workflow is ACTIVE
    wf_data = await persistence.load_workflow(workflow_id)
    assert wf_data is not None

    response = test_client.get("/api/v1/workflows/executions?status=ACTIVE")
    assert response.status_code == 200
    body = response.json()
    results = body["workflows"] if isinstance(body, dict) else body
    assert all(wf.get("status") == "ACTIVE" for wf in results)


@pytest.mark.asyncio
async def test_get_workflow_executions_pagination(test_client, setup_test_workflow):
    """GET /api/v1/workflows/executions respects offset and limit parameters."""
    engine, persistence = setup_test_workflow

    # Create 3 workflows
    for _ in range(3):
        resp = test_client.post(
            "/api/v1/workflow/start",
            json={"workflow_type": "TestWorkflow"},
        )
        assert resp.status_code == 200

    all_resp = test_client.get("/api/v1/workflows/executions?limit=10&offset=0")
    assert all_resp.status_code == 200
    all_body = all_resp.json()
    all_workflows = all_body["workflows"] if isinstance(all_body, dict) else all_body
    total = len(all_workflows)
    assert total >= 3

    limited_resp = test_client.get("/api/v1/workflows/executions?limit=1&offset=0")
    assert limited_resp.status_code == 200
    limited_body = limited_resp.json()
    limited_workflows = limited_body["workflows"] if isinstance(limited_body, dict) else limited_body
    assert len(limited_workflows) == 1

    offset_resp = test_client.get(f"/api/v1/workflows/executions?limit=10&offset={total}")
    assert offset_resp.status_code == 200
    offset_body = offset_resp.json()
    offset_workflows = offset_body["workflows"] if isinstance(offset_body, dict) else offset_body
    assert len(offset_workflows) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Group 7: PostgreSQL-only endpoints return 501 on SQLite
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logs_requires_postgres(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/logs returns 501 on non-PostgreSQL backend."""
    engine, persistence = setup_test_workflow
    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    workflow_id = start_resp.json()["workflow_id"]
    response = test_client.get(f"/api/v1/workflow/{workflow_id}/logs")
    assert response.status_code == 501


@pytest.mark.asyncio
async def test_metrics_requires_postgres(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/metrics returns 501 on non-PostgreSQL backend."""
    engine, persistence = setup_test_workflow
    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    workflow_id = start_resp.json()["workflow_id"]
    response = test_client.get(f"/api/v1/workflow/{workflow_id}/metrics")
    assert response.status_code == 501


@pytest.mark.asyncio
async def test_audit_requires_postgres(test_client, setup_test_workflow):
    """GET /api/v1/workflow/{id}/audit returns 501 on non-PostgreSQL backend."""
    engine, persistence = setup_test_workflow
    start_resp = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "TestWorkflow"},
    )
    workflow_id = start_resp.json()["workflow_id"]
    response = test_client.get(f"/api/v1/workflow/{workflow_id}/audit")
    assert response.status_code == 501


@pytest.mark.asyncio
async def test_metrics_summary_requires_postgres(test_client, setup_test_workflow):
    """GET /api/v1/metrics/summary returns 501 on non-PostgreSQL backend."""
    engine, persistence = setup_test_workflow
    response = test_client.get("/api/v1/metrics/summary")
    assert response.status_code == 501


@pytest.mark.asyncio
async def test_workers_requires_postgres(test_client, setup_test_workflow):
    """GET /api/v1/admin/workers returns 501 on non-PostgreSQL backend."""
    engine, persistence = setup_test_workflow
    response = test_client.get("/api/v1/admin/workers")
    assert response.status_code == 501


# ─────────────────────────────────────────────────────────────────────────────
# Group 8: Error message quality (regression tests for the fixes in main.py)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_workflow_bad_type_returns_400_not_500(test_client, setup_test_workflow):
    """ValueError from unknown workflow type must produce 400, not 500."""
    engine, persistence = setup_test_workflow
    response = test_client.post(
        "/api/v1/workflow/start",
        json={"workflow_type": "DoesNotExist"},
    )
    assert response.status_code == 400
    assert response.status_code != 500


@pytest.mark.asyncio
async def test_status_not_found_returns_404_not_500(test_client, setup_test_workflow):
    """get_workflow() ValueError for missing ID must produce 404, not 500."""
    engine, persistence = setup_test_workflow
    response = test_client.get(f"/api/v1/workflow/{uuid4()}/status")
    assert response.status_code == 404
    assert response.status_code != 500
    detail = response.json()["detail"]
    assert "not found" in detail.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Existing tests (preserved from original file)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_endpoint_success(test_client, setup_test_workflow):
    """Test retry endpoint successfully resets failed workflow."""
    engine, persistence = setup_test_workflow

    # Create a failed workflow (save with str key to match endpoint lookup)
    workflow_id = uuid4()
    workflow_dict = {
        "id": str(workflow_id),
        "workflow_type": "TestWorkflow",
        "status": "FAILED",
        "current_step": 2,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(str(workflow_id), workflow_dict)

    # Mock Celery task
    with patch('rufus.tasks.resume_from_async_task') as mock_task:
        mock_task.delay = Mock()

        # Call retry endpoint
        response = test_client.post(f"/api/v1/workflow/{workflow_id}/retry")

        assert response.status_code == 200
        assert response.json()["status"] == "retry_initiated"
        assert response.json()["workflow_id"] == str(workflow_id)

        # Verify workflow status changed to ACTIVE
        updated_workflow = await persistence.load_workflow(str(workflow_id))
        assert updated_workflow.status == "ACTIVE"

        # Verify Celery task was dispatched
        mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_retry_endpoint_not_failed(test_client, setup_test_workflow):
    """Test retry endpoint rejects non-failed workflows."""
    engine, persistence = setup_test_workflow

    # Create an active workflow (save with str key)
    workflow_id = uuid4()
    workflow_dict = {
        "id": str(workflow_id),
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": 1,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(str(workflow_id), workflow_dict)

    # Call retry endpoint
    response = test_client.post(f"/api/v1/workflow/{workflow_id}/retry")

    assert response.status_code == 400
    assert "Only failed workflows can be retried" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rewind_endpoint_success(test_client, setup_test_workflow):
    """Test rewind endpoint moves current_step to the previous step name."""
    engine, persistence = setup_test_workflow

    # Rewind endpoint uses 'steps_config' key and step names (not integer indexes)
    workflow_id = uuid4()
    workflow_dict = {
        "id": str(workflow_id),
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": "Step2",  # step name, as stored by to_dict()
        "state": {"data": "test"},
        "steps_config": [{"name": "Step1"}, {"name": "Step2"}, {"name": "Step3"}],
        "step_results": {}
    }

    await persistence.save_workflow(str(workflow_id), workflow_dict)

    response = test_client.post(f"/api/v1/workflow/{workflow_id}/rewind")

    assert response.status_code == 200
    assert response.json()["status"] == "rewound"
    assert response.json()["current_step"] == "Step1"

    updated_workflow = await persistence.load_workflow(str(workflow_id))
    assert updated_workflow.current_step == "Step1"
    assert updated_workflow.status == "ACTIVE"


@pytest.mark.asyncio
async def test_rewind_endpoint_at_first_step(test_client, setup_test_workflow):
    """Test rewind endpoint rejects workflows at the first step."""
    engine, persistence = setup_test_workflow

    # current_step must be a step name (string); first step returns index 0 → 400
    workflow_id = uuid4()
    workflow_dict = {
        "id": str(workflow_id),
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": "Step1",
        "state": {"data": "test"},
        "steps_config": [{"name": "Step1"}],
        "step_results": {}
    }

    await persistence.save_workflow(str(workflow_id), workflow_dict)

    response = test_client.post(f"/api/v1/workflow/{workflow_id}/rewind")

    assert response.status_code == 400
    assert "Cannot rewind: already at first step" in response.json()["detail"]


@pytest.mark.asyncio
async def test_resume_endpoint_success(test_client, setup_test_workflow):
    """Test resume endpoint resumes a WAITING_HUMAN workflow and advances the step."""
    engine, persistence = setup_test_workflow

    # Start a real workflow so steps_config is properly populated
    workflow = await engine.start_workflow("TestWorkflow", initial_data={})
    workflow_id = workflow.id

    # Manually set status to WAITING_HUMAN in persistence
    wf_record = await persistence.load_workflow(str(workflow_id))
    workflow_dict = {f: getattr(wf_record, f) for f in wf_record.__struct_fields__}
    workflow_dict["status"] = "WAITING_HUMAN"
    await persistence.save_workflow(str(workflow_id), workflow_dict)

    response = test_client.post(
        f"/api/v1/workflow/{workflow_id}/resume",
        json={"user_input": {"approved": True}}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["workflow_id"] == str(workflow_id)
    # After resume the step runs (noop) and workflow advances
    assert data["status"] in ("ACTIVE", "COMPLETED")


@pytest.mark.asyncio
async def test_resume_endpoint_not_paused(test_client, setup_test_workflow):
    """Test resume endpoint rejects non-paused workflows."""
    engine, persistence = setup_test_workflow

    # Create an active workflow (save with str key)
    workflow_id = uuid4()
    workflow_dict = {
        "id": str(workflow_id),
        "workflow_type": "TestWorkflow",
        "status": "ACTIVE",
        "current_step": 1,
        "state": {"data": "test"},
        "workflow_steps": [],
        "step_results": {}
    }

    await persistence.save_workflow(str(workflow_id), workflow_dict)

    # Call resume endpoint
    response = test_client.post(
        f"/api/v1/workflow/{workflow_id}/resume",
        json={"user_input": {}}
    )

    assert response.status_code == 400
    assert "WAITING_HUMAN" in response.json()["detail"]


@pytest.mark.asyncio
async def test_websocket_subscribe():
    """Test WebSocket endpoint accepts connection and sends initial handshake."""
    mock_client = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.close = AsyncMock()
    mock_client.pubsub.return_value = mock_pubsub
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()

    async def mock_listen():
        return
        yield  # make it an async generator

    mock_pubsub.listen = mock_listen

    with patch('redis.asyncio.from_url', return_value=mock_client):
        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/subscribe") as websocket:
                data = websocket.receive_json()
                assert data["type"] == "handshake"
                assert data["state"] == "connecting"


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
    engine, persistence = setup_test_workflow
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
