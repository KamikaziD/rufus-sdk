#!/usr/bin/env python3
"""
Schema Migration Manager

Manages database schema versions and applies migrations in order.
Supports both PostgreSQL and SQLite.

Usage:
    # List pending migrations
    python tools/migrate.py --db postgres://user:pass@localhost/dbname --status

    # Apply pending migrations
    python tools/migrate.py --db postgres://user:pass@localhost/dbname --up

    # Initialize schema_migrations table
    python tools/migrate.py --db postgres://user:pass@localhost/dbname --init

    # SQLite example
    python tools/migrate.py --db sqlite:///path/to/database.db --up
"""

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

try:
    import aiosqlite
    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False


class Migration:
    """Represents a single migration file"""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.filename = filepath.name

        # Extract version from filename (e.g., 001_init.sql -> 001)
        match = re.match(r'^(\d+)_(.+)\.sql$', self.filename)
        if not match:
            raise ValueError(f"Invalid migration filename: {self.filename}")

        self.version = int(match.group(1))
        self.name = match.group(2)

        # Detect database type from filename
        name_lower = self.name.lower()
        if 'postgres' in name_lower or 'pg' in name_lower:
            self.db_type = 'postgres'
        elif 'sqlite' in name_lower:
            self.db_type = 'sqlite'
        else:
            # Default to postgres if not specified
            self.db_type = 'postgres'

    def __repr__(self):
        return f"Migration(version={self.version}, name={self.name}, db_type={self.db_type})"

    def __lt__(self, other):
        return self.version < other.version


class MigrationManager:
    """Manages database schema migrations"""

    def __init__(self, db_url: str = None, migrations_dir: str = "migrations", db_type: str = None, conn=None):
        """
        Initialize MigrationManager.

        Args:
            db_url: Database URL (optional if conn provided)
            migrations_dir: Directory containing migration files
            db_type: Database type ('postgres' or 'sqlite', optional if db_url provided)
            conn: Existing database connection (optional, will create new if not provided)
        """
        self.db_url = db_url
        self.migrations_dir = Path(migrations_dir)
        self._owns_connection = conn is None  # Track if we created the connection
        self.conn = conn

        # Determine database type
        if db_type:
            self.db_type = db_type
        elif db_url:
            # Parse database type from URL
            parsed = urlparse(db_url)
            self.db_type = parsed.scheme.split('+')[0]  # Handle postgres+asyncpg
            if self.db_type == 'postgresql':
                self.db_type = 'postgres'
        else:
            raise ValueError("Either db_url or db_type must be provided")

        if self.db_type not in ['postgres', 'sqlite']:
            raise ValueError(f"Unsupported database type: {self.db_type}")

        # Check dependencies only if we need to create a connection
        if self._owns_connection:
            if self.db_type == 'postgres' and not ASYNCPG_AVAILABLE:
                raise ImportError("asyncpg is required for PostgreSQL migrations. Install with: pip install asyncpg")

            if self.db_type == 'sqlite' and not AIOSQLITE_AVAILABLE:
                raise ImportError("aiosqlite is required for SQLite migrations. Install with: pip install aiosqlite")

    async def connect(self):
        """Connect to the database (only if we don't already have a connection)"""
        if self.conn is not None:
            return  # Already connected (using external connection)

        if not self.db_url:
            raise ValueError("Cannot connect: no db_url provided and no existing connection")

        if self.db_type == 'postgres':
            self.conn = await asyncpg.connect(self.db_url)
        else:  # sqlite
            # Extract path from URL
            db_path = self.db_url.replace('sqlite:///', '').replace('sqlite://', '')
            self.conn = await aiosqlite.connect(db_path)

    async def close(self):
        """Close database connection (only if we created it)"""
        if self.conn and self._owns_connection:
            if self.db_type == 'postgres':
                await self.conn.close()
            else:
                await self.conn.close()
            self.conn = None

    async def init_schema_migrations_table(self, silent: bool = False):
        """Create schema_migrations table if it doesn't exist"""
        if self.db_type == 'postgres':
            await self.conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    checksum VARCHAR(64)
                )
            """)
        else:  # sqlite
            await self.conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    checksum VARCHAR(64)
                )
            """)
            await self.conn.commit()

        if not silent:
            print("✓ Initialized schema_migrations table")

    async def get_applied_versions(self) -> List[int]:
        """Get list of applied migration versions"""
        try:
            if self.db_type == 'postgres':
                rows = await self.conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
                return [row['version'] for row in rows]
            else:  # sqlite
                async with self.conn.execute("SELECT version FROM schema_migrations ORDER BY version") as cursor:
                    rows = await cursor.fetchall()
                    return [row[0] for row in rows]
        except Exception:
            # Table doesn't exist yet
            return []

    def get_migration_files(self) -> List[Migration]:
        """Get all migration files sorted by version"""
        if not self.migrations_dir.exists():
            raise FileNotFoundError(f"Migrations directory not found: {self.migrations_dir}")

        migrations = []
        for filepath in self.migrations_dir.glob("*.sql"):
            try:
                migration = Migration(filepath)
                # Only include migrations for this database type
                if migration.db_type == self.db_type:
                    migrations.append(migration)
            except ValueError as e:
                print(f"⚠️  Skipping {filepath.name}: {e}", file=sys.stderr)

        return sorted(migrations)

    async def get_pending_migrations(self) -> List[Migration]:
        """Get migrations that haven't been applied yet"""
        applied_versions = await self.get_applied_versions()
        all_migrations = self.get_migration_files()

        pending = [m for m in all_migrations if m.version not in applied_versions]
        return sorted(pending)

    async def apply_migration(self, migration: Migration, silent: bool = False):
        """Apply a single migration"""
        if not silent:
            print(f"\n▶ Applying migration {migration.version:03d}: {migration.name}")

        # Read migration file
        with open(migration.filepath, 'r') as f:
            sql = f.read()

        try:
            if self.db_type == 'postgres':
                # Execute migration
                await self.conn.execute(sql)

                # Record in schema_migrations
                await self.conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                    migration.version,
                    migration.name
                )
            else:  # sqlite
                # Use executescript for SQLite to handle multi-statement SQL
                # This properly handles triggers with BEGIN...END blocks
                await self.conn.executescript(sql)

                # Record in schema_migrations
                await self.conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (migration.version, migration.name)
                )

                await self.conn.commit()

            if not silent:
                print(f"  ✓ Successfully applied migration {migration.version:03d}")

        except Exception as e:
            if not silent:
                print(f"  ✗ Failed to apply migration {migration.version:03d}: {e}", file=sys.stderr)
            if self.db_type == 'sqlite':
                await self.conn.rollback()
            raise

    async def migrate_up(self, target_version: Optional[int] = None, silent: bool = False):
        """Apply pending migrations up to target version (or all if None)"""
        pending = await self.get_pending_migrations()

        if not pending:
            if not silent:
                print("✓ No pending migrations")
            return

        if target_version:
            pending = [m for m in pending if m.version <= target_version]

        if not pending:
            if not silent:
                print(f"✓ No migrations to apply up to version {target_version}")
            return

        if not silent:
            print(f"\nApplying {len(pending)} migration(s)...")

        for migration in pending:
            await self.apply_migration(migration, silent=silent)

        if not silent:
            print(f"\n✅ Successfully applied {len(pending)} migration(s)")

    async def init_fresh_database(self, silent: bool = False):
        """
        Initialize a fresh database by applying all migrations.

        This is used by auto-init and db init commands.

        Args:
            silent: If True, suppress output messages
        """
        # Initialize schema_migrations table
        await self.init_schema_migrations_table(silent=silent)

        # Apply all migrations
        await self.migrate_up(silent=silent)

    async def status(self):
        """Show migration status"""
        applied_versions = await self.get_applied_versions()
        all_migrations = self.get_migration_files()
        pending_migrations = await self.get_pending_migrations()

        print(f"\n{'='*70}")
        print(f"  MIGRATION STATUS ({self.db_type.upper()})")
        print(f"{'='*70}\n")

        print(f"  Database:    {self.db_url}")
        print(f"  Applied:     {len(applied_versions)} migration(s)")
        print(f"  Pending:     {len(pending_migrations)} migration(s)")
        print(f"  Total:       {len(all_migrations)} migration(s)")

        if applied_versions:
            print(f"\n  Last applied: {max(applied_versions):03d}")

        if pending_migrations:
            print(f"\n  Pending migrations:")
            for migration in pending_migrations:
                print(f"    {migration.version:03d} - {migration.name}")
        else:
            print(f"\n  ✓ All migrations applied")

        print(f"\n{'='*70}\n")


async def main():
    parser = argparse.ArgumentParser(
        description="Manage database schema migrations"
    )
    parser.add_argument(
        '--db',
        required=True,
        help='Database URL (e.g., postgres://user:pass@localhost/db or sqlite:///path/to/db.sqlite)'
    )
    parser.add_argument(
        '--migrations-dir',
        default='migrations',
        help='Migrations directory (default: migrations)'
    )
    parser.add_argument(
        '--init',
        action='store_true',
        help='Initialize schema_migrations table'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show migration status'
    )
    parser.add_argument(
        '--up',
        action='store_true',
        help='Apply pending migrations'
    )
    parser.add_argument(
        '--to',
        type=int,
        help='Target version for migration'
    )

    args = parser.parse_args()

    if not any([args.init, args.status, args.up]):
        parser.error("One of --init, --status, or --up is required")

    try:
        manager = MigrationManager(args.db, args.migrations_dir)
        await manager.connect()

        if args.init:
            await manager.init_schema_migrations_table()

        if args.status:
            await manager.status()

        if args.up:
            await manager.migrate_up(target_version=args.to)

        await manager.close()

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
