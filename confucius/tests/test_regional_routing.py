import requests
import time
import subprocess
import pytest
import docker

# Define API base URL
API_URL = "http://localhost:8000/api/v1"

# Define initial data for the loan application
LOAN_APPLICATION_DATA = {
    "workflow_type": "LoanApplication",
    "initial_data": {
        "applicant_profile": {
            "user_id": "U-789",
            "name": "John Doe",
            "email": "j.doe@workplace.com",
            "country": "USA",
            "age": 30,
            "id_document_url": "s3://docs/id_valid.pdf"
        },
        "requested_amount": 25000.00
    }
}

def wait_for_workflow_status(workflow_id, target_status, timeout=60):
    """Polls the workflow status until it reaches the target status or times out."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{API_URL}/workflow/{workflow_id}/status")
            response.raise_for_status()
            current_status = response.json().get("status")
            if current_status == target_status:
                return True
            if current_status in ["FAILED", "FAILED_ROLLED_BACK"]:
                pytest.fail(f"Workflow entered failed state: {response.json()}")
        except requests.exceptions.RequestException as e:
            print(f"Warning: API request failed while polling: {e}")
        time.sleep(2)
    
    # After timeout, get final status one last time for debugging
    final_response = requests.get(f"{API_URL}/workflow/{workflow_id}/status")
    if final_response.status_code == 200:
        print(f"Final workflow status on timeout: {final_response.json().get('status')}")
        print(f"Final workflow state on timeout: {final_response.json().get('state')}")

    return False

def get_container_logs(container_name):
    """Fetches logs from a given docker container."""
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        return container.logs(stdout=True, stderr=True).decode('utf-8')
    except Exception as e:
        print(f"Error fetching logs for {container_name}: {e}")
        return ""

def test_kyc_subworkflow_is_routed_to_onsite_worker():
    """
    Tests that the KYC sub-workflow, when launched by the loan workflow,
    is executed on the 'worker-onsite' container.
    """
    # Step 1: Start the loan application workflow with data that triggers the KYC path
    test_data = LOAN_APPLICATION_DATA.copy()
    # Correctly update the nested 'age' field
    test_data["initial_data"]["applicant_profile"] = LOAN_APPLICATION_DATA["initial_data"]["applicant_profile"].copy()
    test_data["initial_data"]["applicant_profile"]["age"] = 22 # This will result in a lower credit score, avoiding pre-approval

    start_response = requests.post(f"{API_URL}/workflow/start", json=test_data)
    if start_response.status_code != 200:
        pytest.fail(f"Failed to start workflow. Status: {start_response.status_code}, Body: {start_response.json()}")
    assert start_response.status_code == 200
    workflow_id = start_response.json()["workflow_id"]
    print(f"Started Loan Application workflow (KYC path) with ID: {workflow_id}")

    # Step 2: Call /next to kick off the execution of the automated steps
    next_response = requests.post(f"{API_URL}/workflow/{workflow_id}/next", json={"input_data": {}})
    assert next_response.status_code == 202, f"Expected 202 Accepted for async step, but got {next_response.status_code}"

    # Step 3: Wait for the workflow to pause for human review, which happens after the KYC sub-workflow
    assert wait_for_workflow_status(workflow_id, "WAITING_HUMAN"), "Workflow did not reach WAITING_HUMAN status"
    
    # Step 4: Verify the logs
    # Check that the default worker did NOT run the KYC report
    default_worker_logs = get_container_logs("confucius-celery_worker-1")
    assert "[REGIONAL_ROUTING_TEST]" not in default_worker_logs, \
        "The default worker should not have executed the KYC report."

    # Check that the on-site worker DID run the KYC report
    onsite_worker_logs = get_container_logs("confucius-worker-onsite-1")
    assert "KYC: Verifying ID for John Doe" in onsite_worker_logs, \
        "The on-site worker did not execute the KYC report as expected."

    print("Test successful: KYC sub-workflow was correctly routed to the on-site worker.")