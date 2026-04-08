import typer
from typing import Optional, Dict, Any
from pathlib import Path
import yaml
import sys
import os
import json
import asyncio

# Ensure rufus package is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.memory import InMemoryPersistence
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.observability.logging import LoggingObserver
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine
from ruvon.providers.persistence import PersistenceProvider
from ruvon.providers.execution import ExecutionProvider
from ruvon.providers.observer import WorkflowObserver

# Import new command modules
from ruvon_cli.commands import config_cmd, workflow_cmd, db_cmd, interactive, build_cmd, rag_cmd

app = typer.Typer(
    help="Rufus - Python-native workflow orchestration engine",
    no_args_is_help=True
)

# Add command groups
app.add_typer(config_cmd.app, name="config")
app.add_typer(workflow_cmd.app, name="workflow")
app.add_typer(db_cmd.app, name="db")
app.add_typer(interactive.app, name="interactive")
app.add_typer(build_cmd.app, name="build")
app.add_typer(rag_cmd.app, name="rag")

# Convenience aliases for workflow commands at top level
@app.command("list")
def list_alias(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status"),
    workflow_type: Optional[str] = typer.Option(None, "--type", help="Filter by workflow type"),
    limit: int = typer.Option(20, "--limit", help="Maximum number of workflows"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed information"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List workflows (alias for 'workflow list')"""
    workflow_cmd.list_workflows(status, workflow_type, limit, verbose, json_output)


@app.command("start")
def start_alias(
    workflow_type: str = typer.Argument(..., help="Workflow type to start"),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="Initial data as JSON"),
    data_file: Optional[Path] = typer.Option(None, "--data-file", help="Initial data from file"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="Workflow config file"),
    auto_execute: Optional[bool] = typer.Option(None, "--auto", help="Auto-execute all steps"),
    interactive: Optional[bool] = typer.Option(None, "--interactive", "-i", help="Interactive mode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without executing"),
):
    """Start a new workflow (alias for 'workflow start')"""
    workflow_cmd.start_workflow(workflow_type, data, data_file, config_file, auto_execute, interactive, dry_run)


@app.command("show")
def show_alias(
    workflow_id: str = typer.Argument(..., help="Workflow ID to display"),
    state: bool = typer.Option(False, "--state", help="Show full state"),
    logs: bool = typer.Option(False, "--logs", help="Show execution logs"),
    metrics: bool = typer.Option(False, "--metrics", help="Show performance metrics"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all details"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show workflow details (alias for 'workflow show')"""
    workflow_cmd.show_workflow(workflow_id, state, logs, metrics, verbose, json_output)


@app.command("resume")
def resume_alias(
    workflow_id: str = typer.Argument(..., help="Workflow ID to resume"),
    user_input: Optional[str] = typer.Option(None, "--input", "-i", help="User input as JSON"),
    input_file: Optional[Path] = typer.Option(None, "--input-file", help="User input from file"),
    auto_execute: bool = typer.Option(False, "--auto", help="Auto-execute remaining steps"),
):
    """Resume a paused workflow (alias for 'workflow resume')"""
    workflow_cmd.resume_workflow(workflow_id, user_input, input_file, auto_execute)


@app.command("retry")
def retry_alias(
    workflow_id: str = typer.Argument(..., help="Workflow ID to retry"),
    from_step: Optional[str] = typer.Option(None, "--from-step", help="Step to retry from"),
    auto_execute: bool = typer.Option(False, "--auto", help="Auto-execute remaining steps"),
):
    """Retry a failed workflow (alias for 'workflow retry')"""
    workflow_cmd.retry_workflow(workflow_id, from_step, auto_execute)


@app.command("logs")
def logs_alias(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
    step: Optional[str] = typer.Option(None, "--step", help="Filter by step name"),
    level: Optional[str] = typer.Option(None, "--level", help="Filter by log level"),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of logs to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """View workflow logs (alias for 'workflow logs')"""
    workflow_cmd.view_logs(workflow_id, step, level, limit, follow, json_output)


@app.command("metrics")
def metrics_alias(
    workflow_id: Optional[str] = typer.Option(None, "--workflow-id", "-w", help="Workflow ID"),
    workflow_type: Optional[str] = typer.Option(None, "--type", help="Filter by workflow type"),
    summary: bool = typer.Option(False, "--summary", help="Show summary"),
    limit: int = typer.Option(50, "--limit", help="Number of metrics"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """View workflow metrics (alias for 'workflow metrics')"""
    workflow_cmd.view_metrics(workflow_id, workflow_type, summary, limit, json_output)


@app.command("cancel")
def cancel_alias(
    workflow_id: str = typer.Argument(..., help="Workflow ID to cancel"),
    force: bool = typer.Option(False, "--force", help="Skip compensation"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Cancellation reason"),
):
    """Cancel a running workflow (alias for 'workflow cancel')"""
    workflow_cmd.cancel_workflow(workflow_id, force, reason)


async def _create_providers_for_run(
    workflow_registry_config: Dict[str, Any],
    persistence_provider: Optional[PersistenceProvider] = None,
    execution_provider: Optional[ExecutionProvider] = None,
    observer: Optional[WorkflowObserver] = None
) -> tuple:
    """Create and initialize providers plus a WorkflowBuilder for the run command."""

    if persistence_provider is None:
        persistence_provider = InMemoryPersistence()
    if execution_provider is None:
        execution_provider = SyncExecutor()
    if observer is None:
        observer = LoggingObserver()

    await persistence_provider.initialize()
    await observer.initialize()

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry_config,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    return persistence_provider, execution_provider, observer, builder


@app.command()
def validate(
    workflow_file: Path = typer.Argument(..., help="Path to the workflow YAML file."),
    strict: bool = typer.Option(False, "--strict", help="Perform comprehensive validation including function imports"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    graph: bool = typer.Option(False, "--graph", help="Generate dependency graph visualization"),
    graph_format: str = typer.Option("mermaid", "--graph-format", help="Graph format: mermaid, dot, or text")
):
    """
    Validates a Rufus workflow YAML file for syntax, structure, and correctness.

    Basic validation checks:
    - YAML syntax
    - Required fields (workflow_type, steps, initial_state_model)
    - Step structure
    - Dependency references
    - Route targets
    - Circular dependency detection

    Strict validation (--strict) additionally checks:
    - Function paths can be imported
    - State model is a valid Pydantic class
    - Compensation functions exist
    - Parallel task functions exist

    Dependency graph (--graph) generates visualization:
    - Mermaid format (default): Markdown-compatible flowchart
    - DOT format: Graphviz compatible
    - Text format: Simple text representation

    Examples:
        rufus validate workflow.yaml                      # Basic validation
        rufus validate workflow.yaml --strict             # Comprehensive validation
        rufus validate workflow.yaml --graph              # Show dependency graph
        rufus validate workflow.yaml --graph --graph-format dot  # DOT format graph
        rufus validate workflow.yaml --json               # JSON output
    """
    from ruvon_cli.validation import validate_workflow_file, WorkflowValidator

    is_valid, errors, warnings = validate_workflow_file(workflow_file, strict=strict)

    # Generate dependency graph if requested
    graph_output = None
    if graph and workflow_file.exists():
        try:
            with open(workflow_file, "r") as f:
                config = yaml.safe_load(f)

            if isinstance(config, dict) and "steps" in config:
                validator = WorkflowValidator(strict=strict)
                graph_output = validator.generate_dependency_graph(
                    config["steps"],
                    format=graph_format
                )
        except Exception as e:
            warnings.append(f"Could not generate dependency graph: {e}")

    if json_output:
        result = {
            "valid": is_valid,
            "file": str(workflow_file),
            "errors": errors,
            "warnings": warnings
        }
        if graph_output:
            result["dependency_graph"] = graph_output
        typer.echo(json.dumps(result, indent=2))
    else:
        # Pretty output
        if is_valid:
            typer.secho(f"✓ Successfully validated {workflow_file}", fg=typer.colors.GREEN, bold=True)
        else:
            typer.secho(f"✗ Validation failed for {workflow_file}", fg=typer.colors.RED, bold=True, err=True)

        if errors:
            typer.secho(f"\n{len(errors)} Error(s):", fg=typer.colors.RED, bold=True, err=True)
            for i, error in enumerate(errors, 1):
                typer.secho(f"  {i}. {error}", fg=typer.colors.RED, err=True)

        if warnings:
            typer.secho(f"\n{len(warnings)} Warning(s):", fg=typer.colors.YELLOW, bold=True)
            for i, warning in enumerate(warnings, 1):
                typer.secho(f"  {i}. {warning}", fg=typer.colors.YELLOW)

        if graph_output:
            typer.secho(f"\nDependency Graph ({graph_format}):", fg=typer.colors.CYAN, bold=True)
            typer.echo(f"\n{graph_output}\n")

        if not is_valid:
            if not strict and not any("import" in e.lower() for e in errors):
                typer.secho(f"\nTip: Use --strict to check function imports and state models", fg=typer.colors.CYAN)
        elif not warnings:
            typer.secho(f"\nNo issues found!", fg=typer.colors.GREEN)

    if not is_valid:
        raise typer.Exit(code=1)


@app.command()
def run(
    workflow_file: Path = typer.Argument(..., help="Path to the workflow YAML file."),
    initial_data: Optional[str] = typer.Option("{}", "--data", "-d", help="Initial workflow data as a JSON string."),
):
    """
    Runs a Rufus workflow locally using in-memory persistence and synchronous execution.
    """
    async def _run_workflow():
        if not workflow_file.is_file():
            typer.echo(f"Error: Workflow file not found at {workflow_file}", err=True)
            raise typer.Exit(code=1)

        try:
            data = json.loads(initial_data)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: Invalid JSON for initial data: {e}", err=True)
            raise typer.Exit(code=1)

        persistence = None
        execution = None
        observer = None
        try:
            with open(workflow_file, "r") as f:
                workflow_config = yaml.safe_load(f)

            if "workflow_type" not in workflow_config:
                typer.echo(f"Error: 'workflow_type' missing in {workflow_file}", err=True)
                raise typer.Exit(code=1)

            workflow_type = workflow_config["workflow_type"]

            # Create a minimal registry containing only the workflow to be run
            workflow_registry_for_cli = {
                workflow_type: {
                    "initial_state_model_path": workflow_config.get("initial_state_model_path", "pydantic.BaseModel"),
                    "steps": workflow_config.get("steps", []),
                    "parameters": workflow_config.get("parameters", {}),
                    "env": workflow_config.get("env", {})
                }
            }

            persistence, execution, observer, builder = await _create_providers_for_run(workflow_registry_for_cli)

            typer.echo(f"Running workflow from {workflow_file} with initial data: {data}")

            workflow = await builder.create_workflow(
                workflow_type=workflow_type,
                persistence_provider=persistence,
                execution_provider=execution,
                workflow_builder=builder,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
                workflow_observer=observer,
                initial_data=data,
            )
            await persistence.save_workflow(workflow.id, workflow.to_dict())
            await observer.on_workflow_started(workflow.id, workflow.workflow_type, workflow.state)
            if workflow.automate_start:
                await workflow.next_step(user_input={})

            typer.echo(f"Workflow ID: {workflow.id}")
            typer.echo(f"Initial Status: {workflow.status}")
            typer.echo(f"Initial State: {workflow.state.model_dump()}")

            while workflow.status not in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
                typer.echo(f"\n--- Current Step: {workflow.current_step_name} ({workflow.status}) ---")
                typer.echo(f"Current State: {workflow.state.model_dump()}")

                result, next_step_name = await workflow.next_step(user_input={})

                typer.echo(f"Step Result: {result}")
                await persistence.save_workflow(workflow.id, workflow.to_dict())

            typer.echo(f"\n--- Workflow Finished ({workflow.status}) ---")
            typer.echo(f"Final State: {workflow.state.model_dump()}")

            if workflow.status == "COMPLETED":
                typer.secho(f"Successfully completed workflow {workflow.id}", fg=typer.colors.GREEN)
            else:
                typer.secho(f"Workflow {workflow.id} finished with status {workflow.status}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)

        except Exception as e:
            typer.echo(f"An error occurred during workflow execution: {e}", err=True)
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            if persistence and hasattr(persistence, 'close'):
                await persistence.close()
            if observer and hasattr(observer, 'close'):
                await observer.close()
            if execution and hasattr(execution, 'close'):
                await execution.close()


    asyncio.run(_run_workflow())


@app.command(name="scan-zombies")
def scan_zombies(
    database_url: str = typer.Option(..., "--db", help="Database connection URL (postgresql:// or sqlite://)"),
    fix: bool = typer.Option(False, "--fix", help="Automatically mark zombie workflows as FAILED_WORKER_CRASH"),
    stale_threshold: int = typer.Option(120, "--threshold", help="Heartbeat stale threshold in seconds (default: 120)"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON")
):
    """
    Scan for zombie workflows with stale heartbeats.

    A zombie workflow is one where the worker crashed while processing a step,
    leaving the workflow in RUNNING state with a stale heartbeat.

    Example:
        rufus scan-zombies --db postgresql://localhost/ruvon --fix
        rufus scan-zombies --db sqlite:///workflows.db --threshold 180 --json
    """
    async def _scan():
        # Import persistence provider based on database URL
        if database_url.startswith("postgresql://"):
            from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
            persistence = PostgresPersistenceProvider(database_url)
        elif database_url.startswith("sqlite://"):
            from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
            db_path = database_url.replace("sqlite:///", "")
            persistence = SQLitePersistenceProvider(db_path)
        else:
            typer.echo(f"Unsupported database URL: {database_url}", err=True)
            raise typer.Exit(code=1)

        try:
            await persistence.initialize()

            # Import and create zombie scanner
            from ruvon.zombie_scanner import ZombieScanner
            scanner = ZombieScanner(persistence, stale_threshold_seconds=stale_threshold)

            # Scan and optionally recover
            summary = await scanner.scan_and_recover(
                stale_threshold_seconds=stale_threshold,
                dry_run=not fix
            )

            if json_output:
                import json
                typer.echo(json.dumps(summary, indent=2))
            else:
                typer.echo(f"\n{'='*60}")
                typer.echo(f"Zombie Workflow Scan Results")
                typer.echo(f"{'='*60}")
                typer.echo(f"Scan time:          {summary['scan_time']}")
                typer.echo(f"Duration:           {summary['duration_seconds']:.2f}s")
                typer.echo(f"Stale threshold:    {summary['stale_threshold_seconds']}s")
                typer.echo(f"Zombies found:      {summary['zombies_found']}")
                typer.echo(f"Zombies recovered:  {summary['zombies_recovered']}")
                typer.echo(f"Dry run:            {summary['dry_run']}")
                typer.echo(f"{'='*60}\n")

                if summary['zombies_found'] > 0:
                    if fix:
                        typer.secho(
                            f"✓ Marked {summary['zombies_recovered']} zombie workflows as FAILED_WORKER_CRASH",
                            fg=typer.colors.GREEN,
                            bold=True
                        )
                    else:
                        typer.secho(
                            f"⚠ Found {summary['zombies_found']} zombie workflows. Run with --fix to recover them.",
                            fg=typer.colors.YELLOW,
                            bold=True
                        )
                else:
                    typer.secho(
                        "✓ No zombie workflows found",
                        fg=typer.colors.GREEN,
                        bold=True
                    )

        except Exception as e:
            typer.echo(f"Error scanning for zombies: {e}", err=True)
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            if hasattr(persistence, 'close'):
                await persistence.close()

    asyncio.run(_scan())


@app.command(name="zombie-daemon")
def zombie_daemon(
    database_url: str = typer.Option(..., "--db", help="Database connection URL"),
    scan_interval: int = typer.Option(60, "--interval", help="Scan interval in seconds (default: 60)"),
    stale_threshold: int = typer.Option(120, "--threshold", help="Heartbeat stale threshold in seconds (default: 120)")
):
    """
    Run zombie scanner as a continuous background daemon.

    The daemon will periodically scan for zombie workflows and automatically
    mark them as FAILED_WORKER_CRASH.

    Example:
        rufus zombie-daemon --db postgresql://localhost/ruvon --interval 60
    """
    async def _run_daemon():
        # Import persistence provider based on database URL
        if database_url.startswith("postgresql://"):
            from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
            persistence = PostgresPersistenceProvider(database_url)
        elif database_url.startswith("sqlite://"):
            from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
            db_path = database_url.replace("sqlite:///", "")
            persistence = SQLitePersistenceProvider(db_path)
        else:
            typer.echo(f"Unsupported database URL: {database_url}", err=True)
            raise typer.Exit(code=1)

        try:
            await persistence.initialize()

            # Import and create zombie scanner
            from ruvon.zombie_scanner import ZombieScanner
            scanner = ZombieScanner(persistence, stale_threshold_seconds=stale_threshold)

            typer.echo(f"\n{'='*60}")
            typer.echo(f"Starting Zombie Scanner Daemon")
            typer.echo(f"{'='*60}")
            typer.echo(f"Database:          {database_url}")
            typer.echo(f"Scan interval:     {scan_interval}s")
            typer.echo(f"Stale threshold:   {stale_threshold}s")
            typer.echo(f"{'='*60}\n")
            typer.echo("Press Ctrl+C to stop\n")

            # Run daemon
            await scanner.run_daemon(
                scan_interval_seconds=scan_interval,
                stale_threshold_seconds=stale_threshold
            )

        except KeyboardInterrupt:
            typer.secho("\n\nStopping zombie scanner daemon...", fg=typer.colors.YELLOW)
            scanner.stop_daemon()
        except Exception as e:
            typer.echo(f"Error in zombie daemon: {e}", err=True)
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            if hasattr(persistence, 'close'):
                await persistence.close()

    asyncio.run(_run_daemon())


if __name__ == "__main__":
    app()