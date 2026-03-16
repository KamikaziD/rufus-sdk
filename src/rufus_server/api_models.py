"""
API Models for Rufus Edge Cloud Control Plane.

These models define the request/response structures for the REST API.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Workflow API Models
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowStartRequest(BaseModel):
    """Request to start a new workflow."""
    workflow_type: str = Field(..., description="Type of workflow to start")
    initial_data: Dict[str, Any] = Field(default_factory=dict, description="Initial workflow state data")
    data_region: Optional[str] = Field(None, description="Data region for geo-routing")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key to prevent duplicates")


class WorkflowStartResponse(BaseModel):
    """Response after starting a workflow."""
    workflow_id: str
    current_step_name: Optional[str] = None
    status: str


class WorkflowStepRequest(BaseModel):
    """Request to advance workflow to next step."""
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Input data for the step")


class WorkflowStepResponse(BaseModel):
    """Response after executing a workflow step."""
    workflow_id: str
    current_step_name: Optional[str] = None
    next_step_name: Optional[str] = None
    status: str
    state: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStatusResponse(BaseModel):
    """Response with workflow status information."""
    workflow_id: str
    status: str
    current_step_name: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)
    workflow_type: Optional[str] = None
    parent_execution_id: Optional[str] = None
    blocked_on_child_id: Optional[str] = None
    steps_config: List[Dict[str, Any]] = Field(default_factory=list)
    current_step_info: Optional[Dict[str, Any]] = None


class ResumeWorkflowRequest(BaseModel):
    """Request to resume a paused workflow (human-in-the-loop)."""
    user_input: Dict[str, Any] = Field(default_factory=dict, description="User input data to resume the workflow")


class RetryWorkflowRequest(BaseModel):
    """Request to retry a failed workflow step."""
    workflow_id: str
    step_index: int
    retry_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Device Management Models (Fintech Edge)
# ─────────────────────────────────────────────────────────────────────────────

class DeviceRegistrationRequest(BaseModel):
    """Request to register an edge device with the control plane."""
    device_id: str = Field(..., description="Unique device identifier")
    device_type: str = Field(..., description="Device type: pos, atm, kiosk, mobile")
    device_name: str = Field(..., description="Human-readable device name")
    merchant_id: str = Field(..., description="Merchant owning this device")
    location: Optional[str] = Field(None, description="Physical location")
    capabilities: List[str] = Field(default_factory=list, description="Device capabilities")
    firmware_version: str = Field(..., description="Current firmware version")
    sdk_version: str = Field(..., description="Rufus Edge SDK version")


class DeviceRegistrationResponse(BaseModel):
    """Response after device registration."""
    device_id: str
    api_key: str = Field(..., description="Device-specific API key")
    config_url: str = Field(..., description="URL for config polling")
    sync_url: str = Field(..., description="URL for state sync")
    heartbeat_interval: int = Field(default=60, description="Heartbeat interval in seconds")


class DeviceConfigResponse(BaseModel):
    """Device configuration response."""
    version: str
    updated_at: datetime
    floor_limit: float = Field(default=25.00)
    max_offline_transactions: int = Field(default=100)
    fraud_rules: List[Dict[str, Any]] = Field(default_factory=list)
    workflows: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    features: Dict[str, bool] = Field(default_factory=dict)


class DeviceHeartbeatRequest(BaseModel):
    """Device heartbeat request."""
    device_status: str = Field(..., description="online, busy, error")
    active_workflows: int = Field(default=0)
    pending_sync: int = Field(default=0)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class DeviceHeartbeatResponse(BaseModel):
    """Device heartbeat response."""
    ack: bool = True
    commands: List[Dict[str, Any]] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Sync Models (Store-and-Forward)
# ─────────────────────────────────────────────────────────────────────────────

class EncryptedTransaction(BaseModel):
    """Encrypted transaction for sync."""
    transaction_id: str
    encrypted_blob: str = Field(..., description="Base64-encoded encrypted data")
    encryption_key_id: str
    hmac: str = Field(..., description="HMAC for integrity verification")
    # Plaintext metadata included alongside the encrypted blob
    merchant_id: str = ""
    amount_cents: int = 0
    currency: str = "USD"
    card_token: str = ""
    card_last_four: str = ""


class SyncRequest(BaseModel):
    """Request to sync offline transactions."""
    transactions: List[EncryptedTransaction]
    device_sequence: int
    device_timestamp: datetime


class SyncAck(BaseModel):
    """Acknowledgment for a synced transaction."""
    transaction_id: str
    status: str  # ACCEPTED, DUPLICATE, REJECTED
    server_id: Optional[str] = None
    reason: Optional[str] = None


class SyncResponse(BaseModel):
    """Response after sync attempt."""
    accepted: List[SyncAck]
    rejected: List[SyncAck]
    server_sequence: int
    next_sync_delay: int = Field(default=30)


# ─────────────────────────────────────────────────────────────────────────────
# Edge Workflow Sync Models
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowSyncRequest(BaseModel):
    """Batch of completed workflow executions + audit logs from an edge device."""
    workflows: List[Dict[str, Any]]
    audit_logs: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowSyncResponse(BaseModel):
    """Cloud acknowledgment after ingesting edge workflow data."""
    accepted_workflow_ids: List[str]
    audit_rows_inserted: int
    skipped: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Worker Fleet Management Models
# ─────────────────────────────────────────────────────────────────────────────

WorkerCommandType = Literal[
    'restart', 'pool_restart', 'drain', 'update_code', 'update_config',
    'pause_queue', 'resume_queue', 'set_concurrency', 'check_health'
]


class WorkerCommandRequest(BaseModel):
    """Request to send a command to a specific worker."""
    command_type: WorkerCommandType
    command_data: Dict[str, Any] = Field(default_factory=dict)
    priority: Literal['low', 'normal', 'high', 'critical'] = 'normal'
    expires_in_seconds: Optional[int] = None


class WorkerBroadcastRequest(BaseModel):
    """Request to broadcast a command to all workers (or a filtered subset)."""
    target_filter: Dict[str, Any] = Field(
        default_factory=dict,
        description="Empty dict = all workers. Keys: region, zone, or capability keys.",
    )
    command_type: str
    command_data: Dict[str, Any] = Field(default_factory=dict)
    priority: str = 'normal'
    expires_in_seconds: Optional[int] = None


class DeviceBroadcastRequest(BaseModel):
    """Broadcast a command to all (or filtered) registered edge devices."""
    command: str
    command_data: Dict[str, Any] = Field(default_factory=dict)
    target_filter: Dict[str, Any] = Field(
        default_factory=dict,
        description="Empty dict = all devices. Reserved for future tag/region filtering.",
    )
    timeout_seconds: int = 300
    priority: str = "normal"


class WorkerCommandResponse(BaseModel):
    """Worker command status response."""
    command_id: str
    worker_id: Optional[str] = None
    command_type: str
    status: str
    priority: str
    created_at: Optional[str] = None
    delivered_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class WorkerDetail(BaseModel):
    """Worker node detail response."""
    worker_id: str
    hostname: str
    region: str
    zone: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    status: str
    sdk_version: Optional[str] = None
    last_heartbeat: Optional[str] = None
    pending_command_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Definition Models
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowDefinitionUploadRequest(BaseModel):
    """Upload (create) or replace a workflow YAML definition in the DB."""
    workflow_type: str = Field(..., description="Workflow type identifier")
    yaml_content: str = Field(..., description="Full YAML workflow definition")
    description: Optional[str] = Field(None, description="Human-readable description")


class WorkflowDefinitionPatchRequest(BaseModel):
    """Update an existing workflow definition (creates a new version)."""
    yaml_content: str = Field(..., description="Updated full YAML definition")


class WorkflowDefinitionResponse(BaseModel):
    """Workflow definition metadata (no yaml_content for list views)."""
    id: int
    workflow_type: str
    version: int
    is_active: bool
    description: Optional[str] = None
    uploaded_by: Optional[str] = None
    created_at: Optional[str] = None


class WorkflowDefinitionDetailResponse(WorkflowDefinitionResponse):
    """Full workflow definition including yaml_content."""
    yaml_content: str
    resolved_config: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Server Command Models
# ─────────────────────────────────────────────────────────────────────────────

ServerCommandType = Literal[
    'reload_workflows', 'gc_caches', 'update_code', 'restart'
]


class ServerCommandRequest(BaseModel):
    """Request to queue a control-plane server command."""
    command: ServerCommandType
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Command-specific payload. update_code expects {package, version}.",
    )


class ServerCommandResponse(BaseModel):
    """Server command status."""
    id: str
    command: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str
    result: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
