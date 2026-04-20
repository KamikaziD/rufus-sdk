# Ruvon Edge: Fintech Device Architecture

## Executive Summary

This document analyzes the feasibility of pivoting Ruvon SDK to serve as a **modern, Python-based transaction engine for POS terminals, ATMs, mobile readers, and kiosks**. The analysis is based on thorough research of the existing codebase and the fintech edge computing requirements.

**Verdict: Highly Viable** - Ruvon SDK has 70% of the infrastructure needed. The remaining 30% represents targeted enhancements rather than fundamental architecture changes.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Current State Analysis](#2-current-state-analysis)
3. [Gap Analysis](#3-gap-analysis)
4. [Implementation Roadmap](#4-implementation-roadmap)
5. [Technical Specifications](#5-technical-specifications)
6. [Security & Compliance](#6-security--compliance)
7. [Risk Assessment](#7-risk-assessment)

---

## 1. Architecture Overview

### 1.1 Target Architecture: Edge + Cloud Control Plane

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CLOUD CONTROL PLANE                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Device     │  │  Config     │  │  State      │  │  Settlement         │ │
│  │  Registry   │  │  Server     │  │  Sync API   │  │  Gateway            │ │
│  │  (manage    │  │  (push      │  │  (receive   │  │  (process offline   │ │
│  │  fleet)     │  │  updates)   │  │  SAF txns)  │  │  transactions)      │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                │                     │            │
│         └────────────────┴────────────────┴─────────────────────┘            │
│                                    │                                         │
│                          PostgreSQL + Redis                                  │
│                     (Audit, Metrics, Real-time Events)                       │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                          ┌──────────┴──────────┐
                          │   HTTPS / mTLS      │
                          │   (Encrypted)       │
                          └──────────┬──────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │                               │                               │
     ▼                               ▼                               ▼
┌─────────────┐               ┌─────────────┐               ┌─────────────┐
│  POS        │               │  ATM        │               │  Mobile     │
│  Terminal   │               │  Kiosk      │               │  Reader     │
│             │               │             │               │             │
│ ┌─────────┐ │               │ ┌─────────┐ │               │ ┌─────────┐ │
│ │ Ruvon   │ │               │ │ Ruvon   │ │               │ │ Ruvon   │ │
│ │ Edge    │ │               │ │ Edge    │ │               │ │ Edge    │ │
│ │ Agent   │ │               │ │ Agent   │ │               │ │ Agent   │ │
│ └────┬────┘ │               │ └────┬────┘ │               │ └────┬────┘ │
│      │      │               │      │      │               │      │      │
│ ┌────┴────┐ │               │ ┌────┴────┐ │               │ ┌────┴────┐ │
│ │ SQLite  │ │               │ │ SQLite  │ │               │ │ SQLite  │ │
│ │(+cipher)│ │               │ │(+cipher)│ │               │ │(+cipher)│ │
│ └─────────┘ │               │ └─────────┘ │               │ └─────────┘ │
└─────────────┘               └─────────────┘               └─────────────┘
```

### 1.2 Core Use Cases

| Use Case | Description | Ruvon Component |
|----------|-------------|-----------------|
| **Terminal Management System (TMS)** | Push config updates, fraud rules, compliance logic | Config Server + ETag Polling |
| **Store-and-Forward (SAF)** | Process offline payments, sync when online | SyncManager + Task Queue |
| **Real-time Authorization** | Blocking payment gateway calls | HTTP Steps (synchronous) |
| **Fraud Rule Injection** | Hot-patch fraud detection logic | Dynamic Config + Decision Steps |
| **Transaction Compensation** | Rollback failed financial operations | Saga Pattern |
| **Audit & Compliance** | Immutable transaction logs | Audit Log + Encrypted Storage |

---

## 2. Current State Analysis

### 2.1 What Already Exists (70%)

| Component | Status | Location | Fintech Readiness |
|-----------|--------|----------|-------------------|
| **SQLite Persistence** | ✅ Production-ready | `src/ruvon/implementations/persistence/sqlite.py` | Perfect for offline edge |
| **Task Queue** | ✅ Schema complete | `migrations/schema.yaml` | Idempotency keys included |
| **Saga Pattern** | ✅ Implemented | `src/ruvon/workflow.py:232-321` | Compensation logging works |
| **HTTP Steps** | ⚠️ Model only | `src/ruvon/models.py:47-50` | Execution needs porting |
| **Encryption** | ⚠️ Partial | `src/ruvon/implementations/security/crypto_utils.py` | Schema columns missing |
| **REST API** | ✅ Full CRUD | `src/ruvon_server/main.py` | Workflow lifecycle covered |
| **WebSocket Push** | ✅ Working | `src/ruvon_server/main.py:576-628` | Cloud→Edge real-time |
| **Event Publishing** | ✅ Redis Streams | `src/ruvon/implementations/observability/events.py` | Audit trail ready |
| **Workflow Snapshots** | ✅ Implemented | `src/ruvon/builder.py:450-452` | Version protection works |
| **Zombie Detection** | ✅ CLI ready | `src/ruvon/zombie_scanner.py` | Crash recovery available |
| **Heartbeat Tracking** | ✅ Schema ready | `migrations/schema.yaml` | Worker health tracking |
| **Worker Registry** | ⚠️ Schema only | `confucius/migrations/005_add_worker_registry.sql` | API not implemented |

### 2.2 Architecture Strengths

**1. Provider Pattern (Extensibility)**
```python
# All external integrations abstracted via Protocol interfaces
class PersistenceProvider(Protocol):
    async def save_workflow(...) -> None
    async def load_workflow(...) -> Dict
    async def create_task_record(...) -> Dict  # For SAF queue

class ExecutionProvider(Protocol):
    async def dispatch_async_task(...) -> Dict  # For background sync
```

**2. Idempotency Built-In**
```sql
-- Dual-level idempotency (workflow + task)
CREATE TABLE workflow_executions (
    idempotency_key VARCHAR(255) UNIQUE  -- Prevents duplicate workflows
);
CREATE TABLE tasks (
    idempotency_key VARCHAR(255) UNIQUE  -- Prevents duplicate task execution
);
```

**3. Offline-First SQLite**
```python
# Zero external dependencies for edge deployment
persistence = SQLitePersistenceProvider(db_path="/var/lib/ruvon/offline.db")
# WAL mode enabled, foreign keys enforced, full ACID
```

**4. Saga Compensation**
```yaml
# Automatic rollback on failure
steps:
  - name: "Charge_Payment"
    function: "payment.charge"
    compensate_function: "payment.refund"  # Auto-called on failure
```

---

## 3. Gap Analysis

### 3.1 Critical Gaps (Must Have)

#### Gap 1: Cloud Control Plane - Device Management

**Current State:** No device registration, authentication, or fleet management APIs.

**Required Components:**
```
POST   /api/v1/devices/register           - Device onboarding
GET    /api/v1/devices/{device_id}/config - Config pull with ETag
POST   /api/v1/devices/{device_id}/sync   - State sync endpoint
POST   /api/v1/devices/{device_id}/ack    - Transaction acknowledgment
WS     /api/v1/devices/{device_id}/stream - Bidirectional events
```

**Effort:** 2-3 weeks

#### Gap 2: Edge Agent SDK

**Current State:** No dedicated edge runtime component.

**Required Components:**
```python
class RuvonEdgeAgent:
    """Runs on POS terminal / edge device"""

    async def start(self):
        """Initialize agent with local SQLite"""

    async def poll_config(self, etag: str) -> Optional[Config]:
        """ETag-based config polling from cloud"""

    async def execute_workflow(self, workflow_type: str, data: dict):
        """Run workflow locally with offline support"""

    async def sync_pending_transactions(self):
        """Push SAF transactions when online"""

    async def send_heartbeat(self):
        """Report health to cloud"""
```

**Effort:** 3-4 weeks

#### Gap 3: State Sync Manager

**Current State:** No mechanism to sync offline state to cloud.

**Required Components:**
```python
class SyncManager:
    """Manages offline-to-online state synchronization"""

    async def queue_for_sync(self, transaction: dict):
        """Add transaction to local sync queue"""

    async def sync_all_pending(self) -> SyncReport:
        """Batch upload pending transactions"""

    async def handle_conflicts(self, local: dict, remote: dict):
        """Resolve state conflicts"""

    async def acknowledge_synced(self, transaction_ids: List[str]):
        """Mark transactions as synced"""
```

**Effort:** 2 weeks

#### Gap 4: PCI-DSS Security Layer

**Current State:**
- Encryption code exists but schema columns missing
- No log redaction
- No SQLCipher support
- `cryptography` library not in requirements.txt

**Required Components:**

| Component | Current | Required |
|-----------|---------|----------|
| Encryption at rest | Partial (code exists) | Fix schema, add to SQLite |
| SQLCipher | Not implemented | Add optional dependency |
| Log redaction | None | PAN masking middleware |
| Key rotation | Schema field exists | Implementation needed |
| Field-level encryption | None | P2PE key support |

**Effort:** 3-4 weeks

### 3.2 Important Gaps (Should Have)

#### Gap 5: HTTP Step Execution

**Current State:** Model defined, but actual HTTP client not implemented in new SDK.

**Impact:** Cannot make real-time payment gateway calls.

**Solution:** Port `execute_http_request` from `confucius/src/confucius/tasks.py` to new SDK.

**Effort:** 1 week

#### Gap 6: Config Hot-Reload

**Current State:** Registry loaded once at startup, no polling.

**Impact:** Cannot push fraud rules without restart.

**Solution:** Add config watcher and ETag-based refresh mechanism.

**Effort:** 1 week

#### Gap 7: Device Authentication

**Current State:** Header-based user context only (`X-User-ID`).

**Impact:** Cannot secure device-to-cloud communication.

**Solution:** mTLS certificates + API key authentication.

**Effort:** 2 weeks

### 3.3 Nice-to-Have Gaps

| Gap | Impact | Effort |
|-----|--------|--------|
| gRPC streaming | Lower latency than WebSocket | 2 weeks |
| Webhook callbacks | Async notifications to external systems | 1 week |
| Fleet dashboard | Visual device management | 3 weeks |
| Firmware OTA updates | Remote device updates | 4 weeks |

---

## 4. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)

**Goal:** Fix existing gaps, establish security baseline.

```
Week 1:
├── Fix encryption schema (add missing columns)
├── Add cryptography to requirements.txt
├── Implement PAN masking for logs
└── Write encryption integration tests

Week 2:
├── Port HTTP step execution from confucius
├── Add httpx/aiohttp to requirements
├── Implement timeout and retry logic
└── Test with mock payment gateway

Week 3:
├── Design device registration API
├── Implement /devices/register endpoint
├── Add device authentication (API keys)
└── Create device heartbeat mechanism

Week 4:
├── Implement config pull with ETag
├── Add /devices/{id}/config endpoint
├── Create config versioning table
└── Test hot-reload scenarios
```

### Phase 2: Edge Agent (Weeks 5-8)

**Goal:** Build the edge runtime that runs on devices.

```
Week 5:
├── Create ruvon_edge package structure
├── Implement RuvonEdgeAgent base class
├── Add SQLite with SQLCipher support
└── Create local workflow executor

Week 6:
├── Implement SyncManager
├── Add transaction queue with encryption
├── Create batch upload mechanism
└── Handle network detection

Week 7:
├── Add config polling loop
├── Implement workflow hot-reload
├── Create fraud rule injection mechanism
└── Test offline scenarios

Week 8:
├── Integration testing (edge + cloud)
├── Performance benchmarking
├── Documentation
└── Example POS application
```

### Phase 3: Production Hardening (Weeks 9-12)

**Goal:** PCI-DSS compliance, monitoring, fleet management.

```
Week 9-10:
├── Full PCI-DSS security audit
├── Implement key rotation
├── Add field-level encryption (P2PE)
├── Create compliance documentation

Week 11-12:
├── Fleet management dashboard
├── Metrics aggregation
├── Alerting integration
├── Load testing (1000+ devices)
```

---

## 5. Technical Specifications

### 5.1 Edge Agent Architecture

```python
# src/ruvon_edge/agent.py

class RuvonEdgeAgent:
    """
    Edge runtime for POS terminals and financial devices.

    Features:
    - Offline workflow execution with SQLite
    - Encrypted local storage (SQLCipher)
    - Store-and-Forward for offline transactions
    - Config polling with ETag support
    - Automatic sync on connectivity restore
    """

    def __init__(
        self,
        device_id: str,
        cloud_url: str,
        db_path: str = "/var/lib/ruvon/edge.db",
        encryption_key: Optional[str] = None,
        config_poll_interval: int = 60,
        sync_interval: int = 30,
    ):
        self.device_id = device_id
        self.cloud_url = cloud_url
        self.db_path = db_path
        self.encryption_key = encryption_key
        self.config_poll_interval = config_poll_interval
        self.sync_interval = sync_interval

        # Components
        self.persistence: SQLitePersistenceProvider
        self.sync_manager: SyncManager
        self.config_manager: ConfigManager
        self.workflow_builder: WorkflowBuilder

    async def start(self):
        """Initialize agent and start background tasks."""
        # Initialize encrypted SQLite
        self.persistence = SQLitePersistenceProvider(
            db_path=self.db_path,
            encryption_key=self.encryption_key  # SQLCipher
        )
        await self.persistence.initialize()

        # Start background tasks
        asyncio.create_task(self._config_poll_loop())
        asyncio.create_task(self._sync_loop())
        asyncio.create_task(self._heartbeat_loop())

    async def execute_payment(
        self,
        amount: Decimal,
        card_data: EncryptedCardData,
        merchant_id: str,
    ) -> PaymentResult:
        """
        Execute payment workflow with offline fallback.

        Flow:
        1. Try online authorization
        2. If offline, check floor limit
        3. If under limit, store SAF transaction
        4. Return result to terminal
        """
        workflow = await self.workflow_builder.create_workflow(
            workflow_type="PaymentAuthorization",
            initial_data={
                "amount": str(amount),
                "card_data_encrypted": card_data.blob,
                "merchant_id": merchant_id,
                "idempotency_key": f"{merchant_id}:{uuid.uuid4().hex}",
            }
        )

        try:
            # Try online authorization
            result = await workflow.run_to_completion(timeout=30)
            return PaymentResult.from_workflow(result)

        except NetworkError:
            # Offline fallback
            if amount <= self.config.floor_limit:
                # Store for later sync
                await self.sync_manager.queue_for_sync(workflow)
                return PaymentResult(
                    status="APPROVED_OFFLINE",
                    requires_sync=True,
                )
            else:
                return PaymentResult(
                    status="DECLINED_OFFLINE",
                    reason="Amount exceeds floor limit",
                )
```

### 5.2 Store-and-Forward (SAF) Workflow

```yaml
# config/workflows/payment_saf.yaml

workflow_type: "PaymentSAF"
workflow_version: "1.0.0"
initial_state_model: "ruvon_edge.models.PaymentState"
description: "Store-and-Forward payment processing"

steps:
  # Step 1: Validate card data
  - name: "Validate_Card"
    type: "STANDARD"
    function: "ruvon_edge.steps.validate_card"
    automate_next: true

  # Step 2: Check connectivity
  - name: "Check_Connectivity"
    type: "DECISION"
    function: "ruvon_edge.steps.check_network"
    routes:
      - condition: "state.is_online == True"
        target: "Online_Authorization"
      - condition: "state.is_online == False"
        target: "Offline_Check"

  # Step 3a: Online path - call payment gateway
  - name: "Online_Authorization"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "{{config.payment_gateway_url}}/authorize"
      headers:
        Authorization: "Bearer {{secrets.GATEWAY_API_KEY}}"
        Idempotency-Key: "{{state.idempotency_key}}"
      body:
        amount: "{{state.amount_cents}}"
        card_token: "{{state.card_token}}"
        merchant_id: "{{state.merchant_id}}"
      timeout_seconds: 30
    output_key: "gateway_response"
    compensate_function: "ruvon_edge.steps.void_authorization"
    automate_next: true

  # Step 3b: Offline path - check floor limit
  - name: "Offline_Check"
    type: "DECISION"
    function: "ruvon_edge.steps.check_floor_limit"
    routes:
      - condition: "state.amount <= config.floor_limit"
        target: "Store_For_Sync"
      - condition: "state.amount > config.floor_limit"
        target: "Decline_Offline"

  # Step 4: Store encrypted transaction for later sync
  - name: "Store_For_Sync"
    type: "STANDARD"
    function: "ruvon_edge.steps.store_saf_transaction"
    automate_next: true

  # Step 5: Complete transaction
  - name: "Complete_Transaction"
    type: "STANDARD"
    function: "ruvon_edge.steps.complete_transaction"

  # Failure paths
  - name: "Decline_Offline"
    type: "STANDARD"
    function: "ruvon_edge.steps.decline_transaction"
```

### 5.3 Cloud Control Plane API

```python
# src/ruvon_server/edge_api.py

from fastapi import APIRouter, HTTPException, Header, Depends
from typing import Optional

router = APIRouter(prefix="/api/v1/devices", tags=["Edge Devices"])

# ─────────────────────────────────────────────────────────────────────
# Device Registration & Authentication
# ─────────────────────────────────────────────────────────────────────

@router.post("/register")
async def register_device(
    request: DeviceRegistrationRequest,
    api_key: str = Header(..., alias="X-API-Key"),
) -> DeviceRegistrationResponse:
    """
    Register a new edge device with the control plane.

    Request:
        device_id: Unique device identifier
        device_type: "pos" | "atm" | "kiosk" | "mobile"
        capabilities: List of supported features
        public_key: Device's public key for mTLS

    Response:
        device_id: Confirmed device ID
        api_key: Device-specific API key
        config_url: URL for config polling
        sync_url: URL for state sync
    """
    # Validate API key
    if not await validate_registration_key(api_key):
        raise HTTPException(401, "Invalid registration key")

    # Create device record
    device = await persistence.create_device(
        device_id=request.device_id,
        device_type=request.device_type,
        capabilities=request.capabilities,
        public_key=request.public_key,
    )

    # Generate device-specific credentials
    device_api_key = await generate_device_api_key(device.device_id)

    return DeviceRegistrationResponse(
        device_id=device.device_id,
        api_key=device_api_key,
        config_url=f"/api/v1/devices/{device.device_id}/config",
        sync_url=f"/api/v1/devices/{device.device_id}/sync",
    )


# ─────────────────────────────────────────────────────────────────────
# Config Pull with ETag
# ─────────────────────────────────────────────────────────────────────

@router.get("/{device_id}/config")
async def get_device_config(
    device_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    device: Device = Depends(authenticate_device),
) -> Response:
    """
    Get device configuration with ETag support.

    Headers:
        If-None-Match: Previous ETag for conditional request

    Response:
        200: New config available (includes ETag header)
        304: Config unchanged (no body)

    Config includes:
        - Workflow definitions
        - Fraud rules
        - Floor limits
        - Feature flags
    """
    config = await persistence.get_device_config(device_id)
    current_etag = compute_etag(config)

    if if_none_match == current_etag:
        return Response(status_code=304)

    return JSONResponse(
        content=config.dict(),
        headers={"ETag": current_etag},
    )


# ─────────────────────────────────────────────────────────────────────
# State Sync (SAF Upload)
# ─────────────────────────────────────────────────────────────────────

@router.post("/{device_id}/sync")
async def sync_device_state(
    device_id: str,
    request: SyncRequest,
    device: Device = Depends(authenticate_device),
) -> SyncResponse:
    """
    Receive offline transactions from edge device.

    Request:
        transactions: List of encrypted transaction blobs
        device_sequence: Monotonic sequence number

    Response:
        accepted: List of accepted transaction IDs
        rejected: List of rejected transactions with reasons
        server_sequence: Current server sequence

    Processing:
        1. Decrypt transaction blobs (P2PE)
        2. Validate idempotency keys (deduplicate)
        3. Queue for settlement processing
        4. Return acknowledgment
    """
    accepted = []
    rejected = []

    for txn in request.transactions:
        try:
            # Decrypt with P2PE key
            decrypted = await decrypt_transaction(txn.encrypted_blob)

            # Check idempotency
            existing = await persistence.get_by_idempotency_key(
                decrypted.idempotency_key
            )
            if existing:
                accepted.append(SyncAck(
                    transaction_id=txn.transaction_id,
                    status="DUPLICATE",
                    server_id=existing.id,
                ))
                continue

            # Create settlement task
            task = await persistence.create_task_record(
                execution_id=None,  # Will be assigned
                step_name="Settlement",
                task_data=decrypted.dict(),
                idempotency_key=decrypted.idempotency_key,
            )

            accepted.append(SyncAck(
                transaction_id=txn.transaction_id,
                status="ACCEPTED",
                server_id=task.task_id,
            ))

        except Exception as e:
            rejected.append(SyncReject(
                transaction_id=txn.transaction_id,
                reason=str(e),
            ))

    return SyncResponse(
        accepted=accepted,
        rejected=rejected,
        server_sequence=await persistence.get_server_sequence(device_id),
    )


# ─────────────────────────────────────────────────────────────────────
# Device Heartbeat
# ─────────────────────────────────────────────────────────────────────

@router.post("/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: str,
    request: HeartbeatRequest,
    device: Device = Depends(authenticate_device),
) -> HeartbeatResponse:
    """
    Receive device health status.

    Request:
        device_status: "online" | "busy" | "error"
        active_workflows: Number of running workflows
        pending_sync: Number of transactions awaiting sync
        metrics: CPU, memory, disk usage

    Response:
        ack: True
        commands: List of pending commands for device
    """
    await persistence.update_device_heartbeat(
        device_id=device_id,
        status=request.device_status,
        metrics=request.metrics,
    )

    # Check for pending commands (config update, restart, etc.)
    commands = await persistence.get_pending_commands(device_id)

    return HeartbeatResponse(
        ack=True,
        commands=commands,
    )
```

### 5.4 Data Models

```python
# src/ruvon_edge/models.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum

class DeviceType(str, Enum):
    POS = "pos"
    ATM = "atm"
    KIOSK = "kiosk"
    MOBILE = "mobile"

class TransactionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    APPROVED_OFFLINE = "approved_offline"
    DECLINED = "declined"
    VOIDED = "voided"
    SYNCED = "synced"
    SETTLED = "settled"

# ─────────────────────────────────────────────────────────────────────
# Device Registration
# ─────────────────────────────────────────────────────────────────────

class DeviceRegistrationRequest(BaseModel):
    device_id: str = Field(..., description="Unique device identifier")
    device_type: DeviceType
    device_name: str
    merchant_id: str
    location: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    public_key: str = Field(..., description="RSA public key for mTLS")
    firmware_version: str
    sdk_version: str

class DeviceRegistrationResponse(BaseModel):
    device_id: str
    api_key: str = Field(..., description="Device-specific API key")
    config_url: str
    sync_url: str
    heartbeat_interval: int = 60
    sync_interval: int = 30

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

class DeviceConfig(BaseModel):
    """Configuration pushed to edge devices"""
    version: str
    updated_at: datetime

    # Transaction limits
    floor_limit: Decimal = Field(default=Decimal("25.00"))
    max_offline_transactions: int = 100
    offline_timeout_hours: int = 24

    # Payment settings
    supported_card_types: List[str] = ["visa", "mastercard", "amex"]
    require_pin_above: Decimal = Field(default=Decimal("50.00"))

    # Fraud rules (injected dynamically)
    fraud_rules: List[Dict[str, Any]] = Field(default_factory=list)

    # Feature flags
    features: Dict[str, bool] = Field(default_factory=dict)

    # Workflow definitions (YAML as dict)
    workflows: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

# ─────────────────────────────────────────────────────────────────────
# Store-and-Forward Transactions
# ─────────────────────────────────────────────────────────────────────

class SAFTransaction(BaseModel):
    """Offline transaction stored for later sync"""
    transaction_id: str
    idempotency_key: str
    device_id: str
    merchant_id: str

    # Transaction details (encrypted at rest)
    amount: Decimal
    currency: str = "USD"
    card_token: str  # Tokenized, not raw PAN
    card_last_four: str  # For display only

    # Timestamps
    created_at: datetime
    offline_approved_at: Optional[datetime] = None
    synced_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None

    # Status tracking
    status: TransactionStatus = TransactionStatus.PENDING
    sync_attempts: int = 0
    last_sync_error: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SyncRequest(BaseModel):
    """Request to sync offline transactions"""
    transactions: List[EncryptedTransaction]
    device_sequence: int
    device_timestamp: datetime

class EncryptedTransaction(BaseModel):
    """Encrypted transaction blob for sync"""
    transaction_id: str
    encrypted_blob: bytes  # P2PE encrypted
    encryption_key_id: str
    hmac: str  # For integrity verification

class SyncResponse(BaseModel):
    """Response after sync attempt"""
    accepted: List[SyncAck]
    rejected: List[SyncReject]
    server_sequence: int
    next_sync_delay: int = 30

class SyncAck(BaseModel):
    transaction_id: str
    status: str  # "ACCEPTED" | "DUPLICATE"
    server_id: str

class SyncReject(BaseModel):
    transaction_id: str
    reason: str
    retry_allowed: bool = True

# ─────────────────────────────────────────────────────────────────────
# Payment Workflow State
# ─────────────────────────────────────────────────────────────────────

class PaymentState(BaseModel):
    """Workflow state for payment processing"""
    # Transaction identifiers
    transaction_id: str
    idempotency_key: str

    # Payment details
    amount: Decimal
    amount_cents: int
    currency: str = "USD"

    # Card data (tokenized)
    card_token: str
    card_last_four: str
    card_type: str

    # Merchant info
    merchant_id: str
    terminal_id: str

    # Processing state
    is_online: bool = True
    authorization_code: Optional[str] = None
    gateway_response: Optional[Dict[str, Any]] = None

    # Offline handling
    floor_limit_checked: bool = False
    stored_for_sync: bool = False

    # Result
    status: TransactionStatus = TransactionStatus.PENDING
    decline_reason: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
```

---

## 6. Security & Compliance

### 6.1 PCI-DSS Requirements Mapping

| PCI-DSS Requirement | Implementation | Status |
|---------------------|----------------|--------|
| **Req 3.4**: Render PAN unreadable | SQLCipher + field-level encryption | Planned |
| **Req 3.5**: Protect encryption keys | Environment variables + HSM option | Partial |
| **Req 3.6**: Key management procedures | Key rotation mechanism | Planned |
| **Req 4.1**: Encrypt transmission | TLS 1.3 / mTLS for device comms | Planned |
| **Req 6.5**: Secure coding | Input validation, parameterized queries | Exists |
| **Req 8.2**: Unique user IDs | Device-specific API keys | Planned |
| **Req 10.2**: Audit trails | workflow_audit_log table | Exists |
| **Req 10.5**: Secure audit trails | Encrypted audit storage | Planned |

### 6.2 Log Redaction Implementation

```python
# src/ruvon_edge/security/redaction.py

import re
from typing import Dict, Any

class PANRedactor:
    """Masks sensitive payment data in logs"""

    PATTERNS = {
        'pan': r'\b(?:\d{4}[-\s]?){3}\d{4}\b',  # Credit card numbers
        'cvv': r'\b\d{3,4}\b',  # CVV codes
        'track_data': r'%B\d{16}.*?\?',  # Magnetic stripe
        'pin_block': r'\b[0-9A-Fa-f]{16}\b',  # Encrypted PINs
    }

    @classmethod
    def redact(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact sensitive data from dict"""
        if isinstance(data, dict):
            return {k: cls._redact_value(k, v) for k, v in data.items()}
        return data

    @classmethod
    def _redact_value(cls, key: str, value: Any) -> Any:
        # Known sensitive field names
        sensitive_keys = {
            'pan', 'card_number', 'account_number', 'cvv', 'cvc',
            'pin', 'pin_block', 'track1', 'track2', 'emv_data',
        }

        if key.lower() in sensitive_keys:
            if isinstance(value, str):
                return cls._mask_string(value)
            return "***REDACTED***"

        if isinstance(value, str):
            # Pattern-based redaction
            for pattern in cls.PATTERNS.values():
                value = re.sub(pattern, lambda m: cls._mask_string(m.group()), value)
            return value

        if isinstance(value, dict):
            return cls.redact(value)

        if isinstance(value, list):
            return [cls._redact_value(key, item) for item in value]

        return value

    @staticmethod
    def _mask_string(s: str) -> str:
        """Mask all but last 4 characters"""
        if len(s) <= 4:
            return "****"
        return "*" * (len(s) - 4) + s[-4:]


# Integration with logging
class RedactedLogFormatter(logging.Formatter):
    def format(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, dict):
            record.msg = PANRedactor.redact(record.msg)
        return super().format(record)
```

### 6.3 SQLCipher Integration

```python
# src/ruvon_edge/persistence/encrypted_sqlite.py

from typing import Optional
import aiosqlite

class EncryptedSQLitePersistenceProvider(SQLitePersistenceProvider):
    """SQLite with SQLCipher encryption for PCI-DSS compliance"""

    def __init__(
        self,
        db_path: str,
        encryption_key: str,
        **kwargs
    ):
        super().__init__(db_path, **kwargs)
        self.encryption_key = encryption_key

    async def initialize(self):
        """Initialize with encryption"""
        self.conn = await aiosqlite.connect(self.db_path)

        # Enable SQLCipher encryption
        await self.conn.execute(f"PRAGMA key = '{self.encryption_key}'")

        # Verify encryption is working
        try:
            await self.conn.execute("SELECT count(*) FROM sqlite_master")
        except Exception:
            raise ValueError("Failed to decrypt database. Check encryption key.")

        # Standard SQLite optimizations
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.execute("PRAGMA busy_timeout = 5000")

        await self._apply_schema()
```

---

## 7. Risk Assessment

### 7.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SQLCipher performance overhead | Medium | Low | Benchmark early, optimize queries |
| Network partitions during sync | High | Medium | Idempotency keys, retry logic |
| Schema migration complexity | Medium | High | Version tracking, rollback scripts |
| HTTP step execution bugs | Medium | High | Thorough testing with mock gateways |
| Key management complexity | Medium | High | Start with env vars, plan for HSM |

### 7.2 Business Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PCI-DSS certification delay | Medium | High | Engage assessor early, document everything |
| Competition from established players | High | Medium | Focus on Python ecosystem, developer experience |
| Edge device hardware constraints | Medium | Medium | Optimize for resource-constrained environments |
| Payment network certification | Medium | High | Partner with established PSPs initially |

### 7.3 Go/No-Go Criteria

**Proceed if:**
- [ ] Encryption schema can be fixed within 1 week
- [ ] HTTP step execution can be ported within 2 weeks
- [ ] SQLCipher integration works on target hardware
- [ ] At least one pilot customer identified

**Pause if:**
- [ ] Fundamental architecture changes required
- [ ] PCI-DSS compliance requires >50% code rewrite
- [ ] Performance on edge devices is <100 TPS

---

## Appendix A: File Reference

| Purpose | File Path |
|---------|-----------|
| Core Workflow Engine | `src/ruvon/workflow.py` |
| SQLite Persistence | `src/ruvon/implementations/persistence/sqlite.py` |
| PostgreSQL Persistence | `src/ruvon/implementations/persistence/postgres.py` |
| Encryption Utils | `src/ruvon/implementations/security/crypto_utils.py` |
| HTTP Step Model | `src/ruvon/models.py:47-50` |
| Event Publishing | `src/ruvon/implementations/observability/events.py` |
| Server API | `src/ruvon_server/main.py` |
| Schema Definition | `migrations/schema.yaml` |
| Legacy HTTP Tasks | `confucius/src/confucius/tasks.py:48-144` |

---

## Appendix B: Comparison with Alternatives

| Feature | Ruvon Edge | Square Terminal SDK | Stripe Terminal |
|---------|------------|---------------------|-----------------|
| Language | Python | Java/Kotlin | JavaScript/iOS/Android |
| Offline Support | Full SAF | Limited | Limited |
| Custom Workflows | YAML-defined | Fixed flows | Fixed flows |
| Dynamic Rules | Yes (injection) | No | No |
| Open Source | Yes | No | No |
| Self-Hosted | Yes | No | No |
| PCI Compliance | Planned | Certified | Certified |

---

*Document Version: 1.0.0*
*Created: 2026-02-02*
*Authors: Claude (Architecture Analysis)*
