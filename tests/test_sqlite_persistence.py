"""
Unit tests for SQLitePersistenceProvider

Tests all persistence operations with in-memory SQLite database
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# Enable pytest-asyncio
pytest_plugins = ('pytest_asyncio',)


@pytest.fixture(scope="function")
async def sqlite_provider():
    """Create in-memory SQLite provider for testing"""
    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()

    # Create schema (simplified for testing)
    await provider.conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_type TEXT NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT '{}',
            steps_config TEXT NOT NULL DEFAULT '[]',
            state_model_path TEXT NOT NULL,
            saga_mode INTEGER DEFAULT 0,
            completed_steps_stack TEXT DEFAULT '[]',
            parent_execution_id TEXT,
            blocked_on_child_id TEXT,
            data_region TEXT DEFAULT 'us-east-1',
            priority INTEGER DEFAULT 5,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            idempotency_key TEXT UNIQUE,
            metadata TEXT DEFAULT '{}',
            workflow_version TEXT,
            definition_snapshot TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            worker_id TEXT,
            claimed_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            last_error TEXT,
            task_data TEXT,
            result TEXT,
            idempotency_key TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS workflow_execution_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            execution_id TEXT,
            step_name TEXT,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
            worker_id TEXT,
            metadata TEXT DEFAULT '{}',
            trace_id TEXT,
            span_id TEXT
        );

        CREATE TABLE IF NOT EXISTS workflow_audit_log (
            audit_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            execution_id TEXT,
            event_type TEXT NOT NULL,
            step_name TEXT,
            user_id TEXT,
            worker_id TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            old_state TEXT,
            new_state TEXT,
            state_diff TEXT,
            decision_rationale TEXT,
            metadata TEXT DEFAULT '{}',
            ip_address TEXT,
            user_agent TEXT
        );

        CREATE TABLE IF NOT EXISTS compensation_log (
            log_id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            action_result TEXT,
            error_message TEXT,
            executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            executed_by TEXT,
            state_before TEXT,
            state_after TEXT
        );

        CREATE TABLE IF NOT EXISTS workflow_metrics (
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            workflow_type TEXT,
            execution_id TEXT,
            step_name TEXT,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            unit TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            tags TEXT DEFAULT '{}'
        );
    """)

    yield provider

    await provider.close()


class TestSQLitePersistence:
    """Test suite for SQLitePersistenceProvider"""

    @pytest.mark.asyncio
    async def test_save_and_load_workflow(self, sqlite_provider):
        """Test saving and loading workflow state"""
        workflow_id = "test_workflow_123"
        workflow_data = {
            'id': workflow_id,
            'workflow_type': 'TestWorkflow',
            'current_step': 1,
            'status': 'ACTIVE',
            'state': {'user_id': '456', 'amount': 100},
            'steps_config': [{'name': 'step1', 'type': 'STANDARD'}],
            'state_model_path': 'test.models.TestState',
            'saga_mode': False,
            'completed_steps_stack': [],
            'parent_execution_id': None,
            'blocked_on_child_id': None,
            'data_region': 'us-east-1',
            'priority': 5,
            'idempotency_key': 'test_key_123',
            'metadata': {'source': 'test'},
            'completed_at': None,
        }

        # Save workflow
        await sqlite_provider.save_workflow(workflow_id, workflow_data)

        # Load workflow
        loaded = await sqlite_provider.load_workflow(workflow_id)

        # Verify
        assert loaded is not None
        assert loaded['id'] == workflow_id
        assert loaded['workflow_type'] == 'TestWorkflow'
        assert loaded['current_step'] == 1
        assert loaded['status'] == 'ACTIVE'
        assert loaded['state']['user_id'] == '456'
        assert loaded['state']['amount'] == 100
        assert len(loaded['steps_config']) == 1
        assert loaded['saga_mode'] is False
        assert loaded['idempotency_key'] == 'test_key_123'
        assert loaded['metadata']['source'] == 'test'

    @pytest.mark.asyncio
    async def test_load_nonexistent_workflow(self, sqlite_provider):
        """Test loading workflow that doesn't exist"""
        result = await sqlite_provider.load_workflow("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_workflows(self, sqlite_provider):
        """Test listing workflows with filters"""
        # Create multiple workflows
        for i in range(5):
            workflow_data = {
                'id': f'workflow_{i}',
                'workflow_type': 'TestWorkflow' if i < 3 else 'OtherWorkflow',
                'current_step': i,
                'status': 'ACTIVE' if i % 2 == 0 else 'COMPLETED',
                'state': {'index': i},
                'steps_config': [],
                'state_model_path': 'test.models.TestState',
            }
            await sqlite_provider.save_workflow(f'workflow_{i}', workflow_data)

        # List all workflows
        all_workflows = await sqlite_provider.list_workflows()
        assert len(all_workflows) == 5

        # Filter by workflow_type
        test_workflows = await sqlite_provider.list_workflows(workflow_type='TestWorkflow')
        assert len(test_workflows) == 3

        # Filter by status
        active_workflows = await sqlite_provider.list_workflows(status='ACTIVE')
        assert len(active_workflows) == 3

        # Test limit and offset
        limited = await sqlite_provider.list_workflows(limit=2)
        assert len(limited) == 2

        offset_results = await sqlite_provider.list_workflows(limit=2, offset=2)
        assert len(offset_results) == 2

    @pytest.mark.asyncio
    async def test_get_active_workflows(self, sqlite_provider):
        """Test getting active workflows"""
        # Create workflows with different statuses
        statuses = ['ACTIVE', 'ACTIVE', 'COMPLETED', 'FAILED', 'ACTIVE']
        for i, status in enumerate(statuses):
            workflow_data = {
                'id': f'workflow_{i}',
                'workflow_type': 'TestWorkflow',
                'current_step': i,
                'status': status,
                'state': {},
                'steps_config': [],
                'state_model_path': 'test.models.TestState',
            }
            await sqlite_provider.save_workflow(f'workflow_{i}', workflow_data)

        # Get active workflows
        active = await sqlite_provider.get_active_workflows()
        assert len(active) == 3  # Only ACTIVE status

        # Verify structure
        assert all('id' in w for w in active)
        assert all('workflow_type' in w for w in active)
        assert all('status' in w for w in active)
        assert all(w['status'] == 'ACTIVE' for w in active)

    @pytest.mark.asyncio
    async def test_create_and_get_task(self, sqlite_provider):
        """Test creating and retrieving task records"""
        execution_id = "exec_123"
        task_data = {'input': 'test_data'}

        # Insert parent workflow_execution to satisfy FK constraint
        await sqlite_provider.save_workflow(execution_id, {
            'id': execution_id, 'workflow_type': 'Test', 'current_step': 0,
            'status': 'ACTIVE', 'state': {}, 'steps_config': [],
            'state_model_path': 'test.State',
        })

        # Create task
        task_record = await sqlite_provider.create_task_record(
            execution_id=execution_id,
            step_name="ProcessData",
            step_index=0,
            task_data=task_data,
            idempotency_key="task_key_123",
            max_retries=5
        )

        assert 'task_id' in task_record
        assert task_record['execution_id'] == execution_id
        assert task_record['step_name'] == "ProcessData"
        assert task_record['status'] == 'PENDING'

        # Get task
        task_id = task_record['task_id']
        retrieved = await sqlite_provider.get_task_record(task_id)

        assert retrieved is not None
        assert retrieved['task_id'] == task_id
        assert retrieved['execution_id'] == execution_id
        assert retrieved['step_name'] == "ProcessData"
        assert retrieved['step_index'] == 0
        assert retrieved['status'] == 'PENDING'
        assert retrieved['task_data']['input'] == 'test_data'
        assert retrieved['max_retries'] == 5
        assert retrieved['idempotency_key'] == 'task_key_123'

    @pytest.mark.asyncio
    async def test_update_task_status(self, sqlite_provider):
        """Test updating task status"""
        # Insert parent workflow_execution to satisfy FK constraint
        await sqlite_provider.save_workflow("exec_123", {
            'id': 'exec_123', 'workflow_type': 'Test', 'current_step': 0,
            'status': 'ACTIVE', 'state': {}, 'steps_config': [],
            'state_model_path': 'test.State',
        })
        # Create task
        task_record = await sqlite_provider.create_task_record(
            execution_id="exec_123",
            step_name="ProcessData",
            step_index=0
        )
        task_id = task_record['task_id']

        # Update to RUNNING
        await sqlite_provider.update_task_status(task_id, 'RUNNING')
        task = await sqlite_provider.get_task_record(task_id)
        assert task['status'] == 'RUNNING'
        assert task['started_at'] is not None

        # Update to COMPLETED with result
        result_data = {'output': 'success'}
        await sqlite_provider.update_task_status(task_id, 'COMPLETED', result=result_data)
        task = await sqlite_provider.get_task_record(task_id)
        assert task['status'] == 'COMPLETED'
        assert task['result']['output'] == 'success'
        assert task['completed_at'] is not None

    @pytest.mark.asyncio
    async def test_log_execution(self, sqlite_provider):
        """Test logging execution events"""
        workflow_id = "workflow_123"
        metadata = {'trace_id': 'abc123'}

        await sqlite_provider.log_execution(
            workflow_id=workflow_id,
            log_level='INFO',
            message='Test log message',
            step_name='ProcessData',
            metadata=metadata
        )

        # Verify log was created (query directly)
        async with sqlite_provider.conn.execute(
            "SELECT message, log_level, step_name FROM workflow_execution_logs WHERE workflow_id = ?",
            (workflow_id,)
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == 'Test log message'
        assert row[1] == 'INFO'
        assert row[2] == 'ProcessData'

    @pytest.mark.asyncio
    async def test_log_audit_event(self, sqlite_provider):
        """Test logging audit events"""
        workflow_id = "workflow_123"
        old_state = {'status': 'pending'}
        new_state = {'status': 'approved'}

        await sqlite_provider.log_audit_event(
            workflow_id=workflow_id,
            event_type='STEP_COMPLETED',
            step_name='Approval',
            user_id='user_456',
            old_state=old_state,
            new_state=new_state,
            decision_rationale='Meets criteria'
        )

        # Verify audit log
        async with sqlite_provider.conn.execute(
            "SELECT event_type, step_name, user_id FROM workflow_audit_log WHERE workflow_id = ?",
            (workflow_id,)
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == 'STEP_COMPLETED'
        assert row[1] == 'Approval'
        assert row[2] == 'user_456'

    @pytest.mark.asyncio
    async def test_log_compensation(self, sqlite_provider):
        """Test logging compensation actions"""
        execution_id = "exec_123"
        action_result = {'refunded': True, 'amount': 100}
        state_before = {'balance': 1000}
        state_after = {'balance': 1100}

        # Insert parent workflow_execution to satisfy FK constraint
        await sqlite_provider.save_workflow(execution_id, {
            'id': execution_id, 'workflow_type': 'Test', 'current_step': 0,
            'status': 'ACTIVE', 'state': {}, 'steps_config': [],
            'state_model_path': 'test.State',
        })

        await sqlite_provider.log_compensation(
            execution_id=execution_id,
            step_name='RefundPayment',
            step_index=2,
            action_type='COMPENSATE',
            action_result=action_result,
            state_before=state_before,
            state_after=state_after
        )

        # Verify compensation log
        async with sqlite_provider.conn.execute(
            "SELECT step_name, action_type FROM compensation_log WHERE execution_id = ?",
            (execution_id,)
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == 'RefundPayment'
        assert row[1] == 'COMPENSATE'

    @pytest.mark.asyncio
    async def test_record_and_get_metrics(self, sqlite_provider):
        """Test recording and retrieving metrics"""
        workflow_id = "workflow_123"
        tags = {'environment': 'test', 'region': 'us-east-1'}

        # Record multiple metrics
        await sqlite_provider.record_metric(
            workflow_id=workflow_id,
            workflow_type='TestWorkflow',
            metric_name='step_duration_ms',
            metric_value=250.5,
            unit='ms',
            step_name='ProcessData',
            tags=tags
        )

        await sqlite_provider.record_metric(
            workflow_id=workflow_id,
            workflow_type='TestWorkflow',
            metric_name='retry_count',
            metric_value=2,
            unit='count'
        )

        # Get metrics
        metrics = await sqlite_provider.get_workflow_metrics(workflow_id)

        assert len(metrics) == 2
        assert metrics[0]['metric_name'] in ['step_duration_ms', 'retry_count']
        assert all('metric_value' in m for m in metrics)
        assert all('recorded_at' in m for m in metrics)

        # Verify first metric details
        duration_metric = next(m for m in metrics if m['metric_name'] == 'step_duration_ms')
        assert duration_metric['metric_value'] == 250.5
        assert duration_metric['unit'] == 'ms'
        assert duration_metric['step_name'] == 'ProcessData'
        assert duration_metric['tags']['environment'] == 'test'

    @pytest.mark.asyncio
    async def test_get_workflow_summary(self, sqlite_provider):
        """Test getting workflow execution summary"""
        # Create workflows with different types and statuses
        workflows = [
            ('TestWorkflow', 'COMPLETED'),
            ('TestWorkflow', 'COMPLETED'),
            ('TestWorkflow', 'FAILED'),
            ('OtherWorkflow', 'COMPLETED'),
        ]

        for i, (wf_type, status) in enumerate(workflows):
            workflow_data = {
                'id': f'workflow_{i}',
                'workflow_type': wf_type,
                'current_step': 1,
                'status': status,
                'state': {},
                'steps_config': [],
                'state_model_path': 'test.models.TestState',
            }
            await sqlite_provider.save_workflow(f'workflow_{i}', workflow_data)

        # Get summary
        summary = await sqlite_provider.get_workflow_summary(hours=24)

        assert len(summary) >= 3  # At least 3 groups

        # Verify summary structure
        assert all('workflow_type' in s for s in summary)
        assert all('status' in s for s in summary)
        assert all('execution_count' in s for s in summary)

        # Find TestWorkflow COMPLETED group
        test_completed = next(
            s for s in summary
            if s['workflow_type'] == 'TestWorkflow' and s['status'] == 'COMPLETED'
        )
        assert test_completed['execution_count'] == 2

    @pytest.mark.asyncio
    async def test_helper_methods(self, sqlite_provider):
        """Test helper methods for type conversion"""
        # Test UUID generation
        uuid1 = sqlite_provider._generate_uuid()
        uuid2 = sqlite_provider._generate_uuid()
        assert len(uuid1) == 32  # Hex format without dashes
        assert uuid1 != uuid2

        # Test JSON serialization
        data = {'key': 'value', 'nested': {'count': 123}}
        json_str = sqlite_provider._serialize_json(data)
        assert isinstance(json_str, str)

        deserialized = sqlite_provider._deserialize_json(json_str)
        assert deserialized == data

        # Test None handling
        assert sqlite_provider._serialize_json(None) is None
        assert sqlite_provider._deserialize_json(None) is None
        assert sqlite_provider._deserialize_json("") is None

        # Test boolean conversion
        assert sqlite_provider._bool_to_int(True) == 1
        assert sqlite_provider._bool_to_int(False) == 0
        assert sqlite_provider._bool_to_int(None) is None

        assert sqlite_provider._int_to_bool(1) is True
        assert sqlite_provider._int_to_bool(0) is False
        assert sqlite_provider._int_to_bool(None) is None

        # Test datetime conversion
        dt = datetime(2024, 1, 15, 12, 30, 45)
        iso_str = sqlite_provider._to_iso8601(dt)
        assert isinstance(iso_str, str)

        dt_back = sqlite_provider._from_iso8601(iso_str)
        assert dt_back.year == 2024
        assert dt_back.month == 1
        assert dt_back.day == 15

    @pytest.mark.asyncio
    async def test_workflow_update(self, sqlite_provider):
        """Test updating existing workflow"""
        workflow_id = "workflow_123"

        # Create initial workflow
        initial_data = {
            'id': workflow_id,
            'workflow_type': 'TestWorkflow',
            'current_step': 0,
            'status': 'ACTIVE',
            'state': {'count': 1},
            'steps_config': [],
            'state_model_path': 'test.models.TestState',
        }
        await sqlite_provider.save_workflow(workflow_id, initial_data)

        # Update workflow
        updated_data = {
            'id': workflow_id,
            'workflow_type': 'TestWorkflow',
            'current_step': 1,
            'status': 'ACTIVE',
            'state': {'count': 2},
            'steps_config': [],
            'state_model_path': 'test.models.TestState',
        }
        await sqlite_provider.save_workflow(workflow_id, updated_data)

        # Verify update
        loaded = await sqlite_provider.load_workflow(workflow_id)
        assert loaded['current_step'] == 1
        assert loaded['state']['count'] == 2

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, sqlite_provider):
        """Test concurrent workflow operations"""
        # Create multiple workflows concurrently
        async def create_workflow(i):
            workflow_data = {
                'id': f'workflow_{i}',
                'workflow_type': 'TestWorkflow',
                'current_step': 0,
                'status': 'ACTIVE',
                'state': {'index': i},
                'steps_config': [],
                'state_model_path': 'test.models.TestState',
            }
            await sqlite_provider.save_workflow(f'workflow_{i}', workflow_data)

        # Run 10 concurrent creates
        await asyncio.gather(*[create_workflow(i) for i in range(10)])

        # Verify all were created
        workflows = await sqlite_provider.list_workflows(limit=20)
        assert len(workflows) == 10


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
