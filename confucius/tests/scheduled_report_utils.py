import time
from datetime import datetime

def generate_report(state):
    print(f"Generating report {state.report_id}...")
    time.sleep(1) # Simulate work
    return {
        "status": "completed",
        "report_url": f"s3://reports/{state.report_id}.pdf",
        "generated_at": datetime.now().isoformat()
    }
