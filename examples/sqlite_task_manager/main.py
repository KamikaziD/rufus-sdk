"""
SQLite Task Manager Example

Demonstrates using Rufus SDK with SQLite persistence for a task approval workflow.

Usage:
    python examples/sqlite_task_manager/main.py
    python examples/sqlite_task_manager/main.py --in-memory
"""

import asyncio
import argparse
from pathlib import Path

from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine


async def initialize_database(db_path: str):
    """Initialize SQLite database with schema"""
    persistence = SQLitePersistenceProvider(db_path=db_path)
    await persistence.initialize()

    # Create schema
    await persistence.conn.executescript("""
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
            step_name TEXT,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS workflow_audit_log (
            audit_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            step_name TEXT,
            user_id TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            old_state TEXT,
            new_state TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS workflow_metrics (
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            workflow_type TEXT,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            unit TEXT,
            step_name TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            tags TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions(status);
        CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions(workflow_type);
    """)

    return persistence


async def main():
    parser = argparse.ArgumentParser(description='SQLite Task Manager Example')
    parser.add_argument(
        '--in-memory',
        action='store_true',
        help='Use in-memory database instead of file'
    )
    parser.add_argument(
        '--db-path',
        default='tasks.db',
        help='Path to SQLite database file (default: tasks.db)'
    )

    args = parser.parse_args()

    # Determine database path
    db_path = ":memory:" if args.in_memory else args.db_path

    print("="*70)
    print("  RUFUS SDK - SQLITE TASK MANAGER EXAMPLE")
    print("="*70)
    print(f"\n🗄️  Database: {db_path}")
    print(f"   Mode: {'In-Memory' if args.in_memory else 'File-Based'}\n")

    # Initialize persistence
    print("Initializing SQLite persistence...")
    persistence = await initialize_database(db_path)
    print("✓ SQLite database initialized\n")

    # Initialize providers
    executor = SyncExecutor()
    observer = LoggingObserver()

    # Create workflow builder
    print("Creating workflow builder...")
    builder = WorkflowBuilder(
        registry_path=None,  # We'll load workflow directly
        persistence_provider=persistence,
        execution_provider=executor,
        observer=observer,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # Load workflow definition
    workflow_path = Path(__file__).parent / "workflow.yaml"
    builder.load_workflow_config("TaskApprovalWorkflow", str(workflow_path))
    print("✓ Workflow configuration loaded\n")

    # Create a new task workflow
    print("="*70)
    print("  CREATING NEW TASK WORKFLOW")
    print("="*70 + "\n")

    initial_data = {
        "task_id": "TASK-001",
        "title": "Implement SQLite persistence layer",
        "description": "Add SQLite support to Rufus SDK for development and testing",
        "priority": "high",
        "category": "development",
        "requires_approval": True,
    }

    workflow = builder.create_workflow(
        "TaskApprovalWorkflow",
        initial_data=initial_data
    )

    print(f"✓ Workflow created: {workflow.id}\n")

    # Execute automated steps (Create -> Assign -> Request Approval)
    print("="*70)
    print("  EXECUTING AUTOMATED STEPS")
    print("="*70)

    step_count = 0
    while workflow.status == "ACTIVE" and step_count < 10:
        result = await workflow.next_step()
        step_count += 1

        if workflow.status == "PAUSED":
            print("\n⏸️  Workflow paused for approval")
            break

    # Simulate approval process
    print("\n" + "="*70)
    print("  SIMULATING APPROVAL PROCESS")
    print("="*70 + "\n")

    print("Manager reviewing task...")
    print("✓ Task approved!\n")

    # Resume workflow with approval
    approval_input = {
        "approved_by": "alice_manager",
        "approval_notes": "Looks good, proceed with implementation"
    }

    print("="*70)
    print("  RESUMING WORKFLOW AFTER APPROVAL")
    print("="*70)

    while workflow.status in ("ACTIVE", "PAUSED"):
        result = await workflow.next_step(user_input=approval_input)

        if workflow.status == "COMPLETED":
            break

    # Show final status
    print("\n" + "="*70)
    print("  WORKFLOW COMPLETED")
    print("="*70 + "\n")

    print(f"Workflow ID: {workflow.id}")
    print(f"Status: {workflow.status}")
    print(f"Steps Completed: {len(workflow.completed_steps_stack)}")
    print(f"\nFinal State:")
    print(f"  Task ID: {workflow.state.task_id}")
    print(f"  Title: {workflow.state.title}")
    print(f"  Assigned To: {workflow.state.assigned_to}")
    print(f"  Approved By: {workflow.state.approved_by}")
    print(f"  Status: {workflow.state.workflow_status}")
    print(f"  Notification Sent: {workflow.state.notification_sent}")

    # Show database statistics
    print("\n" + "="*70)
    print("  DATABASE STATISTICS")
    print("="*70 + "\n")

    # Count workflows
    async with persistence.conn.execute("SELECT COUNT(*) FROM workflow_executions") as cursor:
        count = (await cursor.fetchone())[0]
    print(f"Total Workflows: {count}")

    # Count logs
    async with persistence.conn.execute("SELECT COUNT(*) FROM workflow_execution_logs") as cursor:
        log_count = (await cursor.fetchone())[0]
    print(f"Execution Logs: {log_count}")

    if not args.in_memory:
        import os
        db_size = os.path.getsize(args.db_path)
        print(f"Database Size: {db_size:,} bytes ({db_size/1024:.2f} KB)")

    # Cleanup
    await persistence.close()

    print("\n" + "="*70)
    print("  EXAMPLE COMPLETED SUCCESSFULLY")
    print("="*70 + "\n")

    if not args.in_memory:
        print(f"💾 Database saved to: {args.db_path}")
        print("   You can inspect it with: sqlite3 tasks.db")


if __name__ == '__main__':
    asyncio.run(main())
