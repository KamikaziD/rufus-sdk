import sys
import os
import pytest
from pydantic import BaseModel
from typing import List, Dict, Any

# Add src to path to allow importing confucius
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from confucius.workflow import Workflow, WorkflowStep, WorkflowJumpDirective, WorkflowPauseDirective
from confucius.workflow_loader import _build_steps_from_config
from confucius.models import StepContext

# --- Mocks and Test Fixtures ---

class SimpleState(BaseModel):
    call_sequence: List[str] = []
    value: int = 0

class InjectionState(BaseModel):
    should_inject: bool = False
    call_sequence: List[str] = []

def step_one_func(state: SimpleState, context: StepContext):
    state.call_sequence.append("one")
    return {"message": "Step one done"}

def step_two_func(state: SimpleState, context: StepContext):
    state.call_sequence.append("two")
    return {"message": "Step two done"}

def step_three_func(state: SimpleState, context: StepContext):
    state.call_sequence.append("three")
    return {"message": "Step three done"}

def jump_directive_func(state: SimpleState, context: StepContext):
    state.call_sequence.append("jump")
    raise WorkflowJumpDirective(target_step_name="Final_Step")

def pause_directive_func(state: SimpleState, context: StepContext):
    state.call_sequence.append("pause")
    raise WorkflowPauseDirective(result={"message": "Paused for input"})

def injection_trigger_func(state: InjectionState, context: StepContext):
    state.call_sequence.append("trigger")
    state.should_inject = True
    return {"message": "Injection triggered"}

def injected_step_func(state: InjectionState, context: StepContext):
    state.call_sequence.append("injected")
    return {"message": "Injected step executed"}

def final_injection_func(state: InjectionState, context: StepContext):
    state.call_sequence.append("final")
    return {"message": "Final step executed"}


@pytest.fixture
def basic_workflow():
    """A simple linear workflow."""
    steps = [
        WorkflowStep(name="Step_One", func=step_one_func),
        WorkflowStep(name="Step_Two", func=step_two_func),
        WorkflowStep(name="Step_Three", func=step_three_func),
    ]
    workflow = Workflow(
        workflow_steps=steps,
        initial_state_model=SimpleState(),
        workflow_type="TestWorkflow"
    )
    return workflow

@pytest.fixture
def directive_workflow():
    """A workflow with jump and pause directives."""
    steps = [
        WorkflowStep(name="Start", func=step_one_func),
        WorkflowStep(name="Jump_Step", func=jump_directive_func),
        WorkflowStep(name="Should_Be_Skipped", func=step_two_func),
        WorkflowStep(name="Final_Step", func=step_three_func),
    ]
    workflow = Workflow(
        workflow_steps=steps,
        initial_state_model=SimpleState(),
        workflow_type="DirectiveWorkflow"
    )
    return workflow

@pytest.fixture
def injection_workflow() -> Workflow:
    """A workflow configured for dynamic step injection."""
    steps_config = [
        {
            "name": "Trigger_Step",
            "type": "STANDARD",
            "function": "tests.test_workflow.injection_trigger_func",
            "dynamic_injection": {
                "rules": [
                    {
                        "condition_key": "should_inject",
                        "value_match": True,
                        "action": "INSERT_AFTER_CURRENT",
                        "steps_to_insert": [
                            {
                                "name": "Injected_Step",
                                "type": "STANDARD",
                                "function": "tests.test_workflow.injected_step_func"
                            }
                        ]
                    }
                ]
            }
        },
        {
            "name": "Final_Step",
            "type": "STANDARD",
            "function": "tests.test_workflow.final_injection_func"
        }
    ]
    
    # We use the real builder functions here to test the whole mechanism
    workflow_steps = _build_steps_from_config(steps_config)
    
    workflow = Workflow(
        workflow_type="InjectionTest",
        workflow_steps=workflow_steps,
        initial_state_model=InjectionState(),
        steps_config=steps_config
    )
    return workflow


# --- Unit Tests ---

def test_workflow_initialization(basic_workflow: Workflow):
    assert basic_workflow.current_step == 0
    assert basic_workflow.status == "ACTIVE"
    assert basic_workflow.current_step_name == "Step_One"
    assert isinstance(basic_workflow.state, SimpleState)
    assert basic_workflow.state.call_sequence == []

def test_linear_progression(basic_workflow: Workflow):
    # Step 1
    result, next_step = basic_workflow.next_step({})
    assert basic_workflow.current_step == 1
    assert basic_workflow.current_step_name == "Step_Two"
    assert basic_workflow.state.call_sequence == ["one"]
    assert result == {"message": "Step one done"}

    # Step 2
    result, next_step = basic_workflow.next_step({})
    assert basic_workflow.current_step == 2
    assert basic_workflow.current_step_name == "Step_Three"
    assert basic_workflow.state.call_sequence == ["one", "two"]

    # Step 3
    result, next_step = basic_workflow.next_step({})
    assert basic_workflow.current_step == 3
    assert basic_workflow.status == "COMPLETED"
    assert basic_workflow.current_step_name is None
    assert basic_workflow.state.call_sequence == ["one", "two", "three"]

    # After completion
    result, next_step = basic_workflow.next_step({})
    assert basic_workflow.status == "COMPLETED"
    assert result["status"] == "Workflow completed"

def test_jump_directive(directive_workflow: Workflow):
    # Step 1 (Start)
    directive_workflow.next_step({})
    assert directive_workflow.current_step == 1
    assert directive_workflow.current_step_name == "Jump_Step"
    assert directive_workflow.state.call_sequence == ["one"]

    # Step 2 (Jump_Step)
    result, next_step = directive_workflow.next_step({})
    assert "Jumped to step" in result["message"]
    assert directive_workflow.current_step == 3 # It jumped
    assert directive_workflow.current_step_name == "Final_Step"
    assert directive_workflow.state.call_sequence == ["one", "jump"]

    # Step 3 (Final_Step)
    directive_workflow.next_step({})
    assert directive_workflow.current_step == 4
    assert directive_workflow.status == "COMPLETED"
    assert directive_workflow.state.call_sequence == ["one", "jump", "three"]

def test_pause_directive():
    # Setup a workflow with a pause step
    steps = [WorkflowStep(name="Pause_Step", func=pause_directive_func)]
    workflow = Workflow(workflow_steps=steps, initial_state_model=SimpleState())

    # Execute the step
    result, next_step = workflow.next_step({})

    # Assertions
    assert workflow.status == "WAITING_HUMAN"
    assert workflow.current_step == 0 # Step doesn't advance on pause
    assert workflow.current_step_name == "Pause_Step"
    assert workflow.state.call_sequence == ["pause"]
    assert result["message"] == "Paused for input"

def test_dynamic_step_injection(injection_workflow: Workflow):
    # Check initial state
    assert len(injection_workflow.workflow_steps) == 2
    assert len(injection_workflow.steps_config) == 2
    assert injection_workflow.workflow_steps[0].name == "Trigger_Step"
    assert injection_workflow.workflow_steps[1].name == "Final_Step"

    # Run the trigger step
    injection_workflow.next_step({})

    # Check state after injection
    assert injection_workflow.state.should_inject is True
    assert injection_workflow.state.call_sequence == ["trigger"]
    assert injection_workflow.current_step == 1 # Advanced past the trigger step
    
    # Verify the new step was injected
    assert len(injection_workflow.workflow_steps) == 3
    assert len(injection_workflow.steps_config) == 3
    assert injection_workflow.workflow_steps[0].name == "Trigger_Step"
    assert injection_workflow.workflow_steps[1].name == "Injected_Step" # New step is here
    assert injection_workflow.workflow_steps[2].name == "Final_Step"
    
    assert injection_workflow.current_step_name == "Injected_Step"

    # Run the injected step
    injection_workflow.next_step({})
    assert injection_workflow.state.call_sequence == ["trigger", "injected"]
    assert injection_workflow.current_step == 2
    assert injection_workflow.current_step_name == "Final_Step"

    # Run the final step
    injection_workflow.next_step({})
    assert injection_workflow.state.call_sequence == ["trigger", "injected", "final"]
    assert injection_workflow.status == "COMPLETED"

# --- Tests for automate_next ---

class AutomatedState(BaseModel):
    call_sequence: List[str] = []
    value: int = 1

def automated_step_one(state: AutomatedState, context: StepContext):
    state.call_sequence.append("auto_one")
    # This value should be doubled by the next automated step
    return {"current_value": state.value}

def automated_step_two(state: AutomatedState, context: StepContext):
    state.call_sequence.append("auto_two")
    current_value = context.previous_step_result.get("current_value")
    state.value = current_value * 2
    # This result will be the input for the non-automated step three
    return {"final_value": state.value}

def automated_step_three(state: AutomatedState, context: StepContext):
    state.call_sequence.append("auto_three")
    final_value = context.previous_step_result.get("final_value")
    # This step is not automated, so it should not run in the chain
    state.value = final_value + 1
    return {"message": "Automation chain finished"}

@pytest.fixture
def automated_workflow():
    """A workflow with a step that has automate_next=True."""
    steps = [
        WorkflowStep(name="Auto_Step_One", func=automated_step_one, automate_next=True),
        WorkflowStep(name="Auto_Step_Two", func=automated_step_two, automate_next=False), # Chain stops here
        WorkflowStep(name="Auto_Step_Three", func=automated_step_three),
    ]
    workflow = Workflow(
        workflow_steps=steps,
        initial_state_model=AutomatedState(),
        workflow_type="AutomatedTestWorkflow"
    )
    return workflow

def test_automate_next_chain(automated_workflow: Workflow):
    """
    Tests that calling a step with automate_next=True triggers the next step
    in the same call, passing the result as input.
    """
    # We only call next_step ONCE
    result, next_step_name = automated_workflow.next_step({})

    # Assertions
    # The workflow should have executed steps one and two and stopped at three
    assert automated_workflow.current_step == 2
    assert next_step_name == "Auto_Step_Three"
    
    # Check that both functions in the automated chain were called
    assert automated_workflow.state.call_sequence == ["auto_one", "auto_two"]
    
    # Check that the state was updated correctly by the chain
    # Initial state value is 1. Step one passes it. Step two doubles it.
    assert automated_workflow.state.value == 2

    # The result returned should be from the LAST step in the chain (Auto_Step_Two)
    assert result == {"final_value": 2}

    # Now, run the third step to ensure it works correctly
    # The result of the last automated step is passed as user_input to the next manual step
    result, next_step_name = automated_workflow.next_step({}, _previous_step_result=result)
    assert automated_workflow.state.call_sequence == ["auto_one", "auto_two", "auto_three"]
    assert automated_workflow.state.value == 3 # 2 + 1
    assert automated_workflow.status == "COMPLETED"