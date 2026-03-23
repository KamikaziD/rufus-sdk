"""
Base compliance test class for PersistenceProvider implementations.

Any concrete implementation can inherit from this class:

    class TestSQLiteCompliance(BasePersistenceCompliance):
        @pytest.fixture
        async def provider(self, tmp_path):
            p = SQLitePersistenceProvider(db_path=str(tmp_path / "test.db"))
            await p.initialize()
            yield p
            await p.close()
"""

import pytest


class BasePersistenceCompliance:
    """
    Inherit and implement the ``provider`` fixture in subclasses.
    The fixture must yield an initialized PersistenceProvider.
    """

    # ── Workflow CRUD ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_save_and_load_workflow(self, provider):
        data = {
            "id": "wf-001",
            "workflow_type": "TestWF",
            "status": "ACTIVE",
            "current_step": 0,
            "state": {"amount": 100},
            "steps_config": [],
            "state_model_path": "tests.fixtures.test_state.TestState",
            "metadata": {},
            "completed_steps_stack": "[]",
            "priority": 5,
            "data_region": "us-east-1",
            "saga_mode": False,
        }
        await provider.save_workflow("wf-001", data)
        loaded = await provider.load_workflow("wf-001")
        assert loaded is not None
        assert loaded.id == "wf-001"
        assert loaded.workflow_type == "TestWF"

    @pytest.mark.asyncio
    async def test_load_nonexistent_workflow_returns_none(self, provider):
        result = await provider.load_workflow("does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_workflows(self, provider):
        data = {
            "id": "wf-002",
            "workflow_type": "ListTest",
            "status": "COMPLETED",
            "current_step": 1,
            "state": {},
            "steps_config": [],
            "state_model_path": "tests.fixtures.test_state.TestState",
            "metadata": {},
            "completed_steps_stack": "[]",
            "priority": 5,
            "data_region": "us-east-1",
            "saga_mode": False,
        }
        await provider.save_workflow("wf-002", data)
        results = await provider.list_workflows(status="COMPLETED")
        ids = [r.get("id") or r.get("workflow_id") for r in results]
        assert "wf-002" in ids

    # ── Task queue ───────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_create_and_get_task_record(self, provider):
        # Need a parent workflow first (FK constraint)
        wf_data = {
            "id": "wf-task",
            "workflow_type": "T",
            "status": "ACTIVE",
            "current_step": 0,
            "state": {},
            "steps_config": [],
            "state_model_path": "tests.fixtures.test_state.TestState",
            "metadata": {},
            "completed_steps_stack": "[]",
            "priority": 5,
            "data_region": "us-east-1",
            "saga_mode": False,
        }
        await provider.save_workflow("wf-task", wf_data)
        record = await provider.create_task_record(
            execution_id="wf-task",
            step_name="StepA",
            step_index=0,
            task_data={"key": "value"},
        )
        assert record is not None
        task_id = record.task_id
        assert task_id is not None

        fetched = await provider.get_task_record(task_id)
        assert fetched is not None

    @pytest.mark.asyncio
    async def test_update_task_status(self, provider):
        wf_data = {
            "id": "wf-update-task",
            "workflow_type": "T",
            "status": "ACTIVE",
            "current_step": 0,
            "state": {},
            "steps_config": [],
            "state_model_path": "tests.fixtures.test_state.TestState",
            "metadata": {},
            "completed_steps_stack": "[]",
            "priority": 5,
            "data_region": "us-east-1",
            "saga_mode": False,
        }
        await provider.save_workflow("wf-update-task", wf_data)
        record = await provider.create_task_record(
            execution_id="wf-update-task",
            step_name="StepB",
            step_index=0,
        )
        task_id = record.task_id
        await provider.update_task_status(task_id, "COMPLETED", result={"done": True})
        fetched = await provider.get_task_record(task_id)
        assert fetched.status == "COMPLETED"

    # ── Logging ──────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_log_execution_does_not_raise(self, provider):
        await provider.log_execution("wf-x", "INFO", "test message", step_name="S1")

    @pytest.mark.asyncio
    async def test_log_audit_event_does_not_raise(self, provider):
        await provider.log_audit_event(
            "wf-x", "STEP_COMPLETED", step_name="S1",
            metadata={"extra": "data"}
        )

    # ── Metrics ──────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_record_and_get_metric(self, provider):
        await provider.record_metric(
            "wf-metric", "TestWF", "step_duration_ms", 42.5, unit="ms", step_name="S1"
        )
        metrics = await provider.get_workflow_metrics("wf-metric")
        assert isinstance(metrics, list)
