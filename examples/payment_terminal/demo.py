#!/usr/bin/env python3
"""
Payment Terminal Demo - Ruvon Edge SDK

Demonstrates payment processing with online/offline support.

Usage:
    python examples/payment_terminal/demo.py

This demo shows:
1. Online payment authorization
2. Offline payment with floor limit check
3. Declined payment (over floor limit while offline)
"""

import asyncio
import sys
import os
import uuid
from decimal import Decimal

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.memory import InMemoryPersistence
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.observability.logging import LoggingObserver
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine

from ruvon_edge.models import PaymentState


async def run_payment_demo():
    """Run the payment terminal demo."""
    print("\n" + "=" * 60)
    print("  RUVON EDGE - Payment Terminal Demo")
    print("=" * 60 + "\n")

    # Initialize persistence (in-memory for demo)
    persistence = InMemoryPersistence()
    await persistence.initialize()

    # Initialize executor
    executor = SyncExecutor()

    # Initialize observer
    observer = LoggingObserver()

    # Load workflow registry with inline config
    import yaml
    config_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'config')
    registry_path = os.path.join(config_dir, 'workflow_registry.yaml')
    workflow_path = os.path.join(config_dir, 'payment_workflow.yaml')

    # Load workflow definition
    with open(workflow_path, 'r') as f:
        workflow_config = yaml.safe_load(f)

    # Build registry with full workflow config embedded
    workflow_registry = {
        "PaymentAuthorization": {
            "type": "PaymentAuthorization",
            "initial_state_model_path": "ruvon_edge.models.PaymentState",
            "steps": workflow_config.get("steps", []),
        }
    }

    # Create workflow builder (new API)
    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 1: Online Payment (Approved)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 60)
    print("Demo 1: ONLINE Payment - $15.00")
    print("-" * 60)

    workflow1 = await builder.create_workflow(
        workflow_type="PaymentAuthorization",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        initial_data={
            "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
            "idempotency_key": f"demo1_{uuid.uuid4().hex}",
            "amount": Decimal("15.00"),
            "card_token": "tok_visa_4242",
            "card_last_four": "4242",
            "card_type": "visa",
            "merchant_id": "merchant_001",
            "terminal_id": "pos_demo_001",
            "is_online": True,  # Simulate online
        }
    )

    # Execute workflow
    while workflow1.status == "ACTIVE":
        result, next_step = await workflow1.next_step({})
        print(f"  Step completed: {workflow1.current_step_name} -> {next_step or 'done'}")

    print(f"\n  Result: {workflow1.status}")
    print(f"  Auth Code: {workflow1.state.authorization_code}")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 2: Offline Payment Under Floor Limit (Approved)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 60)
    print("Demo 2: OFFLINE Payment - $20.00 (under $25 floor limit)")
    print("-" * 60)

    workflow2 = await builder.create_workflow(
        workflow_type="PaymentAuthorization",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        initial_data={
            "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
            "idempotency_key": f"demo2_{uuid.uuid4().hex}",
            "amount": Decimal("20.00"),
            "card_token": "tok_mastercard_5555",
            "card_last_four": "5555",
            "card_type": "mastercard",
            "merchant_id": "merchant_001",
            "terminal_id": "pos_demo_001",
            "is_online": False,  # Simulate offline
        }
    )

    while workflow2.status == "ACTIVE":
        result, next_step = await workflow2.next_step({})
        print(f"  Step completed: {workflow2.current_step_name} -> {next_step or 'done'}")

    print(f"\n  Result: {workflow2.status}")
    print(f"  Auth Code: {workflow2.state.authorization_code}")
    print(f"  Requires Sync: {workflow2.state.stored_for_sync}")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 3: Offline Payment Over Floor Limit (Declined)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 60)
    print("Demo 3: OFFLINE Payment - $50.00 (over $25 floor limit)")
    print("-" * 60)

    workflow3 = await builder.create_workflow(
        workflow_type="PaymentAuthorization",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        initial_data={
            "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
            "idempotency_key": f"demo3_{uuid.uuid4().hex}",
            "amount": Decimal("50.00"),
            "card_token": "tok_amex_3782",
            "card_last_four": "3782",
            "card_type": "amex",
            "merchant_id": "merchant_001",
            "terminal_id": "pos_demo_001",
            "is_online": False,  # Simulate offline
        }
    )

    while workflow3.status == "ACTIVE":
        result, next_step = await workflow3.next_step({})
        print(f"  Step completed: {workflow3.current_step_name} -> {next_step or 'done'}")

    print(f"\n  Result: {workflow3.status}")
    print(f"  Decline Reason: {workflow3.state.decline_reason}")

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  DEMO COMPLETE")
    print("=" * 60)
    print("""
Summary:
  - Online payments go directly to gateway
  - Offline payments check floor limit
  - Under limit: Approved offline (Store-and-Forward)
  - Over limit: Declined immediately

In production:
  - Offline transactions are encrypted and queued
  - SyncManager uploads when connectivity restored
  - Cloud control plane processes settlement
""")

    # Cleanup
    await persistence.close()


if __name__ == "__main__":
    asyncio.run(run_payment_demo())
