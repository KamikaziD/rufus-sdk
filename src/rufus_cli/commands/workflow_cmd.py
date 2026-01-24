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


@app.command("logs")
def view_logs(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
    step: Optional[str] = typer.Option(None, "--step", help="Filter by step name"),
    level: Optional[str] = typer.Option(None, "--level", help="Filter by log level (INFO, WARNING, ERROR)"),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of logs to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs in real-time"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """View workflow execution logs"""
    async def _view_logs():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()

        try:
            # Verify workflow exists
            workflow_data = await persistence.load_workflow(workflow_id)
            if not workflow_data:
                formatter.print_error(f"Workflow not found: {workflow_id}")
                raise typer.Exit(code=1)

            # Build filters
            filters = {
                "workflow_id": workflow_id,
                "limit": limit
            }
            if step:
                filters["step_name"] = step
            if level:
                filters["log_level"] = level.upper()

            # Get logs from persistence
            logs = await persistence.get_workflow_logs(**filters)

            if not logs:
                formatter.print_info("No logs found for this workflow")
                return

            # Display logs
            if json_output:
                print(json.dumps(logs, indent=2, default=str))
            else:
                from rich.table import Table
                from rich import box
                from rich.console import Console

                table = Table(title=f"Workflow Logs: {workflow_id}", box=box.ROUNDED)
                table.add_column("Time", style="cyan", no_wrap=True)
                table.add_column("Level", style="yellow", width=8)
                table.add_column("Step", style="magenta")
                table.add_column("Message", style="white")

                for log in logs:
                    # Format timestamp
                    logged_at = log.get("logged_at", "")
                    if logged_at:
                        from datetime import datetime
                        try:
                            dt = datetime.fromisoformat(logged_at.replace('Z', '+00:00'))
                            logged_at = dt.strftime("%H:%M:%S")
                        except:
                            pass

                    # Color code log level
                    log_level = log.get("log_level", "INFO")
                    level_style = {
                        "ERROR": "bold red",
                        "WARNING": "bold yellow",
                        "INFO": "bold green",
                        "DEBUG": "dim"
                    }.get(log_level, "white")

                    table.add_row(
                        logged_at,
                        f"[{level_style}]{log_level}[/{level_style}]",
                        log.get("step_name", ""),
                        log.get("message", "")
                    )

                console = Console()
                console.print(table)

                formatter.print(f"\nShowing {len(logs)} log entries")
                if len(logs) == limit:
                    formatter.print_info(f"Use --limit to show more logs")

        except Exception as e:
            formatter.print_error(f"Failed to view logs: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_view_logs())


@app.command("metrics")
def view_metrics(
    workflow_id: Optional[str] = typer.Option(None, "--workflow-id", "-w", help="Workflow ID (optional for summary)"),
    workflow_type: Optional[str] = typer.Option(None, "--type", help="Filter by workflow type"),
    summary: bool = typer.Option(False, "--summary", help="Show aggregated summary"),
    limit: int = typer.Option(50, "--limit", help="Number of metrics to show"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """View workflow performance metrics"""
    async def _view_metrics():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()

        try:
            # Build filters
            filters = {"limit": limit}
            if workflow_id:
                # Verify workflow exists
                workflow_data = await persistence.load_workflow(workflow_id)
                if not workflow_data:
                    formatter.print_error(f"Workflow not found: {workflow_id}")
                    raise typer.Exit(code=1)
                filters["workflow_id"] = workflow_id
            if workflow_type:
                filters["workflow_type"] = workflow_type

            # Get metrics from persistence
            metrics = await persistence.get_workflow_metrics(**filters)

            if not metrics:
                formatter.print_info("No metrics found")
                return

            # Display metrics
            if json_output:
                print(json.dumps(metrics, indent=2, default=str))
            else:
                from rich.table import Table
                from rich import box
                from rich.console import Console

                title = "Workflow Metrics"
                if workflow_id:
                    title += f": {workflow_id}"
                elif workflow_type:
                    title += f" ({workflow_type})"

                table = Table(title=title, box=box.ROUNDED)
                table.add_column("Time", style="cyan", no_wrap=True)
                table.add_column("Workflow", style="magenta")
                table.add_column("Step", style="yellow")
                table.add_column("Metric", style="green")
                table.add_column("Value", style="bold white", justify="right")
                table.add_column("Unit", style="dim")

                for metric in metrics:
                    # Format timestamp
                    recorded_at = metric.get("recorded_at", "")
                    if recorded_at:
                        from datetime import datetime
                        try:
                            dt = datetime.fromisoformat(recorded_at.replace('Z', '+00:00'))
                            recorded_at = dt.strftime("%H:%M:%S")
                        except:
                            pass

                    # Format value
                    value = metric.get("metric_value", 0)
                    if isinstance(value, float):
                        value_str = f"{value:.2f}"
                    else:
                        value_str = str(value)

                    # Truncate workflow ID for display
                    wf_id = metric.get("workflow_id", "")
                    if len(wf_id) > 12:
                        wf_id = wf_id[:12] + "..."

                    table.add_row(
                        recorded_at,
                        wf_id,
                        metric.get("step_name", ""),
                        metric.get("metric_name", ""),
                        value_str,
                        metric.get("unit", "")
                    )

                console = Console()
                console.print(table)

                formatter.print(f"\nShowing {len(metrics)} metrics")
                if summary and len(metrics) > 0:
                    # Calculate summary stats
                    total_metrics = len(metrics)
                    unique_steps = len(set(m.get("step_name", "") for m in metrics if m.get("step_name")))
                    formatter.print(f"\nSummary:")
                    formatter.print(f"  Total metrics: {total_metrics}")
                    formatter.print(f"  Unique steps: {unique_steps}")

        except Exception as e:
            formatter.print_error(f"Failed to view metrics: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_view_metrics())


@app.command("cancel")
def cancel_workflow(
    workflow_id: str = typer.Argument(..., help="Workflow ID to cancel"),
    force: bool = typer.Option(False, "--force", help="Skip compensation/rollback"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Cancellation reason"),
):
    """Cancel a running workflow"""
    async def _cancel():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()

        try:
            # Load workflow
            workflow_data = await persistence.load_workflow(workflow_id)
            if not workflow_data:
                formatter.print_error(f"Workflow not found: {workflow_id}")
                raise typer.Exit(code=1)

            current_status = workflow_data.get("status")

            # Check if workflow can be cancelled
            terminal_states = ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK", "CANCELLED"]
            if current_status in terminal_states:
                formatter.print_warning(f"Workflow is already in terminal state: {current_status}")
                return

            # Confirm cancellation
            if not force:
                from rich.prompt import Confirm
                confirmed = Confirm.ask(
                    f"\n[bold yellow]Cancel workflow {workflow_id}?[/bold yellow]\n"
                    f"Current status: {current_status}\n"
                    f"This action may trigger compensation if saga mode is enabled.",
                    default=False
                )
                if not confirmed:
                    formatter.print_info("Cancellation aborted")
                    return

            formatter.print_info(f"🛑 Cancelling workflow: {workflow_id}")

            # Update workflow status to CANCELLED
            workflow_data["status"] = "CANCELLED"
            if reason:
                if "metadata" not in workflow_data:
                    workflow_data["metadata"] = {}
                workflow_data["metadata"]["cancellation_reason"] = reason

            # Save updated workflow
            await persistence.save_workflow(workflow_id, workflow_data)

            # Log cancellation
            await persistence.log_workflow_execution(
                workflow_id=workflow_id,
                step_name=workflow_data.get("current_step_name"),
                log_level="WARNING",
                message=f"Workflow cancelled" + (f": {reason}" if reason else ""),
                metadata={"force": force}
            )

            formatter.print_success(f"Workflow cancelled successfully")
            formatter.print(f"Previous status: {current_status}")
            formatter.print(f"New status: CANCELLED")

            if force:
                formatter.print_warning("Compensation/rollback skipped (--force)")
            elif workflow_data.get("saga_mode"):
                formatter.print_info("Saga mode detected - compensation may be triggered")

        except Exception as e:
            formatter.print_error(f"Failed to cancel workflow: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_cancel())
