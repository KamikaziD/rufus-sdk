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

from rufus.builder import WorkflowBuilder
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.models import WorkflowStep # Import WorkflowStep to analyze its structure

# Import new command modules
from rufus_cli.commands import config_cmd, workflow_cmd, db_cmd

app = typer.Typer(
    help="Rufus - Python-native workflow orchestration engine",
    no_args_is_help=True
)

# Add command groups
app.add_typer(config_cmd.app, name="config")
app.add_typer(workflow_cmd.app, name="workflow")
app.add_typer(db_cmd.app, name="db")

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


async def get_configured_engine(
    workflow_registry_config: Dict[str, Any],
    persistence_provider: Optional[PersistenceProvider] = None,
    execution_provider: Optional[ExecutionProvider] = None,
    observer: Optional[WorkflowObserver] = None
) -> WorkflowEngine:
    """Configures and returns a WorkflowEngine instance."""

    if persistence_provider is None:
        persistence_provider = InMemoryPersistence()
    if execution_provider is None:
        execution_provider = SyncExecutor()
    if observer is None:
        observer = LoggingObserver()
    
    # Initialize providers (especially for async ones)
    await persistence_provider.initialize()
    await observer.initialize()

    # WorkflowBuilder is now initialized by the WorkflowEngine
    engine = WorkflowEngine(
        persistence=persistence_provider,
        executor=execution_provider,
        observer=observer,
        workflow_registry=workflow_registry_config,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )
    # The executor's initialize method will be called within WorkflowEngine's __init__ if present.
    return engine


@app.command()
def validate(workflow_file: Path = typer.Argument(..., help="Path to the workflow YAML file.")):
    """
    Validates a Rufus workflow YAML file for syntax and basic structure.
    """
    if not workflow_file.is_file():
        typer.echo(f"Error: Workflow file not found at {workflow_file}", err=True)
        raise typer.Exit(code=1)

    try:
        with open(workflow_file, "r") as f:
            workflow_config = yaml.safe_load(f)
        
        if not isinstance(workflow_config, dict):
            typer.echo(f"Error: Invalid YAML format in {workflow_file}. Expected a dictionary.", err=True)
            raise typer.Exit(code=1)

        if "workflow_type" not in workflow_config:
            typer.echo(f"Error: 'workflow_type' missing in {workflow_file}", err=True)
            raise typer.Exit(code=1)
        if "steps" not in workflow_config or not isinstance(workflow_config["steps"], list):
            typer.echo(f"Error: 'steps' section missing or not a list in {workflow_file}", err=True)
            raise typer.Exit(code=1)
        
        # Minimal registry for validation
        temp_registry_entry = {
            workflow_config["workflow_type"]:
                {
                    "initial_state_model_path": "pydantic.BaseModel", # Generic model for validation
                    "steps": workflow_config.get("steps", []),
                    "parameters": workflow_config.get("parameters", {}),
                    "env": workflow_config.get("env", {})
                }
        }
        # A dummy WorkflowEngine to get a builder for validation
        # No need to await initialize as it's a dummy run
        persistence = InMemoryPersistence()
        executor = SyncExecutor()
        observer = LoggingObserver()
        expression_evaluator_cls = SimpleExpressionEvaluator
        template_engine_cls = Jinja2TemplateEngine

        engine = WorkflowEngine(
            persistence=persistence,
            executor=executor,
            observer=observer,
            workflow_registry=temp_registry_entry,
            expression_evaluator_cls=expression_evaluator_cls,
            template_engine_cls=template_engine_cls
        )

        # Attempt to build steps to catch more errors
        # Note: This will not fully validate func_paths unless they are importable
        engine.workflow_builder._build_steps_from_config(workflow_config["steps"])


        typer.echo(f"Successfully validated {workflow_file} (syntax and basic structure passed).")
    except yaml.YAMLError as e:
        typer.echo(f"Error: Invalid YAML syntax in {workflow_file}: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"An unexpected error occurred during validation: {e}", err=True)
        import traceback
        traceback.print_exc()
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

        try:
            with open(workflow_file, "r") as f:
                workflow_config = yaml.safe_load(f)
            
            if "workflow_type" not in workflow_config:
                typer.echo(f"Error: 'workflow_type' missing in {workflow_file}", err=True)
                raise typer.Exit(code=1)

            workflow_type = workflow_config["workflow_type"]
            
            # Create a minimal registry containing only the workflow to be run
            workflow_registry_for_cli = {
                workflow_type:
                    {
                        "initial_state_model_path": workflow_config.get("initial_state_model_path", "pydantic.BaseModel"),
                        "steps": workflow_config.get("steps", []),
                        "parameters": workflow_config.get("parameters", {}),
                        "env": workflow_config.get("env", {})
                    }
            }

            engine = await get_configured_engine(workflow_registry_for_cli)
            
            typer.echo(f"Running workflow from {workflow_file} with initial data: {data}")
            
            # Start workflow through the engine
            workflow = await engine.start_workflow(
                workflow_type=workflow_type,
                initial_data=data
            )

            typer.echo(f"Workflow ID: {workflow.id}")
            typer.echo(f"Initial Status: {workflow.status}")
            typer.echo(f"Initial State: {workflow.state.model_dump()}")

            while workflow.status not in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
                typer.echo(f"\n--- Current Step: {workflow.current_step_name} ({workflow.status}) ---")
                typer.echo(f"Current State: {workflow.state.model_dump()}")
                
                # For CLI run, we assume no human input for now, just auto-advance
                # In real scenario, input would be prompted or provided.
                result, next_step_name = await workflow.next_step(user_input={})
                
                typer.echo(f"Step Result: {result}")
                await engine.persistence.save_workflow(workflow.id, workflow.to_dict()) # Save state after each step

            typer.echo(f"\n--- Workflow Finished ({workflow.status}) ---")
            typer.echo(f"Final State: {workflow.state.model_dump()}")

            if workflow.status == "COMPLETED":
                typer.echo(f"Successfully completed workflow {workflow.id}", fg=typer.colors.GREEN)
            else:
                typer.echo(f"Workflow {workflow.id} finished with status {workflow.status}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
        
        except Exception as e:
            typer.echo(f"An error occurred during workflow execution: {e}", err=True)
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            # Ensure providers are closed
            # Some providers might not have close() method, handle gracefully
            if hasattr(engine.persistence, 'close'):
                await engine.persistence.close()
            if hasattr(engine.observer, 'close'):
                await engine.observer.close()
            # executor.close() might be a no-op for SyncExecutor
            if hasattr(engine.executor, 'close'):
                await engine.executor.close()


    asyncio.run(_run_workflow())


if __name__ == "__main__":
    app()