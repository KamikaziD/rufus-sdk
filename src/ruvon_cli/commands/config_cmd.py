"""
Configuration commands for Ruvon CLI.

Handles ruvon config subcommands for managing CLI configuration.
"""

import typer
from typing import Optional
from ruvon_cli.config import get_config_manager, Config
from ruvon_cli.formatters import ConfigFormatter, Formatter


app = typer.Typer(name="config", help="Manage Ruvon CLI configuration")


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
    provider: Optional[str] = typer.Option(None, "--provider", help="Provider type (memory, sqlite, postgres)"),
    db_path: Optional[str] = typer.Option(None, "--db-path", help="Database path (for SQLite)"),
    db_url: Optional[str] = typer.Option(None, "--db-url", help="Database URL (for PostgreSQL)"),
    pool_min: Optional[int] = typer.Option(None, "--pool-min", help="Min pool size (for PostgreSQL)"),
    pool_max: Optional[int] = typer.Option(None, "--pool-max", help="Max pool size (for PostgreSQL)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive mode, skip prompts"),
):
    """
    Set persistence provider configuration

    Examples:\n
        ruvon config set-persistence --provider sqlite --db-path workflows.db --yes\n
        ruvon config set-persistence --provider postgres --db-url postgresql://localhost/ruvon --yes\n
        ruvon config set-persistence  # Interactive mode
    """
    config_manager = get_config_manager()
    formatter = Formatter()

    try:
        # Non-interactive mode if --provider is specified or --yes is used
        if provider or yes:
            # Validate provider
            valid_providers = ["memory", "sqlite", "postgres"]
            if provider and provider not in valid_providers:
                formatter.print_error(f"Invalid provider: {provider}. Must be one of: {', '.join(valid_providers)}")
                raise typer.Exit(code=1)

            # If --yes but no provider, default to sqlite
            if yes and not provider:
                provider = "sqlite"

            # Provider-specific validation
            kwargs = {}
            if provider == "sqlite":
                if not db_path:
                    if yes:
                        db_path = "~/.ruvon/workflows.db"  # Default for non-interactive
                    else:
                        db_path = typer.prompt("Database path", default="~/.ruvon/workflows.db")
                kwargs["db_path"] = db_path
            elif provider == "postgres":
                if not db_url:
                    if yes:
                        formatter.print_error("--db-url is required for postgres provider in non-interactive mode")
                        raise typer.Exit(code=1)
                    else:
                        db_url = typer.prompt("Database URL", default="postgresql://localhost/ruvon")
                kwargs["db_url"] = db_url

                # Pool settings
                if pool_min is None:
                    pool_min = 10 if yes else typer.prompt("Min pool size", default=10, type=int)
                if pool_max is None:
                    pool_max = 50 if yes else typer.prompt("Max pool size", default=50, type=int)
                kwargs["pool_min_size"] = pool_min
                kwargs["pool_max_size"] = pool_max

            # Set configuration
            config_manager.set_persistence(provider, **kwargs)
            formatter.print_success(f"\nPersistence provider set to: {provider}")

            if provider == "sqlite":
                formatter.print_info(f"Database path: {db_path}")
            elif provider == "postgres":
                formatter.print_info(f"Database URL: {db_url}")
        else:
            # Interactive mode (original behavior)
            formatter.print("\n[bold]Available persistence providers:[/bold]")
            formatter.print("  1. memory - In-memory (testing only)")
            formatter.print("  2. sqlite - SQLite database (development/production)")
            formatter.print("  3. postgres - PostgreSQL database (production)")

            provider_choice = typer.prompt("\nSelect provider (1-3)", type=int)

            provider_map = {
                1: "memory",
                2: "sqlite",
                3: "postgres"
            }

            if provider_choice not in provider_map:
                formatter.print_error("Invalid choice")
                raise typer.Exit(code=1)

            provider = provider_map[provider_choice]
            kwargs = {}

            # Provider-specific configuration
            if provider == "sqlite":
                if not db_path:
                    db_path = typer.prompt("Database path", default="~/.ruvon/workflows.db")
                kwargs["db_path"] = db_path
            elif provider == "postgres":
                if not db_url:
                    db_url = typer.prompt("Database URL", default="postgresql://localhost/ruvon")
                kwargs["db_url"] = db_url
                if not pool_min:
                    pool_min = typer.prompt("Min pool size", default=10, type=int)
                if not pool_max:
                    pool_max = typer.prompt("Max pool size", default=50, type=int)
                kwargs["pool_min_size"] = pool_min
                kwargs["pool_max_size"] = pool_max

            config_manager.set_persistence(provider, **kwargs)
            formatter.print_success(f"\nPersistence provider set to: {provider}")

            if provider == "sqlite":
                formatter.print_info(f"Database path: {db_path}")
            elif provider == "postgres":
                formatter.print_info(f"Database URL: {db_url}")

    except Exception as e:
        formatter.print_error(f"Failed to set persistence: {e}")
        raise typer.Exit(code=1)


@app.command("set-execution")
def set_execution():
    """Set execution provider (interactive)"""
    config_manager = get_config_manager()
    formatter = Formatter()

    try:
        # Interactive provider selection
        formatter.print("\n[bold]Available execution providers:[/bold]")
        formatter.print("  1. sync - Synchronous execution (simple, testing)")
        formatter.print("  2. thread_pool - Thread pool execution (parallel tasks)")

        provider_choice = typer.prompt("\nSelect provider (1-2)", type=int)

        provider_map = {
            1: "sync",
            2: "thread_pool"
        }

        if provider_choice not in provider_map:
            formatter.print_error("Invalid choice")
            raise typer.Exit(code=1)

        provider = provider_map[provider_choice]

        config_manager.set_execution(provider)
        formatter.print_success(f"\nExecution provider set to: {provider}")
    except Exception as e:
        formatter.print_error(f"Failed to set execution: {e}")
        raise typer.Exit(code=1)


@app.command("set-default")
def set_default():
    """Set default behavior (interactive)"""
    config_manager = get_config_manager()
    formatter = Formatter()

    try:
        # Interactive key selection
        formatter.print("\n[bold]Available defaults:[/bold]")
        formatter.print("  1. auto_execute - Automatically execute next step")
        formatter.print("  2. interactive - Use interactive mode")
        formatter.print("  3. json_output - Output as JSON by default")

        key_choice = typer.prompt("\nSelect default to configure (1-3)", type=int)

        key_map = {
            1: "auto_execute",
            2: "interactive",
            3: "json_output"
        }

        if key_choice not in key_map:
            formatter.print_error("Invalid choice")
            raise typer.Exit(code=1)

        key = key_map[key_choice]
        value = typer.confirm(f"Enable {key}?", default=True)

        config_manager.set_default(key, value)
        formatter.print_success(f"\nDefault '{key}' set to: {value}")
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
    formatter.print_info("Run 'ruvon config show' to view current configuration")


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
