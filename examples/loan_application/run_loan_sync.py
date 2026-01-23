#!/usr/bin/env python3
"""
Synchronous execution script for the Loan Application workflow.
Demonstrates complex workflow features:
- Parallel execution (credit check + fraud detection)
- Decision steps with conditional branching
- Sub-workflow execution (KYC verification)
- Dynamic step injection based on loan amount
- Human-in-the-loop review
- Saga compensation patterns
"""
from state_models import LoanApplicationState, UserProfileState
import yaml
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.engine import WorkflowEngine
import asyncio
import os
import sys
from pathlib import Path

# Add the example directory to Python path
example_dir = Path(__file__).parent
sys.path.insert(0, str(example_dir))


async def run_loan_workflow():
    """Run the loan application workflow with realistic test scenarios."""

    print("=" * 80)
    print("LOAN APPLICATION WORKFLOW - SYNCHRONOUS EXECUTION")
    print("=" * 80)
    print()

    # Step 1: Load the workflow registry
    registry_path = example_dir / "workflow_registry.yaml"
    with open(registry_path) as f:
        registry_config = yaml.safe_load(f)

    # Create workflow registry dict
    workflow_registry = {}
    for workflow in registry_config["workflows"]:
        workflow_file = example_dir / workflow["config_file"]
        with open(workflow_file) as f:
            workflow_config = yaml.safe_load(f)
        workflow_registry[workflow["type"]] = {
            "initial_state_model_path": workflow["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version", "1.0"),
            "description": workflow.get("description", ""),
        }

    print(f"✓ Loaded workflow registry from: {registry_path}")
    print(f"  Registered workflows: {', '.join(workflow_registry.keys())}")
    print()

    # Step 2: Initialize the workflow engine with in-memory providers
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()
    print("✓ Workflow engine initialized")
    print()

    # Step 3: Test Scenario 1 - Fast Track Approval (high credit, clean fraud)
    print("=" * 80)
    print("SCENARIO 1: Fast-Track Approval")
    print("Profile: Age 30, Clean Country, Small Loan Amount")
    print("=" * 80)
    print()

    applicant1 = UserProfileState(
        user_id="user_001",
        name="Alice Johnson",
        email="alice@example.com",
        country="US",
        age=30,  # Will result in credit score 780 (>25 = high score)
        id_document_url="https://docs.example.com/valid_id_alice.pdf"
    )

    initial_data1 = LoanApplicationState(
        requested_amount=15000.0,  # < 20000 = simplified underwriting
        applicant_profile=applicant1
    )

    # Start the workflow
    workflow1 = await engine.start_workflow(
        workflow_type="LoanApplication",
        initial_data=initial_data1.model_dump()
    )
    print(f"✓ Started workflow: {workflow1.id}")
    print(f"  Status: {workflow1.status}")
    print()

    # Execute workflow steps
    step_count = 0
    while workflow1.status == "ACTIVE":
        step_count += 1
        current_step = workflow1.workflow_steps[workflow1.current_step]
        print(f"\n--- Step {step_count}: {current_step.name} ---")
        result = await workflow1.next_step(user_input={})
        print(f"Status: {workflow1.status}")
        if result:
            print(f"Result: {result}")

    print()
    print(f"✓ Workflow completed with status: {workflow1.status}")
    print(f"  Final state: {workflow1.state.final_loan_status}")
    print(f"  Total steps executed: {step_count}")
    print()

    # Step 4: Test Scenario 2 - Detailed Review Path (triggers KYC sub-workflow)
    print("=" * 80)
    print("SCENARIO 2: Detailed Review Path")
    print("Profile: Age 24, Clean Country, Moderate Risk")
    print("=" * 80)
    print()

    applicant2 = UserProfileState(
        user_id="user_002",
        name="Bob Smith",
        email="bob@example.com",
        country="US",  # Will result in CLEAN fraud status
        age=24,  # Will result in credit score 620 (moderate risk)
        id_document_url="https://docs.example.com/valid_id_bob.pdf"
    )

    initial_data2 = LoanApplicationState(
        requested_amount=22000.0,  # > 20000 = full underwriting
        applicant_profile=applicant2
    )

    # Start the workflow
    workflow2 = await engine.start_workflow(
        workflow_type="LoanApplication",
        initial_data=initial_data2.model_dump()
    )
    print(f"✓ Started workflow: {workflow2.id}")
    print(f"  Status: {workflow2.status}")
    print()

    # Execute workflow steps
    step_count = 0
    while workflow2.status == "ACTIVE":
        step_count += 1
        current_step = workflow2.workflow_steps[workflow2.current_step]
        print(f"\n--- Step {step_count}: {current_step.name} ---")
        result = await workflow2.next_step(user_input={})
        print(f"Status: {workflow2.status}")
        if result:
            print(f"Result: {result}")

    print()
    print(f"✓ Workflow completed with status: {workflow2.status}")
    print(f"  Final state: {workflow2.state.final_loan_status}")
    print(f"  Pre-approval status: {workflow2.state.pre_approval_status}")
    print(f"  Total steps executed: {step_count}")
    print()

    # Step 5: Test Scenario 3 - Automatic Rejection (high risk)
    print("=" * 80)
    print("SCENARIO 3: Automatic Rejection")
    print("Profile: Age 22, High-Risk Country")
    print("=" * 80)
    print()

    applicant3 = UserProfileState(
        user_id="user_003",
        name="Charlie Wilson",
        email="charlie@example.com",
        country="ZA",  # Will trigger HIGH_RISK fraud status
        age=22,  # Will result in credit score 620
        id_document_url="https://docs.example.com/valid_id_charlie.pdf"
    )

    initial_data3 = LoanApplicationState(
        requested_amount=25000.0,
        applicant_profile=applicant3
    )

    workflow3 = await engine.start_workflow(
        workflow_type="LoanApplication",
        initial_data=initial_data3.model_dump()
    )
    print(f"✓ Started workflow: {workflow3.id}")
    print()

    # Execute workflow steps
    step_count = 0
    while workflow3.status == "ACTIVE":
        step_count += 1
        current_step = workflow3.workflow_steps[workflow3.current_step]
        print(f"\n--- Step {step_count}: {current_step.name} ---")
        result = await workflow3.next_step(user_input={})
        print(f"Status: {workflow3.status}")
        if result:
            print(f"Result: {result}")

    print()
    print(f"✓ Workflow completed with status: {workflow3.status}")
    print(f"  Final state: {workflow3.state.final_loan_status}")
    print(f"  Pre-approval status: {workflow3.state.pre_approval_status}")
    print(f"  Total steps executed: {step_count}")
    print()

    # Summary
    print("=" * 80)
    print("EXECUTION SUMMARY")
    print("=" * 80)
    print(
        f"Scenario 1 (Fast-Track):       {workflow1.state.final_loan_status}")
    print(
        f"Scenario 2 (Human Review):     {workflow2.state.final_loan_status}")
    print(
        f"Scenario 3 (Auto-Reject):      {workflow3.state.final_loan_status}")
    print()
    print("✓ Executed scenarios completed successfully!")
    print()


if __name__ == "__main__":
    asyncio.run(run_loan_workflow())
{
    "user_id": "user_001",
    "name": "Alice Johnson",
    "email": "alice@example.com",
    "country": "US",
    "age": 30,
    "id_document_url": "https://docs.example.com/valid_id_alice.pdf"
}
