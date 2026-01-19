#!/usr/bin/env python3
"""Debug workflow loading from PostgreSQL"""

import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from confucius.persistence import load_workflow_state

workflow_id = "c2e0f964-dcee-4a0b-963c-81c53b93b1f3"

print(f"Loading workflow: {workflow_id}")
workflow = load_workflow_state(workflow_id)

if not workflow:
    print("✗ Workflow not found")
    sys.exit(1)

print(f"✓ Workflow loaded")
print(f"  Status: {workflow.status}")
print(f"  Current Step: {workflow.current_step}")
print(f"  Total Steps: {len(workflow.workflow_steps)}")

if workflow.current_step < len(workflow.workflow_steps):
    step = workflow.workflow_steps[workflow.current_step]
    print(f"\nCurrent step details:")
    print(f"  Name: {step.name}")
    print(f"  Type: {type(step).__name__}")
    print(f"  Has input_schema attr: {hasattr(step, 'input_schema')}")

    if hasattr(step, 'input_schema'):
        print(f"  input_schema value: {step.input_schema}")

    print(f"  Attributes: {dir(step)}")
