import asyncio
import httpx
import time
import uuid
import sys
import random

API_URL = "http://localhost:8000/api/v1"
CONCURRENT_WORKFLOWS = 50
POLL_INTERVAL = 2  # seconds
TIMEOUT = 180  # seconds

async def start_workflow(client: httpx.AsyncClient, index: int):
    # Determine scenario based on index to mix things up
    # 0-15: Fast Track (Approve)
    # 16-30: Auto Reject
    # 31-49: Standard Full (Manual Review - will pause)
    
    scenario = "unknown"
    age = 30
    country = "USA"
    amount = 10000
    
    if index < 15:
        scenario = "Fast Track"
        age = 30 # >25 -> 780 score
        amount = 10000
    elif index < 30:
        scenario = "Auto Reject"
        country = "ZA" # High risk
    else:
        scenario = "Manual Review"
        age = 20 # <25 -> 620 score -> Manual
        amount = 50000 # >20k -> Full underwriting
        
    payload = {
        "workflow_type": "LoanApplication",
        "initial_data": {
            "application_id": f"STRESS-{uuid.uuid4().hex[:8]}",
            "requested_amount": amount,
            "applicant_profile": {
                "user_id": f"USER-{index}",
                "name": f"Stress User {index}",
                "email": f"user{index}@example.com",
                "country": country,
                "age": age,
                "id_document_url": "http://example.com/id.pdf"
            }
        }
    }
    
    try:
        resp = await client.post(f"{API_URL}/workflow/start", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {
            "index": index,
            "id": data["workflow_id"], 
            "scenario": scenario,
            "status": "STARTED",
            "start_time": time.time()
        }
    except Exception as e:
        print(f"[{index}] Failed to start: {e}")
        return None

async def monitor_workflow(client: httpx.AsyncClient, workflow_data):
    wf_id = workflow_data["id"]
    index = workflow_data["index"]
    scenario = workflow_data["scenario"]
    
    start_time = time.time()
    last_step = ""
    
    while time.time() - start_time < TIMEOUT:
        try:
            resp = await client.get(f"{API_URL}/workflow/{wf_id}/status")
            if resp.status_code != 200:
                print(f"[{index}] Status check failed: {resp.status_code}")
                await asyncio.sleep(POLL_INTERVAL)
                continue
                
            data = resp.json()
            status = data['status']
            current_step = data['current_step_name']
            
            # Auto-resume manual review for stress test
            if status == "WAITING_HUMAN":
                # print(f"[{index}] Paused for review. Resuming...")
                resume_payload = {
                    "decision": "APPROVED",
                    "reviewer_id": "stress_bot",
                    "comments": "Auto-approved by stress test"
                }
                await client.post(f"{API_URL}/workflow/{wf_id}/resume", json=resume_payload)
                await asyncio.sleep(1)
                continue

            # Drive workflow if stuck in ACTIVE at certain steps (simulating UI interaction)
            if status == "ACTIVE":
                input_data = {}
                # Provide input if stuck at Collect (though start usually passes it)
                if current_step == "Collect_Application_Data":
                     input_data = {"user_id": f"USER-{index}", "name": "Stress", "email": "x@x.com", "country": "USA", "age": 30, "requested_amount": 10000, "id_document_url": "x"}
                
                # Nudge forward
                await client.post(f"{API_URL}/workflow/{wf_id}/next", json={"input_data": input_data})

            if status in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
                duration = time.time() - workflow_data["start_time"]
                return {
                    "id": wf_id,
                    "final_status": status,
                    "duration": duration,
                    "scenario": scenario
                }
            
            await asyncio.sleep(POLL_INTERVAL + random.uniform(0, 1)) # Jitter
            
        except Exception as e:
            print(f"[{index}] Monitor error: {e}")
            await asyncio.sleep(POLL_INTERVAL)
            
    return {
        "id": wf_id,
        "final_status": "TIMEOUT",
        "duration": TIMEOUT,
        "scenario": scenario
    }

async def run_stress_test():
    print(f"--- Starting Stress Test: {CONCURRENT_WORKFLOWS} Concurrent Workflows ---")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Spawn workflows
        start_tasks = [start_workflow(client, i) for i in range(CONCURRENT_WORKFLOWS)]
        workflows = await asyncio.gather(*start_tasks)
        workflows = [w for w in workflows if w] # Filter failed starts
        
        print(f"Successfully started {len(workflows)} workflows. Monitoring...")
        
        # 2. Monitor execution
        monitor_tasks = [monitor_workflow(client, wf) for wf in workflows]
        results = await asyncio.gather(*monitor_tasks)
        
        # 3. Analyze results
        completed = sum(1 for r in results if r["final_status"] == "COMPLETED")
        failed = sum(1 for r in results if r["final_status"].startswith("FAILED"))
        timeouts = sum(1 for r in results if r["final_status"] == "TIMEOUT")
        
        avg_duration = sum(r["duration"] for r in results) / len(results) if results else 0
        
        print("\n--- Stress Test Results ---")
        print(f"Total: {len(results)}")
        print(f"Completed: {completed}")
        print(f"Failed: {failed}")
        print(f"Timeouts: {timeouts}")
        print(f"Avg Duration: {avg_duration:.2f}s")
        
        if failed == 0 and timeouts == 0:
            print("\n✅ SUCCESS: System handled concurrency without errors.")
            sys.exit(0)
        else:
            print("\n❌ FAILURE: Some workflows failed or timed out.")
            # Print details of failures
            for r in results:
                if r["final_status"] != "COMPLETED":
                    print(f"  - {r['id']} ({r['scenario']}): {r['final_status']}")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_stress_test())
