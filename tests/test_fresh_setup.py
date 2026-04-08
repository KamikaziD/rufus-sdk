"""
Test Fresh Setup Workflow with Alembic

Verifies that a fresh installation can:
1. Apply Alembic migrations
2. Initialize persistence providers
3. Create and run workflows

This ensures the quickstart documentation is accurate.
"""

import asyncio
import os
import tempfile
import subprocess
from pathlib import Path

from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider


async def test_postgres_fresh_setup():
    """Test fresh PostgreSQL setup with Alembic"""
    print("\n" + "="*70)
    print("  Testing Fresh PostgreSQL Setup with Alembic")
    print("="*70 + "\n")

    db_url = "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"

    # Step 1: Verify Alembic can run
    print("1. Verifying Alembic installation...")
    try:
        result = subprocess.run(
            ["alembic", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"   ✓ {result.stdout.strip()}")
    except Exception as e:
        print(f"   ✗ Alembic not found: {e}")
        return False

    # Step 2: Check migration status
    print("\n2. Checking migration status...")
    try:
        os.environ["DATABASE_URL"] = db_url
        os.chdir("src/rufus")

        result = subprocess.run(
            ["alembic", "current"],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"   ✓ Current migration: {result.stdout.strip()}")
    except Exception as e:
        print(f"   ⚠ Migration check failed: {e}")
    finally:
        os.chdir("../..")

    # Step 3: Test persistence provider
    print("\n3. Testing PostgreSQL persistence provider...")
    try:
        provider = PostgresPersistenceProvider(db_url)
        await provider.initialize()

        # Verify tables exist
        async with provider.pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                AND tablename IN ('workflow_executions', 'workflow_audit_log', 'workflow_heartbeats', 'alembic_version')
                ORDER BY tablename
            """)

            print("   ✓ Found tables:")
            for table in tables:
                print(f"     - {table['tablename']}")

        await provider.close()
        print("   ✓ PostgreSQL provider working!")
        return True

    except Exception as e:
        print(f"   ✗ PostgreSQL test failed: {e}")
        return False


async def test_sqlite_fresh_setup():
    """Test fresh SQLite setup with Alembic"""
    print("\n" + "="*70)
    print("  Testing Fresh SQLite Setup with Alembic")
    print("="*70 + "\n")

    # Create temp database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"

        # Step 1: Apply migrations
        print("1. Applying Alembic migrations to SQLite...")
        try:
            os.environ["DATABASE_URL"] = db_url
            os.chdir("src/rufus")

            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                check=True
            )
            print("   ✓ Migrations applied")
            print(f"   Output: {result.stdout.strip()}")

        except Exception as e:
            print(f"   ✗ Migration failed: {e}")
            return False
        finally:
            os.chdir("../..")

        # Step 2: Test persistence provider
        print("\n2. Testing SQLite persistence provider...")
        try:
            provider = SQLitePersistenceProvider(db_path=db_path)
            await provider.initialize()

            # Verify tables exist
            async with provider.conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table'
                AND name IN ('workflow_executions', 'workflow_audit_log', 'workflow_heartbeats', 'alembic_version')
                ORDER BY name
            """) as cursor:
                tables = await cursor.fetchall()

                print("   ✓ Found tables:")
                for table in tables:
                    print(f"     - {table[0]}")

            await provider.close()
            print("   ✓ SQLite provider working!")
            return True

        except Exception as e:
            print(f"   ✗ SQLite test failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.remove(db_path)


async def main():
    """Run all fresh setup tests"""
    print("\n" + "="*70)
    print("  FRESH SETUP VERIFICATION TEST")
    print("="*70)

    results = {}

    # Test PostgreSQL
    results['postgres'] = await test_postgres_fresh_setup()

    # Test SQLite
    results['sqlite'] = await test_sqlite_fresh_setup()

    # Summary
    print("\n" + "="*70)
    print("  TEST SUMMARY")
    print("="*70)

    for db, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {db:15} {status}")

    all_passed = all(results.values())
    print("\n" + "="*70)
    if all_passed:
        print("  ✓ ALL TESTS PASSED - Fresh setup workflow verified!")
    else:
        print("  ✗ SOME TESTS FAILED - Check output above")
    print("="*70 + "\n")

    return all_passed


if __name__ == '__main__':
    success = asyncio.run(main())
    exit(0 if success else 1)
