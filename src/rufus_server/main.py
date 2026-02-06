"""
Rufus Edge Cloud Control Plane Server.

This FastAPI server provides:
- Workflow management APIs
- Device registration and management (TODO)
- Config push with ETag polling (TODO)
- State sync for Store-and-Forward transactions (TODO)
"""

import sys
import os
import json
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import importlib.resources
from dotenv import load_dotenv
import yaml
import asyncio
from typing import Optional, Any, Dict, List
import logging

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Import Rufus SDK Components ---
from rufus.engine import WorkflowEngine
from rufus.models import WorkflowJumpDirective, WorkflowPauseDirective
from rufus.workflow import Workflow
from rufus.builder import WorkflowBuilder
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.execution.thread_pool import ThreadPoolExecutorProvider
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

# --- API Models ---
from rufus_server.api_models import (
    WorkflowStartRequest, WorkflowStartResponse, WorkflowStepRequest, WorkflowStepResponse,
    WorkflowStatusResponse, ResumeWorkflowRequest, RetryWorkflowRequest,
    DeviceRegistrationRequest, DeviceRegistrationResponse, DeviceHeartbeatRequest,
    DeviceHeartbeatResponse, SyncRequest, SyncResponse
)

# --- FastAPI App Setup ---
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Initialize limiter for rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Rufus Edge Control Plane",
    description="Cloud control plane for Rufus Edge fintech devices",
    version="0.1.0"
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Device Service ---
from rufus_server.device_service import DeviceService

# --- Policy Engine ---
from rufus_server.policy_engine import (
    Policy, PolicyRule, PolicyStatus, RolloutConfig, RolloutStrategy,
    PolicyEvaluator, DeviceCheckIn, UpdateInstruction, DeviceAssignment,
    AssignmentStatus,
)

# --- Global Instances ---
persistence_provider: Optional[PersistenceProvider] = None
execution_provider: Optional[ExecutionProvider] = None
workflow_observer: Optional[WorkflowObserver] = None
workflow_engine: Optional[WorkflowEngine] = None
workflow_registry_config: Dict[str, Any] = {}
device_service: Optional[DeviceService] = None
policy_evaluator: Optional[PolicyEvaluator] = None
device_assignments: Dict[str, DeviceAssignment] = {}  # In-memory for now
version_service = None  # Command version service
webhook_service = None  # Webhook notification service


# --- User Context ---
class UserContext(BaseModel):
    user_id: str
    org_id: Optional[str] = None


async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_org_id: Optional[str] = Header(None, alias="X-Org-ID")
) -> Optional[UserContext]:
    if x_user_id:
        return UserContext(user_id=x_user_id, org_id=x_org_id)
    return None


# --- Rate Limiting Dependency ---
def rate_limit_check(resource_pattern: str):
    """
    Dependency that checks rate limits before endpoint execution.

    Args:
        resource_pattern: Resource pattern to match (e.g., '/api/v1/commands')

    Usage:
        @app.post("/api/v1/devices/{device_id}/commands")
        async def endpoint(
            ...,
            _: None = rate_limit_check("/api/v1/commands")
        ):
            ...
    """
    async def dependency(request: Request, user: Optional[UserContext] = Depends(get_current_user)):
        if not rate_limit_service:
            return None  # Rate limiting not initialized

        # Get identifier (user or IP)
        identifier = f"user:{user.user_id}" if user else f"ip:{request.client.host}"
        scope = "user" if user else "ip"

        # Check limit
        result = await rate_limit_service.check_rate_limit(
            identifier, resource_pattern, scope
        )

        # Raise 429 if exceeded
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Try again in {result.retry_after}s",
                headers={
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(result.reset_at.timestamp())),
                    "Retry-After": str(result.retry_after)
                }
            )

        # Record request and store for headers
        await rate_limit_service.record_request(identifier, resource_pattern, scope)
        request.state.rate_limit_info = result
        return None

    return Depends(dependency)


# --- Rate Limit Response Middleware ---
@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):
    """Add X-RateLimit-* headers to responses."""
    response = await call_next(request)

    if hasattr(request.state, "rate_limit_info"):
        info = request.state.rate_limit_info
        response.headers["X-RateLimit-Limit"] = str(info.limit)
        response.headers["X-RateLimit-Remaining"] = str(info.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(info.reset_at.timestamp()))

    return response


# --- Startup/Shutdown ---
@app.on_event("startup")
async def startup_event():
    global persistence_provider, execution_provider, workflow_observer, workflow_engine, workflow_registry_config
    global rate_limit_service, version_service, webhook_service

    # Load workflow registry
    RUFUS_WORKFLOW_REGISTRY_PATH = os.getenv("RUFUS_WORKFLOW_REGISTRY_PATH", "config/workflow_registry.yaml")
    try:
        with open(RUFUS_WORKFLOW_REGISTRY_PATH, "r") as f:
            workflow_registry_config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: Workflow registry not found at {RUFUS_WORKFLOW_REGISTRY_PATH}.")
        workflow_registry_config = {"workflows": []}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in workflow registry: {e}")

    # Persistence Provider
    persistence_backend = os.getenv('WORKFLOW_STORAGE', 'sqlite').lower()
    if persistence_backend == 'postgres':
        DATABASE_URL = os.getenv('DATABASE_URL')
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL must be set for PostgreSQL persistence.")
        persistence_provider = PostgresPersistenceProvider(DATABASE_URL)
    elif persistence_backend == 'sqlite':
        DB_PATH = os.getenv('SQLITE_DB_PATH', 'rufus_edge.db')
        persistence_provider = SQLitePersistenceProvider(db_path=DB_PATH)
    else:  # Default to in-memory
        persistence_provider = InMemoryPersistence()

    await persistence_provider.initialize()

    # Workflow Observer (simple logging for now)
    workflow_observer = LoggingObserver()

    # Execution Provider
    execution_backend = os.getenv('WORKFLOW_EXECUTION_BACKEND', 'sync').lower()
    if execution_backend == 'threadpool':
        execution_provider = ThreadPoolExecutorProvider()
    else:  # Default to sync
        execution_provider = SyncExecutor()

    # WorkflowEngine
    workflow_engine = WorkflowEngine(
        persistence=persistence_provider,
        executor=execution_provider,
        observer=workflow_observer,
        workflow_registry={wf['type']: wf for wf in workflow_registry_config.get("workflows", [])},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    # Initialize Version Service
    from rufus_server.version_service import VersionService
    version_service = VersionService(persistence_provider)

    # Initialize Webhook Service
    from rufus_server.webhook_service import WebhookService
    webhook_service = WebhookService(persistence_provider)

    # Initialize Device Service (with version and webhook services)
    global device_service
    device_service = DeviceService(persistence_provider, version_service, webhook_service)

    # Initialize Policy Engine
    global policy_evaluator
    policy_evaluator = PolicyEvaluator()

    # Initialize Rate Limit Service
    from rufus_server.rate_limit_service import RateLimitService
    rate_limit_service = RateLimitService(persistence_provider)

    print("Rufus Edge Control Plane started.")


@app.on_event("shutdown")
async def shutdown_event():
    global persistence_provider, execution_provider, workflow_observer
    if persistence_provider:
        await persistence_provider.close()
    if execution_provider:
        await execution_provider.close()
    print("Rufus Edge Control Plane shut down.")


# ─────────────────────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "rufus-edge-control-plane"}


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Management APIs
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/workflows")
async def get_available_workflows():
    """Returns a list of available workflows from the registry."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    available_workflows = []
    for wf_type, wf_config in workflow_engine.workflow_registry.items():
        processed_config = workflow_engine.workflow_builder.get_workflow_config(wf_type)
        available_workflows.append({
            "type": wf_type,
            "description": processed_config.get("description", "No description provided."),
            "parameters": processed_config.get("parameters", {}),
        })
    return available_workflows


@app.post("/api/v1/workflow/start", response_model=WorkflowStartResponse)
@limiter.limit("100/minute")
async def start_workflow(
    request: Request,
    request_data: WorkflowStartRequest,
    user: Optional[UserContext] = Depends(get_current_user),
    _: None = rate_limit_check("/api/v1/workflow/start")
):
    """Start a new workflow."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        new_workflow = await workflow_engine.start_workflow(
            workflow_type=request_data.workflow_type,
            initial_data=request_data.initial_data,
            owner_id=user.user_id if user else None,
            org_id=user.org_id if user else None,
            data_region=request_data.data_region,
            idempotency_key=request_data.idempotency_key
        )
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {e}")

    return WorkflowStartResponse(
        workflow_id=new_workflow.id,
        current_step_name=new_workflow.current_step_name,
        status=new_workflow.status
    )


@app.get("/api/v1/workflow/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get workflow status."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id)

    return WorkflowStatusResponse(
        workflow_id=workflow.id,
        status=workflow.status,
        current_step_name=workflow.current_step_name,
        state=workflow.state.model_dump(),
        workflow_type=workflow.workflow_type,
        parent_execution_id=workflow.parent_execution_id,
        blocked_on_child_id=workflow.blocked_on_child_id
    )


@app.post("/api/v1/workflow/{workflow_id}/next", response_model=WorkflowStepResponse)
async def next_workflow_step(
    workflow_id: str,
    request_data: WorkflowStepRequest,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Execute the next step in a workflow."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id)

    if workflow.status in ["PENDING_ASYNC", "WAITING_HUMAN", "COMPLETED", "FAILED"]:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is in '{workflow.status}' state. Cannot advance."
        )

    current_step_obj = workflow.workflow_steps[workflow.current_step]

    try:
        result_dict, next_step_name = await workflow.next_step(user_input=request_data.input_data)

        return WorkflowStepResponse(
            workflow_id=workflow.id,
            current_step_name=current_step_obj.name,
            next_step_name=next_step_name,
            status=workflow.status,
            state=workflow.state.model_dump(),
            result=result_dict
        )
    except Exception as e:
        workflow.status = "FAILED"
        await workflow_engine.persistence.save_workflow(workflow_id, workflow.to_dict())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/workflows/executions")
async def get_workflow_executions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """List workflow executions."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    filters = {}
    if status:
        filters['status'] = status

    workflow_list = await workflow_engine.persistence.list_workflows(**filters)
    return workflow_list[offset:offset+limit]


# ─────────────────────────────────────────────────────────────────────────────
# Device Management APIs (TODO: Implement)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/devices/register", response_model=DeviceRegistrationResponse)
async def register_device(
    request_data: DeviceRegistrationRequest,
    x_registration_key: str = Header(..., alias="X-Registration-Key")
):
    """Register an edge device with the control plane."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Validate registration key (in production, verify against allowed keys)
    expected_key = os.getenv("RUFUS_REGISTRATION_KEY", "dev-registration-key")
    if x_registration_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid registration key")

    try:
        result = await device_service.register_device(
            device_id=request_data.device_id,
            device_type=request_data.device_type,
            device_name=request_data.device_name,
            merchant_id=request_data.merchant_id,
            firmware_version=request_data.firmware_version,
            sdk_version=request_data.sdk_version,
            location=request_data.location,
            capabilities=request_data.capabilities,
        )
        return DeviceRegistrationResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")


@app.get("/api/v1/devices")
async def list_devices(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    List all registered devices.

    Automatically marks devices as offline if they haven't sent
    a heartbeat in the last 120 seconds (2 minutes).
    """
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # In production, filter by org_id from user context
    devices = await device_service.list_devices(
        status=status,
        limit=limit,
        offset=offset
    )

    # Update device statuses based on heartbeat timestamps
    from datetime import datetime, timedelta, timezone
    offline_threshold = timedelta(seconds=120)  # 2 minutes
    now = datetime.now(timezone.utc)  # Use timezone-aware datetime

    for device in devices:
        last_heartbeat = device.get('last_heartbeat_at')
        current_status = device.get('status', 'online')

        if last_heartbeat:
            # Ensure timezone-aware comparison
            if not hasattr(last_heartbeat, 'tzinfo') or last_heartbeat.tzinfo is None:
                # Make naive datetime timezone-aware (assume UTC)
                last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)

            # Check if device is stale
            if (now - last_heartbeat) > offline_threshold:
                device['status'] = 'offline'
        elif current_status == 'online':
            # Device never sent heartbeat but marked online - mark as offline
            device['status'] = 'offline'

    return {
        "total": len(devices),
        "devices": devices,
        "limit": limit,
        "offset": offset
    }


@app.get("/api/v1/devices/{device_id}")
async def get_device(
    device_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get details of a specific device."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    device = await device_service.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    return device


@app.get("/api/v1/devices/{device_id}/config")
async def get_device_config(
    device_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Get device configuration with ETag support for caching."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Authenticate device
    if not await device_service.authenticate_device(device_id, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Get active config
    config = await device_service.get_active_config()
    if not config:
        # Return default config if none exists
        config = {
            "config_version": "default",
            "etag": "default",
            "config_data": json.dumps({
                "floor_limit": 25.00,
                "max_offline_transactions": 100,
                "fraud_rules": [],
                "features": {"offline_mode": True},
                "workflows": {},
            })
        }

    current_etag = config.get("etag", "")

    # Check If-None-Match for caching
    if if_none_match and if_none_match == current_etag:
        return Response(status_code=304)

    # Parse config_data if it's a string
    config_data = config.get("config_data", "{}")
    if isinstance(config_data, str):
        config_data = json.loads(config_data)

    return JSONResponse(
        content={
            "version": config.get("config_version"),
            "updated_at": config.get("created_at"),
            **config_data,
        },
        headers={"ETag": current_etag}
    )


@app.post("/api/v1/devices/{device_id}/heartbeat", response_model=DeviceHeartbeatResponse)
async def device_heartbeat(
    device_id: str,
    request_data: DeviceHeartbeatRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    Receive device heartbeat and return pending commands.

    Note: API key is optional for heartbeats in demo mode.
    In production, enable authentication.
    """
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Skip authentication for demo - in production, uncomment this:
    # if x_api_key and not await device_service.authenticate_device(device_id, x_api_key):
    #     raise HTTPException(status_code=401, detail="Invalid API key")

    result = await device_service.process_heartbeat(
        device_id=device_id,
        status=request_data.device_status,
        metrics=request_data.metrics,
    )

    return DeviceHeartbeatResponse(**result)


@app.post("/api/v1/devices/{device_id}/sync", response_model=SyncResponse)
async def sync_device_transactions(
    device_id: str,
    request_data: SyncRequest,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Receive offline transactions from edge device (Store-and-Forward)."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Authenticate device
    if not await device_service.authenticate_device(device_id, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Convert request transactions to dict format
    transactions = [
        {
            "transaction_id": t.transaction_id,
            "idempotency_key": f"{device_id}:{t.transaction_id}",
            "encrypted_payload": t.encrypted_blob,
            "encryption_key_id": t.encryption_key_id,
        }
        for t in request_data.transactions
    ]

    result = await device_service.sync_transactions(
        device_id=device_id,
        transactions=transactions,
    )

    # Convert to response format
    from rufus_server.api_models import SyncAck
    return SyncResponse(
        accepted=[SyncAck(**a) for a in result["accepted"]],
        rejected=[SyncAck(**r) for r in result["rejected"]],
        server_sequence=result.get("server_sequence", 0),
        next_sync_delay=30,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Static Files (optional debug UI)
# ─────────────────────────────────────────────────────────────────────────────

contrib_static_path = Path(__file__).parent / "contrib" / "static"
if contrib_static_path.is_dir():
    app.mount("/static", StaticFiles(directory=contrib_static_path), name="rufus_static")

templates_path = Path(__file__).parent / "contrib" / "templates"
if templates_path.is_dir():
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=templates_path)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def read_root(request: Request):
        """Serves the debug UI's main page."""
        return templates.TemplateResponse("index.html", {"request": request})


# ─────────────────────────────────────────────────────────────────────────────
# Policy Engine APIs
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/policies", response_model=Policy)
async def create_policy(
    policy: Policy,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Create a new deployment policy."""
    if policy_evaluator is None:
        raise HTTPException(status_code=503, detail="Policy engine not initialized")

    policy.created_by = user.user_id if user else None
    policy_evaluator.add_policy(policy)

    return policy


@app.get("/api/v1/policies", response_model=List[Policy])
async def list_policies(
    status: Optional[PolicyStatus] = None,
):
    """List all policies, optionally filtered by status."""
    if policy_evaluator is None:
        raise HTTPException(status_code=503, detail="Policy engine not initialized")

    policies = list(policy_evaluator._policies.values())

    if status:
        policies = [p for p in policies if p.status == status]

    return policies


@app.get("/api/v1/policies/{policy_id}", response_model=Policy)
async def get_policy(policy_id: str):
    """Get a specific policy by ID."""
    if policy_evaluator is None:
        raise HTTPException(status_code=503, detail="Policy engine not initialized")

    from uuid import UUID
    try:
        pid = UUID(policy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid policy ID format")

    policy = policy_evaluator._policies.get(pid)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    return policy


@app.put("/api/v1/policies/{policy_id}/status")
async def update_policy_status(
    policy_id: str,
    new_status: PolicyStatus,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Update policy status (activate, pause, archive)."""
    if policy_evaluator is None:
        raise HTTPException(status_code=503, detail="Policy engine not initialized")

    from uuid import UUID
    try:
        pid = UUID(policy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid policy ID format")

    policy = policy_evaluator._policies.get(pid)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    from datetime import datetime
    policy.status = new_status
    policy.updated_at = datetime.utcnow()

    return {"status": "updated", "new_status": new_status}


@app.post("/api/v1/update-check", response_model=UpdateInstruction)
@limiter.limit("60/minute")
async def check_for_update(
    request: Request,
    checkin: DeviceCheckIn,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Device check-in endpoint for update polling.

    The device sends its hardware identity, and the Policy Engine
    evaluates all active policies to determine if an update is needed.

    Auto-registers devices on first check-in.
    """
    if policy_evaluator is None:
        raise HTTPException(status_code=503, detail="Policy engine not initialized")

    # Authenticate device (in production, verify X-API-Key)
    # For now, just log the check-in
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Device check-in: {checkin.device_id} ({checkin.hw})")

    # Auto-register device if it doesn't exist
    existing_device = await device_service.get_device(checkin.device_id)
    if not existing_device:
        try:
            logger.info(f"Auto-registering device: {checkin.device_id}")
            await device_service.register_device(
                device_id=checkin.device_id,
                device_type=checkin.hw,
                device_name=f"{checkin.platform} {checkin.arch}",
                merchant_id="auto-registered",
                firmware_version="unknown",
                sdk_version="unknown",
                location=None,
                capabilities=checkin.accelerators,
                public_key=None
            )
        except Exception as e:
            logger.warning(f"Auto-registration failed for {checkin.device_id}: {e}")
            # Continue with update check even if registration fails

    # Convert check-in to hardware identity dict
    hw_identity = checkin.model_dump()

    # Check current assignment
    current_assignment = device_assignments.get(checkin.device_id)

    # Evaluate policies
    assignment = policy_evaluator.get_assignment(
        device_id=checkin.device_id,
        hardware_identity=hw_identity,
    )

    if not assignment:
        return UpdateInstruction(
            needs_update=False,
            message="No matching policy found"
        )

    # Check canary status
    policy = policy_evaluator._policies.get(assignment.policy_id)
    if policy and not policy_evaluator.should_deploy_canary(checkin.device_id, policy):
        return UpdateInstruction(
            needs_update=False,
            message="Device not in canary rollout group"
        )

    # Check if update is needed
    if checkin.current_artifact == assignment.assigned_artifact:
        if checkin.current_hash and assignment.artifact_hash:
            if checkin.current_hash == assignment.artifact_hash:
                return UpdateInstruction(
                    needs_update=False,
                    message="Already running latest version"
                )

    # Store assignment
    device_assignments[checkin.device_id] = assignment

    # Generate artifact URL (use full URL for edge devices)
    # Get base URL from request or environment
    base_url = os.getenv("PUBLIC_URL", f"http://{request.client.host}:8000")
    # If request came from localhost/127.0.0.1, use localhost:8000
    if request.client.host in ("127.0.0.1", "::1", "localhost"):
        base_url = "http://localhost:8000"

    artifact_url = f"{base_url}/api/v1/artifacts/{assignment.assigned_artifact}"

    return UpdateInstruction(
        needs_update=True,
        artifact=assignment.assigned_artifact,
        artifact_url=artifact_url,
        artifact_hash=assignment.artifact_hash,
        policy_id=assignment.policy_id,
        policy_version=assignment.policy_version,
        message="Update available"
    )


@app.post("/api/v1/devices/{device_id}/update-status")
async def report_update_status(
    device_id: str,
    status: AssignmentStatus,
    error_message: Optional[str] = None,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Report artifact installation status."""
    assignment = device_assignments.get(device_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="No assignment found for device")

    from datetime import datetime
    assignment.status = status

    if status == AssignmentStatus.INSTALLED:
        assignment.installed_at = datetime.utcnow()
        assignment.current_artifact = assignment.assigned_artifact
        assignment.current_hash = assignment.artifact_hash
    elif status == AssignmentStatus.FAILED:
        assignment.failed_at = datetime.utcnow()
        assignment.error_message = error_message
        assignment.retry_count += 1
    elif status == AssignmentStatus.DOWNLOADING:
        assignment.downloaded_at = datetime.utcnow()

    return {"status": "recorded", "assignment_status": status}


@app.get("/api/v1/devices/{device_id}/assignment")
async def get_device_assignment(
    device_id: str,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Get current artifact assignment for a device."""
    assignment = device_assignments.get(device_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="No assignment found for device")

    return assignment


@app.get("/api/v1/artifacts/{artifact_name}")
async def download_artifact(artifact_name: str):
    """
    Download artifact file for edge devices.

    In production, this would serve from cloud storage (S3, GCS).
    For demo, serves from local artifacts directory.
    """
    from fastapi.responses import FileResponse
    import os

    # Artifact storage directory
    artifacts_dir = os.getenv("ARTIFACTS_DIR", "/tmp/rufus-artifacts")

    # Security: validate artifact name (prevent path traversal)
    if ".." in artifact_name or "/" in artifact_name or "\\" in artifact_name:
        raise HTTPException(status_code=400, detail="Invalid artifact name")

    artifact_path = os.path.join(artifacts_dir, artifact_name)

    # Check if artifact exists
    if not os.path.exists(artifact_path):
        raise HTTPException(
            status_code=404,
            detail=f"Artifact not found: {artifact_name}"
        )

    # Return file for download
    return FileResponse(
        path=artifact_path,
        filename=artifact_name,
        media_type="application/octet-stream"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Remote Command System
# ─────────────────────────────────────────────────────────────────────────────

from rufus_server.command_types import (
    CommandType, CommandPriority, DeviceCommand,
    get_command_priority, should_use_websocket
)

# WebSocket connections for real-time commands
websocket_connections: Dict[str, WebSocket] = {}


@app.post("/api/v1/devices/{device_id}/commands")
async def send_device_command(
    device_id: str,
    command: DeviceCommand,
    user: Optional[UserContext] = Depends(get_current_user),
    _: None = rate_limit_check("/api/v1/commands")
):
    """
    Send a command to an edge device.

    Commands are routed based on priority:
    - CRITICAL: Sent via WebSocket (if connected), otherwise queued
    - HIGH/NORMAL/LOW: Queued and delivered via heartbeat

    Example commands:
    ```json
    {
      "type": "restart",
      "data": {"delay_seconds": 10},
      "priority": "normal"
    }
    ```

    Command types:
    - Device: restart, shutdown, reboot
    - Config: update_config, reload_config
    - Maintenance: backup, schedule_backup, clear_cache, health_check
    - Workflow: start_workflow, cancel_workflow, retry_workflow
    - Critical: emergency_stop, fraud_alert, security_lockdown
    """
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Validate device exists
    device = await device_service.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Determine priority and routing
    priority = get_command_priority(command.type)
    use_websocket = should_use_websocket(command.type)

    # Try WebSocket first for critical commands
    if use_websocket and device_id in websocket_connections:
        ws = websocket_connections[device_id]
        try:
            await ws.send_json({
                "type": "command",
                "command": command.to_dict()
            })
            return {
                "command_id": None,  # WebSocket commands don't get queued
                "device_id": device_id,
                "type": command.type,
                "status": "sent_via_websocket",
                "delivery": "immediate"
            }
        except Exception as e:
            logger.warning(f"WebSocket send failed, falling back to queue: {e}")

    # Queue command for heartbeat delivery
    command_id = await device_service.send_command(
        device_id=device_id,
        command_type=command.type,
        command_data=command.data,
        command_version=command.version,
        expires_in_seconds=command.timeout_seconds,
        retry_policy=command.retry_policy
    )

    delivery_method = "websocket_fallback" if use_websocket else "heartbeat"

    return {
        "command_id": command_id,
        "device_id": device_id,
        "type": command.type,
        "priority": priority,
        "status": "queued",
        "delivery_method": delivery_method,
        "estimated_delivery": "within 30 seconds" if not use_websocket else "immediate (via websocket)",
        "expires_in": command.timeout_seconds
    }


@app.post("/api/v1/devices/{device_id}/commands/{command_id}/status")
async def update_command_status(
    device_id: str,
    command_id: str,
    status_update: dict
):
    """
    Device reports command execution status.

    Status values:
    - received: Command received by device
    - executing: Command is being executed
    - completed: Command completed successfully
    - failed: Command execution failed
    """
    # TODO: Store command execution results
    # For now, just log it
    import logging
    logger = logging.getLogger(__name__)

    status = status_update.get("status")
    result = status_update.get("result")
    error = status_update.get("error")

    logger.info(
        f"Device {device_id} - Command {command_id}: {status} "
        f"(result={result}, error={error})"
    )

    return {"ack": True, "received": True}


@app.websocket("/api/v1/devices/{device_id}/ws")
async def device_websocket(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for real-time device communication.

    Used for:
    - Critical commands (emergency stop, fraud alerts)
    - Real-time monitoring
    - Bidirectional streaming

    Connection lifecycle:
    1. Device connects with API key in query params
    2. Server accepts connection
    3. Device sends heartbeats
    4. Server can push commands instantly
    5. Device reports command results
    """
    # Accept connection
    await websocket.accept()

    # TODO: Authenticate device (check API key from query params)
    # For demo, we'll accept all connections

    # Register connection
    websocket_connections[device_id] = websocket
    logger.info(f"WebSocket connected: {device_id}")

    try:
        while True:
            # Receive messages from device
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "heartbeat":
                # WebSocket heartbeat (more frequent than HTTP heartbeat)
                await websocket.send_json({
                    "type": "heartbeat_ack",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            elif message_type == "command_result":
                # Device reporting command execution result
                command_id = data.get("command_id")
                status = data.get("status")
                result = data.get("result")
                logger.info(f"Device {device_id} command result: {command_id} = {status}")

                # Send acknowledgment
                await websocket.send_json({
                    "type": "command_result_ack",
                    "command_id": command_id
                })

            elif message_type == "log":
                # Real-time log streaming
                log_data = data.get("data")
                logger.info(f"Device {device_id} log: {log_data}")

            else:
                logger.warning(f"Unknown message type from {device_id}: {message_type}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {device_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {device_id}: {e}")
    finally:
        # Cleanup connection
        if device_id in websocket_connections:
            del websocket_connections[device_id]
        logger.info(f"WebSocket cleanup: {device_id}")


@app.get("/api/v1/devices/{device_id}/connection")
async def get_device_connection_status(
    device_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Check if device has an active WebSocket connection."""
    is_connected = device_id in websocket_connections

    return {
        "device_id": device_id,
        "websocket_connected": is_connected,
        "connection_type": "websocket" if is_connected else "heartbeat_only",
        "can_send_critical_commands": is_connected
    }


# ─────────────────────────────────────────────────────────────────────────────
# Command Version Management
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/commands/versions")
async def list_command_versions(
    command_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    List all command versions.

    Query params:
    - command_type: Filter by specific command type
    - is_active: Filter by active status
    - limit: Maximum results (default: 100)
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    versions = await version_service.list_versions(
        command_type=command_type,
        is_active=is_active,
        limit=limit
    )

    return {
        "versions": versions,
        "total": len(versions)
    }


@app.get("/api/v1/commands/versions/{version_id}")
async def get_command_version(
    version_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get specific command version details including schema."""
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    version = await version_service.get_version(version_id)

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return version.dict()


@app.get("/api/v1/commands/{command_type}/versions")
async def list_command_type_versions(
    command_type: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List all versions for a specific command type."""
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    versions = await version_service.list_versions(command_type=command_type)

    return {
        "command_type": command_type,
        "versions": versions,
        "total": len(versions)
    }


@app.get("/api/v1/commands/{command_type}/versions/latest")
async def get_latest_command_version(
    command_type: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get latest active version for a command type."""
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    version = await version_service.get_latest_version(command_type)

    if not version:
        raise HTTPException(status_code=404, detail="No version found for command type")

    return version.dict()


@app.post("/api/v1/commands/{command_type}/validate")
async def validate_command_data(
    command_type: str,
    request_body: Dict[str, Any],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Validate command data against schema.

    Body: {
        "version": "1.0.0",
        "data": { ... command data ... }
    }
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    version = request_body.get("version")
    data = request_body.get("data", {})

    if not version:
        raise HTTPException(status_code=400, detail="Version required")

    validation = await version_service.validate_command_data(
        command_type, version, data
    )

    return {
        "valid": validation.valid,
        "errors": validation.errors,
        "warnings": validation.warnings
    }


@app.get("/api/v1/commands/{command_type}/changelog")
async def get_command_changelog(
    command_type: str,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Get changelog between versions.

    Query params:
    - from_version: Starting version (optional)
    - to_version: Ending version (optional)
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    changelog = await version_service.get_changelog(
        command_type, from_version, to_version
    )

    return {
        "command_type": command_type,
        "changelog": changelog,
        "total_entries": len(changelog)
    }


# Admin-only endpoints

@app.post("/api/v1/admin/commands/versions")
async def create_command_version(
    version_data: Dict[str, Any],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Create new command version (admin only).

    Body: {
        "command_type": "restart",
        "version": "2.0.0",
        "schema_definition": { ... JSON Schema ... },
        "changelog": "Added new parameter...",
        "created_by": "admin_user"
    }
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    # TODO: Add admin check
    # if not user or not user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin access required")

    from rufus_server.version_service import CommandVersion

    try:
        version = CommandVersion(**version_data)
        version_id = await version_service.create_version(version)

        return {
            "version_id": version_id,
            "command_type": version.command_type,
            "version": version.version,
            "status": "created"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/v1/admin/commands/versions/{version_id}")
async def update_command_version(
    version_id: str,
    updates: Dict[str, Any],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Update command version (admin only).

    Allowed updates:
    - is_active: bool
    - is_deprecated: bool
    - deprecated_reason: str
    - changelog: str
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    # TODO: Add admin check

    success = await version_service.update_version(version_id, updates)

    if not success:
        raise HTTPException(status_code=404, detail="Version not found or no valid updates")

    return {
        "version_id": version_id,
        "status": "updated"
    }


@app.post("/api/v1/admin/commands/versions/{version_id}/deprecate")
async def deprecate_command_version(
    version_id: str,
    reason_data: Dict[str, str],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Deprecate command version (admin only).

    Body: {
        "reason": "Replaced by version 2.0.0"
    }
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

    # TODO: Add admin check

    reason = reason_data.get("reason", "No reason provided")
    success = await version_service.deprecate_version(version_id, reason)

    if not success:
        raise HTTPException(status_code=404, detail="Version not found")

    return {
        "version_id": version_id,
        "status": "deprecated",
        "reason": reason
    }


# ─────────────────────────────────────────────────────────────────────────────
# Webhook Notifications
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/webhooks")
async def create_webhook(
    webhook_data: Dict[str, Any],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Register a new webhook.

    Body: {
        "webhook_id": "my-webhook-1",  # Optional, auto-generated if not provided
        "name": "Device Status Notifications",
        "url": "https://example.com/webhooks/device-status",
        "events": ["device.online", "device.offline"],
        "secret": "your-secret-key",  # Optional, for HMAC signature
        "headers": {"Authorization": "Bearer token"},  # Optional custom headers
        "retry_policy": {"max_retries": 3, "backoff_seconds": 60}
    }
    """
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    from rufus_server.webhook_service import WebhookRegistration

    try:
        registration = WebhookRegistration(**webhook_data)
        webhook_id = await webhook_service.register_webhook(registration)

        return {
            "webhook_id": webhook_id,
            "status": "registered",
            "events": [e.value for e in registration.events]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/webhooks")
async def list_webhooks(
    is_active: Optional[bool] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List all webhook registrations."""
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    webhooks = await webhook_service.list_webhooks(is_active=is_active)

    return {
        "webhooks": webhooks,
        "total": len(webhooks)
    }


@app.get("/api/v1/webhooks/{webhook_id}")
async def get_webhook(
    webhook_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get specific webhook details."""
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    webhook = await webhook_service.get_webhook(webhook_id)

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    return webhook.dict()


@app.put("/api/v1/webhooks/{webhook_id}")
async def update_webhook(
    webhook_id: str,
    updates: Dict[str, Any],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Update webhook registration.

    Allowed updates: name, url, events, secret, headers, retry_policy, is_active
    """
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    success = await webhook_service.update_webhook(webhook_id, updates)

    if not success:
        raise HTTPException(status_code=404, detail="Webhook not found or no valid updates")

    return {
        "webhook_id": webhook_id,
        "status": "updated"
    }


@app.delete("/api/v1/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Delete webhook registration."""
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    # TODO: Add admin check

    success = await webhook_service.delete_webhook(webhook_id)

    return {
        "webhook_id": webhook_id,
        "status": "deleted"
    }


@app.get("/api/v1/webhooks/{webhook_id}/deliveries")
async def get_webhook_deliveries(
    webhook_id: str,
    status: Optional[str] = None,
    limit: int = 100,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get webhook delivery history."""
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    from rufus_server.webhook_service import WebhookStatus

    webhook_status = None
    if status:
        try:
            webhook_status = WebhookStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    deliveries = await webhook_service.get_delivery_history(
        webhook_id=webhook_id,
        status=webhook_status,
        limit=limit
    )

    return {
        "webhook_id": webhook_id,
        "deliveries": deliveries,
        "total": len(deliveries)
    }


@app.post("/api/v1/webhooks/test")
async def test_webhook(
    test_data: Dict[str, Any],
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Test webhook delivery without saving to database.

    Body: {
        "url": "https://example.com/webhook",
        "event_type": "device.online",
        "event_data": {"device_id": "test-123"},
        "secret": "optional-secret"
    }
    """
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    from rufus_server.webhook_service import WebhookEvent

    url = test_data.get("url")
    event_type_str = test_data.get("event_type", "device.online")
    event_data = test_data.get("event_data", {})
    secret = test_data.get("secret")

    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    try:
        event_type = WebhookEvent(event_type_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {event_type_str}")

    try:
        # Send test webhook
        await webhook_service._deliver_webhook(
            delivery_id="test",
            webhook_id="test",
            url=url,
            event_type=event_type,
            event_data=event_data,
            secret=secret
        )

        return {
            "status": "sent",
            "url": url,
            "event_type": event_type.value
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook test failed: {str(e)}")


@app.get("/api/v1/rollout/status")
async def get_rollout_status(policy_id: Optional[str] = None):
    """Get rollout status across all devices."""
    if not device_assignments:
        return {
            "total_devices": 0,
            "status_breakdown": {},
            "by_policy": {}
        }

    from collections import Counter

    # Count by status
    status_counts = Counter(a.status for a in device_assignments.values())

    # Count by policy
    by_policy: Dict[str, Dict[str, int]] = {}
    for assignment in device_assignments.values():
        pid = str(assignment.policy_id)
        if pid not in by_policy:
            by_policy[pid] = Counter()
        by_policy[pid][assignment.status] += 1

    # Filter by policy if specified
    if policy_id:
        by_policy = {k: v for k, v in by_policy.items() if k == policy_id}

    return {
        "total_devices": len(device_assignments),
        "status_breakdown": dict(status_counts),
        "by_policy": {k: dict(v) for k, v in by_policy.items()}
    }


# ═════════════════════════════════════════════════════════════════════════
# Broadcast Endpoints
# ═════════════════════════════════════════════════════════════════════════

# Global service instances
broadcast_service = None
template_service = None
batch_service = None
schedule_service = None
audit_service = None
authorization_service = None
rate_limit_service = None


@app.post("/api/v1/broadcasts")
async def create_broadcast(
    broadcast_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Create a multi-device command broadcast.

    Examples:
    ```json
    // All devices in region
    {
      "command_type": "update_config",
      "command_data": {"floor_limit": 50.00},
      "target_filter": {
        "merchant_id": "merchant-123",
        "status": "online"
      }
    }

    // Progressive rollout
    {
      "command_type": "restart",
      "command_data": {"delay_seconds": 10},
      "target_filter": {
        "device_type": "macbook",
        "status": "online"
      },
      "rollout_config": {
        "strategy": "canary",
        "phases": [0.1, 0.5, 1.0],
        "wait_seconds": 300,
        "circuit_breaker_threshold": 0.2
      }
    }
    ```
    """
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence, device_service)

    from rufus_server.broadcast import CommandBroadcast, TargetFilter, RolloutConfig

    # Parse broadcast config
    target_filter = TargetFilter(**broadcast_data.get("target_filter", {}))

    rollout_config = None
    if "rollout_config" in broadcast_data:
        rollout_config = RolloutConfig(**broadcast_data["rollout_config"])

    broadcast = CommandBroadcast(
        command_type=broadcast_data["command_type"],
        command_data=broadcast_data.get("command_data", {}),
        target_filter=target_filter,
        rollout_config=rollout_config,
        created_by=user.get("user_id") if user else None
    )

    # Create broadcast
    broadcast_id = await broadcast_service.create_broadcast(broadcast)

    return {
        "broadcast_id": broadcast_id,
        "status": "created",
        "message": "Broadcast created and execution started"
    }


@app.get("/api/v1/broadcasts/{broadcast_id}")
async def get_broadcast_status(
    broadcast_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get broadcast execution progress."""
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence, device_service)

    progress = await broadcast_service.get_broadcast_progress(broadcast_id)

    if not progress:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    return progress.dict()


@app.get("/api/v1/broadcasts")
async def list_broadcasts(
    status: Optional[str] = None,
    limit: int = 50,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List recent broadcasts."""
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence, device_service)

    broadcasts = await broadcast_service.list_broadcasts(status=status, limit=limit)

    return {
        "total": len(broadcasts),
        "broadcasts": broadcasts
    }


@app.delete("/api/v1/broadcasts/{broadcast_id}")
async def cancel_broadcast(
    broadcast_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Cancel ongoing broadcast."""
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence, device_service)

    success = await broadcast_service.cancel_broadcast(broadcast_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel broadcast (already completed or not found)"
        )

    return {
        "broadcast_id": broadcast_id,
        "status": "cancelled",
        "message": "Broadcast cancelled successfully"
    }


# ═════════════════════════════════════════════════════════════════════════
# Template Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/templates")
async def create_template(
    template_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Create a command template.

    Example:
    ```json
    {
      "template_name": "soft-restart",
      "description": "Graceful restart with cleanup",
      "commands": [
        {"type": "clear_cache", "data": {}},
        {"type": "restart", "data": {"delay_seconds": "{{delay}}"}}
      ],
      "variables": [
        {"name": "delay", "type": "integer", "default": 30}
      ],
      "tags": ["maintenance"]
    }
    ```
    """
    global template_service

    if not template_service:
        from rufus_server.template_service import TemplateService
        template_service = TemplateService(persistence, device_service)

    from rufus_server.templates import CommandTemplate

    template = CommandTemplate(**template_data)
    template.created_by = user.get("user_id") if user else None

    template_name = await template_service.create_template(template)

    return {
        "template_name": template_name,
        "status": "created",
        "message": f"Template '{template_name}' created successfully"
    }


@app.get("/api/v1/templates/{template_name}")
async def get_template(
    template_name: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get template details."""
    global template_service

    if not template_service:
        from rufus_server.template_service import TemplateService
        template_service = TemplateService(persistence, device_service)

    template = await template_service.get_template(template_name)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template.dict()


@app.get("/api/v1/templates")
async def list_templates(
    active_only: bool = True,
    tag: Optional[str] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List available templates."""
    global template_service

    if not template_service:
        from rufus_server.template_service import TemplateService
        template_service = TemplateService(persistence, device_service)

    tags = [tag] if tag else None
    templates = await template_service.list_templates(active_only=active_only, tags=tags)

    return {
        "total": len(templates),
        "templates": templates
    }


@app.delete("/api/v1/templates/{template_name}")
async def delete_template(
    template_name: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Delete a template (soft delete)."""
    global template_service

    if not template_service:
        from rufus_server.template_service import TemplateService
        template_service = TemplateService(persistence, device_service)

    success = await template_service.delete_template(template_name)

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Template not found or already deleted"
        )

    return {
        "template_name": template_name,
        "status": "deleted",
        "message": f"Template '{template_name}' deleted successfully"
    }


@app.post("/api/v1/templates/{template_name}/apply")
async def apply_template(
    template_name: str,
    apply_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Apply template to device(s).

    Single device:
    ```json
    {
      "device_id": "macbook-m4-001",
      "variables": {"delay": 60}
    }
    ```

    Broadcast:
    ```json
    {
      "target_filter": {"merchant_id": "merchant-123"},
      "variables": {"delay": 60},
      "rollout_config": {"strategy": "canary", "phases": [0.1, 1.0]}
    }
    ```
    """
    global template_service

    if not template_service:
        from rufus_server.template_service import TemplateService
        template_service = TemplateService(persistence, device_service)

    variables = apply_data.get("variables", {})

    # Single device or broadcast?
    if "device_id" in apply_data:
        # Single device
        command_ids = await template_service.apply_template_to_device(
            template_name=template_name,
            device_id=apply_data["device_id"],
            variables=variables
        )

        return {
            "template_name": template_name,
            "device_id": apply_data["device_id"],
            "command_ids": command_ids,
            "message": f"Template applied: {len(command_ids)} commands created"
        }
    elif "target_filter" in apply_data:
        # Broadcast
        broadcast_id = await template_service.apply_template_broadcast(
            template_name=template_name,
            target_filter=apply_data["target_filter"],
            variables=variables,
            rollout_config=apply_data.get("rollout_config")
        )

        return {
            "template_name": template_name,
            "broadcast_id": broadcast_id,
            "message": "Template applied as broadcast"
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Must specify either 'device_id' or 'target_filter'"
        )


# ═════════════════════════════════════════════════════════════════════════
# Command Batch Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/batches")
async def create_batch(
    batch_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Create an atomic multi-command batch.

    Examples:
    ```json
    // Sequential execution
    {
      "device_id": "macbook-m4-001",
      "commands": [
        {"type": "clear_cache", "data": {}, "sequence": 1},
        {"type": "sync_now", "data": {}, "sequence": 2},
        {"type": "restart", "data": {"delay_seconds": 30}, "sequence": 3}
      ],
      "execution_mode": "sequential"
    }

    // Parallel execution
    {
      "device_id": "macbook-m4-001",
      "commands": [
        {"type": "health_check", "data": {}},
        {"type": "sync_now", "data": {}},
        {"type": "clear_cache", "data": {}}
      ],
      "execution_mode": "parallel"
    }
    ```
    """
    global batch_service

    if not batch_service:
        from rufus_server.batch_service import BatchService
        batch_service = BatchService(persistence, device_service)

    from rufus_server.batching import CommandBatch, BatchCommand, ExecutionMode

    # Parse batch config
    commands = [BatchCommand(**cmd) for cmd in batch_data["commands"]]

    batch = CommandBatch(
        device_id=batch_data["device_id"],
        commands=commands,
        execution_mode=ExecutionMode(batch_data.get("execution_mode", "sequential"))
    )

    # Create batch
    batch_id = await batch_service.create_batch(batch)

    return {
        "batch_id": batch_id,
        "status": "created",
        "total_commands": len(commands),
        "execution_mode": batch.execution_mode.value,
        "message": "Batch created successfully"
    }


@app.get("/api/v1/batches/{batch_id}")
async def get_batch_progress(
    batch_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get batch execution progress."""
    global batch_service

    if not batch_service:
        from rufus_server.batch_service import BatchService
        batch_service = BatchService(persistence, device_service)

    progress = await batch_service.get_batch_progress(batch_id)

    if not progress:
        raise HTTPException(status_code=404, detail="Batch not found")

    return {
        "batch_id": progress.batch_id,
        "device_id": progress.device_id,
        "status": progress.status.value,
        "execution_mode": progress.execution_mode.value,
        "total_commands": progress.total_commands,
        "completed_commands": progress.completed_commands,
        "failed_commands": progress.failed_commands,
        "pending_commands": progress.pending_commands,
        "success_rate": progress.success_rate,
        "failure_rate": progress.failure_rate,
        "created_at": progress.created_at.isoformat(),
        "started_at": progress.started_at.isoformat() if progress.started_at else None,
        "completed_at": progress.completed_at.isoformat() if progress.completed_at else None,
        "error_message": progress.error_message,
        "command_statuses": progress.command_statuses
    }


@app.get("/api/v1/batches")
async def list_batches(
    device_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List command batches with optional filters."""
    global batch_service

    if not batch_service:
        from rufus_server.batch_service import BatchService
        batch_service = BatchService(persistence, device_service)

    batches = await batch_service.list_batches(
        device_id=device_id,
        status=status,
        limit=limit
    )

    return {
        "batches": batches,
        "count": len(batches)
    }


@app.delete("/api/v1/batches/{batch_id}")
async def cancel_batch(
    batch_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Cancel a pending batch."""
    global batch_service

    if not batch_service:
        from rufus_server.batch_service import BatchService
        batch_service = BatchService(persistence, device_service)

    success = await batch_service.cancel_batch(batch_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Batch not found or already in progress/completed"
        )

    return {
        "batch_id": batch_id,
        "status": "cancelled",
        "message": "Batch cancelled successfully"
    }


# ═════════════════════════════════════════════════════════════════════════
# Command Schedule Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/schedules")
async def create_schedule(
    schedule_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Create a command schedule (one-time or recurring).

    Examples:
    ```json
    // One-time schedule
    {
      "schedule_name": "Maintenance restart",
      "device_id": "macbook-m4-001",
      "command_type": "restart",
      "command_data": {"delay_seconds": 10},
      "schedule_type": "one_time",
      "execute_at": "2026-02-05T02:00:00Z"
    }

    // Recurring schedule with cron
    {
      "schedule_name": "Daily health check",
      "device_id": "pos-terminal-042",
      "command_type": "health_check",
      "command_data": {},
      "schedule_type": "recurring",
      "cron_expression": "0 2 * * *",
      "timezone": "America/New_York",
      "maintenance_window_start": "02:00:00",
      "maintenance_window_end": "06:00:00"
    }

    // Fleet recurring schedule
    {
      "schedule_name": "Weekly cache clear",
      "target_filter": {"device_type": "macbook", "status": "online"},
      "command_type": "clear_cache",
      "command_data": {},
      "schedule_type": "recurring",
      "cron_expression": "0 3 * * 0",
      "max_executions": 52
    }
    ```
    """
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence, device_service)

        schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    from rufus_server.scheduling import CommandSchedule
    from datetime import time

    # Parse maintenance window times if provided
    if "maintenance_window_start" in schedule_data:
        from datetime import datetime
        schedule_data["maintenance_window_start"] = datetime.strptime(
            schedule_data["maintenance_window_start"], "%H:%M:%S"
        ).time()

    if "maintenance_window_end" in schedule_data:
        from datetime import datetime
        schedule_data["maintenance_window_end"] = datetime.strptime(
            schedule_data["maintenance_window_end"], "%H:%M:%S"
        ).time()

    # Parse execute_at if provided
    if "execute_at" in schedule_data and isinstance(schedule_data["execute_at"], str):
        from datetime import datetime
        schedule_data["execute_at"] = datetime.fromisoformat(
            schedule_data["execute_at"].replace("Z", "+00:00")
        )

    # Add created_by from user context
    if user:
        schedule_data["created_by"] = user.get("user_id")

    # Create schedule
    schedule = CommandSchedule(**schedule_data)
    schedule_id = await schedule_service.create_schedule(schedule)

    return {
        "schedule_id": schedule_id,
        "status": "created",
        "message": "Schedule created successfully"
    }


@app.get("/api/v1/schedules/{schedule_id}")
async def get_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get schedule details and execution history."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence, device_service)

        schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    progress = await schedule_service.get_schedule(schedule_id)

    if not progress:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return {
        "schedule_id": progress.schedule_id,
        "schedule_name": progress.schedule_name,
        "device_id": progress.device_id,
        "target_filter": progress.target_filter,
        "command_type": progress.command_type,
        "schedule_type": progress.schedule_type.value,
        "status": progress.status.value,
        "execution_count": progress.execution_count,
        "max_executions": progress.max_executions,
        "next_execution_at": progress.next_execution_at.isoformat() if progress.next_execution_at else None,
        "last_execution_at": progress.last_execution_at.isoformat() if progress.last_execution_at else None,
        "cron_expression": progress.cron_expression,
        "timezone": progress.timezone,
        "created_at": progress.created_at.isoformat(),
        "updated_at": progress.updated_at.isoformat(),
        "expires_at": progress.expires_at.isoformat() if progress.expires_at else None,
        "recent_executions": progress.recent_executions,
        "error_message": progress.error_message
    }


@app.get("/api/v1/schedules")
async def list_schedules(
    device_id: Optional[str] = None,
    status: Optional[str] = None,
    schedule_type: Optional[str] = None,
    limit: int = 50,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List command schedules with optional filters."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence, device_service)

        schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    schedules = await schedule_service.list_schedules(
        device_id=device_id,
        status=status,
        schedule_type=schedule_type,
        limit=limit
    )

    return {
        "schedules": schedules,
        "count": len(schedules)
    }


@app.post("/api/v1/schedules/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Pause an active schedule."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence, device_service)

        schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    success = await schedule_service.pause_schedule(schedule_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Schedule not found or not active"
        )

    return {
        "schedule_id": schedule_id,
        "status": "paused",
        "message": "Schedule paused successfully"
    }


@app.post("/api/v1/schedules/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Resume a paused schedule."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence, device_service)

        schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    success = await schedule_service.resume_schedule(schedule_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Schedule not found or not paused"
        )

    return {
        "schedule_id": schedule_id,
        "status": "active",
        "message": "Schedule resumed successfully"
    }


@app.delete("/api/v1/schedules/{schedule_id}")
async def cancel_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Cancel a schedule."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence, device_service)

        schedule_service = ScheduleService(persistence, device_service, broadcast_service)

    success = await schedule_service.cancel_schedule(schedule_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Schedule not found or already completed/cancelled"
        )

    return {
        "schedule_id": schedule_id,
        "status": "cancelled",
        "message": "Schedule cancelled successfully"
    }


# ═════════════════════════════════════════════════════════════════════════
# Command Audit Log Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/audit/query")
async def query_audit_logs(
    query_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Query audit logs with filters.

    Example:
    ```json
    {
      "start_time": "2026-02-01T00:00:00Z",
      "end_time": "2026-02-04T23:59:59Z",
      "device_id": "macbook-m4-001",
      "event_types": ["command_created", "command_completed"],
      "limit": 100,
      "offset": 0
    }
    ```
    """
    global audit_service

    if not audit_service:
        from rufus_server.audit_service import AuditService
        audit_service = AuditService(persistence)

    from rufus_server.audit import AuditQuery
    from datetime import datetime

    # Parse datetime strings
    if "start_time" in query_data and isinstance(query_data["start_time"], str):
        query_data["start_time"] = datetime.fromisoformat(
            query_data["start_time"].replace("Z", "+00:00")
        )

    if "end_time" in query_data and isinstance(query_data["end_time"], str):
        query_data["end_time"] = datetime.fromisoformat(
            query_data["end_time"].replace("Z", "+00:00")
        )

    query = AuditQuery(**query_data)
    result = await audit_service.query_logs(query)

    return {
        "entries": [
            {
                "audit_id": entry.audit_id,
                "event_type": entry.event_type,
                "command_type": entry.command_type,
                "device_id": entry.device_id,
                "merchant_id": entry.merchant_id,
                "actor_type": entry.actor_type,
                "actor_id": entry.actor_id,
                "status": entry.status,
                "timestamp": entry.timestamp.isoformat(),
                "error_message": entry.error_message,
                "compliance_tags": entry.compliance_tags
            }
            for entry in result.entries
        ],
        "total_count": result.total_count,
        "limit": result.limit,
        "offset": result.offset,
        "has_more": result.has_more
    }


@app.post("/api/v1/audit/export")
async def export_audit_logs(
    export_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Export audit logs in specified format (JSON, CSV, JSONL).

    Example:
    ```json
    {
      "query": {
        "start_time": "2026-02-01T00:00:00Z",
        "end_time": "2026-02-04T23:59:59Z",
        "device_id": "macbook-m4-001"
      },
      "format": "csv"
    }
    ```
    """
    global audit_service

    if not audit_service:
        from rufus_server.audit_service import AuditService
        audit_service = AuditService(persistence)

    from rufus_server.audit import AuditQuery, AuditExportFormat
    from datetime import datetime

    # Parse query
    query_data = export_data.get("query", {})

    # Parse datetime strings
    if "start_time" in query_data and isinstance(query_data["start_time"], str):
        query_data["start_time"] = datetime.fromisoformat(
            query_data["start_time"].replace("Z", "+00:00")
        )

    if "end_time" in query_data and isinstance(query_data["end_time"], str):
        query_data["end_time"] = datetime.fromisoformat(
            query_data["end_time"].replace("Z", "+00:00")
        )

    query = AuditQuery(**query_data)

    # Get export format
    export_format = AuditExportFormat(export_data.get("format", "json"))

    # Export logs
    export_data_str = await audit_service.export_logs(query, export_format)

    # Determine content type
    content_types = {
        AuditExportFormat.JSON: "application/json",
        AuditExportFormat.CSV: "text/csv",
        AuditExportFormat.JSONL: "application/x-ndjson"
    }

    return Response(
        content=export_data_str,
        media_type=content_types[export_format],
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{export_format.value}"
        }
    )


@app.get("/api/v1/audit/stats")
async def get_audit_stats(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get audit log statistics."""
    global audit_service

    if not audit_service:
        from rufus_server.audit_service import AuditService
        audit_service = AuditService(persistence)

    from datetime import datetime, timedelta

    # Default to last 7 days
    if not start_time:
        start_dt = datetime.utcnow() - timedelta(days=7)
    else:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))

    if not end_time:
        end_dt = datetime.utcnow()
    else:
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

    async with persistence.pool.acquire() as conn:
        # Total events
        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM command_audit_log
            WHERE timestamp >= $1 AND timestamp <= $2
            """,
            start_dt,
            end_dt
        )

        # Events by type
        events_by_type = await conn.fetch(
            """
            SELECT event_type, COUNT(*) as count
            FROM command_audit_log
            WHERE timestamp >= $1 AND timestamp <= $2
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 10
            """,
            start_dt,
            end_dt
        )

        # Events by actor
        events_by_actor = await conn.fetch(
            """
            SELECT actor_type, COUNT(*) as count
            FROM command_audit_log
            WHERE timestamp >= $1 AND timestamp <= $2
            GROUP BY actor_type
            ORDER BY count DESC
            """,
            start_dt,
            end_dt
        )

        # Failed events
        failed = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM command_audit_log
            WHERE timestamp >= $1 AND timestamp <= $2
              AND status = 'failed'
            """,
            start_dt,
            end_dt
        )

    return {
        "period": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat()
        },
        "total_events": total,
        "failed_events": failed,
        "events_by_type": {row["event_type"]: row["count"] for row in events_by_type},
        "events_by_actor": {row["actor_type"]: row["count"] for row in events_by_actor}
    }


# ═════════════════════════════════════════════════════════════════════════
# Command Authorization Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/authorization/check")
async def check_authorization(
    check_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Check if user is authorized to execute a command.

    Example:
    ```json
    {
      "user_id": "user-123",
      "command_type": "update_firmware",
      "device_type": "macbook"
    }
    ```
    """
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    result = await authorization_service.check_authorization(
        user_id=check_data["user_id"],
        command_type=check_data["command_type"],
        device_type=check_data.get("device_type")
    )

    return {
        "authorized": result.authorized,
        "requires_approval": result.requires_approval,
        "user_roles": result.user_roles,
        "missing_roles": result.missing_roles,
        "reason": result.reason,
        "policy": {
            "policy_name": result.policy.policy_name,
            "risk_level": result.policy.risk_level.value,
            "approvers_required": result.policy.approvers_required
        } if result.policy else None
    }


@app.post("/api/v1/approvals")
async def request_approval(
    approval_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Request approval for a command.

    Example:
    ```json
    {
      "command_type": "update_firmware",
      "command_data": {"version": "2.5.0"},
      "device_id": "macbook-m4-001",
      "requested_by": "user-123",
      "approvers_required": 2,
      "approval_timeout_seconds": 3600,
      "risk_level": "critical",
      "reason": "Critical security patch"
    }
    ```
    """
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    from rufus_server.authorization import ApprovalRequest

    request = ApprovalRequest(**approval_data)
    approval_id = await authorization_service.request_approval(request)

    return {
        "approval_id": approval_id,
        "status": "pending",
        "message": "Approval request created"
    }


@app.get("/api/v1/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get approval request details."""
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    approval = await authorization_service.get_approval(approval_id)

    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    return {
        "approval_id": approval.approval_id,
        "command_type": approval.command_type,
        "command_data": approval.command_data,
        "device_id": approval.device_id,
        "target_filter": approval.target_filter,
        "requested_by": approval.requested_by,
        "requested_at": approval.requested_at.isoformat(),
        "status": approval.status.value,
        "approvers_required": approval.approvers_required,
        "approvers_count": approval.approvers_count,
        "expires_at": approval.expires_at.isoformat(),
        "completed_at": approval.completed_at.isoformat() if approval.completed_at else None,
        "reason": approval.reason,
        "command_id": approval.command_id,
        "risk_level": approval.risk_level.value,
        "responses": approval.responses
    }


@app.get("/api/v1/approvals")
async def list_approvals(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List approval requests."""
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    approvals = await authorization_service.list_approvals(
        user_id=user_id,
        status=status,
        limit=limit
    )

    return {
        "approvals": approvals,
        "count": len(approvals)
    }


@app.post("/api/v1/approvals/{approval_id}/approve")
async def approve_command(
    approval_id: str,
    approval_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Approve a command.

    Example:
    ```json
    {
      "approver_id": "user-456",
      "comment": "Approved - security patch is critical"
    }
    ```
    """
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    from rufus_server.authorization import ApprovalResponse

    success = await authorization_service.respond_to_approval(
        approval_id=approval_id,
        approver_id=approval_data["approver_id"],
        response=ApprovalResponse.APPROVED,
        comment=approval_data.get("comment")
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot approve (already responded, expired, or not pending)"
        )

    return {
        "approval_id": approval_id,
        "status": "approved",
        "message": "Approval recorded"
    }


@app.post("/api/v1/approvals/{approval_id}/reject")
async def reject_command(
    approval_id: str,
    rejection_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Reject a command.

    Example:
    ```json
    {
      "approver_id": "user-456",
      "comment": "Rejected - need more testing first"
    }
    ```
    """
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    from rufus_server.authorization import ApprovalResponse

    success = await authorization_service.respond_to_approval(
        approval_id=approval_id,
        approver_id=rejection_data["approver_id"],
        response=ApprovalResponse.REJECTED,
        comment=rejection_data.get("comment")
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot reject (already responded, expired, or not pending)"
        )

    return {
        "approval_id": approval_id,
        "status": "rejected",
        "message": "Rejection recorded"
    }


@app.delete("/api/v1/approvals/{approval_id}")
async def cancel_approval(
    approval_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Cancel a pending approval request."""
    global authorization_service

    if not authorization_service:
        from rufus_server.authorization_service import AuthorizationService
        authorization_service = AuthorizationService(persistence)

    # Extract user_id from user context
    user_id = user.get("user_id") if user else None
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    success = await authorization_service.cancel_approval(approval_id, user_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel (not found, not your request, or not pending)"
        )

    return {
        "approval_id": approval_id,
        "status": "cancelled",
        "message": "Approval request cancelled"
    }


# ═════════════════════════════════════════════════════════════════════════
# Rate Limiting Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/rate-limits/status")
async def get_rate_limit_status(
    request: Request,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Get current rate limit status for authenticated user or IP.

    Returns remaining quota and reset times for all applicable rules.
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

    # Get identifier (user or IP)
    identifier = f"user:{user.user_id}" if user else f"ip:{request.client.host}"

    # Get status for all rules
    status = await rate_limit_service.get_limit_status(identifier)

    return {
        "identifier": identifier,
        "limits": [
            {
                "rule_name": limit.rule_name,
                "resource_pattern": limit.resource_pattern,
                "limit": limit.limit,
                "used": limit.used,
                "remaining": limit.remaining,
                "window_seconds": limit.window_seconds,
                "resets_at": limit.resets_at.isoformat()
            }
            for limit in status.values()
        ]
    }


@app.get("/api/v1/admin/rate-limits")
async def list_rate_limits(
    is_active: Optional[bool] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    List all rate limit rules.

    Admin endpoint - requires admin privileges in production.
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

    # TODO: Add admin check in production
    # if not user or not user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin access required")

    rules = await rate_limit_service.get_rules(is_active=is_active)

    return {
        "rules": [
            {
                "rule_name": rule.rule_name,
                "resource_pattern": rule.resource_pattern,
                "scope": rule.scope,
                "limit_per_window": rule.limit_per_window,
                "window_seconds": rule.window_seconds,
                "is_active": rule.is_active,
                "created_at": rule.created_at.isoformat(),
                "updated_at": rule.updated_at.isoformat()
            }
            for rule in rules
        ],
        "total": len(rules)
    }


@app.put("/api/v1/admin/rate-limits/{rule_name}")
async def update_rate_limit(
    rule_name: str,
    update_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Update an existing rate limit rule.

    Admin endpoint - requires admin privileges in production.

    Example:
    ```json
    {
      "limit_per_window": 150,
      "window_seconds": 60,
      "is_active": true
    }
    ```
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

    # TODO: Add admin check in production
    # if not user or not user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin access required")

    success = await rate_limit_service.update_rule(
        rule_name=rule_name,
        limit_per_window=update_data.get("limit_per_window"),
        window_seconds=update_data.get("window_seconds"),
        is_active=update_data.get("is_active")
    )

    if not success:
        raise HTTPException(status_code=404, detail="Rate limit rule not found")

    return {
        "rule_name": rule_name,
        "status": "updated",
        "message": "Rate limit rule updated successfully"
    }


@app.post("/api/v1/admin/rate-limits")
async def create_rate_limit(
    rule_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Create a new rate limit rule.

    Admin endpoint - requires admin privileges in production.

    Example:
    ```json
    {
      "rule_name": "api_requests",
      "resource_pattern": "/api/v1/*",
      "scope": "ip",
      "limit_per_window": 1000,
      "window_seconds": 60,
      "is_active": true
    }
    ```
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

    # TODO: Add admin check in production
    # if not user or not user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin access required")

    success = await rate_limit_service.create_rule(
        rule_name=rule_data["rule_name"],
        resource_pattern=rule_data["resource_pattern"],
        scope=rule_data["scope"],
        limit_per_window=rule_data["limit_per_window"],
        window_seconds=rule_data["window_seconds"],
        is_active=rule_data.get("is_active", True)
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Rate limit rule already exists or invalid data"
        )

    return {
        "rule_name": rule_data["rule_name"],
        "status": "created",
        "message": "Rate limit rule created successfully"
    }


@app.delete("/api/v1/admin/rate-limits/{rule_name}")
async def delete_rate_limit(
    rule_name: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Deactivate a rate limit rule (soft delete).

    Admin endpoint - requires admin privileges in production.
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

    # TODO: Add admin check in production
    # if not user or not user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin access required")

    success = await rate_limit_service.delete_rule(rule_name)

    if not success:
        raise HTTPException(status_code=404, detail="Rate limit rule not found")

    return {
        "rule_name": rule_name,
        "status": "deactivated",
        "message": "Rate limit rule deactivated successfully"
    }


# To run: uvicorn rufus_server.main:app --reload
