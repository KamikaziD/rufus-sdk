import json
import pprint
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.engine import WorkflowEngine
import asyncio
import sys
from pathlib import Path
import yaml

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))


async def main():
    """
    Docstring for main
    """
    # Load workflow registry
    with open("workflow_registry.yaml") as f:
        registry_config = yaml.safe_load(f)

    # Build registry dict
    workflow_registry = {}
    for workflow in registry_config["workflows"]:
        with open(workflow["config_file"]) as f:
            workflow_config = yaml.safe_load(f)
        workflow_registry[workflow["type"]] = {
            "initial_state_model_path": workflow["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version", "1.0"),
        }

    # Initialize engine with providers
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()

    # Start workflow with initial data
    initial_data = {"name": "Detmar"}
    workflow = await engine.start_workflow(
        workflow_type="MyWorkflow",
        initial_data=initial_data
    )

    print(f"✓ Workflow started: {workflow.id}")
    print(f"  Status: {workflow.status}\n")
    print(f"\n\n  Initial state: {workflow.state}\n")

    # Execute steps
    while workflow.status == "ACTIVE":
        result = await workflow.next_step(user_input={})
        print(f"  Step completed: {result}\n")

    # Display results
    print("✓ Workflow completed!", workflow.status)
    print(f"  Final output: {workflow.state.formatted_output}\n\n")

    print("Final output: \n\n")

    pprint.pprint(workflow.state.model_dump())
    print("\n\n")


if __name__ == "__main__":
    asyncio.run(main())
