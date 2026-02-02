#!/usr/bin/env python3
"""
Quick script to run the GreetingWorkflow example end-to-end
"""
import asyncio
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
import yaml


async def main():
    # Load workflow config
    with open("examples/quickstart/greeting_workflow.yaml") as f:
        workflow_config = yaml.safe_load(f)

    # Create workflow registry
    workflow_registry = {
        "GreetingWorkflow": {
            "initial_state_model_path": workflow_config["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version"),
            "parameters": workflow_config.get("parameters", {}),
            "env": workflow_config.get("env", {})
        }
    }

    # Create providers
    persistence = SQLitePersistenceProvider(db_path="./test.db", auto_init=True)
    await persistence.initialize()

    executor = SyncExecutor()
    observer = LoggingObserver()
    await observer.initialize()

    # Create engine
    engine = WorkflowEngine(
        persistence=persistence,
        executor=executor,
        observer=observer,
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )
    await engine.initialize()

    try:
        # Start workflow
        print("\n" + "="*70)
        print("🚀 Starting GreetingWorkflow...")
        print("="*70 + "\n")

        workflow = await engine.start_workflow(
            workflow_type="GreetingWorkflow",
            initial_data={"name": "Detmar"}
        )

        print(f"\n✅ Workflow created: {workflow.id}")
        print(f"   Status: {workflow.status}")
        print(f"   Current step: {workflow.current_step_name}\n")

        # Execute steps
        print("="*70)
        print("📝 Executing workflow steps...")
        print("="*70 + "\n")

        # Step 1: Generate_Greeting
        result1, next_step = await workflow.next_step(user_input={})
        await persistence.save_workflow(workflow.id, workflow.to_dict())
        print(f"✓ Step 1 completed: {workflow.current_step_name}")
        print(f"  Result: {result1}\n")

        # Step 2: Format_Output
        result2, next_step = await workflow.next_step(user_input={})
        await persistence.save_workflow(workflow.id, workflow.to_dict())
        print(f"✓ Step 2 completed: {workflow.current_step_name}")
        print(f"  Result: {result2}\n")

        # Show final result
        print("="*70)
        print("🎉 Workflow Complete!")
        print("="*70)
        print(f"\nFinal state:")
        print(f"  Name: {workflow.state.name}")
        print(f"  Greeting: {workflow.state.greeting}")
        print(f"  Formatted Output: {workflow.state.formatted_output}")
        print(f"\n{workflow.state.formatted_output}\n")
        print("="*70 + "\n")

    finally:
        await persistence.close()
        await observer.close()


if __name__ == "__main__":
    asyncio.run(main())
