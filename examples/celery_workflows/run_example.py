#!/usr/bin/env python
"""
Main example runner for Celery workflows.

Usage:
    python run_example.py              # Run all examples
    python run_example.py order        # Run order processing only
    python run_example.py payment      # Run payment workflow only
    python run_example.py notification # Run notification workflow only
"""
import asyncio
import sys
import os
from pathlib import Path

# Add example directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from rufus.builder import WorkflowBuilder
from rufus.implementations.execution.celery import CeleryExecutionProvider
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.observability.logging import LoggingObserver


async def run_order_processing_example():
    """Run order processing workflow with async tasks and sub-workflow."""
    print("\n" + "="*70)
    print(" ORDER PROCESSING WORKFLOW")
    print("="*70)
    print("Demonstrates:")
    print("  - Async task execution (payment processing)")
    print("  - Sub-workflow orchestration (notifications)")
    print("  - Automatic workflow resumption")
    print("="*70 + "\n")

    # Initialize providers
    db_url = os.environ.get("DATABASE_URL", "postgresql://rufus:rufus_secret_2024@localhost:5432/rufus_example")
    execution = CeleryExecutionProvider()
    persistence = PostgresPersistenceProvider(db_url=db_url)
    await persistence.initialize()

    # Initialize execution provider with mock engine
    class MockEngine:
        class MockBuilder:
            @staticmethod
            def _import_from_string(path: str):
                import importlib
                module_path, func_name = path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                return getattr(module, func_name)
        workflow_builder = MockBuilder()

    await execution.initialize(MockEngine())

    # Create workflow builder
    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=execution,
        observer=LoggingObserver()
    )

    # Start workflow
    from models.state_models import OrderState

    workflow = await builder.create_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-12345",
            "customer_email": "customer@example.com",
            "customer_phone": "+1234567890",
            "amount": 99.99,
            "currency": "USD"
        }
    )

    print(f"✅ Workflow created: {workflow.id}")
    print(f"📊 Initial status: {workflow.status}")

    # Execute workflow
    print(f"\n⏩ Starting workflow execution...")
    result, next_step = await workflow.next_step()

    print(f"\n📊 Status after first step: {workflow.status}")
    print(f"📝 Current step: {workflow.current_step_name}")

    if workflow.status == "PENDING_ASYNC":
        print(f"\n⏸️  Workflow paused - waiting for Celery worker to process async task")
        print(f"💡 The workflow will automatically resume when the task completes")
        print(f"💡 Worker will execute: {next_step}")

    # Save workflow
    await persistence.save_workflow(workflow.id, workflow.to_dict())
    await persistence.close()

    print(f"\n✅ Example complete - workflow ID: {workflow.id}")
    print(f"📋 To check workflow status:")
    print(f"   rufus show {workflow.id}")


async def run_payment_example():
    """Run payment workflow with parallel validation checks."""
    print("\n" + "="*70)
    print(" PAYMENT PROCESSING WORKFLOW")
    print("="*70)
    print("Demonstrates:")
    print("  - Parallel task execution (credit/fraud/limit checks)")
    print("  - Result merging from parallel tasks")
    print("  - Decision logic based on merged results")
    print("="*70 + "\n")

    # Initialize providers
    db_url = os.environ.get("DATABASE_URL", "postgresql://rufus:rufus_secret_2024@localhost:5432/rufus_example")
    execution = CeleryExecutionProvider()
    persistence = PostgresPersistenceProvider(db_url=db_url)
    await persistence.initialize()

    # Initialize execution provider
    class MockEngine:
        class MockBuilder:
            @staticmethod
            def _import_from_string(path: str):
                import importlib
                module_path, func_name = path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                return getattr(module, func_name)
        workflow_builder = MockBuilder()

    await execution.initialize(MockEngine())

    # Create workflow builder
    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=execution,
        observer=LoggingObserver()
    )

    # Start workflow
    workflow = await builder.create_workflow(
        workflow_type="PaymentProcessing",
        initial_data={
            "payment_id": "PAY-67890",
            "card_number": "4532015112830366",
            "cvv": "123",
            "amount": 149.99,
            "currency": "USD"
        }
    )

    print(f"✅ Workflow created: {workflow.id}")
    print(f"📊 Initial status: {workflow.status}")

    # Execute workflow
    print(f"\n⏩ Starting workflow execution...")
    result, next_step = await workflow.next_step()

    print(f"\n📊 Status: {workflow.status}")
    print(f"📝 Current step: {workflow.current_step_name}")

    if workflow.status == "PENDING_ASYNC":
        print(f"\n⏸️  Workflow paused - waiting for parallel checks to complete")
        print(f"💡 Running 3 tasks in parallel: credit, fraud, limit checks")
        print(f"💡 Workflow will resume when all tasks complete")

    # Save workflow
    await persistence.save_workflow(workflow.id, workflow.to_dict())
    await persistence.close()

    print(f"\n✅ Example complete - workflow ID: {workflow.id}")


async def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        example_type = sys.argv[1].lower()
    else:
        example_type = "all"

    try:
        if example_type in ("order", "all"):
            await run_order_processing_example()
            await asyncio.sleep(2)  # Brief pause between examples

        if example_type in ("payment", "all"):
            await run_payment_example()

        if example_type == "notification":
            print("\n⚠️  Notification workflow is a sub-workflow")
            print("💡 Run 'python run_example.py order' to see it in action")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
