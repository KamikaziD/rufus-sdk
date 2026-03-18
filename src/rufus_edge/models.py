"""
Data models for Rufus Edge SDK.

These models define the core data structures for fintech edge operations:
- Payment state management
- Store-and-Forward transactions
- Device configuration
- Sync status tracking
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class TransactionStatus(str, Enum):
    """Status of a payment transaction."""
    PENDING = "pending"
    APPROVED = "approved"
    APPROVED_OFFLINE = "approved_offline"
    DECLINED = "declined"
    VOIDED = "voided"
    SYNCED = "synced"
    SETTLED = "settled"
    FAILED = "failed"


class SyncStatus(str, Enum):
    """Status of sync operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class DeviceStatus(str, Enum):
    """Device operational status."""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"


# ─────────────────────────────────────────────────────────────────────────────
# Payment State Model
# ─────────────────────────────────────────────────────────────────────────────

class PaymentState(BaseModel):
    """
    Workflow state for payment processing.

    This model is used as the workflow state for payment workflows.
    It tracks the complete lifecycle of a payment transaction.
    """
    # Transaction identifiers
    transaction_id: str = Field(..., description="Unique transaction ID")
    idempotency_key: str = Field(..., description="Key to prevent duplicate processing")

    # Payment details
    amount: Decimal = Field(..., description="Transaction amount")
    amount_cents: int = Field(0, description="Amount in cents for gateway APIs")
    currency: str = Field(default="USD", description="ISO currency code")

    # Card data (tokenized - NEVER store raw PAN)
    card_token: Optional[str] = Field(None, description="Tokenized card reference")
    card_last_four: Optional[str] = Field(None, description="Last 4 digits for display")
    card_type: Optional[str] = Field(None, description="Card brand: visa, mastercard, etc.")

    # Merchant info
    merchant_id: str = Field(..., description="Merchant identifier")
    terminal_id: Optional[str] = Field(None, description="Terminal/device identifier")

    # Processing state
    is_online: bool = Field(default=True, description="Network connectivity status")
    authorization_code: Optional[str] = Field(None, description="Auth code from gateway")
    gateway_response: Optional[Dict[str, Any]] = Field(None, description="Raw gateway response")

    # Offline handling
    floor_limit_checked: bool = Field(default=False, description="Floor limit validation done")
    stored_for_sync: bool = Field(default=False, description="Queued for later sync")
    offline_approved_at: Optional[datetime] = Field(None, description="When offline approval granted")

    # Result
    status: TransactionStatus = Field(default=TransactionStatus.PENDING)
    decline_reason: Optional[str] = Field(None, description="Reason for decline")
    error_message: Optional[str] = Field(None, description="Error details if failed")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(None)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-calculate cents from amount
        if self.amount and not self.amount_cents:
            self.amount_cents = int(self.amount * 100)


# ─────────────────────────────────────────────────────────────────────────────
# Store-and-Forward Transaction
# ─────────────────────────────────────────────────────────────────────────────

class SAFTransaction(BaseModel):
    """
    Store-and-Forward transaction record.

    Represents an offline transaction that needs to be synced
    to the cloud when connectivity is restored.
    """
    # Identifiers
    transaction_id: str = Field(..., description="Unique transaction ID")
    idempotency_key: str = Field(..., description="Idempotency key for deduplication")
    device_id: str = Field(..., description="Device that created this transaction")
    merchant_id: str = Field(..., description="Merchant identifier")

    # Transaction details (encrypted at rest)
    amount: Decimal = Field(..., description="Transaction amount")
    currency: str = Field(default="USD")
    card_token: str = Field(..., description="Tokenized card reference")
    card_last_four: str = Field(..., description="Last 4 digits for display")

    # Encrypted payload
    encrypted_payload: Optional[bytes] = Field(None, description="P2PE encrypted data")
    encryption_key_id: Optional[str] = Field(None, description="Key ID used for encryption")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    offline_approved_at: Optional[datetime] = Field(None)
    synced_at: Optional[datetime] = Field(None)
    settled_at: Optional[datetime] = Field(None)

    # Status tracking
    status: TransactionStatus = Field(default=TransactionStatus.APPROVED_OFFLINE)
    sync_attempts: int = Field(default=0)
    last_sync_error: Optional[str] = Field(None)
    server_transaction_id: Optional[str] = Field(None, description="ID assigned by server after sync")

    # Workflow reference
    workflow_id: Optional[str] = Field(None, description="Associated workflow ID")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Device Configuration
# ─────────────────────────────────────────────────────────────────────────────

class DeviceConfig(BaseModel):
    """
    Configuration pushed to edge devices from cloud control plane.

    This includes transaction limits, fraud rules, feature flags,
    and workflow definitions.
    """
    # Version tracking
    version: str = Field(..., description="Config version for ETag")
    updated_at: Optional[str] = Field(default=None, description="ISO timestamp of last update")

    # Transaction limits
    floor_limit: Decimal = Field(
        default=Decimal("25.00"),
        description="Max amount for offline approval"
    )
    max_offline_transactions: int = Field(
        default=100,
        description="Max offline transactions before forcing sync"
    )
    offline_timeout_hours: int = Field(
        default=24,
        description="Hours before offline transactions expire"
    )

    # Payment settings
    supported_card_types: List[str] = Field(
        default=["visa", "mastercard", "amex", "discover"],
        description="Accepted card brands"
    )
    require_pin_above: Decimal = Field(
        default=Decimal("50.00"),
        description="Require PIN for amounts above this"
    )
    require_signature_above: Decimal = Field(
        default=Decimal("25.00"),
        description="Require signature above this amount"
    )

    # Fraud rules (dynamically injected)
    fraud_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Dynamic fraud detection rules"
    )

    # Feature flags
    features: Dict[str, bool] = Field(
        default_factory=lambda: {
            "offline_mode": True,
            "contactless": True,
            "chip_fallback": True,
            "manual_entry": False,
        }
    )

    # Workflow definitions (YAML as dict)
    workflows: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Workflow definitions keyed by type"
    )

    # AI/ML Model configurations
    models: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="AI model configurations for on-device inference"
    )
    # Example model config:
    # {
    #     "anomaly_detector": {
    #         "version": "1.2.0",
    #         "url": "https://models.example.com/anomaly_v1.2.tflite",
    #         "hash": "sha256:abc123...",
    #         "runtime": "tflite",
    #         "size_kb": 312
    #     }
    # }

    # Cloud endpoints
    sync_url: Optional[str] = Field(None, description="URL for transaction sync")
    heartbeat_url: Optional[str] = Field(None, description="URL for heartbeat")

    # Sync settings
    sync_interval_seconds: int = Field(default=30)
    heartbeat_interval_seconds: int = Field(default=60)


# ─────────────────────────────────────────────────────────────────────────────
# Sync Report
# ─────────────────────────────────────────────────────────────────────────────

class SyncReport(BaseModel):
    """Report from a sync operation."""
    status: SyncStatus
    started_at: datetime
    completed_at: Optional[datetime] = None

    # Counts
    total_transactions: int = 0
    synced_count: int = 0
    failed_count: int = 0
    duplicate_count: int = 0

    # Details
    synced_ids: List[str] = Field(default_factory=list)
    failed_ids: List[str] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)

    # Server response
    server_sequence: Optional[int] = None
    next_sync_delay: int = 30


# ─────────────────────────────────────────────────────────────────────────────
# Device Health
# ─────────────────────────────────────────────────────────────────────────────

class DeviceHealth(BaseModel):
    """Device health metrics for heartbeat."""
    device_id: str
    status: DeviceStatus = DeviceStatus.ONLINE

    # Workflow counts
    active_workflows: int = 0
    pending_sync: int = 0
    completed_today: int = 0
    failed_today: int = 0

    # System metrics
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    disk_percent: Optional[float] = None

    # Network
    is_online: bool = True
    last_sync_at: Optional[datetime] = None
    last_config_pull_at: Optional[datetime] = None

    # Timestamps
    reported_at: datetime = Field(default_factory=datetime.utcnow)
