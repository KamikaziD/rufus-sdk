#!/usr/bin/env python3
"""
Database Initialization Script for Confucius Workflow Engine

This script:
1. Checks if PostgreSQL is accessible
2. Creates the database schema
3. Verifies table creation
4. Provides helpful diagnostic information

Usage:
    python scripts/init_database.py
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


async def init_database():
    """Initialize PostgreSQL database schema"""

    print("=" * 70)
    print("Confucius Workflow Engine - Database Initialization")
    print("=" * 70)
    print()

    # Check DATABASE_URL environment variable
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        print()
        print("Please set DATABASE_URL before running this script:")
        print("  export DATABASE_URL='postgresql://user:password@localhost:5432/confucius'")
        print()
        return False

    print(f"✓ DATABASE_URL found: {db_url[:30]}...")
    print()

    try:
        # Import persistence module
        from confucius.persistence_postgres import PostgresWorkflowStore

        print("📦 Creating PostgreSQL connection pool...")
        store = PostgresWorkflowStore(db_url)
        await store.initialize()
        print("✓ Connection successful")
        print()

        # Run Migrations
        print("📋 Checking for migrations...")
        async with store.pool.acquire() as conn:
            # Create migrations table if not exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            migration_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
            migration_files = sorted([f for f in os.listdir(migration_dir) if f.endswith('.sql')])

            for migration_file in migration_files:
                # Check if already applied
                applied = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version = $1)",
                    migration_file
                )

                if applied:
                    print(f"  ✓ {migration_file} (already applied)")
                else:
                    print(f"  ▶ Applying {migration_file}...")
                    file_path = os.path.join(migration_dir, migration_file)
                    with open(file_path, 'r') as f:
                        sql = f.read()
                    
                    try:
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO schema_migrations (version) VALUES ($1)",
                            migration_file
                        )
                        print(f"  ✓ {migration_file} applied successfully")
                    except Exception as e:
                        print(f"  ❌ Failed to apply {migration_file}: {e}")
                        raise

        print()
        # Verify tables
        async with store.pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)

            print(f"Current tables ({len(tables)}):")
            for table in tables:
                print(f"  - {table['table_name']}")
        print()

        # Close connection
        await store.close()

        print("=" * 70)
        print("✅ Database initialization complete!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1. Set WORKFLOW_STORAGE=postgres in your environment")
        print("  2. Start Celery worker: celery -A celery_setup worker --loglevel=info")
        print("  3. Start FastAPI: uvicorn main:app --reload")
        print()

        return True

    except ImportError as e:
        print(f"❌ ERROR: Could not import required modules: {e}")
        print()
        print("Make sure to install dependencies:")
        print("  pip install -r requirements.txt")
        print()
        return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print()
        import traceback
        traceback.print_exc()
        print()
        return False


async def check_connection():
    """Quick connection check"""
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        return False

    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        version = await conn.fetchval('SELECT version()')
        await conn.close()
        print(f"✓ PostgreSQL connection successful")
        print(f"  Version: {version.split(',')[0]}")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def main():
    """Main entry point"""

    # Check if we're just testing connection
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        asyncio.run(check_connection())
        return

    # Run full initialization
    success = asyncio.run(init_database())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
