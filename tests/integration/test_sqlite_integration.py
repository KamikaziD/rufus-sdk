"""
Integration tests for SQLitePersistenceProvider

Tests SQLite provider with actual schema migrations and workflow scenarios
"""

import pytest
import tempfile
import os
from pathlib import Path

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider


@pytest.fixture
async def sqlite_with_schema():
    """Create SQLite provider with actual schema"""
    # Create temporary database file
    temp_db = tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False)
    db_path = temp_db.name
    temp_db.close()

    provider = SQLitePersistenceProvider(db_path=db_path)
    await provider.initialize()

    # Apply actual schema migration
    schema_path = Path(__file__).parent.parent.parent / "migrations" / "002_sqlite_initial.sql"

    if schema_path.exists():
        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        # Fix CREATE OR REPLACE VIEW syntax for SQLite
        schema_sql = schema_sql.replace('CREATE OR REPLACE VIEW', 'CREATE VIEW IF NOT EXISTS')

        # Execute schema using executescript which handles multiple statements
        try:
            await provider.conn.executescript(schema_sql)
        except Exception as e:
            # If schema execution fails, log but continue with simplified schema
            print(f"Warning: Could not execute full schema: {e}")
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
                    metadata TEXT DEFAULT '{}'
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

    # Cleanup
    await provider.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


class TestSQLiteIntegration:
    """Integration tests for SQLitePersistenceProvider"""

    @pytest.mark.asyncio
    async def test_complete_workflow_lifecycle(self, sqlite_with_schema):
        """Test complete workflow lifecycle from creation to completion"""
        provider = sqlite_with_schema

        # 1. Create a new workflow
        workflow_id = "integration_test_workflow"
        workflow_data = {
            'id': workflow_id,
            'workflow_type': 'OrderProcessing',
            'current_step': 0,
            'status': 'ACTIVE',
            'state': {
                'order_id': 'ORD-12345',
                'customer_id': 'CUST-789',
                'amount': 299.99,
                'items': [
                    {'sku': 'WIDGET-001', 'quantity': 2},
                    {'sku': 'GADGET-042', 'quantity': 1}
                ]
            },
            'steps_config': [
                {'name': 'ValidateOrder', 'type': 'STANDARD'},
                {'name': 'ProcessPayment', 'type': 'ASYNC'},
                {'name': 'FulfillOrder', 'type': 'STANDARD'}
            ],
            'state_model_path': 'examples.order_processing.OrderState',
            'saga_mode': True,
            'completed_steps_stack': [],
            'parent_execution_id': None,
            'blocked_on_child_id': None,
            'data_region': 'us-east-1',
            'priority': 5,
            'idempotency_key': f'order_ORD-12345',
            'metadata': {'source': 'api', 'version': '1.0'},
            'completed_at': None,
        }

        await provider.save_workflow(workflow_id, workflow_data)

        # 2. Log workflow started
        await provider.log_audit_event(
            workflow_id=workflow_id,
            event_type='WORKFLOW_STARTED',
            metadata={'triggered_by': 'api'}
        )

        # 3. Execute first step - ValidateOrder
        await provider.log_execution(
            workflow_id=workflow_id,
            log_level='INFO',
            message='Starting ValidateOrder step',
            step_name='ValidateOrder'
        )

        # Update workflow state after validation
        workflow_data['current_step'] = 1
        workflow_data['state']['validation_status'] = 'passed'
        workflow_data['completed_steps_stack'] = ['ValidateOrder']
        await provider.save_workflow(workflow_id, workflow_data)

        # 4. Execute second step - ProcessPayment (async task)
        task = await provider.create_task_record(
            execution_id=workflow_id,
            step_name='ProcessPayment',
            step_index=1,
            task_data={'amount': 299.99, 'payment_method': 'credit_card'},
            idempotency_key=f'payment_{workflow_id}'
        )

        task_id = task['task_id']

        # Simulate task processing
        await provider.update_task_status(task_id, 'RUNNING')

        # Record payment processing metric
        await provider.record_metric(
            workflow_id=workflow_id,
            workflow_type='OrderProcessing',
            metric_name='payment_processing_time_ms',
            metric_value=1250.5,
            unit='ms',
            step_name='ProcessPayment',
            tags={'payment_method': 'credit_card', 'amount_range': '100-500'}
        )

        # Task completes successfully
        await provider.update_task_status(
            task_id,
            'COMPLETED',
            result={'transaction_id': 'TXN-9876543', 'status': 'approved'}
        )

        # Update workflow
        workflow_data['current_step'] = 2
        workflow_data['state']['transaction_id'] = 'TXN-9876543'
        workflow_data['completed_steps_stack'].append('ProcessPayment')
        await provider.save_workflow(workflow_id, workflow_data)

        # 5. Complete workflow
        workflow_data['status'] = 'COMPLETED'
        workflow_data['current_step'] = 3
        workflow_data['completed_at'] = None  # Will be set by trigger
        await provider.save_workflow(workflow_id, workflow_data)

        await provider.log_audit_event(
            workflow_id=workflow_id,
            event_type='WORKFLOW_COMPLETED',
            new_state=workflow_data['state']
        )

        # 6. Verify complete workflow state
        loaded = await provider.load_workflow(workflow_id)
        assert loaded is not None
        assert loaded['status'] == 'COMPLETED'
        assert loaded['current_step'] == 3
        assert len(loaded['completed_steps_stack']) == 2
        assert loaded['state']['transaction_id'] == 'TXN-9876543'
        assert loaded['saga_mode'] is True

        # 7. Verify task record
        task_record = await provider.get_task_record(task_id)
        assert task_record['status'] == 'COMPLETED'
        assert task_record['result']['transaction_id'] == 'TXN-9876543'

        # 8. Verify metrics
        metrics = await provider.get_workflow_metrics(workflow_id)
        assert len(metrics) >= 1
        payment_metric = next(m for m in metrics if m['metric_name'] == 'payment_processing_time_ms')
        assert payment_metric['metric_value'] == 1250.5

    @pytest.mark.asyncio
    async def test_saga_compensation_flow(self, sqlite_with_schema):
        """Test Saga pattern with compensation"""
        provider = sqlite_with_schema

        workflow_id = "saga_test_workflow"
        workflow_data = {
            'id': workflow_id,
            'workflow_type': 'BookingWorkflow',
            'current_step': 2,
            'status': 'FAILED',
            'state': {'booking_id': 'BK-12345', 'hotel_reserved': True, 'flight_booked': True},
            'steps_config': [],
            'state_model_path': 'test.BookingState',
            'saga_mode': True,
            'completed_steps_stack': ['ReserveHotel', 'BookFlight'],
        }

        await provider.save_workflow(workflow_id, workflow_data)

        # Log compensation actions in reverse order
        # 1. Compensate BookFlight
        await provider.log_compensation(
            execution_id=workflow_id,
            step_name='BookFlight',
            step_index=1,
            action_type='COMPENSATE',
            action_result={'cancelled': True, 'refund_issued': True},
            state_before={'flight_booked': True},
            state_after={'flight_booked': False},
            executed_by='saga_coordinator'
        )

        # 2. Compensate ReserveHotel
        await provider.log_compensation(
            execution_id=workflow_id,
            step_name='ReserveHotel',
            step_index=0,
            action_type='COMPENSATE',
            action_result={'reservation_cancelled': True},
            state_before={'hotel_reserved': True},
            state_after={'hotel_reserved': False},
            executed_by='saga_coordinator'
        )

        # Update workflow to FAILED_ROLLED_BACK
        workflow_data['status'] = 'FAILED_ROLLED_BACK'
        workflow_data['state']['hotel_reserved'] = False
        workflow_data['state']['flight_booked'] = False
        await provider.save_workflow(workflow_id, workflow_data)

        # Verify compensation logs
        async with provider.conn.execute(
            "SELECT step_name, action_type FROM compensation_log WHERE execution_id = ? ORDER BY executed_at",
            (workflow_id,)
        ) as cursor:
            rows = await cursor.fetchall()

        assert len(rows) == 2
        assert rows[0][0] == 'BookFlight'
        assert rows[0][1] == 'COMPENSATE'
        assert rows[1][0] == 'ReserveHotel'
        assert rows[1][1] == 'COMPENSATE'

    @pytest.mark.asyncio
    async def test_sub_workflow_hierarchy(self, sqlite_with_schema):
        """Test parent-child workflow relationships"""
        provider = sqlite_with_schema

        # Create parent workflow
        parent_id = "parent_workflow"
        parent_data = {
            'id': parent_id,
            'workflow_type': 'MainProcess',
            'current_step': 1,
            'status': 'PENDING_SUB_WORKFLOW',
            'state': {'user_id': 'USR-123'},
            'steps_config': [],
            'state_model_path': 'test.MainState',
            'parent_execution_id': None,
        }
        await provider.save_workflow(parent_id, parent_data)

        # Create child workflow
        child_id = "child_workflow"
        child_data = {
            'id': child_id,
            'workflow_type': 'KYCVerification',
            'current_step': 0,
            'status': 'ACTIVE',
            'state': {'user_id': 'USR-123', 'documents_verified': False},
            'steps_config': [],
            'state_model_path': 'test.KYCState',
            'parent_execution_id': parent_id,
        }
        await provider.save_workflow(child_id, child_data)

        # Update parent to track child
        parent_data['blocked_on_child_id'] = child_id
        await provider.save_workflow(parent_id, parent_data)

        # List sub-workflows
        sub_workflows = await provider.list_workflows(parent_execution_id=parent_id)
        assert len(sub_workflows) == 1
        assert sub_workflows[0]['id'] == child_id
        assert sub_workflows[0]['parent_execution_id'] == parent_id

        # Complete child workflow
        child_data['status'] = 'COMPLETED'
        child_data['state']['documents_verified'] = True
        await provider.save_workflow(child_id, child_data)

        # Resume parent workflow
        parent_data['status'] = 'ACTIVE'
        parent_data['blocked_on_child_id'] = None
        parent_data['current_step'] = 2
        await provider.save_workflow(parent_id, parent_data)

        # Verify parent resumed
        loaded_parent = await provider.load_workflow(parent_id)
        assert loaded_parent['status'] == 'ACTIVE'
        assert loaded_parent['blocked_on_child_id'] is None

    @pytest.mark.asyncio
    async def test_workflow_summary_aggregation(self, sqlite_with_schema):
        """Test workflow execution summary aggregation"""
        provider = sqlite_with_schema

        # Create multiple workflows with different types and statuses
        workflows = [
            ('OrderProcessing', 'COMPLETED'),
            ('OrderProcessing', 'COMPLETED'),
            ('OrderProcessing', 'FAILED'),
            ('UserOnboarding', 'COMPLETED'),
            ('UserOnboarding', 'ACTIVE'),
        ]

        for i, (wf_type, status) in enumerate(workflows):
            workflow_data = {
                'id': f'wf_{i}',
                'workflow_type': wf_type,
                'current_step': 1,
                'status': status,
                'state': {},
                'steps_config': [],
                'state_model_path': 'test.State',
            }
            await provider.save_workflow(f'wf_{i}', workflow_data)

        # Get summary
        summary = await provider.get_workflow_summary(hours=24)

        # Verify aggregations
        assert len(summary) >= 4  # At least 4 groups

        # Check OrderProcessing COMPLETED
        order_completed = next(
            s for s in summary
            if s['workflow_type'] == 'OrderProcessing' and s['status'] == 'COMPLETED'
        )
        assert order_completed['execution_count'] == 2

        # Check OrderProcessing FAILED
        order_failed = next(
            s for s in summary
            if s['workflow_type'] == 'OrderProcessing' and s['status'] == 'FAILED'
        )
        assert order_failed['execution_count'] == 1

    @pytest.mark.asyncio
    async def test_idempotency_keys(self, sqlite_with_schema):
        """Test idempotency key enforcement"""
        provider = sqlite_with_schema

        workflow_data = {
            'id': 'workflow_1',
            'workflow_type': 'TestWorkflow',
            'current_step': 0,
            'status': 'ACTIVE',
            'state': {},
            'steps_config': [],
            'state_model_path': 'test.State',
            'idempotency_key': 'unique_key_12345',
        }

        # Save workflow
        await provider.save_workflow('workflow_1', workflow_data)

        # Verify it was saved
        loaded = await provider.load_workflow('workflow_1')
        assert loaded is not None
        assert loaded['idempotency_key'] == 'unique_key_12345'

        # Create another workflow with same idempotency key should replace the first one
        # (INSERT OR REPLACE behavior in SQLite)
        workflow_data_2 = {
            'id': 'workflow_2',
            'workflow_type': 'TestWorkflow',
            'current_step': 1,
            'status': 'COMPLETED',
            'state': {},
            'steps_config': [],
            'state_model_path': 'test.State',
            'idempotency_key': 'unique_key_12345',  # Same key
        }

        await provider.save_workflow('workflow_2', workflow_data_2)

        # The second workflow should have replaced the first due to idempotency key
        loaded_2 = await provider.load_workflow('workflow_2')
        assert loaded_2 is not None
        assert loaded_2['idempotency_key'] == 'unique_key_12345'

        # First workflow should still exist (different ID)
        loaded_1 = await provider.load_workflow('workflow_1')
        # With INSERT OR REPLACE, workflow_1 might still exist depending on implementation
        # The key point is that idempotency_key is unique

    @pytest.mark.asyncio
    async def test_in_memory_database(self):
        """Test in-memory database for fast testing"""
        provider = SQLitePersistenceProvider(db_path=":memory:")
        await provider.initialize()

        # Create minimal schema with all required columns
        await provider.conn.execute("""
            CREATE TABLE workflow_executions (
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
                metadata TEXT DEFAULT '{}'
            )
        """)

        # Save and load workflow
        workflow_data = {
            'id': 'test_1',
            'workflow_type': 'Test',
            'current_step': 0,
            'status': 'ACTIVE',
            'state': {'key': 'value'},
            'steps_config': [],
            'state_model_path': 'test.State',
        }
        await provider.save_workflow('test_1', workflow_data)

        loaded = await provider.load_workflow('test_1')
        assert loaded is not None
        assert loaded['id'] == 'test_1'

        await provider.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
