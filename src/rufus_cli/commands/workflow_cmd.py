"""
Workflow management commands for Rufus CLI.

Handles workflow lifecycle commands: list, start, show, resume, retry.
"""

import typer
import asyncio
import json
import yaml
from typing import Optional
from pathlib import Path

from rufus_cli.config import get_config
from rufus_cli.providers import create_providers, close_providers
from rufus_cli.formatters import WorkflowListFormatter, WorkflowDetailFormatter, Formatter
from rufus.engine import WorkflowEngine
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine


app = typer.Typer(name="workflow", help="Manage workflows")


@app.command("list")
def list_workflows(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status (ACTIVE, COMPLETED, FAILED, etc.)"),
    workflow_type: Optional[str] = typer.Option(None, "--type", help="Filter by workflow type"),
    limit: int = typer.Option(20, "--limit", help="Maximum number of workflows to display"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed information"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List workflows"""
    async def _list():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = WorkflowListFormatter()

        try:
            # Build filters
            filters = {"limit": limit}
            if status:
                filters["status"] = status
            if workflow_type:
                filters["workflow_type"] = workflow_type

            # Get workflows
            workflows = await persistence.list_workflows(**filters)

            # Format and display
            formatter.format(workflows, verbose=verbose, json_output=json_output)

        except Exception as e:
            formatter.print_error(f"Failed to list workflows: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_list())


@app.command("start")
def start_workflow(
    workflow_type: str = typer.Argument(..., help="Workflow type to start"),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="Initial workflow data as JSON string"),
    data_file: Optional[Path] = typer.Option(None, "--data-file", help="Initial workflow data from JSON file"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="Workflow YAML config file"),
    auto_execute: Optional[bool] = typer.Option(None, "--auto", help="Auto-execute all steps"),
    interactive: Optional[bool] = typer.Option(None, "--interactive", "-i", help="Interactive mode (prompt for HITL)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without executing"),
):
    """Start a new workflow"""
    async def _start():
        config = get_config()

        # Override config with CLI flags
        if auto_execute is not None:
            config.defaults.auto_execute = auto_execute
        if interactive is not None:
            config.defaults.interactive = interactive

        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()
        detail_formatter = WorkflowDetailFormatter()

        try:
            # Parse initial data
            initial_data = {}
            if data:
                try:
                    initial_data = json.loads(data)
                except json.JSONDecodeError as e:
                    formatter.print_error(f"Invalid JSON in --data: {e}")
                    raise typer.Exit(code=1)
            elif data_file:
                if not data_file.exists():
                    formatter.print_error(f"Data file not found: {data_file}")
                    raise typer.Exit(code=1)
                try:
                    with open(data_file, "r") as f:
                        initial_data = json.load(f)
                except json.JSONDecodeError as e:
                    formatter.print_error(f"Invalid JSON in {data_file}: {e}")
                    raise typer.Exit(code=1)

            # Load workflow config if provided
            workflow_registry = {}
            if config_file:
                if not config_file.exists():
                    formatter.print_error(f"Config file not found: {config_file}")
                    raise typer.Exit(code=1)

                with open(config_file, "r") as f:
                    workflow_config = yaml.safe_load(f)

                wf_type = workflow_config.get("workflow_type", workflow_type)
                workflow_registry[wf_type] = {
                    "initial_state_model_path": workflow_config.get("initial_state_model_path", "pydantic.BaseModel"),
                    "steps": workflow_config.get("steps", []),
                    "parameters": workflow_config.get("parameters", {}),
                    "env": workflow_config.get("env", {})
                }
            else:
                # Try to find config file automatically
                # For now, require explicit config file
                formatter.print_error(f"Workflow config file required. Use --config <file.yaml>")
                formatter.print_info(f"Example: rufus start {workflow_type} --config workflows/{workflow_type}.yaml")
                raise typer.Exit(code=1)

            if dry_run:
                formatter.print_info(f"Dry run: Would start workflow '{workflow_type}' with data:")
                print(json.dumps(initial_data, indent=2))
                return

            # Create workflow engine
            engine = WorkflowEngine(
                persistence=persistence,
                executor=execution,
                observer=observer,
                workflow_registry=workflow_registry,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine
            )

            # Start workflow
            formatter.print_info(f"Starting workflow: {workflow_type}")
            workflow = await engine.start_workflow(
                workflow_type=workflow_type,
                initial_data=initial_data
            )

            formatter.print_success(f"Workflow started successfully")
            formatter.print(f"\nWorkflow ID: [bold cyan]{workflow.id}[/bold cyan]")
            formatter.print(f"Status: [bold yellow]{workflow.status}[/bold yellow]")
            formatter.print(f"Current Step: [bold green]{workflow.current_step_name}[/bold green]")

            formatter.print_info(f"\nNext steps:")
            formatter.print(f"  • View details: [bold]rufus show {workflow.id}[/bold]")
            formatter.print(f"  • Resume: [bold]rufus resume {workflow.id}[/bold]")

        except Exception as e:
            formatter.print_error(f"Failed to start workflow: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_start())


@app.command("show")
def show_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID to display"),
    state: bool = typer.Option(False, "--state", help="Show full state"),
    logs: bool = typer.Option(False, "--logs", help="Show execution logs"),
    metrics: bool = typer.Option(False, "--metrics", help="Show performance metrics"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all details"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show workflow details"""
    async def _show():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = WorkflowDetailFormatter()

        try:
            # Load workflow
            workflow_data = await persistence.load_workflow(workflow_id)

            if not workflow_data:
                formatter.print_error(f"Workflow not found: {workflow_id}")
                raise typer.Exit(code=1)

            # Format and display
            show_state_flag = state or verbose
            show_logs_flag = logs or verbose
            show_metrics_flag = metrics or verbose

            formatter.format(
                workflow_data,
                show_state=show_state_flag,
                show_logs=show_logs_flag,
                show_metrics=show_metrics_flag,
                json_output=json_output
            )

        except Exception as e:
            if "not found" in str(e).lower():
                formatter.print_error(f"Workflow not found: {workflow_id}")
            else:
                formatter.print_error(f"Failed to show workflow: {e}")
                import traceback
                traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_show())


@app.command("resume")
def resume_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID to resume"),
    user_input: Optional[str] = typer.Option(None, "--input", "-i", help="User input as JSON string"),
    input_file: Optional[Path] = typer.Option(None, "--input-file", help="User input from JSON file"),
    auto_execute: bool = typer.Option(False, "--auto", help="Auto-execute remaining steps"),
):
    """Resume a paused workflow"""
    async def _resume():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()

        try:
            # Parse user input
            input_data = {}
            if user_input:
                try:
                    input_data = json.loads(user_input)
                except json.JSONDecodeError as e:
                    formatter.print_error(f"Invalid JSON in --input: {e}")
                    raise typer.Exit(code=1)
            elif input_file:
                if not input_file.exists():
                    formatter.print_error(f"Input file not found: {input_file}")
                    raise typer.Exit(code=1)
                try:
                    with open(input_file, "r") as f:
                        input_data = json.load(f)
                except json.JSONDecodeError as e:
                    formatter.print_error(f"Invalid JSON in {input_file}: {e}")
                    raise typer.Exit(code=1)

            # Load workflow
            workflow_data = await persistence.load_workflow(workflow_id)
            if not workflow_data:
                formatter.print_error(f"Workflow not found: {workflow_id}")
                raise typer.Exit(code=1)

            formatter.print_info(f"⏯  Resuming workflow: {workflow_id}")

            # For now, print message about resumption
            # Full implementation would reconstruct workflow and call next_step
            formatter.print_warning("Resume functionality requires full workflow reconstruction")
            formatter.print_info("This feature will be fully implemented in the next iteration")

            formatter.print(f"\nWorkflow: {workflow_data.get('id')}")
            formatter.print(f"Status: {workflow_data.get('status')}")
            formatter.print(f"Current Step: {workflow_data.get('current_step_name', 'N/A')}")

        except Exception as e:
            formatter.print_error(f"Failed to resume workflow: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_resume())


@app.command("retry")
def retry_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID to retry"),
    from_step: Optional[str] = typer.Option(None, "--from-step", help="Step name to retry from"),
    auto_execute: bool = typer.Option(False, "--auto", help="Auto-execute remaining steps"),
):
    """Retry a failed workflow"""
    async def _retry():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()

        try:
            # Load workflow
            workflow_data = await persistence.load_workflow(workflow_id)
            if not workflow_data:
                formatter.print_error(f"Workflow not found: {workflow_id}")
                raise typer.Exit(code=1)

            formatter.print_info(f"🔄 Retrying workflow: {workflow_id}")

            # For now, print message about retry
            # Full implementation would modify workflow state and resume
            formatter.print_warning("Retry functionality requires workflow state modification")
            formatter.print_info("This feature will be fully implemented in the next iteration")

            formatter.print(f"\nWorkflow: {workflow_data.get('id')}")
            formatter.print(f"Previous Status: {workflow_data.get('status')}")
            if from_step:
                formatter.print(f"Retry from step: {from_step}")

        except Exception as e:
            formatter.print_error(f"Failed to retry workflow: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_retry())
