"""
Interactive workflow execution commands.

Provides interactive mode for running workflows with Human-in-the-Loop prompts.
"""

import typer
import asyncio
import json
import yaml
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel

from ruvon_cli.config import get_config
from ruvon_cli.providers import create_providers, close_providers
from ruvon_cli.formatters import Formatter
from ruvon_cli.input_collector import InputCollector
from ruvon.workflow import Workflow
from ruvon.builder import WorkflowBuilder
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


app = typer.Typer(name="interactive", help="Interactive workflow execution")


@app.command("run")
def run_interactive(
    workflow_type: str = typer.Argument(..., help="Workflow type to run"),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="Initial workflow data as JSON string"),
    data_file: Optional[Path] = typer.Option(None, "--data-file", help="Initial workflow data from JSON file"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="Workflow YAML config file"),
):
    """
    Run workflow interactively, prompting for input at each HITL step.

    This command starts a workflow and automatically executes steps, pausing
    to collect user input whenever the workflow enters a WAITING_HUMAN state.

    Example:
        ruvon interactive run OrderProcessing --config workflows/order.yaml
        ruvon interactive run Approval --data '{"request_id": "123"}'
    """
    async def _run_interactive():
        config = get_config()
        persistence, execution, observer = await create_providers(config)
        formatter = Formatter()
        console = Console()
        input_collector = InputCollector(console=console)

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
                formatter.print_error(f"Workflow config file required. Use --config <file.yaml>")
                formatter.print_info(f"Example: ruvon interactive run {workflow_type} --config workflows/{workflow_type}.yaml")
                raise typer.Exit(code=1)

            # Display startup info
            console.print(Panel(
                f"[bold]Workflow Type:[/bold] {workflow_type}\n"
                f"[bold]Mode:[/bold] Interactive\n"
                f"[bold]Initial Data:[/bold] {json.dumps(initial_data, indent=2) if initial_data else 'None'}",
                title="[bold cyan]Starting Interactive Workflow[/bold cyan]",
                border_style="cyan"
            ))

            # Create builder and workflow
            builder = WorkflowBuilder(
                workflow_registry=workflow_registry,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
            )

            # Start workflow
            formatter.print_info(f"\n🚀 Starting workflow: {workflow_type}")
            workflow = await builder.create_workflow(
                workflow_type=workflow_type,
                persistence_provider=persistence,
                execution_provider=execution,
                workflow_builder=builder,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
                workflow_observer=observer,
                initial_data=initial_data,
            )
            await persistence.save_workflow(workflow.id, workflow.to_dict())
            await observer.on_workflow_started(workflow.id, workflow.workflow_type, workflow.state)
            if workflow.automate_start:
                await workflow.next_step(user_input={})

            formatter.print_success(f"Workflow started successfully")
            formatter.print(f"Workflow ID: [bold cyan]{workflow.id}[/bold cyan]")
            formatter.print(f"Status: [bold yellow]{workflow.status}[/bold yellow]\n")

            # Interactive execution loop
            await _interactive_execution_loop(
                workflow=workflow,
                persistence=persistence,
                execution=execution,
                observer=observer,
                formatter=formatter,
                console=console,
                input_collector=input_collector
            )

        except KeyboardInterrupt:
            formatter.print_warning("\n\nInteractive execution cancelled by user")
        except Exception as e:
            formatter.print_error(f"Interactive execution failed: {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(code=1)
        finally:
            await close_providers(persistence, execution, observer)

    asyncio.run(_run_interactive())


async def _interactive_execution_loop(
    workflow: Workflow,
    persistence,
    execution,
    observer,
    formatter: Formatter,
    console: Console,
    input_collector: InputCollector
):
    """
    Execute workflow interactively, prompting for input at HITL steps.

    Args:
        workflow: Workflow instance to execute
        persistence: Persistence provider
        execution: Execution provider
        observer: Workflow observer
        formatter: Output formatter
        console: Rich Console
        input_collector: Input collector for HITL prompts
    """
    total_steps = len(workflow.workflow_steps)
    steps_executed = 0
    max_iterations = total_steps * 3  # Safety limit

    formatter.print_info("🎯 Entering interactive execution mode")
    formatter.print(f"Total steps: {total_steps}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:

        task = progress.add_task(
            "Executing workflow steps",
            total=total_steps
        )

        iteration = 0
        user_input = {}

        while iteration < max_iterations:
            iteration += 1

            # Check workflow status
            if workflow.status == 'COMPLETED':
                progress.update(task, completed=total_steps)
                console.print()
                formatter.print_success(f"✅ Workflow completed successfully!")
                formatter.print(f"Total steps executed: {steps_executed}")
                _display_final_state(workflow, formatter, console)
                break

            if workflow.status == 'FAILED':
                console.print()
                formatter.print_error(f"❌ Workflow failed")
                formatter.print(f"Failed at step: {workflow.current_step_name}")
                break

            if workflow.status == 'CANCELLED':
                console.print()
                formatter.print_warning(f"🛑 Workflow was cancelled")
                break

            if workflow.status == 'WAITING_HUMAN':
                # Pause progress and collect input
                progress.stop()

                console.print()
                console.print(Panel(
                    f"[bold]Step:[/bold] {workflow.current_step_name}\n"
                    f"[bold]Status:[/bold] Waiting for human input\n"
                    f"[bold]Current Step:[/bold] {workflow.current_step}/{total_steps}",
                    title="[bold yellow]⏸  Human Input Required[/bold yellow]",
                    border_style="yellow"
                ))

                # Get step config to check for input schema
                current_step_config = workflow.workflow_steps[workflow.current_step]
                input_schema = getattr(current_step_config, 'input_schema_def', None)

                if input_schema:
                    # Collect based on schema
                    try:
                        user_input = input_collector.collect_from_schema(
                            schema=input_schema,
                            step_name=workflow.current_step_name
                        )
                    except KeyboardInterrupt:
                        formatter.print_warning("\nInput cancelled - workflow paused")
                        break
                else:
                    # Free-form input
                    try:
                        user_input = input_collector.collect_free_form(
                            prompt_text=f"Input for {workflow.current_step_name}"
                        )
                    except KeyboardInterrupt:
                        formatter.print_warning("\nInput cancelled - workflow paused")
                        break

                console.print()
                formatter.print_success("✓ Input collected")
                console.print()

                # Resume progress
                progress.start()

            elif workflow.status not in ['ACTIVE', 'RUNNING']:
                console.print()
                formatter.print_warning(f"Workflow entered unexpected state: {workflow.status}")
                break

            # Check if we've reached the end
            if workflow.current_step >= total_steps:
                console.print()
                formatter.print_info(f"Reached end of workflow steps")
                break

            # Update progress description
            step_name = workflow.current_step_name or f"step_{workflow.current_step}"
            progress.update(
                task,
                description=f"Executing: {step_name}",
                completed=steps_executed
            )

            # Execute next step
            try:
                result, error = await workflow.next_step(user_input=user_input)

                steps_executed += 1

                if error:
                    progress.stop()
                    console.print()
                    formatter.print_error(f"Step failed: {step_name}")
                    formatter.print(f"Error: {error}")
                    break

                # Clear user input for next iteration
                user_input = {}

                # Brief pause for visibility
                await asyncio.sleep(0.1)

            except Exception as step_error:
                progress.stop()
                console.print()
                formatter.print_error(f"Exception during step execution: {step_name}")
                formatter.print(f"Error: {str(step_error)}")
                break

        if iteration >= max_iterations:
            console.print()
            formatter.print_error(f"⚠️  Safety limit reached ({max_iterations} iterations)")
            formatter.print_info("Workflow may have entered an infinite loop")

    # Show final status
    console.print()
    console.print("=" * 60)
    formatter.print(f"Final Status: [bold]{workflow.status}[/bold]")
    formatter.print(f"Steps Executed: {steps_executed}/{total_steps}")
    formatter.print(f"Workflow ID: {workflow.id}")


def _display_final_state(workflow: Workflow, formatter: Formatter, console: Console):
    """Display final workflow state."""
    console.print()
    console.print(Panel(
        f"[bold]Workflow ID:[/bold] {workflow.id}\n"
        f"[bold]Type:[/bold] {workflow.workflow_type}\n"
        f"[bold]Status:[/bold] {workflow.status}\n"
        f"[bold]Steps Completed:[/bold] {workflow.current_step}/{len(workflow.workflow_steps)}\n\n"
        f"[bold]Final State:[/bold]\n{json.dumps(workflow.state.model_dump(), indent=2)}",
        title="[bold green]✅ Workflow Complete[/bold green]",
        border_style="green"
    ))
