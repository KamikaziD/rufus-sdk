#!/usr/bin/env python3
"""
Example runner for JavaScript steps workflow.

This demonstrates how to run a workflow that uses JavaScript/TypeScript steps
for data transformation and business logic.
"""

import asyncio
import sys
import os

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))

from state_models import OrderState, OrderItem


async def main():
    """Run the JavaScript steps example workflow."""

    # Check for py_mini_racer
    try:
        from rufus.javascript import is_mini_racer_available
        if not is_mini_racer_available():
            print("ERROR: py_mini_racer is not installed.")
            print("Install with: pip install py-mini-racer")
            return
    except ImportError as e:
        print(f"ERROR: Could not import rufus.javascript: {e}")
        print("Make sure rufus SDK is installed.")
        return

    # Import workflow components
    from rufus.builder import WorkflowBuilder
    from rufus.implementations.persistence.memory import InMemoryPersistenceProvider
    from rufus.implementations.execution.sync import SyncExecutionProvider
    from rufus.implementations.observability.logging import LoggingObserver
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.template_engine.jinja2 import Jinja2TemplateEngine

    print("=" * 60)
    print("JavaScript Steps Example - Order Processing Workflow")
    print("=" * 60)

    # Load workflow registry
    import yaml
    config_dir = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(config_dir, 'workflow_registry.yaml')) as f:
        registry_data = yaml.safe_load(f)

    # Build workflow registry dict
    workflow_registry = {}
    for wf in registry_data.get('workflows', []):
        wf_type = wf['type']
        with open(os.path.join(config_dir, wf['config_file'])) as f:
            wf_config = yaml.safe_load(f)
        workflow_registry[wf_type] = {
            **wf_config,
            'initial_state_model_path': wf['initial_state_model_path']
        }

    # Create providers
    persistence = InMemoryPersistenceProvider()
    execution = SyncExecutionProvider()
    observer = LoggingObserver()

    # Create workflow builder
    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    # Create sample order data
    initial_data = {
        "customer_id": "CUST-12345",
        "items": [
            {"product_id": "PROD-001", "name": "Wireless Headphones", "quantity": 2, "unit_price": 79.99, "category": "electronics"},
            {"product_id": "PROD-002", "name": "USB-C Cable", "quantity": 3, "unit_price": 12.99, "category": "electronics"},
            {"product_id": "PROD-003", "name": "Coffee Mug", "quantity": 1, "unit_price": 15.00, "category": "home"},
        ],
        "discount_code": "SAVE10",
        "shipping_method": "express"
    }

    print("\nInitial Order Data:")
    print(f"  Customer: {initial_data['customer_id']}")
    print(f"  Items: {len(initial_data['items'])}")
    print(f"  Discount Code: {initial_data['discount_code']}")
    print(f"  Shipping: {initial_data['shipping_method']}")

    # Create workflow
    print("\n" + "-" * 60)
    print("Creating workflow...")

    # Set config_dir for JavaScript executor to find scripts
    os.chdir(config_dir)

    workflow = await builder.create_workflow(
        workflow_type="OrderWithJavaScript",
        initial_data=initial_data,
        persistence_provider=persistence,
        execution_provider=execution,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer
    )

    print(f"Workflow created: {workflow.id}")

    # Execute workflow steps
    print("\n" + "-" * 60)
    print("Executing workflow steps...")
    print("-" * 60)

    while workflow.status == "ACTIVE":
        try:
            result, next_step = await workflow.next_step(user_input={})
            print(f"\nStep completed: {workflow.workflow_steps[workflow.current_step - 1].name if workflow.current_step > 0 else 'N/A'}")

            if result:
                # Print key results
                if 'pricing' in str(result):
                    print(f"  Pricing calculated")
                elif 'final_pricing' in str(result):
                    print(f"  Discounts applied")
                elif 'summary' in str(result):
                    print(f"  Summary generated")
                elif 'order_id' in str(result):
                    print(f"  Order ID: {result.get('order_id')}")

            if next_step:
                print(f"  Next step: {next_step}")

        except Exception as e:
            print(f"\nError during workflow execution: {e}")
            import traceback
            traceback.print_exc()
            break

    # Print final results
    print("\n" + "=" * 60)
    print("WORKFLOW COMPLETED")
    print("=" * 60)
    print(f"\nStatus: {workflow.status}")

    if workflow.state.summary:
        print("\nOrder Summary:")
        summary = workflow.state.summary
        print(f"  Order ID: {summary.get('order_id', 'N/A')}")
        print(f"  Items: {summary.get('items_count', 0)}")
        print(f"  Subtotal: ${summary.get('subtotal', 0):.2f}")
        print(f"  Discount: ${summary.get('discount_amount', 0):.2f}")
        print(f"  Total: ${summary.get('total', 0):.2f}")

    if workflow.state.final_pricing:
        fp = workflow.state.final_pricing
        print(f"\nDiscount Details:")
        print(f"  Code: {fp.get('discount_code', 'None')}")
        print(f"  Message: {fp.get('discount_message', 'N/A')}")

    print(f"\nFinal Order ID: {workflow.state.order_id}")
    print(f"Final Status: {workflow.state.status}")


if __name__ == "__main__":
    asyncio.run(main())
