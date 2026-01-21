# Assuming this is the chosen Jinja2 implementation
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.engine import WorkflowEngine
from rufus.builder import WorkflowBuilder
import json
import typer
from typing import Optional
from pathlib import Path
import yaml
import sys
import os

# Ensure rufus package is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


app = typer.Typer()

# --- Helper to get common providers ---


def get_default_providers():
    persistence = InMemoryPersistence()
    executor = SyncExecutor()
    observer = LoggingObserver()
    builder = WorkflowBuilder(
        registry_path="config/workflow_registry.yaml")  # Placeholder path
    expression_evaluator = SimpleExpressionEvaluator
    template_engine = Jinja2TemplateEngine
    return persistence, executor, observer, builder, expression_evaluator, template_engine


@app.command()
def validate(workflow_file: Path = typer.Argument(..., help="Path to the workflow YAML file.")):
    """
    Validates a Rufus workflow YAML file for syntax and basic structure.
    """
    if not workflow_file.is_file():
        typer.echo(
            f"Error: Workflow file not found at {workflow_file}", err=True)
        raise typer.Exit(code=1)

    try:
        with open(workflow_file, "r") as f:
            workflow_config = yaml.safe_load(f)

        # Basic YAML syntax check
        if not isinstance(workflow_config, dict):
            typer.echo(
                f"Error: Invalid YAML format in {workflow_file}. Expected a dictionary.", err=True)
            raise typer.Exit(code=1)

        # Further validation could involve trying to build steps with a mock builder
        # For a full validation, you'd need a registry and proper function resolution.
        # This is a basic check.
        if "workflow_type" not in workflow_config:
            typer.echo(
                f"Error: 'workflow_type' missing in {workflow_file}", err=True)
            raise typer.Exit(code=1)
        if "steps" not in workflow_config or not isinstance(workflow_config["steps"], list):
            typer.echo(
                f"Error: 'steps' section missing or not a list in {workflow_file}", err=True)
            raise typer.Exit(code=1)

        # A more advanced validation would involve constructing a dummy workflow builder
        # and trying to build steps to resolve func_paths, etc.
        # For now, we rely on basic YAML structure and required keys.

        typer.echo(
            f"Successfully validated {workflow_file} (basic checks passed).")
    except yaml.YAMLError as e:
        typer.echo(
            f"Error: Invalid YAML syntax in {workflow_file}: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(
            f"An unexpected error occurred during validation: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def run(
    workflow_file: Path = typer.Argument(...,
                                         help="Path to the workflow YAML file."),
    initial_data: Optional[str] = typer.Option(
        "{}", "--data", "-d", help="Initial workflow data as a JSON string."),
    registry_path: Optional[Path] = typer.Option(
        "config/workflow_registry.yaml", "--registry", "-r", help="Path to the workflow registry YAML file.")
):
    """
    Runs a Rufus workflow locally using in-memory persistence and synchronous execution.
    """
    if not workflow_file.is_file():
        typer.echo(
            f"Error: Workflow file not found at {workflow_file}", err=True)
        raise typer.Exit(code=1)

    try:
        data = json.loads(initial_data)
    except json.JSONDecodeError as e:
        typer.echo(f"Error: Invalid JSON for initial data: {e}", err=True)
        raise typer.Exit(code=1)

    try:
        # Temporarily create a dummy registry file for single-file run
        # This is a simplification for CLI run for a single workflow file
        # A real registry is assumed for multi-workflow scenarios.
        temp_registry_dir = Path("temp_rufus_cli_config")
        temp_registry_dir.mkdir(exist_ok=True)
        temp_workflow_config_path = temp_registry_dir / workflow_file.name

        # Copy the workflow file to the temp config dir
        import shutil
        shutil.copy(workflow_file, temp_workflow_config_path)

        temp_registry_content = {
            "workflows": [
                {
                    "type": "CliRunWorkflow",  # Use a generic type for direct run
                    "description": f"Temporary workflow for CLI run of {workflow_file.name}",
                    "config_file": workflow_file.name,
                    "initial_state_model": "pydantic.BaseModel"  # Use generic BaseModel
                }
            ]
        }
        temp_registry_path = temp_registry_dir / "cli_registry.yaml"
        with open(temp_registry_path, "w") as f:
            yaml.dump(temp_registry_content, f)

        # Instantiate providers and builder
        persistence, executor, observer, builder, expression_evaluator_cls, template_engine_cls = get_default_providers()

        # Override builder registry path for this run
        builder.registry_path = str(temp_registry_path)
        builder._load_registry()  # Reload registry with temp content

        typer.echo(
            f"Running workflow from {workflow_file} with initial data: {data}")

        # Create workflow
        workflow = builder.create_workflow(
            workflow_type="CliRunWorkflow",  # Use the temporary type
            initial_data=data,
            persistence_provider=persistence,
            execution_provider=executor,
            workflow_builder=builder,
            expression_evaluator_cls=expression_evaluator_cls,
            template_engine_cls=template_engine_cls,
            workflow_observer=observer
        )

        typer.echo(f"Workflow ID: {workflow.id}")
        typer.echo(f"Initial Status: {workflow.status}")
        typer.echo(f"Initial State: {workflow.state.model_dump()}")

        while workflow.status not in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
            typer.echo(
                f"\n--- Current Step: {workflow.current_step_name} ({workflow.status}) ---")
            typer.echo(f"Current State: {workflow.state.model_dump()}")

            # For CLI run, we assume no human input for now, just auto-advance
            # In real scenario, input would be prompted or provided.
            result, next_step_name = workflow.next_step(user_input={})

            typer.echo(f"Step Result: {result}")
            # Save state after each step
            persistence.save_workflow(workflow.id, workflow.to_dict())

        typer.echo(f"\n--- Workflow Finished ({workflow.status}) ---")
        typer.echo(f"Final State: {workflow.state.model_dump()}")

        if workflow.status == "COMPLETED":
            typer.echo(
                f"Successfully completed workflow {workflow.id}", color=typer.colors.GREEN)
        else:
            typer.echo(
                f"Workflow {workflow.id} finished with status {workflow.status}", color=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

    except Exception as e:
        typer.echo(
            f"An error occurred during workflow execution: {e}", err=True)
        import traceback
        traceback.print_exc()
        raise typer.Exit(code=1)
    finally:
        # Clean up temporary files
        import shutil
        if temp_registry_dir.exists():
            shutil.rmtree(temp_registry_dir)


if __name__ == "__main__":
    app()
