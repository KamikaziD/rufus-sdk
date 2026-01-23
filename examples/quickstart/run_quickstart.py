"""
Rufus Quickstart Example - Run Script

This script demonstrates how to use the Rufus SDK to:
1. Initialize a WorkflowEngine with providers
2. Start a workflow with initial data
3. Execute workflow steps
4. Access the final state

Usage:
    python run_quickstart.py
"""

import asyncio
import sys
from pathlib import Path

# Add current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
import yaml


async def main():
    """Main function to run the greeting workflow."""

    print("=" * 60)
    print("Rufus SDK Quickstart Example")
    print("=" * 60)
    print()

    # ===================================================================
    # STEP 1: Load Workflow Registry
    # ===================================================================
    print("Step 1: Loading workflow registry...")
    registry_path = Path(__file__).parent / "workflow_registry.yaml"
    with open(registry_path) as f:
        registry_config = yaml.safe_load(f)

    # Create workflow registry dict
    workflow_registry = {}
    for workflow in registry_config["workflows"]:
        workflow_file = Path(__file__).parent / workflow["config_file"]
        with open(workflow_file) as f:
            workflow_config = yaml.safe_load(f)
        workflow_registry[workflow["type"]] = {
            "initial_state_model_path": workflow["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version", "1.0"),
            "description": workflow_config.get("description", ""),
        }
    print(f"✓ Loaded {len(workflow_registry)} workflow(s)")
    print()

    # ===================================================================
    # STEP 2: Initialize WorkflowEngine with Providers
    # ===================================================================
    print("Step 2: Initializing WorkflowEngine...")
    print("  - Persistence: InMemoryPersistence (no database required)")
    print("  - Executor: SyncExecutor (synchronous, single-process)")
    print("  - Observer: LoggingObserver (console logging)")
    print()

    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()
    print("✓ Engine initialized")
    print()

    # ===================================================================
    # STEP 3: Start Workflow
    # ===================================================================
    print("Step 3: Starting GreetingWorkflow...")
    initial_data = {"name": "World"}
    print(f"  Initial data: {initial_data}")
    print()

    workflow = await engine.start_workflow(
        workflow_type="GreetingWorkflow", initial_data=initial_data
    )

    print(f"✓ Workflow started")
    print(f"  Workflow ID: {workflow.id}")
    print(f"  Status: {workflow.status}")
    print(f"  Current Step: {workflow.current_step + 1}/{len(workflow.workflow_steps)}")
    print(f"  State: {workflow.state}")
    print()

    # ===================================================================
    # STEP 4: Execute Workflow Steps
    # ===================================================================
    print("Step 4: Executing workflow steps...")
    print()

    step_count = 0
    while workflow.status == "ACTIVE":
        step_count += 1
        current_step = workflow.workflow_steps[workflow.current_step]

        print(f"--- Step {step_count}: {current_step.name} ---")
        result = await workflow.next_step(user_input={})

        print(f"✓ Step completed")
        print(f"  Result: {result}")
        print(f"  Status: {workflow.status}")
        print(f"  State: {workflow.state}")
        print()

    # ===================================================================
    # STEP 5: Display Final Results
    # ===================================================================
    print("=" * 60)
    print("Workflow Complete!")
    print("=" * 60)
    print(f"Final Status: {workflow.status}")
    print(f"Final Output: {workflow.state.formatted_output}")
    print()
    print("✅ Quickstart example completed successfully!")
    print()
    print("Next Steps:")
    print("  - Try changing the 'name' in initial_data")
    print("  - Explore the loan application example for advanced features")
    print("  - Read the full documentation at docs/QUICKSTART.md")
    print()


if __name__ == "__main__":
    asyncio.run(main())
