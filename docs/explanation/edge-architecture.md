# Edge Architecture: Fintech Offline-First

Rufus Edge is designed for fintech edge devices—POS terminals, ATMs, mobile card readers, and kiosks that must operate offline and sync when connectivity is available.

## The Edge Computing Challenge

Traditional cloud-first architectures assume always-on connectivity:

```
POS Terminal → Network → Cloud Server → Response
```

**Problems in fintech**:
- **Network unreliable**: Basement restaurants, subway stations, rural areas
- **Latency unacceptable**: Payment must complete in < 2 seconds
- **Downtime costly**: Lost sales if terminal can't process transactions
- **Compliance required**: PCI-DSS mandates local processing for sensitive data

## Edge-First Architecture

Rufus Edge inverts the model: **edge devices are autonomous, cloud provides coordination**.

```
┌─────────────────────────────────────────┐
│          CLOUD CONTROL PLANE            │
│     (PostgreSQL + Rufus Server)         │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Device Registry API           │    │
│  │  - Register devices            │    │
│  │  - Track device status         │    │
│  └────────────────────────────────┘    │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Config Server (ETag-based)    │    │
│  │  - Push workflow updates       │    │
│  │  - Push fraud rules            │    │
│  │  - Push pricing tables         │    │
│  └────────────────────────────────┘    │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Transaction Sync API          │    │
│  │  - Receive offline transactions│    │
│  │  - Settle batches              │    │
│  │  - Reconcile ledgers           │    │
│  └────────────────────────────────┘    │
└──────────────┬───────────────────────────┘
               │
               │ HTTP/MQTT (intermittent)
               │
┌──────────────▼───────────────────────────┐
│      EDGE DEVICE (POS/ATM/Kiosk)         │
│       (SQLite + RufusEdgeAgent)          │
│                                           │
│  ┌────────────────────────────────┐     │
│  │  RufusEdgeAgent                │     │
│  │  - Run workflows locally       │     │
│  │  - SQLite persistence          │     │
│  │  - Store-and-Forward queue     │     │
│  └────────────────────────────────┘     │
│                                           │
│  ┌────────────────────────────────┐     │
│  │  SyncManager                   │     │
│  │  - Push transactions to cloud  │     │
│  │  - Pull config updates         │     │
│  │  - Handle network failures     │     │
│  └────────────────────────────────┘     │
│                                           │
│  ┌────────────────────────────────┐     │
│  │  ConfigManager                 │     │
│  │  - ETag-based update detection │     │
│  │  - Hot-reload workflows        │     │
│  │  - Version management          │     │
│  └────────────────────────────────┘     │
└───────────────────────────────────────────┘
```

## Key Concepts

### 1. Store-and-Forward (SAF)

Transactions processed offline, synced when online:

```
Customer swipes card (offline)
    ↓
Edge device validates card locally
    ↓
Workflow processes payment (SQLite)
    ↓
Transaction queued for sync
    ↓
Customer receives receipt (immediate!)
    ↓
[Hours later, network available]
    ↓
SyncManager uploads transaction batch
    ↓
Cloud settlement gateway processes
```

**Key Principle**: Customer experience is immediate, settlement is eventual.

### 2. Floor Limits

Low-value transactions approved offline, high-value deferred to cloud:

```yaml
workflow_type: "PaymentProcessing"
steps:
  - name: "Validate_Card"
    type: "STANDARD"
    function: "edge.validate_card_offline"

  - name: "Check_Amount"
    type: "DECISION"
    routes:
      - condition: "state.amount <= 50"
        target: "Approve_Offline"  # Fast path
      - condition: "state.amount > 50"
        target: "Queue_For_Cloud_Auth"  # Defer to cloud
```

**Regulation**: PCI-DSS allows offline approval up to floor limit (typically $25-$100).

### 3. Config Push (ETag-based)

Hot-deploy fraud rules without firmware updates:

```
Edge device polls: GET /api/v1/config/fraud-rules
    Headers: If-None-Match: "v1.2.0"

Cloud responds:
    304 Not Modified (config unchanged)

[Admin updates fraud rules to v1.3.0]

Edge device polls: GET /api/v1/config/fraud-rules
    Headers: If-None-Match: "v1.2.0"

Cloud responds:
    200 OK
    ETag: "v1.3.0"
    Body: {"rules": [...]}

Edge device:
    - Downloads new rules
    - Validates config
    - Hot-reloads workflows
    - Updates local ETag
```

**Benefit**: No device downtime, no firmware flash, instant deployment.

### 4. Encryption at Rest

Edge devices store sensitive data encrypted:

```python
# src/rufus_edge/encryption.py
from cryptography.fernet import Fernet

class EncryptedPersistence:
    def __init__(self, sqlite_path, encryption_key):
        self.sqlite = SQLitePersistenceProvider(sqlite_path)
        self.cipher = Fernet(encryption_key)

    async def save_workflow(self, workflow_id, workflow_dict):
        # Encrypt sensitive fields
        encrypted_state = self.cipher.encrypt(
            json.dumps(workflow_dict['state']).encode()
        )

        workflow_dict['state'] = encrypted_state.decode()
        await self.sqlite.save_workflow(workflow_id, workflow_dict)
```

**Compliance**: Meets PCI-DSS requirement for data-at-rest encryption.

## Edge Device Capabilities

### Offline Operations

**What works offline**:
- ✅ Card validation (EMV chip, magnetic stripe)
- ✅ PIN verification (local secure element)
- ✅ Floor limit approval (< $50)
- ✅ Receipt printing
- ✅ Transaction logging
- ✅ Fraud rule evaluation (locally cached rules)

**What requires connectivity**:
- ❌ High-value authorization (> floor limit)
- ❌ Real-time fraud scoring (cloud ML models)
- ❌ Account balance checks
- ❌ Multi-currency conversion (live exchange rates)
- ❌ Settlement

### Hardware Integration

```python
# src/rufus_edge/hardware/
├── card_reader.py       # EMV/MSR/contactless
├── pin_pad.py           # Secure PIN entry
├── printer.py           # Receipt printer
├── display.py           # Customer/merchant display
└── secure_element.py    # Crypto operations
```

**Example: Card validation**:
```python
from rufus_edge.hardware import CardReader

def validate_card_offline(state: PaymentState, context: StepContext) -> dict:
    reader = CardReader()

    # Read card
    card_data = reader.read_emv_chip()

    # Validate locally
    if not card_data.is_valid_checksum():
        return {"approved": False, "reason": "invalid_card"}

    # Check expiration
    if card_data.is_expired():
        return {"approved": False, "reason": "expired_card"}

    # Check against local blacklist
    if card_data.pan in state.blacklisted_cards:
        return {"approved": False, "reason": "blocked_card"}

    return {
        "approved": True,
        "card_type": card_data.card_type,
        "masked_pan": card_data.masked_pan
    }
```

## Sync Strategies

### 1. Push on Connectivity

Device detects network, immediately syncs:

```python
class SyncManager:
    async def on_network_available(self):
        # Network just came online
        await self.sync_pending_transactions()
        await self.sync_config_updates()

    async def sync_pending_transactions(self):
        # Get all unsynced transactions
        pending = await self.persistence.list_workflows(
            status="COMPLETED",
            synced=False
        )

        # Upload batch
        batch = [self.serialize_transaction(w) for w in pending]
        response = await self.cloud_api.post("/api/v1/transactions/batch", batch)

        # Mark as synced
        for workflow_id in response['synced_ids']:
            await self.persistence.mark_synced(workflow_id)
```

### 2. Scheduled Batch Sync

Device syncs every N minutes, regardless of connectivity:

```python
async def scheduled_sync_daemon(sync_manager):
    while True:
        try:
            await sync_manager.sync_pending_transactions()
        except NetworkError:
            logger.warning("Sync failed, will retry")

        await asyncio.sleep(300)  # 5 minutes
```

### 3. Low-Priority Background Sync

Sync only when device idle:

```python
class SyncManager:
    async def background_sync(self):
        # Check if device is idle (no active workflows)
        active_count = await self.persistence.count_workflows(status="ACTIVE")

        if active_count == 0:
            # Device idle, safe to sync
            await self.sync_pending_transactions()
        else:
            # Device busy, defer sync
            logger.debug("Deferring sync, device busy")
```

## Use Cases

### 1. POS Terminal (Retail)

**Scenario**: Coffee shop in subway station with spotty WiFi.

**Workflow**:
```yaml
workflow_type: "CoffeePurchase"
steps:
  - name: "Read_Card"
    type: "STANDARD"
    function: "edge.read_card"

  - name: "Check_Floor_Limit"
    type: "DECISION"
    routes:
      - condition: "state.amount <= 25"
        target: "Approve_Offline"
      - default: "Queue_For_Auth"

  - name: "Approve_Offline"
    type: "STANDARD"
    function: "edge.approve_offline"

  - name: "Print_Receipt"
    type: "STANDARD"
    function: "edge.print_receipt"

  - name: "Queue_For_Settlement"
    type: "STANDARD"
    function: "edge.queue_for_sync"
```

**Result**: Customer gets receipt in 2 seconds, settlement happens hours later.

### 2. ATM (Cash Withdrawal)

**Scenario**: ATM in rural area with slow satellite link.

**Offline capability**:
- Card validation
- PIN verification
- Balance check (cached from last sync)
- Dispense cash (up to daily limit)
- Update local ledger
- Queue withdrawal for settlement

**Online requirement**:
- Balance updates synced every 5 minutes
- High-value withdrawals (> $500) require real-time auth

### 3. Mobile Card Reader (Delivery)

**Scenario**: Food delivery driver with mobile reader, roaming between dead zones.

**Workflow**:
```yaml
workflow_type: "DeliveryPayment"
steps:
  - name: "Validate_Card"
  - name: "Approve_Offline"  # Always offline (< $100)
  - name: "Update_Delivery_Status"
  - name: "Queue_For_Sync"
```

**Sync strategy**: Batch upload at end of shift.

## Security Considerations

### 1. Device Authentication

Each device has unique credentials:

```python
# Device registration
device_id = "POS-12345"
device_secret = generate_secret()  # Stored in secure element

# API authentication
headers = {
    "Authorization": f"Device {device_id}:{sign(device_secret, request_body)}"
}
```

### 2. Transaction Integrity

Transactions signed with device key:

```python
transaction = {
    "amount": 50.00,
    "timestamp": "2026-02-13T10:15:00Z",
    "card_hash": "...",
}

signature = sign(device_secret, transaction)
transaction['signature'] = signature

# Cloud verifies signature
if not verify_signature(transaction, device_public_key):
    reject("Invalid signature")
```

### 3. Config Validation

Downloaded configs validated before loading:

```python
def validate_config(config, expected_checksum):
    # Verify checksum
    if sha256(config) != expected_checksum:
        raise ConfigCorruptionError("Checksum mismatch")

    # Validate schema
    ConfigSchema.validate(config)

    # Check signature
    if not verify_signature(config, cloud_public_key):
        raise ConfigTamperingError("Invalid signature")

    return config
```

## Deployment

### Edge Agent Installation

```bash
# Install Rufus Edge Agent
pip install rufus-edge

# Generate device credentials
rufus-edge register --device-type POS --location "Store-123"
# Outputs: device_id, device_secret

# Start agent
rufus-edge start --device-id POS-12345 --secret <device-secret>
```

### Cloud Server Setup

```bash
# Deploy Rufus Server with edge endpoints
docker-compose -f docker/docker-compose.edge.yml up -d

# Registers edge API routes:
# - POST /api/v1/devices/register
# - GET /api/v1/devices/{device_id}/config
# - POST /api/v1/transactions/batch
# - GET /api/v1/devices/{device_id}/commands
```

## Monitoring

### Edge Device Metrics

```python
# Device health
await device_api.report_metrics({
    "disk_usage_percent": 45,
    "memory_usage_mb": 128,
    "pending_transactions": 15,
    "last_sync": "2026-02-13T10:00:00Z",
    "network_available": False
})
```

### Cloud Dashboard

```
Device Status:
├── Online: 850 devices
├── Offline (< 1h): 120 devices
├── Offline (> 24h): 5 devices (ALERT!)
└── Total: 975 devices

Pending Transactions:
├── Last hour: 1,245 transactions
├── Last 24h: 18,567 transactions
├── Unsynced: 3,421 transactions (ALERT!)

Config Version Distribution:
├── v1.5.0: 920 devices (95%)
├── v1.4.0: 50 devices (5%)
└── v1.3.0: 5 devices (OUTDATED!)
```

## What's Next

Now that you understand edge architecture:
- [Architecture](architecture.md) - How edge fits into overall Rufus architecture
- [State Management](state-management.md) - Offline state persistence
- [Performance](performance.md) - Edge device performance characteristics
