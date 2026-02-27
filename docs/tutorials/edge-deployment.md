# Tutorial: Deploy Rufus to Edge Hardware

**Learning Objectives:**
- Deploy Rufus workflows to edge devices (Raspberry Pi, IoT hardware)
- Configure SQLite for offline-first operation
- Implement Store-and-Forward (SAF) for network resilience
- Test workflows in offline mode
- Sync with cloud when connectivity restored

**Prerequisites:**
- Completed [Build a Task Manager](./build-task-manager.md)
- Raspberry Pi or similar edge device (optional - can test on laptop)
- Basic understanding of IoT/edge computing

**Time:** 35 minutes

---

## What is Edge Deployment?

**Edge Computing** runs workflows on hardware devices instead of cloud servers:

```
TRADITIONAL (Cloud-Only):          EDGE (Hybrid):
┌──────────┐                       ┌──────────┐
│  Device  │                       │  Device  │ <- Workflow runs here!
└────┬─────┘                       └────┬─────┘
     │ Every operation               │ Offline OK
     │ requires network              │ Sync later
     ▼                                  ▼
┌──────────┐                       ┌──────────┐
│  Cloud   │                       │  Cloud   │
└──────────┘                       └──────────┘
```

**Use Cases:**
- **POS Terminals**: Process payments offline, sync when internet restored
- **ATMs**: Dispense cash even if network is down
- **Mobile Card Readers**: Accept payments in remote locations
- **Kiosks**: Self-service workflows without cloud dependency
- **Industrial IoT**: Factory floor operations with intermittent connectivity

---

## Architecture: Edge + Cloud

```
┌─────────────────────────────────────────┐
│         EDGE DEVICE (SQLite)            │
│  ┌──────────────────────────────────┐   │
│  │  Rufus Edge Agent                │   │
│  │  - Workflows run locally         │   │
│  │  - SQLite persistence            │   │
│  │  - Offline queue                 │   │
│  └──────────────────────────────────┘   │
└────────────┬────────────────────────────┘
             │
             │ Store-and-Forward (SAF)
             │ Sync when online
             │
┌────────────▼────────────────────────────┐
│    CLOUD CONTROL PLANE (PostgreSQL)     │
│  ┌──────────────────────────────────┐   │
│  │  Rufus Cloud Server              │   │
│  │  - Device registry               │   │
│  │  - Config push (ETag)            │   │
│  │  - Transaction aggregation       │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

---

## Step 1: Set Up Edge Project

Create a new project for edge deployment:

```bash
mkdir rufus-edge-demo
cd rufus-edge-demo
mkdir -p edge_app config
touch edge_app/__init__.py
```

Project structure:

```
rufus-edge-demo/
├── edge_app/
│   ├── __init__.py
│   ├── models.py          # State models
│   ├── steps.py           # Workflow steps
│   └── sync_manager.py    # Store-and-forward
├── config/
│   └── payment_workflow.yaml
└── edge_agent.py          # Main edge agent
```

---

## Step 2: Create an Edge Workflow

Let's build a payment terminal workflow that works offline.

### Define State Model

Create `edge_app/models.py`:

```python
"""
State models for edge payment terminal
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PaymentState(BaseModel):
    """State for offline payment processing"""

    # Transaction details
    transaction_id: str
    device_id: str
    merchant_id: str
    amount: float
    currency: str = "USD"

    # Card details (in real app: use encryption!)
    card_last_four: str
    card_type: Optional[str] = None

    # Processing
    authorization_code: Optional[str] = None
    approved: bool = False
    offline_approved: bool = False

    # Floor limits (offline approval thresholds)
    floor_limit: float = 100.00  # Approve offline if under $100

    # Sync status
    synced_to_cloud: bool = False
    sync_timestamp: Optional[datetime] = None

    # Metadata
    processed_at: datetime
    network_available: bool = True
```

---

## Step 3: Implement Edge Workflow Steps

Create `edge_app/steps.py`:

```python
"""
Edge payment workflow steps
"""

import uuid
from datetime import datetime
from edge_app.models import PaymentState
from rufus.models import StepContext


def check_network(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Check if network is available
    """
    print(f"\n🌐 Checking network connectivity...")

    # Simulate network check
    # In production: ping cloud server, check DNS, etc.
    import random
    network_available = random.choice([True, True, False])  # 66% online

    state.network_available = network_available

    status = "ONLINE" if network_available else "OFFLINE"
    print(f"   Network Status: {status}")

    return {
        "network_available": network_available
    }


def validate_transaction(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Validate transaction details
    """
    print(f"\n✅ Validating transaction...")
    print(f"   Device: {state.device_id}")
    print(f"   Merchant: {state.merchant_id}")
    print(f"   Amount: ${state.amount:.2f}")
    print(f"   Card: **** {state.card_last_four}")

    # Basic validation
    valid = (
        state.amount > 0 and
        state.amount < 100000 and
        len(state.card_last_four) == 4
    )

    if not valid:
        raise ValueError("Transaction validation failed")

    print(f"   ✓ Transaction valid")

    return {"validated": True}


def authorize_payment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Authorize payment (online or offline)
    """
    print(f"\n💳 Authorizing payment: ${state.amount:.2f}")

    if state.network_available:
        # ONLINE: Contact payment gateway
        print(f"   Mode: ONLINE")
        print(f"   Contacting payment gateway...")

        # Simulate online authorization
        auth_code = f"AUTH-{uuid.uuid4().hex[:8].upper()}"
        approved = True

        print(f"   ✓ Authorization Code: {auth_code}")
        print(f"   Status: APPROVED")

        return {
            "approved": True,
            "offline_approved": False,
            "authorization_code": auth_code
        }

    else:
        # OFFLINE: Use floor limits
        print(f"   Mode: OFFLINE")
        print(f"   Floor Limit: ${state.floor_limit:.2f}")

        if state.amount <= state.floor_limit:
            # Approve offline if under floor limit
            auth_code = f"OFFLINE-{uuid.uuid4().hex[:8].upper()}"
            print(f"   ✓ APPROVED (under floor limit)")
            print(f"   Offline Auth Code: {auth_code}")

            return {
                "approved": True,
                "offline_approved": True,
                "authorization_code": auth_code
            }
        else:
            # Decline if over floor limit
            print(f"   ✗ DECLINED (exceeds floor limit)")
            print(f"   Network required for amounts over ${state.floor_limit:.2f}")

            return {
                "approved": False,
                "offline_approved": False,
                "authorization_code": None
            }


def record_transaction(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Record transaction to local database
    """
    print(f"\n💾 Recording transaction to local storage...")

    # In production: write to SQLite with encryption
    print(f"   Transaction ID: {state.transaction_id}")
    print(f"   Auth Code: {state.authorization_code}")
    print(f"   Offline: {state.offline_approved}")
    print(f"   ✓ Transaction recorded")

    return {
        "recorded": True,
        "processed_at": datetime.utcnow()
    }


def print_receipt(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Print receipt for customer
    """
    print(f"\n🧾 Printing receipt...")
    print(f"")
    print(f"   ================================")
    print(f"          PAYMENT RECEIPT")
    print(f"   ================================")
    print(f"   Merchant: {state.merchant_id}")
    print(f"   Device: {state.device_id}")
    print(f"   ")
    print(f"   Amount: ${state.amount:.2f} {state.currency}")
    print(f"   Card: **** {state.card_last_four}")
    print(f"   ")
    print(f"   Auth Code: {state.authorization_code}")
    print(f"   Status: {'APPROVED' if state.approved else 'DECLINED'}")

    if state.offline_approved:
        print(f"   Mode: OFFLINE APPROVAL")
        print(f"   (Will sync when online)")

    print(f"   ")
    print(f"   Date: {state.processed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Transaction: {state.transaction_id}")
    print(f"   ================================")
    print(f"")

    return {"receipt_printed": True}
```

**Key Edge Features:**
- **Network detection**: Check if cloud is reachable
- **Offline approval**: Use floor limits when offline
- **Local storage**: Record to SQLite immediately
- **Graceful degradation**: Work without network

---

## Step 4: Define Edge Workflow YAML

Create `config/payment_workflow.yaml`:

```yaml
workflow_type: "EdgePayment"
workflow_version: "1.0.0"
initial_state_model: "edge_app.models.PaymentState"
description: "Edge payment workflow with offline support"

steps:
  - name: "Check_Network"
    type: "STANDARD"
    function: "edge_app.steps.check_network"
    automate_next: true
    description: "Check network availability"

  - name: "Validate_Transaction"
    type: "STANDARD"
    function: "edge_app.steps.validate_transaction"
    automate_next: true
    description: "Validate transaction details"

  - name: "Authorize_Payment"
    type: "STANDARD"
    function: "edge_app.steps.authorize_payment"
    automate_next: true
    description: "Authorize payment (online or offline)"

  - name: "Record_Transaction"
    type: "STANDARD"
    function: "edge_app.steps.record_transaction"
    automate_next: true
    description: "Record to local database"

  - name: "Print_Receipt"
    type: "STANDARD"
    function: "edge_app.steps.print_receipt"
    description: "Print customer receipt"
```

---

## Step 5: Build Store-and-Forward Manager

Create `edge_app/sync_manager.py`:

```python
"""
Store-and-Forward (SAF) Manager

Handles sync between edge device and cloud.
"""

import asyncio
from typing import List
from datetime import datetime


class SyncManager:
    """
    Manages offline transaction queue and cloud sync
    """

    def __init__(self, persistence_provider, cloud_url: str = None):
        self.persistence = persistence_provider
        self.cloud_url = cloud_url
        self.sync_queue = []  # Offline transactions pending sync

    async def queue_for_sync(self, workflow_id: str):
        """
        Add workflow to sync queue
        """
        self.sync_queue.append({
            "workflow_id": workflow_id,
            "queued_at": datetime.utcnow()
        })

        print(f"📤 Queued for sync: {workflow_id}")
        print(f"   Queue size: {len(self.sync_queue)}")

    async def sync_to_cloud(self) -> dict:
        """
        Sync pending transactions to cloud
        """
        if not self.sync_queue:
            print("✓ Sync queue empty")
            return {"synced": 0, "failed": 0}

        print(f"\n🔄 Syncing {len(self.sync_queue)} transaction(s) to cloud...")

        synced_count = 0
        failed_count = 0

        for item in self.sync_queue[:]:  # Copy list to allow removal
            workflow_id = item["workflow_id"]

            try:
                # Load workflow from local storage
                workflow_data = await self.persistence.load_workflow(workflow_id)

                # Simulate cloud API call
                # In production: POST to cloud server
                print(f"   Syncing {workflow_id}...")
                await asyncio.sleep(0.1)  # Simulate network delay

                # Mark as synced
                workflow_data["state"]["synced_to_cloud"] = True
                workflow_data["state"]["sync_timestamp"] = datetime.utcnow().isoformat()
                await self.persistence.save_workflow(workflow_id, workflow_data)

                # Remove from queue
                self.sync_queue.remove(item)
                synced_count += 1

                print(f"   ✓ Synced {workflow_id}")

            except Exception as e:
                print(f"   ✗ Failed to sync {workflow_id}: {e}")
                failed_count += 1

        print(f"\n✓ Sync complete: {synced_count} synced, {failed_count} failed")

        return {
            "synced": synced_count,
            "failed": failed_count,
            "remaining": len(self.sync_queue)
        }

    async def run_sync_daemon(self, interval_seconds: int = 60):
        """
        Run continuous sync daemon
        """
        print(f"\n🔁 Starting sync daemon (interval: {interval_seconds}s)")
        print("   Press Ctrl+C to stop\n")

        while True:
            try:
                await self.sync_to_cloud()
                await asyncio.sleep(interval_seconds)
            except KeyboardInterrupt:
                print("\n\n⏹️  Sync daemon stopped")
                break
            except Exception as e:
                print(f"⚠️  Sync error: {e}")
                await asyncio.sleep(interval_seconds)
```

---

## Step 6: Build Edge Agent

Create `edge_agent.py`:

```python
"""
Rufus Edge Agent

Runs workflows on edge devices with offline support.
"""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

from edge_app.sync_manager import SyncManager


async def initialize_edge_database(db_path: str):
    """Initialize SQLite database for edge device"""
    persistence = SQLitePersistenceProvider(db_path=db_path)
    await persistence.initialize()

    # Create minimal schema
    await persistence.conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_type TEXT NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT '{}',
            steps_config TEXT NOT NULL DEFAULT '[]',
            state_model_path TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS workflow_execution_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            step_name TEXT,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    return persistence


async def process_payment(builder: WorkflowBuilder, sync_manager: SyncManager, transaction_data: dict):
    """
    Process a payment transaction
    """
    # Create workflow
    workflow = builder.create_workflow(
        "EdgePayment",
        initial_data=transaction_data
    )

    print(f"\n{'='*70}")
    print(f"  PROCESSING PAYMENT: {transaction_data['transaction_id']}")
    print(f"{'='*70}")

    # Execute workflow
    while workflow.status == "ACTIVE":
        await workflow.next_step()

        if workflow.status == "COMPLETED":
            break

    # Queue for sync if offline approval
    if workflow.state.offline_approved and not workflow.state.synced_to_cloud:
        await sync_manager.queue_for_sync(workflow.id)

    return workflow


async def main():
    print("="*70)
    print("  RUFUS EDGE AGENT - PAYMENT TERMINAL")
    print("="*70)

    # Initialize edge persistence
    print("\n💾 Initializing edge database...")
    persistence = await initialize_edge_database("edge_terminal.db")
    print("✓ SQLite database ready")

    # Create workflow builder
    print("\n⚙️  Initializing workflow engine...")
    builder = WorkflowBuilder(
        registry_path=None,
        persistence_provider=persistence,
        execution_provider=SyncExecutionProvider(),
        observer=LoggingObserver(),
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # Load workflow
    workflow_path = Path(__file__).parent / "config" / "payment_workflow.yaml"
    builder.load_workflow_config("EdgePayment", str(workflow_path))
    print("✓ Edge workflow loaded")

    # Create sync manager
    sync_manager = SyncManager(
        persistence_provider=persistence,
        cloud_url="https://api.example.com"  # Cloud API endpoint
    )

    # Simulate 3 payment transactions
    print("\n" + "="*70)
    print("  SIMULATING PAYMENT TRANSACTIONS")
    print("="*70)

    transactions = [
        {
            "transaction_id": f"TXN-{uuid.uuid4().hex[:8].upper()}",
            "device_id": "POS-TERMINAL-001",
            "merchant_id": "MERCHANT-123",
            "amount": 45.99,
            "card_last_four": "1234",
            "card_type": "Visa",
            "processed_at": datetime.utcnow(),
        },
        {
            "transaction_id": f"TXN-{uuid.uuid4().hex[:8].upper()}",
            "device_id": "POS-TERMINAL-001",
            "merchant_id": "MERCHANT-123",
            "amount": 89.50,
            "card_last_four": "5678",
            "card_type": "Mastercard",
            "processed_at": datetime.utcnow(),
        },
        {
            "transaction_id": f"TXN-{uuid.uuid4().hex[:8].upper()}",
            "device_id": "POS-TERMINAL-001",
            "merchant_id": "MERCHANT-123",
            "amount": 12.75,
            "card_last_four": "9012",
            "card_type": "Amex",
            "processed_at": datetime.utcnow(),
        }
    ]

    # Process each transaction
    workflows = []
    for txn_data in transactions:
        workflow = await process_payment(builder, sync_manager, txn_data)
        workflows.append(workflow)

        # Small delay between transactions
        await asyncio.sleep(1)

    # Summary
    print("\n" + "="*70)
    print("  TRANSACTION SUMMARY")
    print("="*70 + "\n")

    online_count = sum(1 for w in workflows if not w.state.offline_approved)
    offline_count = sum(1 for w in workflows if w.state.offline_approved)
    approved_count = sum(1 for w in workflows if w.state.approved)

    print(f"Total Transactions: {len(workflows)}")
    print(f"  Approved: {approved_count}")
    print(f"  Online: {online_count}")
    print(f"  Offline: {offline_count}")
    print(f"\nPending Sync: {len(sync_manager.sync_queue)}")

    # Sync to cloud
    if sync_manager.sync_queue:
        print("\n" + "="*70)
        print("  SYNCING TO CLOUD")
        print("="*70)

        sync_result = await sync_manager.sync_to_cloud()

        print(f"\nSync Result:")
        print(f"  Synced: {sync_result['synced']}")
        print(f"  Failed: {sync_result['failed']}")
        print(f"  Remaining: {sync_result['remaining']}")

    # Cleanup
    await persistence.close()

    print("\n" + "="*70)
    print("  EDGE AGENT DEMO COMPLETED")
    print("="*70)
    print("\n💾 Database saved to: edge_terminal.db")
    print("   Inspect with: sqlite3 edge_terminal.db\n")


if __name__ == '__main__':
    asyncio.run(main())
```

---

## Step 7: Run the Edge Agent

Run the edge agent:

```bash
python edge_agent.py
```

Output:

```
======================================================================
  RUFUS EDGE AGENT - PAYMENT TERMINAL
======================================================================

💾 Initializing edge database...
✓ SQLite database ready

⚙️  Initializing workflow engine...
✓ Edge workflow loaded

======================================================================
  SIMULATING PAYMENT TRANSACTIONS
======================================================================

======================================================================
  PROCESSING PAYMENT: TXN-A1B2C3D4
======================================================================

🌐 Checking network connectivity...
   Network Status: OFFLINE

✅ Validating transaction...
   Device: POS-TERMINAL-001
   Merchant: MERCHANT-123
   Amount: $45.99
   Card: **** 1234
   ✓ Transaction valid

💳 Authorizing payment: $45.99
   Mode: OFFLINE
   Floor Limit: $100.00
   ✓ APPROVED (under floor limit)
   Offline Auth Code: OFFLINE-12345678

💾 Recording transaction to local storage...
   Transaction ID: TXN-A1B2C3D4
   Auth Code: OFFLINE-12345678
   Offline: True
   ✓ Transaction recorded

🧾 Printing receipt...

   ================================
          PAYMENT RECEIPT
   ================================
   Merchant: MERCHANT-123
   Device: POS-TERMINAL-001

   Amount: $45.99 USD
   Card: **** 1234

   Auth Code: OFFLINE-12345678
   Status: APPROVED
   Mode: OFFLINE APPROVAL
   (Will sync when online)

   Date: 2026-02-13 15:30:45
   Transaction: TXN-A1B2C3D4
   ================================

📤 Queued for sync: 550e8400-e29b-41d4-a716-446655440000
   Queue size: 1

[... similar output for other transactions ...]

======================================================================
  TRANSACTION SUMMARY
======================================================================

Total Transactions: 3
  Approved: 3
  Online: 1
  Offline: 2

Pending Sync: 2

======================================================================
  SYNCING TO CLOUD
======================================================================

🔄 Syncing 2 transaction(s) to cloud...
   Syncing 550e8400-e29b-41d4-a716-446655440000...
   ✓ Synced 550e8400-e29b-41d4-a716-446655440000
   Syncing 660e8400-e29b-41d4-a716-446655440001...
   ✓ Synced 660e8400-e29b-41d4-a716-446655440001

✓ Sync complete: 2 synced, 0 failed

Sync Result:
  Synced: 2
  Failed: 0
  Remaining: 0

======================================================================
  EDGE AGENT DEMO COMPLETED
======================================================================

💾 Database saved to: edge_terminal.db
   Inspect with: sqlite3 edge_terminal.db
```

---

## What You've Learned

1. **Edge Architecture**: Run workflows on hardware devices
2. **Offline-First**: Work without network connectivity
3. **Floor Limits**: Approve transactions offline under thresholds
4. **Store-and-Forward**: Queue offline transactions for sync
5. **SQLite Persistence**: Embedded database for edge devices
6. **Cloud Sync**: Upload queued transactions when online

---

## Production Deployment

### Raspberry Pi Deployment

1. **Copy files to device**:
   ```bash
   scp -r rufus-edge-demo/ pi@raspberrypi:~/
   ```

2. **Install dependencies**:
   ```bash
   ssh pi@raspberrypi
   cd ~/rufus-edge-demo
   python -m venv venv
   source venv/bin/activate
   pip install 'rufus-sdk-edge[edge]'
   ```

3. **Run as systemd service**:
   ```ini
   # /etc/systemd/system/rufus-edge.service
   [Unit]
   Description=Rufus Edge Agent
   After=network.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/rufus-edge-demo
   ExecStart=/home/pi/rufus-edge-demo/venv/bin/python edge_agent.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   ```bash
   sudo systemctl enable rufus-edge
   sudo systemctl start rufus-edge
   ```

---

## Best Practices

**✅ Do:**
- Use **SQLite WAL mode** for better concurrency
- **Encrypt sensitive data** (card numbers, PINs)
- Set **floor limits** based on risk tolerance
- **Log everything** for audit compliance
- Test **offline scenarios** thoroughly
- Implement **retry logic** for sync failures

**❌ Don't:**
- Store **unencrypted card data** (PCI-DSS violation)
- Set **floor limits too high** (fraud risk)
- **Skip sync** (transactions must reach cloud)
- Use **in-memory database** (data loss on crash)
- **Ignore network errors** (implement exponential backoff)

---

## Security Considerations

### PCI-DSS Compliance

```python
# Encrypt sensitive data before storage
from cryptography.fernet import Fernet

class SecurePaymentState(BaseModel):
    encrypted_card_data: bytes  # Never store plain text!

def encrypt_card_data(card_number: str, key: bytes) -> bytes:
    f = Fernet(key)
    return f.encrypt(card_number.encode())
```

### API Key Management

```python
# Never hardcode API keys!
import os

API_KEY = os.getenv("RUFUS_API_KEY")  # From environment
CLOUD_URL = os.getenv("RUFUS_CLOUD_URL")
```

---

## Troubleshooting

**Database locked errors:**
- Enable WAL mode: `PRAGMA journal_mode=WAL`
- Close connections properly
- Avoid concurrent writes from multiple processes

**Sync failures:**
- Check network connectivity
- Verify cloud API endpoint
- Implement exponential backoff retry
- Log failed syncs for manual investigation

**High memory usage:**
- Limit sync queue size
- Clear old workflows from SQLite
- Implement database cleanup daemon

---

## Next Steps

**Try these enhancements:**
1. Add encryption for sensitive data
2. Implement cloud config push (ETag-based)
3. Add device heartbeat monitoring
4. Implement webhook delivery for critical events
5. Add metrics collection and dashboards

**Recommended Reading:**
- [Advanced: Security](../advanced/security.md) - PCI-DSS compliance
- [Advanced: Resource Management](../advanced/resource-management.md) - Memory optimization

---

## Real-World Example

The complete edge deployment example is in the repository:

```
examples/edge_deployment/
├── run_edge_rpi.py      # Raspberry Pi agent
├── run_edge_macbook.py  # MacBook agent
├── cloud_admin.py       # Cloud control plane
└── sync_manager.py      # Store-and-forward
```

Run it:

```bash
# Start cloud (in one terminal)
python examples/edge_deployment/cloud_admin.py

# Start edge agent (in another terminal)
python examples/edge_deployment/run_edge_rpi.py --cloud-url http://localhost:8000
```
