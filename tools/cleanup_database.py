#!/usr/bin/env python3
"""
Cleanup Ruvon database and reset to seed data.

This script removes test data from the database and optionally re-seeds
with default demo data. Useful for resetting after load tests.

Usage:
    # Clean PostgreSQL and re-seed
    python tools/cleanup_database.py --db-url "postgresql://ruvon:pass@localhost:5433/ruvon_cloud"

    # Clean SQLite and re-seed
    python tools/cleanup_database.py --db-url "sqlite:///workflow.db"

    # Clean without re-seeding
    python tools/cleanup_database.py --db-url "postgresql://..." --no-seed

    # Delete only load test data (preserve everything else)
    python tools/cleanup_database.py --db-url "postgresql://..." --mode load-test-only
"""

import asyncio
import sys
import argparse
import subprocess
from pathlib import Path
from typing import Optional

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider


async def delete_all_data(persistence, verbose: bool = False):
    """
    Delete all workflows and edge devices from the database.

    Args:
        persistence: Persistence provider instance
        verbose: Print detailed output
    """
    deleted_counts = {
        "workflows": 0,
        "edge_devices": 0,
        "heartbeats": 0
    }

    print("\n🗑️  Deleting all data from database...")

    # Delete workflows
    if verbose:
        print("  Deleting workflows...")

    try:
        # Get count before deletion
        workflows = await persistence.list_workflows(limit=100000)
        workflow_count = len(workflows)

        # Delete all workflows
        for workflow in workflows:
            try:
                # Use raw SQL for faster deletion
                if hasattr(persistence, 'pool'):  # PostgreSQL
                    async with persistence.pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM workflow_executions WHERE id = $1",
                            workflow['id']
                        )
                else:  # SQLite
                    async with persistence.conn.execute(
                        "DELETE FROM workflow_executions WHERE id = ?",
                        (workflow['id'],)
                    ):
                        pass
                    await persistence.conn.commit()
                deleted_counts["workflows"] += 1
            except Exception as e:
                if verbose:
                    print(f"    Warning: Failed to delete workflow {workflow['id']}: {e}")

        if verbose:
            print(f"  ✓ Deleted {deleted_counts['workflows']} workflows")

    except Exception as e:
        print(f"  ⚠ Error deleting workflows: {e}")

    # Delete edge devices (PostgreSQL only)
    if hasattr(persistence, 'pool'):
        if verbose:
            print("  Deleting edge devices...")

        try:
            async with persistence.pool.acquire() as conn:
                result = await conn.execute("DELETE FROM edge_devices;")
                # PostgreSQL returns result like "DELETE 5"
                deleted_counts["edge_devices"] = int(result.split()[-1]) if result.split() else 0

            if verbose:
                print(f"  ✓ Deleted {deleted_counts['edge_devices']} edge devices")

        except Exception as e:
            if verbose:
                print(f"  ⚠ Error deleting edge devices: {e}")

        # Delete workflow heartbeats (PostgreSQL only, if table exists)
        try:
            async with persistence.pool.acquire() as conn:
                # Check if table exists first
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'workflow_heartbeats'
                    )
                """)

                if table_exists:
                    if verbose:
                        print("  Deleting workflow heartbeats...")

                    result = await conn.execute("DELETE FROM workflow_heartbeats;")
                    deleted_counts["heartbeats"] = int(result.split()[-1]) if result.split() else 0

                    if verbose:
                        print(f"  ✓ Deleted {deleted_counts['heartbeats']} heartbeat records")

        except Exception as e:
            if verbose:
                print(f"  ⚠ Error deleting heartbeats: {e}")

    return deleted_counts


async def delete_load_test_data(persistence, verbose: bool = False):
    """
    Delete only load test data, preserving other workflows/devices.

    Deletes:
    - Edge devices with device_id starting with 'load-test-'
    - Workflows created by load test orchestrator

    Args:
        persistence: Persistence provider instance
        verbose: Print detailed output
    """
    deleted_counts = {
        "workflows": 0,
        "edge_devices": 0
    }

    print("\n🗑️  Deleting load test data (preserving other data)...")

    # Delete load test edge devices (PostgreSQL only)
    if hasattr(persistence, 'pool'):
        if verbose:
            print("  Deleting load test edge devices...")

        try:
            async with persistence.pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM edge_devices WHERE device_id LIKE 'load-test-%';"
                )
                deleted_counts["edge_devices"] = int(result.split()[-1]) if result.split() else 0

            if verbose:
                print(f"  ✓ Deleted {deleted_counts['edge_devices']} load test devices")

        except Exception as e:
            if verbose:
                print(f"  ⚠ Error deleting load test devices: {e}")

    # Note: Currently no reliable way to identify load test workflows
    # They don't have a special marker, so we skip workflow deletion in this mode
    print("  ℹ Load test workflows cannot be automatically identified")
    print("    Use --mode delete-all to remove all workflows")

    return deleted_counts


async def run_seed_script(db_url: str, verbose: bool = False):
    """
    Run seed_data.py to populate database with demo data.

    Args:
        db_url: Database connection URL
        verbose: Print detailed output
    """
    print("\n🌱 Seeding database with demo data...")

    seed_script = project_root / "tools" / "seed_data.py"

    if not seed_script.exists():
        print(f"  ⚠ Seed script not found at {seed_script}")
        return False

    try:
        cmd = [
            sys.executable,
            str(seed_script),
            "--db-url", db_url,
            "--type", "all"
        ]

        if verbose:
            cmd.append("--verbose")

        result = subprocess.run(
            cmd,
            capture_output=not verbose,
            text=True,
            timeout=60,
            check=True
        )

        if not verbose and result.stdout:
            # Show summary even in non-verbose mode
            for line in result.stdout.split('\n'):
                if '✓' in line or 'Seeded' in line:
                    print(f"  {line}")

        return True

    except subprocess.CalledProcessError as e:
        print(f"  ✗ Seed script failed: {e}")
        if e.stdout:
            print(f"  Output: {e.stdout}")
        if e.stderr:
            print(f"  Error: {e.stderr}")
        return False
    except Exception as e:
        print(f"  ✗ Error running seed script: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="Cleanup Ruvon database and reset to seed data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clean PostgreSQL database and re-seed with demo data
  python tools/cleanup_database.py \\
    --db-url "postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"

  # Clean SQLite database and re-seed
  python tools/cleanup_database.py --db-url "sqlite:///workflow.db"

  # Clean without re-seeding
  python tools/cleanup_database.py --db-url "postgresql://..." --no-seed

  # Delete only load test devices (preserve other data)
  python tools/cleanup_database.py --db-url "postgresql://..." --mode load-test-only

  # Verbose output
  python tools/cleanup_database.py --db-url "postgresql://..." --verbose

Cleanup Modes:
  delete-all        - Delete all workflows and edge devices, then re-seed (default)
  load-test-only    - Delete only load test data (devices starting with 'load-test-')
        """
    )

    parser.add_argument(
        "--db-url",
        required=True,
        help="Database URL (e.g., sqlite:///workflow.db or postgresql://user:pass@host/db)"
    )

    parser.add_argument(
        "--mode",
        choices=["delete-all", "load-test-only"],
        default="delete-all",
        help="Cleanup mode (default: delete-all)"
    )

    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip re-seeding after cleanup"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
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
        print(f"✗ Unsupported database URL: {args.db_url}")
        print("Supported formats:")
        print("  - sqlite:///path/to/database.db")
        print("  - postgresql://user:password@host:port/database")
        sys.exit(1)

    # Confirmation prompt
    if not args.yes:
        print(f"\n{'='*60}")
        print(f"DATABASE CLEANUP")
        print(f"{'='*60}")
        print(f"Database: {db_type}")
        print(f"URL: {args.db_url}")
        print(f"Mode: {args.mode}")
        print(f"Re-seed: {'No' if args.no_seed else 'Yes'}")
        print(f"{'='*60}\n")

        if args.mode == "delete-all":
            print("⚠️  WARNING: This will delete ALL data from the database!")
        else:
            print("ℹ️  This will delete load test data only")

        response = input("\nContinue? [y/N]: ").strip().lower()
        if response not in ['y', 'yes']:
            print("Cancelled.")
            sys.exit(0)

    try:
        # Initialize persistence
        await persistence.initialize()

        print(f"\n{'='*60}")
        print(f"CLEANUP STARTING - {db_type}")
        print(f"{'='*60}")

        # Delete data based on mode
        if args.mode == "delete-all":
            deleted = await delete_all_data(persistence, verbose=args.verbose)
            print(f"\n✓ Cleanup complete:")
            print(f"  - Workflows deleted: {deleted['workflows']}")
            print(f"  - Edge devices deleted: {deleted['edge_devices']}")
            if deleted['heartbeats'] > 0:
                print(f"  - Heartbeats deleted: {deleted['heartbeats']}")

        elif args.mode == "load-test-only":
            deleted = await delete_load_test_data(persistence, verbose=args.verbose)
            print(f"\n✓ Load test cleanup complete:")
            print(f"  - Edge devices deleted: {deleted['edge_devices']}")

        # Re-seed if requested
        if not args.no_seed and args.mode == "delete-all":
            success = await run_seed_script(args.db_url, verbose=args.verbose)
            if success:
                print("\n✓ Database reset complete!")
            else:
                print("\n⚠ Database cleaned but seeding failed")
        else:
            print("\n✓ Database cleanup complete!")

        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n✗ Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        # Close persistence connection
        await persistence.close()


if __name__ == "__main__":
    asyncio.run(main())
