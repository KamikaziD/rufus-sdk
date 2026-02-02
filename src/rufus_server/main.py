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

# --- Global Instances ---
persistence_provider: Optional[PersistenceProvider] = None
execution_provider: Optional[ExecutionProvider] = None
workflow_observer: Optional[WorkflowObserver] = None
workflow_engine: Optional[WorkflowEngine] = None
workflow_registry_config: Dict[str, Any] = {}
device_service: Optional[DeviceService] = None


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


# --- Startup/Shutdown ---
@app.on_event("startup")
async def startup_event():
    global persistence_provider, execution_provider, workflow_observer, workflow_engine, workflow_registry_config

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

    # Initialize Device Service
    global device_service
    device_service = DeviceService(persistence_provider)

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
    user: Optional[UserContext] = Depends(get_current_user)
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
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Receive device heartbeat and return pending commands."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Authenticate device
    if not await device_service.authenticate_device(device_id, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

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


# To run: uvicorn rufus_server.main:app --reload
