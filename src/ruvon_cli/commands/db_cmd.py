"""
Database management commands for Ruvon CLI.

Provides commands for database initialization, migration, and validation.
"""

import asyncio
import sys
import typer
from pathlib import Path
from typing import Optional

# Add tools directory to path
tools_dir = Path(__file__).parent.parent.parent.parent / "tools"
sys.path.insert(0, str(tools_dir))

from ruvon_cli.config import get_config_manager
from ruvon_cli.formatters import Formatter

try:
    # Import migration manager
    sys.path.insert(0, str(tools_dir))
    import migrate
    MigrationManager = migrate.MigrationManager
    TOOLS_AVAILABLE = True
except ImportError as e:
    TOOLS_AVAILABLE = False
    MigrationManager = None


app = typer.Typer(name="db", help="Manage Ruvon database")


def get_db_url_from_config() -> str:
    """Get database URL from configuration"""
    config_manager = get_config_manager()
    config = config_manager.get()

    if config.persistence.provider == "sqlite":
        db_path = config.persistence.sqlite.db_path.replace("~", str(Path.home()))
        return f"sqlite:///{db_path}"
    elif config.persistence.provider == "postgres":
        return config.persistence.postgres.db_url
    else:
        raise ValueError(f"Unsupported persistence provider: {config.persistence.provider}")


@app.command("init")
def init(
    db_url: Optional[str] = typer.Option(None, "--db-url", help="Database URL (uses config if not provided)")
):
    """Initialize database schema"""
    formatter = Formatter()

    if not TOOLS_AVAILABLE:
        formatter.print_error("Database tools not available. Please check installation.")
        raise typer.Exit(code=1)

    async def _init():
        migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"

        # Determine database type
        is_sqlite = db_url.startswith("sqlite")

        if is_sqlite:
            # For SQLite, use migrations to create schema
            db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")

            # Ensure parent directory exists
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            formatter.print(f"Creating SQLite database: {db_path}")

            # Use MigrationManager to apply all migrations
            manager = MigrationManager(db_url, str(migrations_dir))
            await manager.connect()
            try:
                await manager.init_fresh_database()
                formatter.print_success("Database schema initialized successfully")
            finally:
                await manager.close()
        else:
            # For PostgreSQL, use MigrationManager
            manager = MigrationManager(db_url, str(migrations_dir))
            await manager.connect()
            try:
                # Initialize migrations table
                await manager.init_schema_migrations_table()
                formatter.print_success("Migrations table initialized")

                # Apply all pending migrations
                formatter.print("Applying migrations...")
                await manager.migrate_up()
                formatter.print_success("Database schema initialized successfully")
            finally:
                await manager.close()

    try:
        if not db_url:
            db_url = get_db_url_from_config()
            formatter.print_info(f"Using database from config")

        formatter.print("Initializing database schema...")
        asyncio.run(_init())

    except Exception as e:
        formatter.print_error(f"Failed to initialize database: {e}")
        raise typer.Exit(code=1)


@app.command("migrate")
def migrate_cmd(
    db_url: Optional[str] = typer.Option(None, "--db-url", help="Database URL (uses config if not provided)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show pending migrations without applying")
):
    """Apply pending database migrations"""
    formatter = Formatter()

    if not TOOLS_AVAILABLE:
        formatter.print_error("Database tools not available. Please check installation.")
        raise typer.Exit(code=1)

    async def _migrate():
        migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
        manager = MigrationManager(db_url, str(migrations_dir))
        await manager.connect()
        try:
            if dry_run:
                formatter.print("Checking for pending migrations...")
                pending = await manager.get_pending_migrations()
                if not pending:
                    formatter.print_success("No pending migrations")
                else:
                    formatter.print_warning(f"Found {len(pending)} pending migration(s):")
                    for migration in pending:
                        formatter.print(f"  - {migration.version:03d}: {migration.name}")
            else:
                formatter.print("Applying pending migrations...")
                await manager.migrate_up()
                formatter.print_success("Migrations applied successfully")
        finally:
            await manager.close()

    try:
        if not db_url:
            db_url = get_db_url_from_config()
            formatter.print_info(f"Using database from config")

        asyncio.run(_migrate())

    except Exception as e:
        formatter.print_error(f"Failed to apply migrations: {e}")
        raise typer.Exit(code=1)


@app.command("status")
def status(
    db_url: Optional[str] = typer.Option(None, "--db-url", help="Database URL (uses config if not provided)")
):
    """Show database migration status"""
    formatter = Formatter()

    if not TOOLS_AVAILABLE:
        formatter.print_error("Database tools not available. Please check installation.")
        raise typer.Exit(code=1)

    async def _status():
        migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
        manager = MigrationManager(db_url, str(migrations_dir))
        await manager.connect()
        try:
            # Get migration info
            applied_versions = await manager.get_applied_versions()
            pending = await manager.get_pending_migrations()
            all_migrations = manager.get_migration_files()

            formatter.print("\n[bold]Database Migration Status[/bold]\n")

            # Show database type
            db_type = "SQLite" if db_url.startswith("sqlite") else "PostgreSQL"
            formatter.print(f"Database type: {db_type}")

            formatter.print(f"\nApplied migrations: {len(applied_versions)}")
            if applied_versions:
                recent_applied = sorted(applied_versions)[-5:]  # Show last 5
                for version in recent_applied:
                    formatter.print(f"  ✓ {version:03d}", style="green")
                if len(applied_versions) > 5:
                    formatter.print(f"  ... and {len(applied_versions) - 5} more")

            formatter.print(f"\nPending migrations: {len(pending)}")
            if pending:
                for migration in pending:
                    formatter.print(f"  ⏳ {migration.version:03d}: {migration.name}", style="yellow")
            else:
                formatter.print_success("  Database is up to date")

        finally:
            await manager.close()

    try:
        if not db_url:
            db_url = get_db_url_from_config()

        asyncio.run(_status())

    except Exception as e:
        formatter.print_error(f"Failed to get migration status: {e}")
        raise typer.Exit(code=1)


@app.command("validate")
def validate():
    """Validate database schema against definition"""
    formatter = Formatter()

    try:
        formatter.print("Validating schema definition...")

        # Run the validate_schema.py script
        validate_script = Path(__file__).parent.parent.parent.parent / "tools" / "validate_schema.py"
        import subprocess
        result = subprocess.run(
            [sys.executable, str(validate_script), "--all"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            formatter.print_success("Schema validation passed")
            formatter.print(result.stdout)
        else:
            formatter.print_error("Schema validation failed")
            formatter.print(result.stderr)
            raise typer.Exit(code=1)

    except Exception as e:
        formatter.print_error(f"Failed to validate schema: {e}")
        raise typer.Exit(code=1)


@app.command("stats")
def stats(
    db_url: Optional[str] = typer.Option(None, "--db-url", help="Database URL (uses config if not provided)")
):
    """Show database statistics"""
    formatter = Formatter()

    try:
        if not db_url:
            db_url = get_db_url_from_config()

        formatter.print("\n[bold]Database Statistics[/bold]\n")

        # Show database type and URL
        if db_url.startswith("sqlite"):
            db_type = "SQLite"
            db_path = db_url.replace("sqlite:///", "")
            formatter.print(f"Type: {db_type}")
            formatter.print(f"Path: {db_path}")

            # Check if file exists
            if Path(db_path).exists():
                size = Path(db_path).stat().st_size
                formatter.print(f"Size: {size:,} bytes ({size / 1024:.2f} KB)")
            else:
                formatter.print_warning("Database file does not exist")
                return

        elif db_url.startswith("postgres"):
            db_type = "PostgreSQL"
            masked_url = db_url.split('@')[-1] if '@' in db_url else db_url
            formatter.print(f"Type: {db_type}")
            formatter.print(f"URL: {masked_url}")

        # Get table counts
        formatter.print("\n[bold]Table Statistics:[/bold]")

        async def get_table_stats():
            if db_url.startswith("sqlite"):
                import aiosqlite
                async with aiosqlite.connect(db_path) as conn:
                    # Get table counts
                    tables = ["workflow_executions", "workflow_execution_logs", "workflow_metrics"]
                    for table in tables:
                        cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
                        count = (await cursor.fetchone())[0]
                        formatter.print(f"  {table}: {count:,} rows")
            else:
                import asyncpg
                conn = await asyncpg.connect(db_url)
                try:
                    tables = ["workflow_executions", "workflow_execution_logs", "workflow_metrics"]
                    for table in tables:
                        count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                        formatter.print(f"  {table}: {count:,} rows")
                finally:
                    await conn.close()

        asyncio.run(get_table_stats())

        formatter.print_success("\nStats retrieved successfully")

    except Exception as e:
        formatter.print_error(f"Failed to get database stats: {e}")
        raise typer.Exit(code=1)
