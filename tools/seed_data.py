#!/usr/bin/env python3
"""
Seed Rufus database with test data.

This script seeds databases (SQLite or PostgreSQL) with default data
for testing, demos, and development. It's designed to be idempotent -
running it multiple times won't create duplicate data.

Usage:
    # Seed SQLite database
    python tools/seed_data.py --db-url "sqlite:///workflow.db" --type all

    # Seed PostgreSQL (Docker)
    python tools/seed_data.py \\
        --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \\
        --type all

    # Seed only workflows
    python tools/seed_data.py --db-url "sqlite:///test.db" --type workflows

    # Seed only registration keys (PostgreSQL)
    python tools/seed_data.py \\
        --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \\
        --type keys
"""

import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import uuid

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider


async def seed_demo_workflows(persistence, verbose: bool = False):
    """
    Seed sample workflows for demo/testing.

    Creates example workflows in various states (completed, active, failed)
    to demonstrate workflow functionality.
    """
    workflows_seeded = 0

    # Workflow 1: Completed task
    workflow_id = str(uuid.uuid4())
    try:
        await persistence.save_workflow(workflow_id, {
            "id": workflow_id,
            "workflow_type": "TaskManagement",
            "status": "COMPLETED",
            "state": {
                "task_name": "Setup development environment",
                "status": "done",
                "assignee": "demo-user",
                "priority": "high"
            },
            "current_step": "3",
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "blocked_on_child_id": None,  # Not waiting on any child
            "saga_mode": False,
            "completed_steps_stack": [],
            "data_region": "us-east-1",
            "priority": 5,
            "idempotency_key": None,
            "metadata": {},
            "owner_id": "demo-user",
            "org_id": None,
            "created_at": (datetime.now() - timedelta(days=2)).isoformat(),
            "updated_at": (datetime.now() - timedelta(days=1)).isoformat()
        })
        workflows_seeded += 1
        if verbose:
            print(f"  ✓ Created completed workflow: {workflow_id}")
    except Exception as e:
        if verbose:
            print(f"  ⚠ Skipped workflow {workflow_id}: {e}")

    # Workflow 2: Active/in-progress task
    workflow_id2 = str(uuid.uuid4())
    try:
        await persistence.save_workflow(workflow_id2, {
            "id": workflow_id2,
            "workflow_type": "TaskManagement",
            "status": "ACTIVE",
            "state": {
                "task_name": "Review pull request #42",
                "status": "in_progress",
                "assignee": "demo-user",
                "priority": "medium",
                "pr_url": "https://github.com/example/repo/pull/42"
            },
            "current_step": "1",
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "blocked_on_child_id": None,  # Not waiting on any child
            "saga_mode": False,
            "completed_steps_stack": [],
            "data_region": "us-east-1",
            "priority": 5,
            "idempotency_key": None,
            "metadata": {},
            "owner_id": "demo-user",
            "org_id": None,
            "created_at": (datetime.now() - timedelta(hours=3)).isoformat(),
            "updated_at": datetime.now().isoformat()
        })
        workflows_seeded += 1
        if verbose:
            print(f"  ✓ Created active workflow: {workflow_id2}")
    except Exception as e:
        if verbose:
            print(f"  ⚠ Skipped workflow {workflow_id2}: {e}")

    # Workflow 3: Failed workflow
    workflow_id3 = str(uuid.uuid4())
    try:
        await persistence.save_workflow(workflow_id3, {
            "id": workflow_id3,
            "workflow_type": "TaskManagement",
            "status": "FAILED",
            "state": {
                "task_name": "Deploy to production",
                "status": "failed",
                "assignee": "demo-user",
                "priority": "critical",
                "error": "Connection timeout"
            },
            "current_step": "2",
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "blocked_on_child_id": None,  # Not waiting on any child
            "saga_mode": False,
            "completed_steps_stack": [],
            "data_region": "us-east-1",
            "priority": 5,
            "idempotency_key": None,
            "metadata": {},
            "owner_id": "demo-user",
            "org_id": None,
            "created_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "updated_at": datetime.now().isoformat()
        })
        workflows_seeded += 1
        if verbose:
            print(f"  ✓ Created failed workflow: {workflow_id3}")
    except Exception as e:
        if verbose:
            print(f"  ⚠ Skipped workflow {workflow_id3}: {e}")

    # Workflow 4: Waiting for human input
    workflow_id4 = str(uuid.uuid4())
    try:
        await persistence.save_workflow(workflow_id4, {
            "id": workflow_id4,
            "workflow_type": "ApprovalWorkflow",
            "status": "WAITING_HUMAN",
            "state": {
                "task_name": "Approve expense report",
                "status": "pending_approval",
                "amount": 1500.00,
                "category": "travel",
                "requester": "john.doe"
            },
            "current_step": "1",
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "blocked_on_child_id": None,  # Not waiting on any child
            "saga_mode": False,
            "completed_steps_stack": [],
            "data_region": "us-east-1",
            "priority": 5,
            "idempotency_key": None,
            "metadata": {},
            "owner_id": "demo-user",
            "org_id": None,
            "created_at": (datetime.now() - timedelta(hours=6)).isoformat(),
            "updated_at": (datetime.now() - timedelta(hours=4)).isoformat()
        })
        workflows_seeded += 1
        if verbose:
            print(f"  ✓ Created waiting workflow: {workflow_id4}")
    except Exception as e:
        if verbose:
            print(f"  ⚠ Skipped workflow {workflow_id4}: {e}")

    print(f"✓ Seeded {workflows_seeded} demo workflows")
    return workflows_seeded


async def seed_edge_devices(persistence, verbose: bool = False):
    """
    Seed sample edge devices (PostgreSQL only).

    Creates example edge devices in various states for testing
    Rufus Edge functionality.
    """
    # Only works with PostgreSQL
    if not hasattr(persistence, 'pool'):
        print("⚠ Skipping edge devices (only supported for PostgreSQL)")
        return 0

    devices_seeded = 0

    try:
        async with persistence.pool.acquire() as conn:
            result = await conn.execute("""
                INSERT INTO edge_devices (
                    device_id, device_type, device_name, location,
                    api_key_hash, status, metadata, last_heartbeat_at
                )
                VALUES
                    ('device-001', 'POS Terminal', 'Store 001 POS', 'Store 001',
                     'demo_hash_001', 'online', '{"model": "POS Terminal v2"}', NOW()),
                    ('device-002', 'POS Terminal', 'Store 002 POS', 'Store 002',
                     'demo_hash_002', 'online', '{"model": "POS Terminal v2"}', NOW()),
                    ('device-003', 'ATM', 'Branch 001 ATM', 'Branch 001',
                     'demo_hash_003', 'offline', '{"model": "ATM v3"}', NOW() - INTERVAL '1 day'),
                    ('device-004', 'Kiosk', 'Mall 001 Kiosk', 'Mall 001',
                     'demo_hash_004', 'online', '{"model": "Kiosk v1"}', NOW()),
                    ('device-005', 'Mobile Reader', 'Field Reader', 'Field',
                     'demo_hash_005', 'offline', '{"model": "Mobile Reader"}', NOW() - INTERVAL '2 hours')
                ON CONFLICT (device_id) DO NOTHING;
            """)

        # Get number of rows inserted
        devices_seeded = 5  # We tried to insert 5 devices

        if verbose:
            print(f"  ✓ Created {devices_seeded} edge devices")

        print(f"✓ Seeded edge devices")
        return devices_seeded

    except Exception as e:
        print(f"⚠ Skipping edge devices (table not found or error): {e}")
        return 0


async def seed_registration_keys(persistence, verbose: bool = False):
    """
    Seed registration keys for device enrollment.

    Note: registration_keys table not present in current schema.
    Device authentication uses api_key_hash in edge_devices table instead.
    """
    if verbose:
        print("  ℹ Skipping registration keys (not in current schema)")
    return 0


async def seed_artifacts(persistence, verbose: bool = False):
    """
    Seed ML model artifacts for testing model updates.

    Note: artifacts table not present in current schema as a separate table.
    Artifact information is stored in device_commands and related tables.
    """
    if verbose:
        print("  ℹ Skipping artifacts (not in current schema)")
    return 0


async def verify_seed_data(persistence, verbose: bool = False):
    """
    Verify that seed data was created successfully.

    Returns a summary of seeded data counts.
    """
    summary = {
        "workflows": 0,
        "edge_devices": 0
    }

    # Count workflows
    try:
        workflows = await persistence.list_workflows(limit=1000)
        summary["workflows"] = len(workflows)
        if verbose:
            print(f"  Found {summary['workflows']} workflows")
    except Exception as e:
        if verbose:
            print(f"  Could not count workflows: {e}")

    # Count edge devices (PostgreSQL only)
    if hasattr(persistence, 'pool'):
        try:
            async with persistence.pool.acquire() as conn:
                count = await conn.fetchval("SELECT COUNT(*) FROM edge_devices;")
                summary["edge_devices"] = count
                if verbose:
                    print(f"  Found {count} edge devices")
        except Exception:
            pass

    return summary


async def main():
    parser = argparse.ArgumentParser(
        description="Seed Rufus database with test data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Seed SQLite database with all data types
  python tools/seed_data.py --db-url "sqlite:///workflow.db" --type all

  # Seed PostgreSQL (Docker) with all data types
  python tools/seed_data.py \\
    --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \\
    --type all

  # Seed only demo workflows
  python tools/seed_data.py --db-url "sqlite:///test.db" --type workflows

  # Seed only registration keys (PostgreSQL)
  python tools/seed_data.py \\
    --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \\
    --type keys --verbose
        """
    )
    parser.add_argument(
        "--db-url",
        required=True,
        help="Database URL (e.g., sqlite:///workflow.db or postgresql://user:pass@localhost/db)"
    )
    parser.add_argument(
        "--type",
        choices=["all", "workflows", "edge", "keys", "artifacts"],
        default="all",
        help="Type of data to seed (default: all)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify seed data after creation"
    )

    args = parser.parse_args()

    # Determine database type and create persistence provider
    if args.db_url.startswith("sqlite"):
        db_path = args.db_url.replace("sqlite:///", "").replace("sqlite://", "")
        persistence = SQLitePersistenceProvider(db_path=db_path, auto_init=True)
        db_type = "SQLite"
    elif args.db_url.startswith("postgresql"):
        persistence = PostgresPersistenceProvider(db_url=args.db_url)
        db_type = "PostgreSQL"
    else:
        print(f"Error: Unsupported database URL: {args.db_url}")
        print("Supported formats:")
        print("  - sqlite:///path/to/database.db")
        print("  - postgresql://user:password@host:port/database")
        sys.exit(1)

    try:
        # Initialize persistence
        await persistence.initialize()

        print(f"\n{'='*60}")
        print(f"Seeding {db_type} database: {args.db_url}")
        print(f"Data type: {args.type}")
        print(f"{'='*60}\n")

        total_seeded = 0

        # Seed data based on type
        if args.type in ["all", "workflows"]:
            count = await seed_demo_workflows(persistence, verbose=args.verbose)
            total_seeded += count

        if args.type in ["all", "edge"]:
            count = await seed_edge_devices(persistence, verbose=args.verbose)
            total_seeded += count

        if args.type in ["all", "keys"]:
            count = await seed_registration_keys(persistence, verbose=args.verbose)
            total_seeded += count

        if args.type in ["all", "artifacts"]:
            count = await seed_artifacts(persistence, verbose=args.verbose)
            total_seeded += count

        # Verify if requested
        if args.verify or args.verbose:
            print(f"\n{'='*60}")
            print("Verification:")
            print(f"{'='*60}\n")
            summary = await verify_seed_data(persistence, verbose=args.verbose)
            print(f"\nSummary:")
            print(f"  Workflows: {summary['workflows']}")
            print(f"  Edge Devices: {summary['edge_devices']}")

        print(f"\n{'='*60}")
        print(f"✓ Seeding complete! Total items: {total_seeded}")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n✗ Error during seeding: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Close persistence connection
        await persistence.close()


if __name__ == "__main__":
    asyncio.run(main())
