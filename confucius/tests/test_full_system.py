import requests
import time
import sys
import json
import uuid

API_URL = "http://localhost:8000/api/v1"

def print_step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def test_system_health():
    print_step("--- Test 1: System Health ---")
    try:
        # Check available workflows as a liveness probe
        resp = requests.get(f"{API_URL}/workflows")
        resp.raise_for_status()
        workflows = resp.json()
        print_step(f"✅ API Reachable. Found {len(workflows)} registered workflows.")
        return True
    except Exception as e:
        print_step(f"❌ API Unreachable: {e}")
        return False

def test_standard_workflow():
    print_step("--- Test 2: Standard Workflow (LoanApplication) ---")
    payload = {
        "workflow_type": "LoanApplication",
        "initial_data": {
            "application_id": f"TEST-{uuid.uuid4().hex[:8]}",
            "requested_amount": 10000,
            "applicant_profile": {
                "user_id": "U-TEST",
                "name": "Test User",
                "email": "test@example.com",
                "country": "USA",
                "age": 30, # Fast track
                "id_document_url": "http://example.com/id.pdf"
            }
        }
    }
    try:
        resp = requests.post(f"{API_URL}/workflow/start", json=payload)
        resp.raise_for_status()
        wf_id = resp.json()["workflow_id"]
        print_step(f"Started Workflow: {wf_id}")
        
        # Advance (step 1 needs input)
        input_data = payload["initial_data"]["applicant_profile"].copy()
        input_data["requested_amount"] = payload["initial_data"]["requested_amount"]
        requests.post(f"{API_URL}/workflow/{wf_id}/next", json={"input_data": input_data})
        
        # Poll for completion
        for _ in range(20):
            resp = requests.get(f"{API_URL}/workflow/{wf_id}/status")
            status = resp.json()['status']
            if status == 'COMPLETED':
                print_step("✅ Workflow Completed Successfully")
                return True
            time.sleep(1)
            
        print_step("❌ Timeout waiting for completion")
        return False
        
    except Exception as e:
        print_step(f"❌ Error: {e}")
        return False

def test_http_workflow():
    print_step("--- Test 3: HTTP Step (TodoProcessingWorkflow) ---")
    try:
        resp = requests.post(f"{API_URL}/workflow/start", json={
            "workflow_type": "TodoProcessingWorkflow",
            "initial_data": {}
        })
        resp.raise_for_status()
        wf_id = resp.json()["workflow_id"]
        print_step(f"Started HTTP Workflow: {wf_id}")
        
        # Kick off first step
        requests.post(f"{API_URL}/workflow/{wf_id}/next", json={"input_data": {}})
        
        for _ in range(30):
            resp = requests.get(f"{API_URL}/workflow/{wf_id}/status")
            data = resp.json()
            status = data['status']
            
            if status == "COMPLETED":
                # Verify HTTP data populated
                state = data['state']
                if "todo_list_response" in state and "spawned_workflows" in state:
                    print_step("✅ Workflow Completed with HTTP Data and Spawned Notification")
                    return True
                else:
                    print_step(f"❌ Completed but missing data. Keys: {list(state.keys())}")
                    return False
            
            if status == "FAILED":
                print_step("❌ Workflow Failed")
                return False

            time.sleep(1)
            
        print_step("❌ Timeout")
        return False
    except Exception as e:
        print_step(f"❌ Error: {e}")
        return False

def test_scheduler():
    print_step("--- Test 4: Scheduler (TestScheduler) ---")
    print_step("Waiting 70 seconds for scheduled task trigger...")
    time.sleep(70) 
    
    try:
        # Check executions list for "TestScheduler" type
        # Note: current API doesn't filter by type in list, so fetch all and filter client side 
        # or check specific ID if we knew it (we don't).
        # Actually I added filter logic to router?
        # No, I added status/exclude_status filter.
        
        resp = requests.get(f"{API_URL}/workflows/executions?limit=50")
        executions = resp.json()
        
        found = False
        for ex in executions:
            if ex['workflow_type'] == 'TestScheduler':
                print_step(f"✅ Found Scheduled Execution: {ex['id']} ({ex['status']})")
                found = True
                break
        
        if not found:
            print_step("❌ No scheduled execution found after waiting.")
            return False
            
        return True
    except Exception as e:
        print_step(f"❌ Error checking scheduler: {e}")
        return False

def main():
    print_step("=== Starting Comprehensive E2E System Test ===")
    
    results = []
    results.append(test_system_health())
    results.append(test_standard_workflow())
    results.append(test_http_workflow())
    results.append(test_scheduler())
    
    print("\n=== Test Summary ===")
    if all(results):
        print("✅ ALL SYSTEMS GO")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
