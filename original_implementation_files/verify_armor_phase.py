import requests
import time
import sys
import os

API_URL = "http://localhost:8000/api/v1"

def test_rate_limiting():
    print("--- Testing Rate Limiting (10/min) ---")
    payload = {
        "workflow_type": "GearsTest",
        "initial_data": {"test_id": "RATE-LIMIT-TEST", "items": ["A"]}
    }
    
    success_count = 0
    limited_count = 0
    
    for i in range(15):
        resp = requests.post(f"{API_URL}/workflow/start", json=payload)
        if resp.status_code == 200:
            success_count += 1
        elif resp.status_code == 429:
            limited_count += 1
            print(f"  [Request {i+1}] Rate limited as expected (429)")
        else:
            print(f"  [Request {i+1}] Unexpected status: {resp.status_code}")
            
    print(f"Summary: Success: {success_count}, Rate Limited: {limited_count}")
    if limited_count > 0:
        print("✅ Rate limiting is active.")
    else:
        print("❌ Rate limiting NOT triggered. Ensure main.py has limiter initialized and passed to router.")

def test_encryption_at_rest():
    print("\n--- Testing Encryption at Rest ---")
    # This test requires ENABLE_ENCRYPTION_AT_REST=true
    # We will start a workflow and then check the DB directly via a shell command
    
    payload = {
        "workflow_type": "GearsTest",
        "initial_data": {"test_id": "ENCRYPT-TEST", "items": ["SECRET-ITEM"]}
    }
    
    resp = requests.post(f"{API_URL}/workflow/start", json=payload)
    if resp.status_code != 200:
        print(f"❌ Failed to start workflow: {resp.text}")
        return
        
    wf_id = resp.json()["workflow_id"]
    print(f"Started workflow: {wf_id}")
    
    # Wait for DB persistence
    time.sleep(1)
    
    # Query DB directly to see if 'state' is empty and 'encrypted_state' is populated
    import subprocess
    cmd = [
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "confucius", "-d", "confucius", "-c",
        f"SELECT state, encrypted_state IS NOT NULL as is_encrypted FROM workflow_executions WHERE id = '{wf_id}';"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Database Record Check:\n{result.stdout}")
    
    if "is_encrypted | t" in result.stdout and '"SECRET-ITEM"' not in result.stdout:
        print("✅ Encryption at rest confirmed: Plaintext state is empty, encrypted_state is populated.")
    else:
        print("⚠️ Encryption might NOT be enabled or state is still visible in plaintext.")
        print("Ensure ENABLE_ENCRYPTION_AT_REST=true is set in environment.")

if __name__ == "__main__":
    test_rate_limiting()
    test_encryption_at_rest()
