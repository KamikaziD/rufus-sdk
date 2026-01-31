"""
Simple SQLite Demo - No dependencies on workflow builder

Demonstrates SQLite persistence with a straightforward example.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider


async def main():
    print("="*70)
    print("  RUFUS SDK - SQLITE SIMPLE DEMO")
    print("="*70)
    print("\n🗄️  Using in-memory SQLite database\n")

    # Initialize SQLite persistence
    print("1. Initializing SQLite persistence...")
    persistence = SQLitePersistenceProvider(db_path=":memory:")
    await persistence.initialize()
    print("   ✓ SQLite provider initialized\n")

    # Apply demo schema
    print("2. Applying database schema...")
    schema_path = Path(__file__).parent / "demo_schema.sql"

    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    await persistence.conn.executescript(schema_sql)
    print("   ✓ Schema applied\n")

    # Create a workflow
    print("3. Creating a sample workflow...")
    workflow_id = "demo_workflow_001"
    workflow_data = {
        'id': workflow_id,
        'workflow_type': 'DemoWorkflow',
        'workflow_version': '1.0.0',
        'current_step': 0,
        'status': 'ACTIVE',
        'state': {
            'task_name': 'Process Customer Order',
            'customer_id': 'CUST-12345',
            'order_total': 299.99,
            'items': [
                {'sku': 'WIDGET-001', 'quantity': 2, 'price': 99.99},
                {'sku': 'GADGET-042', 'quantity': 1, 'price': 100.01}
            ]
        },
        'steps_config': [
            {'name': 'Validate_Order', 'type': 'STANDARD'},
            {'name': 'Process_Payment', 'type': 'ASYNC'},
            {'name': 'Ship_Order', 'type': 'STANDARD'}
        ],
        'state_model_path': 'demo.OrderState',
        'priority': 5,
    }

    await persistence.save_workflow(workflow_id, workflow_data)
    print(f"   ✓ Workflow created: {workflow_id}\n")

    # Log some execution events
    print("4. Logging execution events...")
    await persistence.log_execution(
        workflow_id=workflow_id,
        log_level='INFO',
        message='Workflow started',
        step_name='Validate_Order'
    )
    await persistence.log_execution(
        workflow_id=workflow_id,
        log_level='INFO',
        message='Order validation successful',
        step_name='Validate_Order'
    )
    await persistence.log_execution(
        workflow_id=workflow_id,
        log_level='INFO',
        message='Processing payment',
        step_name='Process_Payment'
    )
    print("   ✓ 3 log entries created\n")

    # Record some metrics
    print("5. Recording performance metrics...")
    await persistence.record_metric(
        workflow_id=workflow_id,
        workflow_type='DemoWorkflow',
        metric_name='validation_time_ms',
        metric_value=45.3,
        unit='ms',
        step_name='Validate_Order'
    )
    await persistence.record_metric(
        workflow_id=workflow_id,
        workflow_type='DemoWorkflow',
        metric_name='payment_processing_time_ms',
        metric_value=1250.7,
        unit='ms',
        step_name='Process_Payment'
    )
    print("   ✓ 2 metrics recorded\n")

    # Update workflow status
    print("6. Updating workflow status...")
    workflow_data['current_step'] = 2
    workflow_data['status'] = 'COMPLETED'
    workflow_data['state']['payment_status'] = 'approved'
    workflow_data['state']['shipping_tracking'] = 'SHIP-9876543210'
    await persistence.save_workflow(workflow_id, workflow_data)
    print("   ✓ Workflow updated to COMPLETED\n")

    # Load workflow back
    print("7. Loading workflow from database...")
    loaded = await persistence.load_workflow(workflow_id)
    print(f"   ✓ Loaded workflow: {loaded['id']}")
    print(f"     Status: {loaded['status']}")
    print(f"     Current Step: {loaded['current_step']}")
    print(f"     Order Total: ${loaded['state']['order_total']}")
    print(f"     Payment Status: {loaded['state']['payment_status']}")
    print(f"     Tracking: {loaded['state']['shipping_tracking']}\n")

    # Query database statistics
    print("="*70)
    print("  DATABASE STATISTICS")
    print("="*70 + "\n")

    async with persistence.conn.execute("SELECT COUNT(*) FROM workflow_executions") as cursor:
        wf_count = (await cursor.fetchone())[0]
    print(f"Workflows: {wf_count}")

    async with persistence.conn.execute("SELECT COUNT(*) FROM workflow_execution_logs") as cursor:
        log_count = (await cursor.fetchone())[0]
    print(f"Logs: {log_count}")

    async with persistence.conn.execute("SELECT COUNT(*) FROM workflow_metrics") as cursor:
        metric_count = (await cursor.fetchone())[0]
    print(f"Metrics: {metric_count}")

    # Show all logs
    print("\nExecution Logs:")
    async with persistence.conn.execute(
        "SELECT log_level, step_name, message FROM workflow_execution_logs ORDER BY logged_at"
    ) as cursor:
        rows = await cursor.fetchall()
        for level, step, message in rows:
            print(f"  [{level}] {step}: {message}")

    # Show metrics
    print("\nPerformance Metrics:")
    async with persistence.conn.execute(
        "SELECT step_name, metric_value, unit FROM workflow_metrics ORDER BY recorded_at"
    ) as cursor:
        rows = await cursor.fetchall()
        for step, value, unit in rows:
            print(f"  {step}: {value}{unit}")

    # Cleanup
    await persistence.close()

    print("\n" + "="*70)
    print("  DEMO COMPLETED SUCCESSFULLY")
    print("="*70)
    print("\n✅ SQLite persistence is working perfectly!")
    print("   No PostgreSQL required - just pure embedded SQLite.\n")


if __name__ == '__main__':
    asyncio.run(main())
