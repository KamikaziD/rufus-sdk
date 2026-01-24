"""
Configuration commands for Rufus CLI.

Handles rufus config subcommands for managing CLI configuration.
"""

import typer
from typing import Optional
from rufus_cli.config import get_config_manager, Config
from rufus_cli.formatters import ConfigFormatter, Formatter


app = typer.Typer(name="config", help="Manage Rufus CLI configuration")


@app.command("show")
def show(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON")
):
    """Show current configuration"""
    config_manager = get_config_manager()
    config = config_manager.get()

    # Convert to dict for display
    config_dict = config_manager._config_to_dict(config)

    # Format and display
    formatter = ConfigFormatter()
    formatter.format(config_dict, json_output=json_output)


@app.command("set-persistence")
def set_persistence(
    provider: str = typer.Option(..., "--provider", "-p", help="Provider type (sqlite, postgres, memory)"),
    db_path: Optional[str] = typer.Option(None, "--db-path", help="Database path (for SQLite)"),
    db_url: Optional[str] = typer.Option(None, "--db-url", help="Database URL (for PostgreSQL)"),
    pool_min: Optional[int] = typer.Option(None, "--pool-min", help="Min pool size (for PostgreSQL)"),
    pool_max: Optional[int] = typer.Option(None, "--pool-max", help="Max pool size (for PostgreSQL)"),
):
    """
    Set persistence provider configuration

    Examples:\n
        rufus config set-persistence --provider sqlite --db-path workflows.db\n
        rufus config set-persistence --provider postgres --db-url postgresql://localhost/rufus
    """
    config_manager = get_config_manager()
    formatter = Formatter()

    try:
        kwargs = {}
        if db_path:
            kwargs["db_path"] = db_path
        if db_url:
            kwargs["db_url"] = db_url
        if pool_min:
            kwargs["pool_min_size"] = pool_min
        if pool_max:
            kwargs["pool_max_size"] = pool_max

        config_manager.set_persistence(provider, **kwargs)
        formatter.print_success(f"Persistence provider set to: {provider}")

        if provider == "sqlite" and db_path:
            formatter.print_info(f"Database path: {db_path}")
        elif provider == "postgres" and db_url:
            formatter.print_info(f"Database URL: {db_url}")

    except Exception as e:
        formatter.print_error(f"Failed to set persistence: {e}")
        raise typer.Exit(code=1)


@app.command("set-execution")
def set_execution(
    provider: str = typer.Option(..., "--provider", "-p", help="Provider type (sync, thread_pool)")
):
    """Set execution provider"""
    config_manager = get_config_manager()
    formatter = Formatter()

    try:
        config_manager.set_execution(provider)
        formatter.print_success(f"Execution provider set to: {provider}")
    except Exception as e:
        formatter.print_error(f"Failed to set execution: {e}")
        raise typer.Exit(code=1)


@app.command("set-default")
def set_default(
    key: str = typer.Option(..., "--key", "-k", help="Default key (auto_execute, interactive, json_output)"),
    value: bool = typer.Option(..., "--value", "-v", help="Value (true/false)"),
):
    """Set default behavior"""
    config_manager = get_config_manager()
    formatter = Formatter()

    try:
        config_manager.set_default(key, value)
        formatter.print_success(f"Default '{key}' set to: {value}")
    except Exception as e:
        formatter.print_error(f"Failed to set default: {e}")
        raise typer.Exit(code=1)


@app.command("reset")
def reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
):
    """Reset configuration to defaults"""
    formatter = Formatter()

    if not confirm:
        confirm = typer.confirm("Are you sure you want to reset configuration to defaults?")
        if not confirm:
            formatter.print_info("Reset cancelled")
            return

    config_manager = get_config_manager()
    config_manager.reset()

    formatter.print_success("Configuration reset to defaults")
    formatter.print_info("Run 'rufus config show' to view current configuration")


@app.command("path")
def path():
    """Show configuration file path"""
    config_manager = get_config_manager()
    formatter = Formatter()

    formatter.print(f"Configuration file: {config_manager.config_path}")

    if config_manager.config_path.exists():
        formatter.print_info("File exists")
    else:
        formatter.print_warning("File does not exist (using defaults)")
