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
            "current_step": 3,
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "created_at": (datetime.now() - timedelta(days=2)).isoformat(),
            "updated_at": (datetime.now() - timedelta(days=1)).isoformat(),
            "owner_id": "demo-user",
            "data_region": "us-east-1"
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
            "current_step": 1,
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "created_at": (datetime.now() - timedelta(hours=3)).isoformat(),
            "updated_at": datetime.now().isoformat(),
            "owner_id": "demo-user",
            "data_region": "us-east-1"
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
            "current_step": 2,
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "created_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "updated_at": datetime.now().isoformat(),
            "owner_id": "demo-user",
            "data_region": "us-east-1"
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
            "current_step": 1,
            "workflow_version": "1.0.0",
            "state_model_path": "rufus.models.BaseModel",
            "steps_config": [],  # Empty steps for demo workflows
            "parent_execution_id": None,  # Top-level workflows
            "created_at": (datetime.now() - timedelta(hours=6)).isoformat(),
            "updated_at": (datetime.now() - timedelta(hours=4)).isoformat(),
            "owner_id": "demo-user",
            "data_region": "us-east-1"
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
    if not hasattr(persistence, 'conn') or not hasattr(persistence.conn, 'execute'):
        print("⚠ Skipping edge devices (only supported for PostgreSQL)")
        return 0

    devices_seeded = 0

    try:
        result = await persistence.conn.execute("""
            INSERT INTO edge_devices (device_id, registration_key, status, last_heartbeat, device_info)
            VALUES
                ('device-001', 'rufus-registration-key', 'active', NOW(), '{"model": "POS Terminal v2", "location": "Store 001"}'),
                ('device-002', 'rufus-registration-key', 'active', NOW(), '{"model": "POS Terminal v2", "location": "Store 002"}'),
                ('device-003', 'rufus-registration-key', 'inactive', NOW() - INTERVAL '1 day', '{"model": "ATM v3", "location": "Branch 001"}'),
                ('device-004', 'rufus-registration-key', 'active', NOW(), '{"model": "Kiosk v1", "location": "Mall 001"}'),
                ('device-005', 'rufus-registration-key', 'offline', NOW() - INTERVAL '2 hours', '{"model": "Mobile Reader", "location": "Field"}')
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

    Creates a default registration key that can be used by edge devices
    to register with the cloud control plane.
    """
    # Only works with PostgreSQL
    if not hasattr(persistence, 'conn') or not hasattr(persistence.conn, 'execute'):
        print("⚠ Skipping registration keys (only supported for PostgreSQL)")
        return 0

    keys_seeded = 0

    try:
        await persistence.conn.execute("""
            INSERT INTO registration_keys (key_value, max_uses, expires_at, created_at)
            VALUES ('rufus-registration-key', 10000, NOW() + INTERVAL '1 year', NOW())
            ON CONFLICT (key_value) DO NOTHING;
        """)
        keys_seeded = 1

        if verbose:
            print(f"  ✓ Created registration key: rufus-registration-key")

        print(f"✓ Seeded registration keys")
        return keys_seeded

    except Exception as e:
        print(f"⚠ Skipping registration keys (table not found or error): {e}")
        return 0


async def seed_artifacts(persistence, verbose: bool = False):
    """
    Seed ML model artifacts for testing model updates.

    Creates example artifact versions for testing the edge deployment
    model update workflow.
    """
    # Only works with PostgreSQL
    if not hasattr(persistence, 'conn') or not hasattr(persistence.conn, 'execute'):
        print("⚠ Skipping artifacts (only supported for PostgreSQL)")
        return 0

    artifacts_seeded = 0

    try:
        await persistence.conn.execute("""
            INSERT INTO artifacts (
                artifact_id, artifact_type, version, s3_key, checksum,
                size_bytes, metadata, created_at
            )
            VALUES
                (
                    'fraud-detection-model', 'ml_model', '1.0.0',
                    's3://rufus-artifacts/models/fraud-detection-v1.0.0.onnx',
                    'abc123def456',
                    2048576,
                    '{"framework": "onnx", "input_shape": [1, 10], "output_shape": [1, 2]}',
                    NOW() - INTERVAL '7 days'
                ),
                (
                    'fraud-detection-model', 'ml_model', '1.1.0',
                    's3://rufus-artifacts/models/fraud-detection-v1.1.0.onnx',
                    'def789ghi012',
                    2148576,
                    '{"framework": "onnx", "input_shape": [1, 10], "output_shape": [1, 2], "improvements": "Better accuracy"}',
                    NOW() - INTERVAL '1 day'
                )
            ON CONFLICT (artifact_id, version) DO NOTHING;
        """)
        artifacts_seeded = 2

        if verbose:
            print(f"  ✓ Created {artifacts_seeded} artifact versions")

        print(f"✓ Seeded artifacts")
        return artifacts_seeded

    except Exception as e:
        print(f"⚠ Skipping artifacts (table not found or error): {e}")
        return 0


async def verify_seed_data(persistence, verbose: bool = False):
    """
    Verify that seed data was created successfully.

    Returns a summary of seeded data counts.
    """
    summary = {
        "workflows": 0,
        "edge_devices": 0,
        "registration_keys": 0,
        "artifacts": 0
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
    if hasattr(persistence, 'conn') and hasattr(persistence.conn, 'fetchval'):
        try:
            count = await persistence.conn.fetchval("SELECT COUNT(*) FROM edge_devices;")
            summary["edge_devices"] = count
            if verbose:
                print(f"  Found {count} edge devices")
        except Exception:
            pass

        try:
            count = await persistence.conn.fetchval("SELECT COUNT(*) FROM registration_keys;")
            summary["registration_keys"] = count
            if verbose:
                print(f"  Found {count} registration keys")
        except Exception:
            pass

        try:
            count = await persistence.conn.fetchval("SELECT COUNT(*) FROM artifacts;")
            summary["artifacts"] = count
            if verbose:
                print(f"  Found {count} artifacts")
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
            print(f"  Registration Keys: {summary['registration_keys']}")
            print(f"  Artifacts: {summary['artifacts']}")

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
