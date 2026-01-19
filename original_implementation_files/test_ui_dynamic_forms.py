import pytest
import requests
import json
import os
import time

# Base URL for the API, will be overridden by fixture in Docker environment
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")

@pytest.fixture(scope="module")
def api_base_url():
    """Fixture to provide the API base URL, configurable via environment variable."""
    return BASE_URL

@pytest.fixture(scope="module")
def started_loan_workflow(api_base_url):
    """
    Fixture to start a LoanApplication workflow and return its ID.
    This workflow will pause for human interaction at some point.
    """
    print("\n" + "=" * 70)
    print("UI DYNAMIC FORM TEST - Starting Workflow")
    print("=" * 70)

    start_payload = {
        "workflow_type": "LoanApplication",
        "initial_data": {
            "application_id": "UI-TEST-001",
            "requested_amount": 25000.0,
            "applicant_profile": {
                "user_id": "U-UI-001",
                "name": "UI Test User",
                "email": "ui@example.com",
                "country": "USA",
                "age": 22,
                "id_document_url": "s3://docs/ui_test.pdf"
            }
        }
    }
    
    # Wait for API to be ready
    max_retries = 10
    for i in range(max_retries):
        try:
            response = requests.post(f"{api_base_url}/workflow/start", json=start_payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                workflow_id = data['workflow_id']
                print(f"✓ Workflow created: {workflow_id}")
                print(f"  Status: {data['status']}")
                print(f"  Current Step: {data['current_step_name']}")
                return workflow_id
            else:
                print(f"Attempt {i+1}: API returned status {response.status_code}. Retrying...")
                time.sleep(2)
        except requests.exceptions.ConnectionError as e:
            print(f"Attempt {i+1}: API not reachable. Retrying... Error: {e}")
            time.sleep(2)
    
    pytest.fail(f"Failed to start workflow after {max_retries} attempts.")


def test_get_current_step_info_returns_schema(api_base_url, started_loan_workflow):
    """
    Test that /current_step_info endpoint returns a valid input_schema.
    """
    workflow_id = started_loan_workflow
    print(f"\n[2] GET /workflow/{workflow_id}/current_step_info")
    response = requests.get(f"{api_base_url}/workflow/{workflow_id}/current_step_info")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    step_info = response.json()

    print(f"✓ Step info retrieved:")
    print(f"  Step Name: {step_info.get('name')}")
    print(f"  Step Type: {step_info.get('type')}")

    assert 'input_schema' in step_info, "Expected 'input_schema' in step info"
    schema = step_info['input_schema']

    if schema:
        assert isinstance(schema, dict), "Input schema should be a dictionary"
        print(f"\n  ✓ Input Schema Found:")
        print(f"    Title: {schema.get('title', 'N/A')}")

        if 'properties' in schema:
            print(f"    Properties ({len(schema['properties'])} fields):")
            for prop_name, prop_def in schema['properties'].items():
                prop_type = prop_def.get('type', 'unknown')
                required = prop_name in schema.get('required', [])
                print(f"      - {prop_name}: {prop_type} {'(required)' if required else '(optional)'}")
                if 'description' in prop_def:
                    print(f"        Description: {prop_def['description']}")
        print("\n  ✓ UI should dynamically generate form from this schema")
    else:
        print(f"  ℹ No input required for this step")


def test_submit_form_data_advances_workflow(api_base_url, started_loan_workflow):
    """
    Test submitting form data to advance the workflow.
    """
    workflow_id = started_loan_workflow
    print(f"\n[3] Submitting form data (simulating UI form submission)")

    # First, get current step info to know what input is expected
    response = requests.get(f"{api_base_url}/workflow/{workflow_id}/current_step_info")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    step_info = response.json()
    schema = step_info.get('input_schema')

    input_data = {}
    if schema and 'properties' in schema:
        properties = schema['properties']
        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get('type')
            if prop_type == 'string':
                input_data[prop_name] = f"test_{prop_name}_value"
            elif prop_type == 'integer':
                input_data[prop_name] = 123
            elif prop_type == 'number':
                input_data[prop_name] = 123.45
            elif prop_type == 'boolean':
                input_data[prop_name] = True
            elif prop_type == 'array':
                input_data[prop_name] = ["item1", "item2"] # Example for array

    print(f"  Form data to submit: {json.dumps(input_data, indent=2)}")

    response = requests.post(
        f"{api_base_url}/workflow/{workflow_id}/next",
        json={"input_data": input_data}
    )

    assert response.status_code in [200, 202], \
        f"Expected 200 or 202, got {response.status_code}: {response.text}"
    result = response.json()
    print(f"\n✓ Step advanced successfully")
    print(f"  Status: {result.get('status')}")
    print(f"  Next Step: {result.get('next_step_name', 'N/A')}")
    assert result.get('status') != 'FAILED', "Workflow should not be in FAILED state after submission"


def test_workflow_reaches_human_in_loop_and_provides_schema(api_base_url, started_loan_workflow):
    """
    Test that the workflow eventually reaches a HUMAN_IN_LOOP step
    and its schema can be retrieved.
    """
    workflow_id = started_loan_workflow
    print(f"\n[4] Advancing to find HUMAN_IN_LOOP step...")

    max_attempts = 20
    for i in range(max_attempts):
        time.sleep(1) # Wait a bit for async operations to process
        response = requests.get(f"{api_base_url}/workflow/{workflow_id}/status")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.text}"
        status_data = response.json()

        if status_data['status'] == 'WAITING_HUMAN':
            print(f"\n✓ Found HUMAN_IN_LOOP step!")
            print(f"  Current Step: {status_data['current_step_name']}")

            # Get step info for human review
            step_info_response = requests.get(f"{api_base_url}/workflow/{workflow_id}/current_step_info")
            assert step_info_response.status_code == 200, \
                f"Expected 200 for step info, got {step_info_response.status_code}: {step_info_response.text}"
            human_step_info = step_info_response.json()

            print(f"\n  Human Review Form Schema:")
            assert 'input_schema' in human_step_info, "Expected 'input_schema' for human step"
            human_schema = human_step_info['input_schema']

            if human_schema:
                assert isinstance(human_schema, dict), "Human input schema should be a dictionary"
                if 'properties' in human_schema:
                    print(f"    Properties:")
                    for prop_name, prop_def in human_schema['properties'].items():
                        print(f"      - {prop_name}: {prop_def.get('type')} {'(required)' if prop_name in human_schema.get('required', []) else ''}")
            
            print(f"\n  ✓ UI will show 'Submit Review' button instead of 'Next Step'")
            print(f"  ✓ UI will call /resume endpoint instead of /next")
            return # Test passed, exit loop
        
        elif status_data['status'] in ['COMPLETED', 'FAILED']:
            pytest.fail(f"Workflow unexpectedly ended with status: {status_data['status']}")
        
        elif status_data['status'] == 'ACTIVE':
            # Try to advance if not waiting for human and not completed/failed
            print(f"  Workflow is ACTIVE at {status_data['current_step_name']}. Advancing...")
            try:
                requests.post(f"{api_base_url}/workflow/{workflow_id}/next", json={"input_data": {}}, timeout=5)
            except requests.exceptions.ConnectionError:
                # API might be temporarily down or busy, continue trying status
                pass
        
        else:
            print(f"  Current status: {status_data['status']}. Waiting...")

    pytest.fail(f"Workflow did not reach WAITING_HUMAN status after {max_attempts} attempts.")