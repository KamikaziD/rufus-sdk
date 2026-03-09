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
from datetime import datetime
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import importlib.resources
from dotenv import load_dotenv
import yaml
import asyncio
from typing import Optional, Any, Dict, List
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Import Rufus SDK Components ---
from rufus.engine import WorkflowEngine
from rufus.models import WorkflowJumpDirective, WorkflowPauseDirective, WorkflowFailedException, SagaWorkflowException, HumanWorkflowStep
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
# CeleryExecutionProvider imported lazily in startup_event to avoid
# ImportError when celery is not installed in the server image
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.observability.events import EventPublisherObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

# --- API Models ---
from rufus_server.api_models import (
    WorkflowStartRequest, WorkflowStartResponse, WorkflowStepRequest, WorkflowStepResponse,
    WorkflowStatusResponse, ResumeWorkflowRequest, RetryWorkflowRequest,
    DeviceRegistrationRequest, DeviceRegistrationResponse, DeviceHeartbeatRequest,
    DeviceHeartbeatResponse, SyncRequest, SyncResponse, DeviceBroadcastRequest,
    WorkerCommandRequest, WorkerBroadcastRequest, WorkerCommandResponse, WorkerDetail,
    WorkflowDefinitionUploadRequest, WorkflowDefinitionPatchRequest,
    WorkflowDefinitionResponse, WorkflowDefinitionDetailResponse,
    ServerCommandRequest, ServerCommandResponse,
    WorkflowSyncRequest, WorkflowSyncResponse,
)

# --- FastAPI App Setup ---
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Initialize limiter for rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Rufus Edge Control Plane",
    description="Cloud control plane for Rufus Edge fintech devices",
    version="0.5.0",
    openapi_tags=[
        {"name": "Health",           "description": "Service health check"},
        {"name": "Workflows",        "description": "Workflow registry, execution, and lifecycle control"},
        {"name": "Devices",          "description": "Edge device registration, management, and communication"},
        {"name": "Commands",         "description": "Device command versioning, validation, and execution"},
        {"name": "Policies",         "description": "Policy management and rollout control"},
        {"name": "Webhooks",         "description": "Webhook registration and event delivery"},
        {"name": "Broadcasts",       "description": "Mass message broadcasts and notifications"},
        {"name": "Batch Operations", "description": "Batch job creation and management"},
        {"name": "Scheduling",       "description": "Scheduled task and automation management"},
        {"name": "Configuration",    "description": "Template and configuration management"},
        {"name": "Audit",            "description": "Audit logs and compliance queries"},
        {"name": "Authorization",    "description": "Authorization checks and approval workflows"},
        {"name": "Rate Limiting",    "description": "Rate limit status, quotas, and admin configuration"},
        {"name": "Monitoring",       "description": "Metrics, worker status, and system monitoring"},
    ]
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow the dashboard (Next.js dev + prod)
_cors_origins = os.getenv(
    "RUFUS_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Device Service ---
from rufus_server.device_service import DeviceService

# --- Broadcast Service ---
from rufus_server.broadcast_service import BroadcastService

# --- Worker Fleet Service ---
from rufus_server.worker_service import WorkerService

# --- Workflow Definition + Server Command Services ---
from rufus_server.workflow_definition_service import WorkflowDefinitionService
from rufus_server.server_command_service import ServerCommandService

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
broadcast_service: Optional[BroadcastService] = None
worker_service: Optional[WorkerService] = None
workflow_definition_service: Optional[WorkflowDefinitionService] = None
server_command_service: Optional[ServerCommandService] = None
_definition_poller_task: Optional[asyncio.Task] = None


# --- Auth / RBAC ---
from rufus_server.auth import get_current_user, require_admin as _require_admin_orig, AuthUser as UserContext  # noqa: F401 (UserContext alias keeps existing type annotations valid)
from rufus_server.auth.loader import load_auth_provider, set_auth_provider

async def require_admin(user: Optional[UserContext] = Depends(get_current_user)) -> UserContext:
    """When auth is disabled (default dev mode), treat every request as admin."""
    if os.getenv("RUFUS_AUTH_PROVIDER", "disabled") == "disabled":
        return user or UserContext(user_id="system", roles=["admin"])
    return await _require_admin_orig(user=user)


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

        # Get identifier (user or IP); request.client may be None in test/proxy contexts
        client_host = request.client.host if request.client else "unknown"
        identifier = f"user:{user.user_id}" if user else f"ip:{client_host}"
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
    global rate_limit_service, version_service, webhook_service, broadcast_service, worker_service
    global workflow_definition_service, server_command_service, _definition_poller_task

    # Load workflow registry
    RUFUS_WORKFLOW_REGISTRY_PATH = os.getenv("RUFUS_WORKFLOW_REGISTRY_PATH", "config/workflow_registry.yaml")
    RUFUS_CONFIG_DIR = os.getenv("RUFUS_CONFIG_DIR", "config")  # Directory containing workflow YAML files
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

    # Workflow Observer - use EventPublisherObserver for real-time updates
    workflow_observer = EventPublisherObserver(persistence_provider=persistence_provider)
    await workflow_observer.initialize()
    logger.info("EventPublisherObserver initialized for real-time WebSocket updates")

    # Execution Provider
    execution_backend = os.getenv('WORKFLOW_EXECUTION_BACKEND', 'sync').lower()
    if execution_backend == 'celery':
        from rufus.implementations.execution.celery import CeleryExecutionProvider
        execution_provider = CeleryExecutionProvider()
        logger.info("Using CeleryExecutionProvider for distributed async execution")
    elif execution_backend == 'threadpool':
        execution_provider = ThreadPoolExecutorProvider()
        logger.info("Using ThreadPoolExecutorProvider")
    else:  # Default to sync
        execution_provider = SyncExecutor()
        logger.info("Using SyncExecutor")

    # WorkflowEngine
    workflow_engine = WorkflowEngine(
        persistence=persistence_provider,
        executor=execution_provider,
        observer=workflow_observer,
        workflow_registry={wf['type']: wf for wf in workflow_registry_config.get("workflows", [])},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        config_dir=RUFUS_CONFIG_DIR
    )

    # Initialize execution provider with engine reference
    if hasattr(execution_provider, 'initialize'):
        await execution_provider.initialize(workflow_engine)
        logger.info(f"Initialized {execution_provider.__class__.__name__} with engine reference")

    # Initialize Version Service
    from rufus_server.version_service import VersionService
    version_service = VersionService(persistence_provider)

    # Initialize Webhook Service
    from rufus_server.webhook_service import WebhookService
    webhook_service = WebhookService(persistence_provider)

    # Initialize Device Service (with version and webhook services)
    global device_service
    device_service = DeviceService(persistence_provider, version_service, webhook_service)

    # Initialize Broadcast Service
    broadcast_service = BroadcastService(persistence_provider, device_service)

    # Initialize Worker Fleet Service (PostgreSQL only; no-op when using sqlite/memory)
    if isinstance(persistence_provider, PostgresPersistenceProvider):
        worker_service = WorkerService(persistence_provider)
        logger.info("WorkerService initialized for Celery fleet management")

        # Initialize Workflow Definition + Server Command services
        workflow_definition_service = WorkflowDefinitionService(persistence_provider)
        server_command_service = ServerCommandService(persistence_provider)
        logger.info("WorkflowDefinitionService and ServerCommandService initialized")

        # Pre-load all active DB definitions into the builder before first request
        try:
            active_defs = await workflow_definition_service.get_all_active()
            for defn in active_defs:
                try:
                    workflow_engine.workflow_builder.reload_workflow_type(
                        defn["workflow_type"], defn["yaml_content"]
                    )
                    logger.info(
                        f"Pre-loaded DB definition: {defn['workflow_type']} "
                        f"v{defn['version']}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to pre-load definition "
                        f"'{defn['workflow_type']}': {e}"
                    )
        except Exception as e:
            logger.warning(f"Could not pre-load workflow definitions: {e}")

        # Start background pollers
        _definition_poller_task = asyncio.create_task(
            _definition_poller_loop(), name="definition_poller"
        )

    # Wire services into ConfigRollout step module
    from rufus_server.steps.config_rollout_steps import init_services as init_rollout_services
    init_rollout_services(persistence_provider, broadcast_service, device_service)

    # Initialize Policy Engine
    global policy_evaluator
    policy_evaluator = PolicyEvaluator()

    # Wire services into PolicyRollout step module
    from rufus_server.steps.policy_rollout_steps import init_services as init_policy_rollout_services
    init_policy_rollout_services(persistence_provider, policy_evaluator)

    # Initialize Rate Limit Service
    from rufus_server.rate_limit_service import RateLimitService
    rate_limit_service = RateLimitService(persistence_provider)

    # Initialize Auth Provider
    auth_provider = await load_auth_provider()
    set_auth_provider(auth_provider)
    logger.info("Auth provider: %s", os.getenv("RUFUS_AUTH_PROVIDER", "disabled"))

    # Load custom user routers (RUFUS_CUSTOM_ROUTERS=my_app.routes.router,my_app.webhooks.router)
    custom_routers_env = os.getenv("RUFUS_CUSTOM_ROUTERS", "").strip()
    if custom_routers_env:
        for router_path in custom_routers_env.split(","):
            router_path = router_path.strip()
            if not router_path:
                continue
            try:
                module_path, _, attr_name = router_path.rpartition(".")
                module = importlib.import_module(module_path)
                router_obj = getattr(module, attr_name)
                app.include_router(router_obj)
                logger.info(f"Mounted custom router: {router_path}")
            except Exception as e:
                logger.error(f"Failed to mount custom router '{router_path}': {e}")

    print("Rufus Edge Control Plane started.")


@app.on_event("shutdown")
async def shutdown_event():
    global persistence_provider, execution_provider, workflow_observer, _definition_poller_task
    if _definition_poller_task and not _definition_poller_task.done():
        _definition_poller_task.cancel()
        try:
            await _definition_poller_task
        except asyncio.CancelledError:
            pass
    from rufus_server.auth.loader import get_auth_provider
    auth_provider = get_auth_provider()
    if auth_provider:
        await auth_provider.close()
    if workflow_observer:
        await workflow_observer.close()
    if persistence_provider:
        await persistence_provider.close()
    if execution_provider:
        await execution_provider.close()
    print("Rufus Edge Control Plane shut down.")


# ─────────────────────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "rufus-edge-control-plane"}


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Management APIs
# ─────────────────────────────────────────────────────────────────────────────

async def _get_workflow_or_404(workflow_id: str):
    """Load a workflow by ID, raising 404 if not found."""
    try:
        return await workflow_engine.get_workflow(workflow_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/workflows", tags=["Workflows"])
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
            "initial_data_example": processed_config.get("initial_data_example", {}),
        })
    return available_workflows


@app.post(
    "/api/v1/workflow/start",
    response_model=WorkflowStartResponse,
    tags=["Workflows"],
    responses={
        400: {"description": "Unknown workflow type or invalid initial data"},
        503: {"description": "Workflow engine not initialized"},
    },
)
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


@app.get(
    "/api/v1/workflow/{workflow_id}/status",
    response_model=WorkflowStatusResponse,
    tags=["Workflows"],
    responses={
        404: {"description": "Workflow ID not found"},
        503: {"description": "Workflow engine not initialized"},
    },
)
async def get_workflow_status(
    workflow_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get workflow status."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        workflow = await _get_workflow_or_404(workflow_id)
    except HTTPException as exc:
        if exc.status_code == 404 and persistence_provider is not None:
            # Reconstruction may have failed (e.g. edge workflow whose step modules
            # aren't installed on the server). Check if the row actually exists.
            raw = await persistence_provider.load_workflow(workflow_id)
            if raw is None:
                raise  # genuine 404 — row doesn't exist
            # Return read-only status from raw DB data — no step reconstruction needed
            state = raw.get("state", {})
            if isinstance(state, str):
                try:
                    state = json.loads(state)
                except Exception:
                    state = {}
            steps_cfg = raw.get("steps_config", [])
            if isinstance(steps_cfg, str):
                try:
                    steps_cfg = json.loads(steps_cfg)
                except Exception:
                    steps_cfg = []
            current_step_raw = raw.get("current_step")
            return WorkflowStatusResponse(
                workflow_id=workflow_id,
                status=raw.get("status", "UNKNOWN"),
                current_step_name=str(current_step_raw) if current_step_raw is not None else None,
                state=state if isinstance(state, dict) else {},
                workflow_type=raw.get("workflow_type"),
                parent_execution_id=raw.get("parent_execution_id"),
                blocked_on_child_id=raw.get("blocked_on_child_id"),
                steps_config=steps_cfg if isinstance(steps_cfg, list) else [],
                current_step_info=None,
            )
        raise

    steps_config = [step.to_dict() for step in workflow.workflow_steps]

    current_step_info: Optional[Dict[str, Any]] = None
    if isinstance(workflow.current_step, int) and workflow.current_step < len(workflow.workflow_steps):
        step = workflow.workflow_steps[workflow.current_step]
        info: Dict[str, Any] = {
            "name": step.name,
            "type": type(step).__name__,
            "required_input": getattr(step, "required_input", []) or [],
            "input_schema": None,
        }
        if hasattr(step, "input_schema") and step.input_schema:
            try:
                info["input_schema"] = step.input_schema.model_json_schema()
            except Exception:
                pass
        current_step_info = info

    return WorkflowStatusResponse(
        workflow_id=workflow.id,
        status=workflow.status,
        current_step_name=workflow.current_step_name,
        state=workflow.state.model_dump(),
        workflow_type=workflow.workflow_type,
        parent_execution_id=workflow.parent_execution_id,
        blocked_on_child_id=workflow.blocked_on_child_id,
        steps_config=steps_config,
        current_step_info=current_step_info,
    )


@app.get("/api/v1/workflow/{workflow_id}/logs", tags=["Workflows"])
async def get_workflow_logs(
    workflow_id: str,
    limit: int = 100,
    log_level: Optional[str] = None,
    step_name: Optional[str] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get workflow execution logs (PostgreSQL backend required)."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    # Check if using PostgreSQL
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(
            status_code=501,
            detail="Execution logs require PostgreSQL backend"
        )

    # Build SQL query
    query = """
        SELECT id, workflow_id, execution_id, step_name, log_level, message, metadata, logged_at
        FROM workflow_execution_logs
        WHERE workflow_id = $1
    """
    params = [workflow_id]

    if log_level:
        query += f" AND log_level = ${len(params) + 1}"
        params.append(log_level)

    if step_name:
        query += f" AND step_name = ${len(params) + 1}"
        params.append(step_name)

    query += f" ORDER BY logged_at DESC LIMIT ${len(params) + 1}"
    params.append(limit)

    try:
        async with workflow_engine.persistence.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            logs = [dict(row) for row in rows]

            # Convert datetime to ISO format for JSON serialization
            for log in logs:
                if log.get('logged_at'):
                    log['logged_at'] = log['logged_at'].isoformat()

            # Return array directly (not wrapped in object) for UI compatibility
            return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


@app.get("/api/v1/workflow/{workflow_id}/current_step_info", tags=["Workflows"])
async def get_current_step_info(
    workflow_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get current step information including input schema."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        workflow = await workflow_engine.get_workflow(workflow_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow.status == "COMPLETED" or workflow.current_step >= len(workflow.workflow_steps):
        return {"name": "Workflow Complete", "required_input": [], "input_schema": None}

    step = workflow.workflow_steps[workflow.current_step]
    response = {
        "name": step.name,
        "type": type(step).__name__,
        "required_input": getattr(step, "required_input", []) or []
    }

    # Add input schema for dynamic form rendering
    if workflow.status == "WAITING_HUMAN":
        current_paused_step = workflow.workflow_steps[workflow.current_step]
        if isinstance(current_paused_step, HumanWorkflowStep):
            # New path: expose the HITL step's own input_schema
            if hasattr(current_paused_step, 'input_schema') and current_paused_step.input_schema:
                response["input_schema"] = current_paused_step.input_schema.model_json_schema()
            else:
                response["input_schema"] = None
        else:
            # Legacy path: show the next step's schema (old 2-step HITL pattern)
            next_step_index = workflow.current_step + 1
            if next_step_index < len(workflow.workflow_steps):
                next_step = workflow.workflow_steps[next_step_index]
                if hasattr(next_step, 'input_schema') and next_step.input_schema:
                    response["input_schema"] = next_step.input_schema.model_json_schema()
                else:
                    response["input_schema"] = None
            else:
                response["input_schema"] = None
    elif hasattr(step, "input_model") and step.input_model:
        try:
            response["input_schema"] = step.input_model.model_json_schema()
        except AttributeError:
            response["input_schema"] = None
    else:
        response["input_schema"] = None

    return response


@app.post(
    "/api/v1/workflow/{workflow_id}/next",
    response_model=WorkflowStepResponse,
    tags=["Workflows"],
    responses={
        404: {"description": "Workflow ID not found"},
        409: {"description": "Workflow is in a non-advanceable state"},
        422: {"description": "Step execution failed"},
        503: {"description": "Workflow engine not initialized"},
    },
)
async def next_workflow_step(
    workflow_id: str,
    request_data: WorkflowStepRequest,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Execute the next step in a workflow."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await _get_workflow_or_404(workflow_id)

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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except WorkflowFailedException as e:
        raise HTTPException(status_code=422, detail=f"Step '{e.step_name}' failed: {e.original_exception}")
    except SagaWorkflowException as e:
        raise HTTPException(status_code=409, detail=f"Saga rollback triggered by step '{e.step_name}': {e.original_exception}")
    except Exception as e:
        workflow.status = "FAILED"
        await workflow_engine.persistence.save_workflow(workflow_id, workflow.to_dict())
        raise HTTPException(status_code=500, detail=f"Unexpected error executing step: {e}")


@app.get("/api/v1/workflows/executions", tags=["Workflows"])
async def get_workflow_executions(
    status: Optional[str] = None,
    exclude_status: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """List workflow executions.

    Args:
        status: Filter by specific status (e.g., "ACTIVE", "FAILED")
        exclude_status: Exclude specific status (e.g., "COMPLETED")
        since: ISO 8601 datetime — only return workflows updated at or after this time
        limit: Maximum number of results to return
        offset: Number of results to skip
    """
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    filters = {}
    if status:
        filters['status'] = status

    workflow_list = await workflow_engine.persistence.list_workflows(**filters)

    # Apply exclude_status filter if provided
    if exclude_status:
        workflow_list = [wf for wf in workflow_list if wf.get('status') != exclude_status]

    # Apply since filter if provided
    if since:
        try:
            from datetime import datetime as _dt, timezone as _tz
            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
            def _ts(val):
                if val is None:
                    return _dt.min.replace(tzinfo=_tz.utc)
                if isinstance(val, str):
                    return _dt.fromisoformat(val.replace("Z", "+00:00"))
                if isinstance(val, _dt) and val.tzinfo is None:
                    return val.replace(tzinfo=_tz.utc)
                return val
            workflow_list = [wf for wf in workflow_list if _ts(wf.get('updated_at')) >= since_dt]
        except (ValueError, TypeError):
            pass

    total = len(workflow_list)
    page_items = workflow_list[offset:offset + limit]
    return {"total": total, "workflows": page_items}


@app.get("/api/v1/metrics/summary", tags=["Monitoring"])
async def get_metrics_summary(hours: int = 24):
    """Get aggregated metrics across workflows (PostgreSQL backend required)."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    # Check if using PostgreSQL
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(
            status_code=501,
            detail="Metrics require PostgreSQL backend"
        )

    try:
        async with workflow_engine.persistence.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    workflow_type,
                    COUNT(DISTINCT id) as total_executions,
                    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN id END) as completed,
                    COUNT(DISTINCT CASE WHEN status LIKE 'FAILED%' THEN id END) as failed,
                    COUNT(DISTINCT CASE WHEN status LIKE 'PENDING%' OR status = 'ACTIVE' THEN id END) as pending,
                    MAX(updated_at) as last_execution
                FROM workflow_executions
                WHERE created_at > NOW() - INTERVAL '1 hour' * $1
                GROUP BY workflow_type
                ORDER BY total_executions DESC
            """, hours)

            return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch metrics: {str(e)}")


@app.get("/api/v1/workflow/{workflow_id}/metrics", tags=["Workflows"])
async def get_workflow_metrics(
    workflow_id: str,
    limit: int = 500,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get performance metrics for a specific workflow (PostgreSQL backend required)."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(
            status_code=501,
            detail="Metrics require PostgreSQL backend"
        )

    try:
        async with workflow_engine.persistence.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT step_name, metric_name, metric_value, unit, tags, recorded_at
                FROM workflow_metrics
                WHERE workflow_id = $1
                ORDER BY recorded_at DESC
                LIMIT $2
            """, workflow_id, limit)

            metrics = [dict(row) for row in rows]

            # Convert datetime to ISO format
            for metric in metrics:
                if metric.get('recorded_at'):
                    metric['recorded_at'] = metric['recorded_at'].isoformat()

            return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch metrics: {str(e)}")


@app.get("/api/v1/workflow/{workflow_id}/audit", tags=["Workflows"])
async def get_workflow_audit_log(
    workflow_id: str,
    limit: int = 100,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get audit trail for workflow (PostgreSQL backend required)."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(
            status_code=501,
            detail="Audit logs require PostgreSQL backend"
        )

    try:
        async with workflow_engine.persistence.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT event_type, step_name, old_status, new_status, details, timestamp
                FROM workflow_audit_log
                WHERE workflow_id = $1
                ORDER BY timestamp DESC
                LIMIT $2
            """, workflow_id, limit)

            audit_logs = [dict(row) for row in rows]

            # Convert datetime to ISO format
            for log in audit_logs:
                if log.get('timestamp'):
                    log['timestamp'] = log['timestamp'].isoformat()

            return audit_logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch audit log: {str(e)}")


@app.get("/api/v1/admin/workers", tags=["Monitoring"])
async def get_registered_workers(
    limit: int = 100,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List registered worker nodes (PostgreSQL backend required)."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(
            status_code=501,
            detail="Worker registry requires PostgreSQL backend"
        )

    try:
        async with workflow_engine.persistence.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT worker_id, hostname, region, zone, capabilities, status, last_heartbeat, updated_at
                FROM worker_nodes
                ORDER BY last_heartbeat DESC
                LIMIT $1
            """, limit)

            workers = [dict(row) for row in rows]

            # Convert datetime to ISO format
            for worker in workers:
                if worker.get('last_heartbeat'):
                    worker['last_heartbeat'] = worker['last_heartbeat'].isoformat()
                if worker.get('updated_at'):
                    worker['updated_at'] = worker['updated_at'].isoformat()

            return workers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch workers: {str(e)}")


@app.post("/api/v1/workflow/{workflow_id}/retry", tags=["Workflows"])
async def retry_workflow(
    workflow_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Retry a failed workflow from the failed step."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        workflow_uuid = UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workflow ID format")

    # Load workflow
    workflow_dict = await workflow_engine.persistence.load_workflow(str(workflow_uuid))
    if not workflow_dict:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Allow retry for FAILED and FAILED_ROLLED_BACK workflows
    if workflow_dict['status'] not in ['FAILED', 'FAILED_ROLLED_BACK', 'FAILED_CHILD_WORKFLOW']:
        raise HTTPException(
            status_code=400,
            detail=f"Only failed workflows can be retried (current status: {workflow_dict['status']})"
        )

    # Reset to ACTIVE
    old_status = workflow_dict['status']
    workflow_dict['status'] = 'ACTIVE'
    await workflow_engine.persistence.save_workflow(str(workflow_uuid), workflow_dict)

    # Publish event
    from rufus.events import event_publisher
    await event_publisher._publish(
        'workflow:persistence',
        'workflow.status_changed',
        {
            "workflow_id": str(workflow_uuid),
            "old_status": old_status,
            "new_status": "ACTIVE",
            "retried": True
        }
    )

    # Dispatch async task to resume execution
    from rufus.tasks import resume_from_async_task
    steps = workflow_dict.get('steps_config', [])
    current_step_name = workflow_dict.get('current_step')
    current_step_index = next(
        (i for i, s in enumerate(steps) if s.get('name') == current_step_name), 0
    )
    resume_from_async_task.delay({}, str(workflow_uuid), current_step_index)

    return {"status": "retry_initiated", "workflow_id": workflow_id}


@app.post("/api/v1/workflow/{workflow_id}/rewind", tags=["Workflows"])
async def rewind_workflow(
    workflow_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Rewind workflow to previous step for debugging/correction."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        workflow_uuid = UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workflow ID format")

    # Load workflow
    workflow_dict = await workflow_engine.persistence.load_workflow(str(workflow_uuid))
    if not workflow_dict:
        raise HTTPException(status_code=404, detail="Workflow not found")

    steps = workflow_dict.get('steps_config', [])
    current_step_name = workflow_dict.get('current_step')

    current_index = next(
        (i for i, s in enumerate(steps) if s.get('name') == current_step_name), None
    )
    if current_index is None or current_index == 0:
        raise HTTPException(status_code=400, detail="Cannot rewind: already at first step")

    previous_step_name = steps[current_index - 1]['name']
    old_status = workflow_dict['status']
    workflow_dict['current_step'] = previous_step_name
    workflow_dict['status'] = 'ACTIVE'

    await workflow_engine.persistence.save_workflow(str(workflow_uuid), workflow_dict)

    # Publish event
    from rufus.events import event_publisher
    await event_publisher._publish(
        'workflow:persistence',
        'workflow.status_changed',
        {
            "workflow_id": str(workflow_uuid),
            "old_status": old_status,
            "new_status": "ACTIVE",
            "current_step": previous_step_name,
            "rewound": True
        }
    )

    return {
        "status": "rewound",
        "current_step": previous_step_name,
        "workflow_id": workflow_id
    }


@app.post(
    "/api/v1/workflow/{workflow_id}/resume",
    tags=["Workflows"],
    responses={
        400: {"description": "Workflow is not in WAITING_HUMAN state"},
        404: {"description": "Workflow ID not found"},
        422: {"description": "Step execution failed after resume"},
        503: {"description": "Workflow engine not initialized"},
    },
)
async def resume_workflow(
    workflow_id: str,
    request_data: ResumeWorkflowRequest,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Resume a paused workflow with user input."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        workflow_uuid = UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workflow ID format")

    # Load workflow
    workflow_dict = await workflow_engine.persistence.load_workflow(str(workflow_uuid))
    if not workflow_dict:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow_dict['status'] != 'WAITING_HUMAN':
        raise HTTPException(status_code=400, detail="Only paused (WAITING_HUMAN) workflows can be resumed")

    workflow = await _get_workflow_or_404(workflow_id)
    current_step_obj = workflow.workflow_steps[workflow.current_step] if workflow.workflow_steps else None
    current_step_name = current_step_obj.name if current_step_obj else None

    try:
        result_dict, next_step_name = await workflow.next_step(
            user_input=request_data.user_input or {}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except WorkflowFailedException as e:
        raise HTTPException(status_code=422, detail=f"Step '{e.step_name}' failed: {e.original_exception}")
    except SagaWorkflowException as e:
        raise HTTPException(status_code=409, detail=f"Saga rollback triggered by step '{e.step_name}': {e.original_exception}")
    except Exception as e:
        workflow.status = "FAILED"
        await workflow_engine.persistence.save_workflow(workflow_id, workflow.to_dict())
        raise HTTPException(status_code=500, detail=f"Unexpected error executing step: {e}")

    # Publish event
    from rufus.events import event_publisher
    await event_publisher._publish(
        'workflow:persistence',
        'workflow.resume_requested',
        {
            "workflow_id": str(workflow_uuid),
            "user_input": request_data.user_input
        }
    )

    return {
        "status": workflow.status,
        "workflow_id": workflow_id,
        "current_step_name": current_step_name,
        "next_step_name": next_step_name
    }


@app.websocket("/api/v1/subscribe")
async def subscribe(websocket: WebSocket):
    """
    WebSocket endpoint for real-time workflow updates.

    Single persistent connection that supports subscribing to multiple workflows.

    Client sends: {"action": "subscribe", "workflow_id": "xxx"}
    Client sends: {"action": "unsubscribe", "workflow_id": "xxx"}

    Implements ping/pong keepalive to detect half-open connections.
    """
    await websocket.accept()
    logger.warning(f"[WS] WebSocket connection accepted")

    # Send connection handshake - connecting state
    await websocket.send_json({"type": "handshake", "state": "connecting"})
    logger.warning(f"[WS-HANDSHAKE] Sent 'connecting'")

    # Get Redis connection (lazy import — redis is optional when not using pub/sub)
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        await websocket.send_json({"type": "error", "message": "Redis not available on this server"})
        await websocket.close(code=1011)
        return
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_url = os.getenv("REDIS_URL", f"redis://{redis_host}:6379/0")
    redis_client = redis_asyncio.from_url(redis_url, decode_responses=True)

    # Track subscribed workflows
    subscribed_workflows = set()
    pubsub = redis_client.pubsub()

    # Ping/pong state
    ping_interval = 15  # Send ping every 15 seconds
    pong_timeout = 30   # Wait up to 30 seconds for pong
    last_pong = asyncio.get_event_loop().time()
    ping_task = None
    redis_task = None
    client_task = None

    async def ping_pong_loop():
        """Send periodic pings to keep connection alive and detect half-open connections."""
        nonlocal last_pong
        try:
            while True:
                await asyncio.sleep(ping_interval)

                # Check if we've received a pong recently
                current_time = asyncio.get_event_loop().time()
                if current_time - last_pong > pong_timeout:
                    logger.warning(f"[WS-PING] No pong received for {pong_timeout}s, closing connection")
                    await websocket.close(code=1008, reason="Pong timeout")
                    break

                # Send ping
                logger.debug(f"[WS-PING] Sending ping")
                await websocket.send_json({"type": "ping", "timestamp": current_time})
        except Exception as e:
            logger.error(f"[WS-PING] Ping loop error: {e}")

    async def listen_for_client_messages():
        """Listen for subscribe/unsubscribe commands and pong responses from client."""
        nonlocal last_pong
        try:
            while True:
                # Receive message from WebSocket
                message = await websocket.receive_json()
                action = message.get('action') or message.get('type')

                if action == 'pong':
                    last_pong = asyncio.get_event_loop().time()
                    logger.debug(f"[WS-PONG] Received pong")

                elif action == 'subscribe':
                    workflow_id = message.get('workflow_id')
                    if not workflow_id:
                        logger.warning(f"[WS] Subscribe message missing workflow_id")
                        continue

                    logger.info(f"[WS] Client subscribing to workflow {workflow_id}")

                    # Add to subscribed set
                    subscribed_workflows.add(workflow_id)

                    # Subscribe to Redis channel
                    channel = f"rufus:events:{workflow_id}"
                    await pubsub.subscribe(channel)
                    logger.info(f"[WS] Subscribed to Redis channel {channel}")

                    # Send initial workflow state
                    if workflow_engine is not None:
                        try:
                            workflow = await workflow_engine.get_workflow(workflow_id)
                            initial_state = {
                                "type": "initial_state",
                                "workflow_id": workflow_id,
                                "id": str(workflow.id),
                                "status": workflow.status,
                                "current_step": workflow.current_step_name,
                                "state": workflow.state.model_dump(),
                                "workflow_type": workflow.workflow_type,
                                "steps_config": [step.to_dict() for step in workflow.workflow_steps],
                                "parent_execution_id": str(workflow.parent_execution_id) if workflow.parent_execution_id else None,
                                "blocked_on_child_id": str(workflow.blocked_on_child_id) if workflow.blocked_on_child_id else None,
                                "skipped_steps": (getattr(workflow, 'metadata', None) or {}).get("skipped_steps", [])
                            }
                            await websocket.send_json(initial_state)
                            logger.info(f"[WS] Sent initial state for workflow {workflow_id}")
                        except Exception as e:
                            logger.error(f"[WS] Failed to send initial state for workflow {workflow_id}: {e}")

                    # Send subscription confirmation
                    await websocket.send_json({
                        "type": "subscribed",
                        "workflow_id": workflow_id
                    })

                elif action == 'unsubscribe':
                    workflow_id = message.get('workflow_id')
                    if not workflow_id:
                        logger.warning(f"[WS] Unsubscribe message missing workflow_id")
                        continue

                    logger.info(f"[WS] Client unsubscribing from workflow {workflow_id}")

                    # Remove from subscribed set
                    subscribed_workflows.discard(workflow_id)

                    # Unsubscribe from Redis channel
                    channel = f"rufus:events:{workflow_id}"
                    await pubsub.unsubscribe(channel)
                    logger.info(f"[WS] Unsubscribed from Redis channel {channel}")

                    # Send unsubscription confirmation
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "workflow_id": workflow_id
                    })

                else:
                    logger.debug(f"[WS] Received unknown message type: {action}")

        except Exception as e:
            logger.error(f"[WS] Client message listener error: {e}")

    async def listen_for_redis_messages():
        """Listen for Redis pub/sub messages and forward to WebSocket."""
        try:
            while True:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                    if message and message['type'] == 'message':
                        try:
                            channel = message['channel']
                            workflow_id = channel.replace('rufus:events:', '')
                            logger.info(f"[WS-REDIS] Received message for workflow {workflow_id}")
                            event_data = json.loads(message['data'])
                            event_data['workflow_id'] = workflow_id
                            logger.info(f"[WS-REDIS] Event keys: {list(event_data.keys())}")
                            await websocket.send_json(event_data)
                            logger.info(f"[WS-REDIS] Successfully forwarded message to client")
                        except json.JSONDecodeError as e:
                            logger.error(f"[WS-REDIS] Failed to parse message: {e}")
                        except Exception as e:
                            import traceback
                            logger.error(f"[WS-REDIS] Failed to send message: {type(e).__name__}: {str(e)}")
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            break
                except asyncio.CancelledError:
                    raise  # Let cancellation propagate cleanly
                except Exception as e:
                    err_msg = str(e)
                    if "connection not set" in err_msg or "not subscribed" in err_msg:
                        # No channels subscribed yet — wait for client to subscribe
                        await asyncio.sleep(0.1)
                    else:
                        logger.error(f"[WS-REDIS] Error in message loop: {e}")
                        break
        except asyncio.CancelledError:
            pass  # Normal shutdown
        except Exception as e:
            logger.error(f"[WS-REDIS] Redis listener error: {e}")

    try:
        # Send connection handshake - connected state
        await websocket.send_json({"type": "handshake", "state": "connected"})
        logger.warning(f"[WS-HANDSHAKE] Sent 'connected'")

        # Start ping/pong keepalive loop
        ping_task = asyncio.create_task(ping_pong_loop())
        logger.warning(f"[WS-PING] Started ping/pong loop")

        # Start listening for client messages (subscribe/unsubscribe/pong)
        client_task = asyncio.create_task(listen_for_client_messages())
        logger.warning(f"[WS] Started client message listener")

        # Start listening for Redis messages
        redis_task = asyncio.create_task(listen_for_redis_messages())
        logger.warning(f"[WS-REDIS] Started Redis message listener")

        # Wait for any task to complete (or fail)
        done, pending = await asyncio.wait(
            [ping_task, client_task, redis_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Debug: which task completed?
        for task in done:
            task_name = "unknown"
            if task == ping_task:
                task_name = "ping_task"
            elif task == client_task:
                task_name = "client_task"
            elif task == redis_task:
                task_name = "redis_task"

            logger.warning(f"[WS-DEBUG] Task completed: {task_name}")
            if task.exception():
                logger.error(f"[WS-DEBUG] Task exception: {task.exception()}")

        logger.warning(f"[WS] Task completed, cleaning up...")

        # Cancel any pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] WebSocket error: {e}")
    finally:
        # Cancel tasks if still running
        if ping_task and not ping_task.done():
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        if client_task and not client_task.done():
            client_task.cancel()
            try:
                await client_task
            except asyncio.CancelledError:
                pass
        if redis_task and not redis_task.done():
            redis_task.cancel()
            try:
                await redis_task
            except asyncio.CancelledError:
                pass

        # Cleanup Redis
        try:
            # Unsubscribe from all channels
            for workflow_id in subscribed_workflows:
                channel = f"rufus:events:{workflow_id}"
                await pubsub.unsubscribe(channel)

            await redis_client.close()
            logger.info(f"[WS] Cleaned up Redis connection")
        except Exception as e:
            logger.error(f"[WS] Cleanup error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Device Management APIs (TODO: Implement)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/devices/register", response_model=DeviceRegistrationResponse, tags=["Devices"])
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


@app.get("/api/v1/devices", tags=["Devices"])
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


@app.get("/api/v1/devices/{device_id}", tags=["Devices"])
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


@app.delete("/api/v1/devices/{device_id}", tags=["Devices"])
async def delete_device(
    device_id: str,
    x_registration_key: str = Header(..., alias="X-Registration-Key")
):
    """Delete a device (requires registration key for security)."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Validate registration key
    expected_key = os.getenv("RUFUS_REGISTRATION_KEY", "dev-registration-key")
    if x_registration_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid registration key")

    try:
        await device_service.delete_device(device_id)
        return {"status": "deleted", "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deletion failed: {e}")


@app.get("/api/v1/devices/{device_id}/config", tags=["Devices"])
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

    # Serialize datetime to ISO format
    created_at = config.get("created_at")
    if created_at and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()

    return JSONResponse(
        content={
            "version": config.get("config_version"),
            "updated_at": created_at,
            **config_data,
        },
        headers={"ETag": current_etag}
    )


@app.post("/api/v1/devices/{device_id}/heartbeat", response_model=DeviceHeartbeatResponse, tags=["Devices"])
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


@app.post("/api/v1/devices/{device_id}/sync", response_model=SyncResponse, tags=["Devices"])
async def sync_device_transactions(
    device_id: str,
    request_data: SyncRequest,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Receive offline transactions from edge device (Store-and-Forward).

    HMAC verification is performed on each transaction to ensure payload integrity.
    """
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    # Authenticate device
    if not await device_service.authenticate_device(device_id, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Convert request transactions to dict format (include HMAC for verification)
    transactions = [
        {
            "transaction_id": t.transaction_id,
            "idempotency_key": f"{device_id}:{t.transaction_id}",
            "encrypted_payload": t.encrypted_blob,
            "encrypted_blob": t.encrypted_blob,  # Needed for HMAC verification
            "encryption_key_id": t.encryption_key_id,
            "hmac": t.hmac,  # HMAC signature from device
        }
        for t in request_data.transactions
    ]

    result = await device_service.sync_transactions(
        device_id=device_id,
        transactions=transactions,
        api_key=x_api_key,  # Pass API key for HMAC verification
    )

    # Convert to response format
    from rufus_server.api_models import SyncAck
    return SyncResponse(
        accepted=[SyncAck(**a) for a in result["accepted"]],
        rejected=[SyncAck(**r) for r in result["rejected"]],
        server_sequence=result.get("server_sequence", 0),
        next_sync_delay=30,
    )


def _parse_edge_dt(s) -> Optional[datetime]:
    """Parse ISO8601 string from edge device → datetime. Returns None on failure."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


@app.post("/api/v1/devices/{device_id}/sync/workflows", response_model=WorkflowSyncResponse, tags=["Devices"])
async def sync_edge_workflows(
    device_id: str,
    request_data: WorkflowSyncRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Ingest completed edge workflow executions + audit logs into cloud PostgreSQL.

    Called by EdgeWorkflowSyncer on each online sync cycle. Idempotent — duplicate
    workflow IDs are silently skipped (ON CONFLICT DO NOTHING).
    """
    if persistence_provider is None:
        raise HTTPException(status_code=503, detail="Persistence not initialized")

    if not isinstance(persistence_provider, PostgresPersistenceProvider):
        raise HTTPException(status_code=503, detail="Workflow sync requires PostgreSQL persistence")

    accepted_ids = []
    skipped = 0
    audit_count = 0

    async with persistence_provider.pool.acquire() as conn:
        for wf in request_data.workflows:
            existing = await conn.fetchval(
                "SELECT id FROM workflow_executions WHERE id=$1", wf.get("id")
            )
            if existing:
                skipped += 1
                continue

            await conn.execute(
                """INSERT INTO workflow_executions
                   (id, workflow_type, workflow_version, definition_snapshot, current_step,
                    status, state, steps_config, state_model_path, saga_mode,
                    completed_steps_stack, parent_execution_id, data_region, priority,
                    idempotency_key, metadata, owner_id, created_at, updated_at, completed_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
                   ON CONFLICT (id) DO NOTHING""",
                wf.get("id"), wf.get("workflow_type"), wf.get("workflow_version"),
                wf.get("definition_snapshot"), str(wf.get("current_step", 0)), wf.get("status"),
                wf.get("state", "{}"), wf.get("steps_config", "[]"),
                wf.get("state_model_path", ""), bool(wf.get("saga_mode", 0)),
                wf.get("completed_steps_stack", "[]"), wf.get("parent_execution_id"),
                wf.get("data_region", "edge"), int(wf.get("priority", 5)),
                wf.get("idempotency_key"), wf.get("metadata", "{}"),
                device_id,
                _parse_edge_dt(wf.get("created_at")), _parse_edge_dt(wf.get("updated_at")),
                _parse_edge_dt(wf.get("completed_at")),
            )
            accepted_ids.append(wf["id"])

        # Insert audit rows only for newly accepted workflows
        accepted_set = set(accepted_ids)
        for log in request_data.audit_logs:
            if log.get("workflow_id") not in accepted_set:
                continue
            try:
                await conn.execute(
                    """INSERT INTO workflow_audit_log
                       (workflow_id, event_type, step_name, actor, old_status, new_status, details, timestamp)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    log.get("workflow_id"), log.get("event_type"), log.get("step_name"),
                    log.get("user_id") or log.get("worker_id"),
                    log.get("old_state"), log.get("new_state"),
                    log.get("metadata", "{}"),
                    _parse_edge_dt(log.get("recorded_at")),
                )
                audit_count += 1
            except Exception as audit_err:
                logger.warning(f"Audit row insert skipped: {audit_err}")

    return WorkflowSyncResponse(
        accepted_workflow_ids=accepted_ids,
        audit_rows_inserted=audit_count,
        skipped=skipped,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Debug UI (ported from Confucius)
# ─────────────────────────────────────────────────────────────────────────────

debug_ui_static_path = Path(__file__).parent / "debug_ui" / "static"
if debug_ui_static_path.is_dir():
    app.mount("/static", StaticFiles(directory=debug_ui_static_path), name="debug_ui_static")
    logger.info(f"✅ Debug UI static files mounted at /static from {debug_ui_static_path}")
else:
    logger.warning(f"⚠️  Debug UI static files not found at {debug_ui_static_path}")

debug_ui_templates_path = Path(__file__).parent / "debug_ui" / "templates"
if debug_ui_templates_path.is_dir():
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=debug_ui_templates_path)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def debug_ui_root(request: Request):
        """Serves the Debug UI's main page (ported from Confucius)."""
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/debug", response_class=HTMLResponse, include_in_schema=False)
    async def debug_ui_alias(request: Request):
        """Alias for Debug UI."""
        return templates.TemplateResponse("index.html", {"request": request})

    logger.info(f"✅ Debug UI templates loaded from {debug_ui_templates_path}")
    logger.info("🎨 Debug UI available at http://localhost:8000/ and http://localhost:8000/debug")
else:
    logger.warning(f"⚠️  Debug UI templates not found at {debug_ui_templates_path}")
    logger.info("💡 To enable Debug UI, copy templates from confucius/src/confucius/contrib/")


# ─────────────────────────────────────────────────────────────────────────────
# Policy Engine APIs
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/policies", response_model=Policy, tags=["Policies"])
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


@app.get("/api/v1/policies", response_model=List[Policy], tags=["Policies"])
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


@app.get("/api/v1/policies/{policy_id}", response_model=Policy, tags=["Policies"])
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


@app.put("/api/v1/policies/{policy_id}/status", tags=["Policies"])
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


@app.post("/api/v1/policies/rollout", tags=["Policies"],
          responses={
              200: {"description": "Policy created successfully"},
              409: {"description": "Saga compensation triggered — policy rolled back"},
              422: {"description": "Workflow failed without compensation"},
          })
async def create_policy_rollout(
    policy: Policy,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Create a new deployment policy via durable workflow with saga compensation."""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    policy_data = policy.model_dump(mode="json")
    if user:
        policy_data["created_by"] = user.user_id

    try:
        workflow = await workflow_engine.start_workflow(
            workflow_type="PolicyRollout",
            initial_data={"policy_data": policy_data, "created_by": policy_data.get("created_by")},
            owner_id=user.user_id if user else None,
        )
        await workflow.enable_saga_mode()
        result, _ = await workflow.next_step(user_input={})
    except WorkflowFailedException as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Policy rollout failed: {exc.original_exception}"
        )
    except SagaWorkflowException as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Policy rollout compensated (saga): {exc.original_exception}"
        )

    final = await workflow_engine.get_workflow(workflow.id)
    state = final.state
    return {
        "workflow_id": str(workflow.id),
        "policy_id": state.policy_id,
        "policy_name": state.policy_name,
        "rollout_outcome": state.rollout_outcome,
        "completed_at": state.completed_at,
    }


@app.post("/api/v1/update-check", response_model=UpdateInstruction, tags=["Devices"])
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


@app.post("/api/v1/devices/{device_id}/update-status", tags=["Devices"])
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


@app.get("/api/v1/devices/{device_id}/assignment", tags=["Devices"])
async def get_device_assignment(
    device_id: str,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Get current artifact assignment for a device."""
    assignment = device_assignments.get(device_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="No assignment found for device")

    return assignment


@app.get("/api/v1/artifacts/{artifact_name}", tags=["Devices"])
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


@app.post("/api/v1/devices/{device_id}/commands", tags=["Devices"])
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


@app.get("/api/v1/devices/{device_id}/commands", tags=["Commands"])
async def list_device_commands(
    device_id: str,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """List commands sent to an edge device, ordered by created_at DESC."""
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    device = await device_service.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    commands = await device_service.list_commands(device_id, status=status)
    total = len(commands)
    return {"commands": commands[offset: offset + limit], "total": total}


@app.post("/api/v1/devices/commands/broadcast", tags=["Devices"])
async def broadcast_device_command(
    request: DeviceBroadcastRequest,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """
    Broadcast a command to all registered edge devices.

    Devices receive the command on their next heartbeat poll (within 30–60 s).
    Primary use: push updated workflow definitions via the `update_workflow` command.
    """
    if device_service is None:
        raise HTTPException(status_code=503, detail="Device service not initialized")

    devices = await device_service.list_devices(limit=1000)
    device_ids = [d["device_id"] for d in devices]

    import uuid as _uuid
    queued, failed = 0, 0
    for device_id in device_ids:
        try:
            await device_service.send_command(
                device_id=device_id,
                command_type=request.command,
                command_data=request.command_data,
                expires_in_seconds=request.timeout_seconds,
            )
            queued += 1
        except Exception as exc:
            logger.error(f"broadcast: failed to queue for {device_id}: {exc}")
            failed += 1

    return {
        "command_id": f"broadcast-{_uuid.uuid4().hex[:12]}",
        "status": "queued",
        "broadcast": True,
        "queued": queued,
        "failed": failed,
        "device_count": len(device_ids),
    }


@app.post("/api/v1/devices/{device_id}/commands/{command_id}/status", tags=["Devices"])
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
    # Authenticate device via API key in query params before accepting
    api_key = websocket.query_params.get("api_key")
    if not api_key:
        await websocket.close(code=4003)
        logger.warning(f"WebSocket rejected (no api_key): {device_id}")
        return

    if device_service is not None:
        try:
            device = await device_service.get_device(device_id)
            if device is None or getattr(device, "api_key", None) != api_key:
                await websocket.close(code=4003)
                logger.warning(f"WebSocket rejected (invalid api_key): {device_id}")
                return
        except Exception as e:
            logger.error(f"WebSocket auth error for {device_id}: {e}")
            await websocket.close(code=4003)
            return

    # Accept connection after successful auth
    await websocket.accept()

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


@app.get("/api/v1/devices/{device_id}/connection", tags=["Devices"])
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

@app.get("/api/v1/commands/versions", tags=["Commands"])
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


@app.get("/api/v1/commands/versions/{version_id}", tags=["Commands"])
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


@app.get("/api/v1/commands/{command_type}/versions", tags=["Commands"])
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


@app.get("/api/v1/commands/{command_type}/versions/latest", tags=["Commands"])
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


@app.post("/api/v1/commands/{command_type}/validate", tags=["Commands"])
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


@app.get("/api/v1/commands/{command_type}/changelog", tags=["Commands"])
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

@app.post("/api/v1/admin/commands/versions", tags=["Commands"])
async def create_command_version(
    version_data: Dict[str, Any],
    user: UserContext = Depends(require_admin)
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


@app.put("/api/v1/admin/commands/versions/{version_id}", tags=["Commands"])
async def update_command_version(
    version_id: str,
    updates: Dict[str, Any],
    user: UserContext = Depends(require_admin)
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

    success = await version_service.update_version(version_id, updates)

    if not success:
        raise HTTPException(status_code=404, detail="Version not found or no valid updates")

    return {
        "version_id": version_id,
        "status": "updated"
    }


@app.post("/api/v1/admin/commands/versions/{version_id}/deprecate", tags=["Commands"])
async def deprecate_command_version(
    version_id: str,
    reason_data: Dict[str, str],
    user: UserContext = Depends(require_admin)
):
    """
    Deprecate command version (admin only).

    Body: {
        "reason": "Replaced by version 2.0.0"
    }
    """
    if version_service is None:
        raise HTTPException(status_code=503, detail="Version service not initialized")

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

@app.post("/api/v1/webhooks", tags=["Webhooks"])
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


@app.get("/api/v1/webhooks", tags=["Webhooks"])
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


@app.get("/api/v1/webhooks/{webhook_id}", tags=["Webhooks"])
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


@app.put("/api/v1/webhooks/{webhook_id}", tags=["Webhooks"])
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


@app.delete("/api/v1/webhooks/{webhook_id}", tags=["Webhooks"])
async def delete_webhook(
    webhook_id: str,
    user: UserContext = Depends(require_admin)
):
    """Delete webhook registration."""
    if webhook_service is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")

    success = await webhook_service.delete_webhook(webhook_id)

    return {
        "webhook_id": webhook_id,
        "status": "deleted"
    }


@app.get("/api/v1/webhooks/{webhook_id}/deliveries", tags=["Webhooks"])
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


@app.post("/api/v1/webhooks/test", tags=["Webhooks"])
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


@app.get("/api/v1/rollout/status", tags=["Policies"])
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


@app.post("/api/v1/broadcasts", tags=["Broadcasts"])
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
        broadcast_service = BroadcastService(persistence_provider, device_service)

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


@app.get("/api/v1/broadcasts/{broadcast_id}", tags=["Broadcasts"])
async def get_broadcast_status(
    broadcast_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get broadcast execution progress."""
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence_provider, device_service)

    progress = await broadcast_service.get_broadcast_progress(broadcast_id)

    if not progress:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    return progress.dict()


@app.get("/api/v1/broadcasts", tags=["Broadcasts"])
async def list_broadcasts(
    status: Optional[str] = None,
    limit: int = 50,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """List recent broadcasts."""
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence_provider, device_service)

    broadcasts = await broadcast_service.list_broadcasts(status=status, limit=limit)

    return {
        "total": len(broadcasts),
        "broadcasts": broadcasts
    }


@app.delete("/api/v1/broadcasts/{broadcast_id}", tags=["Broadcasts"])
async def cancel_broadcast(
    broadcast_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Cancel ongoing broadcast."""
    global broadcast_service

    if not broadcast_service:
        from rufus_server.broadcast_service import BroadcastService
        broadcast_service = BroadcastService(persistence_provider, device_service)

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
# Config Rollout Endpoint
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/config/rollout", tags=["Configuration"],
          responses={
              200: {"description": "Rollout completed successfully"},
              409: {"description": "Saga compensation triggered — previous config restored"},
              422: {"description": "Workflow failed without compensation"},
          })
async def start_config_rollout(
    request_body: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Trigger a fleet-wide config push.

    Runs the ConfigRollout workflow: validate → create config version →
    broadcast to devices → monitor progress (LOOP/WHILE) → finalize.

    Saga compensation automatically restores the previous config if broadcast fails.
    """
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    # Inject created_by from auth context
    if user and "created_by" not in request_body:
        request_body["created_by"] = user.user_id

    try:
        workflow = await workflow_engine.start_workflow(
            workflow_type="ConfigRollout",
            initial_data=request_body,
            owner_id=user.user_id if user else None,
        )
        # Enable saga compensation before running steps
        await workflow.enable_saga_mode()
        # Drive to completion — automate_next chains all steps in one call
        result, _ = await workflow.next_step(user_input={})
    except WorkflowFailedException as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Config rollout failed: {exc.original_exception}"
        )
    except SagaWorkflowException as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Config rollout compensated (saga): {exc.original_exception}"
        )

    # Reload final workflow state
    final = await workflow_engine.get_workflow(workflow.id)
    state = final.state

    return {
        "workflow_id": workflow.id,
        "status": final.status,
        "rollout_outcome": getattr(state, "rollout_outcome", None),
        "broadcast_id": getattr(state, "broadcast_id", None),
        "new_config_etag": getattr(state, "new_config_etag", None),
    }


# ═════════════════════════════════════════════════════════════════════════
# Template Endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/templates", tags=["Configuration"])
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


@app.get("/api/v1/templates/{template_name}", tags=["Configuration"])
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


@app.get("/api/v1/templates", tags=["Configuration"])
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


@app.delete("/api/v1/templates/{template_name}", tags=["Configuration"])
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


@app.post("/api/v1/templates/{template_name}/apply", tags=["Configuration"])
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

@app.post("/api/v1/batches", tags=["Batch Operations"])
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


@app.get("/api/v1/batches/{batch_id}", tags=["Batch Operations"])
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


@app.get("/api/v1/batches", tags=["Batch Operations"])
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


@app.delete("/api/v1/batches/{batch_id}", tags=["Batch Operations"])
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

@app.post("/api/v1/schedules", tags=["Scheduling"])
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
            device_service = DeviceService(persistence_provider)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence_provider, device_service)

        schedule_service = ScheduleService(persistence_provider, device_service, broadcast_service)

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


@app.get("/api/v1/schedules/{schedule_id}", tags=["Scheduling"])
async def get_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get schedule details and execution history."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence_provider)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence_provider, device_service)

        schedule_service = ScheduleService(persistence_provider, device_service, broadcast_service)

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


@app.get("/api/v1/schedules", tags=["Scheduling"])
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
            device_service = DeviceService(persistence_provider)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence_provider, device_service)

        schedule_service = ScheduleService(persistence_provider, device_service, broadcast_service)

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


@app.post("/api/v1/schedules/{schedule_id}/pause", tags=["Scheduling"])
async def pause_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Pause an active schedule."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence_provider)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence_provider, device_service)

        schedule_service = ScheduleService(persistence_provider, device_service, broadcast_service)

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


@app.post("/api/v1/schedules/{schedule_id}/resume", tags=["Scheduling"])
async def resume_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Resume a paused schedule."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence_provider)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence_provider, device_service)

        schedule_service = ScheduleService(persistence_provider, device_service, broadcast_service)

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


@app.delete("/api/v1/schedules/{schedule_id}", tags=["Scheduling"])
async def cancel_schedule(
    schedule_id: str,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Cancel a schedule."""
    global schedule_service, device_service, broadcast_service

    if not schedule_service:
        from rufus_server.schedule_service import ScheduleService

        if not device_service:
            device_service = DeviceService(persistence_provider)

        if not broadcast_service:
            from rufus_server.broadcast_service import BroadcastService
            broadcast_service = BroadcastService(persistence_provider, device_service)

        schedule_service = ScheduleService(persistence_provider, device_service, broadcast_service)

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

@app.post("/api/v1/audit/query", tags=["Audit"])
async def query_audit_logs(
    query_data: dict,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """
    Query workflow audit events across all workflows.

    Example:
    ```json
    {
      "start_time": "2026-02-01T00:00:00Z",
      "end_time": "2026-02-04T23:59:59Z",
      "event_types": ["WORKFLOW_COMPLETED", "WORKFLOW_FAILED"],
      "limit": 50,
      "offset": 0
    }
    ```
    """
    limit  = int(query_data.get("limit", 50))
    offset = int(query_data.get("offset", 0))
    event_types = query_data.get("event_types") or []
    start_time  = query_data.get("start_time")
    end_time    = query_data.get("end_time")

    filters = ["1=1"]
    args    = []
    idx     = 1

    if event_types:
        filters.append(f"event_type = ANY(${idx}::text[])")
        args.append(event_types); idx += 1
    if start_time:
        filters.append(f"timestamp >= ${idx}::timestamptz")
        args.append(start_time); idx += 1
    if end_time:
        filters.append(f"timestamp <= ${idx}::timestamptz")
        args.append(end_time); idx += 1

    where = " AND ".join(filters)

    try:
        async with workflow_engine.persistence.pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM workflow_audit_log WHERE {where}", *args
            )
            rows = await conn.fetch(
                f"""
                SELECT id, workflow_id, event_type, step_name, actor,
                       old_status, new_status, details, timestamp
                FROM workflow_audit_log
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT {limit} OFFSET {offset}
                """,
                *args
            )
        entries = [
            {
                "log_id":      str(row["id"]),
                "timestamp":   row["timestamp"].isoformat() if row["timestamp"] else None,
                "event_type":  row["event_type"],
                "entity_type": "workflow",
                "entity_id":   row["workflow_id"],
                "actor":       row["actor"] or "system",
            }
            for row in rows
        ]
        return {"entries": entries, "total_count": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query audit log: {str(e)}")


@app.post("/api/v1/audit/export", tags=["Audit"])
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
        audit_service = AuditService(workflow_engine.persistence)

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


@app.get("/api/v1/audit/stats", tags=["Audit"])
async def get_audit_stats(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    user: Optional[UserContext] = Depends(get_current_user)
):
    """Get audit log statistics."""
    global audit_service

    if not audit_service:
        from rufus_server.audit_service import AuditService
        audit_service = AuditService(workflow_engine.persistence)

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

@app.post("/api/v1/authorization/check", tags=["Authorization"])
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


@app.post("/api/v1/approvals", tags=["Authorization"])
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


@app.get("/api/v1/approvals/{approval_id}", tags=["Authorization"])
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


@app.get("/api/v1/approvals", tags=["Authorization"])
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


@app.post("/api/v1/approvals/{approval_id}/approve", tags=["Authorization"])
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


@app.post("/api/v1/approvals/{approval_id}/reject", tags=["Authorization"])
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


@app.delete("/api/v1/approvals/{approval_id}", tags=["Authorization"])
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

@app.get("/api/v1/rate-limits/status", tags=["Rate Limiting"])
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


@app.get("/api/v1/admin/rate-limits", tags=["Rate Limiting"])
async def list_rate_limits(
    is_active: Optional[bool] = None,
    user: UserContext = Depends(require_admin)
):
    """
    List all rate limit rules.

    Admin endpoint - requires admin privileges in production.
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

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


@app.put("/api/v1/admin/rate-limits/{rule_name}", tags=["Rate Limiting"])
async def update_rate_limit(
    rule_name: str,
    update_data: dict,
    user: UserContext = Depends(require_admin)
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


@app.post("/api/v1/admin/rate-limits", tags=["Rate Limiting"])
async def create_rate_limit(
    rule_data: dict,
    user: UserContext = Depends(require_admin)
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


@app.delete("/api/v1/admin/rate-limits/{rule_name}", tags=["Rate Limiting"])
async def delete_rate_limit(
    rule_name: str,
    user: UserContext = Depends(require_admin)
):
    """
    Deactivate a rate limit rule (soft delete).

    Admin endpoint - requires admin privileges in production.
    """
    if not rate_limit_service:
        raise HTTPException(status_code=503, detail="Rate limiting not initialized")

    success = await rate_limit_service.delete_rule(rule_name)

    if not success:
        raise HTTPException(status_code=404, detail="Rate limit rule not found")

    return {
        "rule_name": rule_name,
        "status": "deactivated",
        "message": "Rate limit rule deactivated successfully"
    }


# ─────────────────────────────────────────────────────────────────────────────
# Worker Fleet Management
# Route ordering is critical: /workers/broadcast must be registered BEFORE
# /workers/{worker_id} or FastAPI will interpret "broadcast" as a worker_id.
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/workers", tags=["Monitoring"])
async def list_workers(
    status: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """List registered Celery worker nodes (PostgreSQL backend required)."""
    if worker_service is None:
        raise HTTPException(
            status_code=503,
            detail="Worker service not initialized (requires PostgreSQL backend)"
        )
    workers = await worker_service.list_workers(
        status=status, region=region, limit=limit, offset=offset
    )
    return {"workers": workers, "total": len(workers)}


@app.post("/api/v1/workers/broadcast", tags=["Monitoring"])
async def broadcast_worker_command(
    request: WorkerBroadcastRequest,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """
    Broadcast a command to all workers (or a filtered subset).

    Use `target_filter` to narrow recipients, e.g. `{"region": "us-east-1"}`.
    An empty `target_filter` targets all online workers.
    Workers pick up the command within 30s (next heartbeat cycle).
    """
    if worker_service is None:
        raise HTTPException(
            status_code=503,
            detail="Worker service not initialized (requires PostgreSQL backend)"
        )
    command_id = await worker_service.broadcast_command(
        command_type=request.command_type,
        target_filter=request.target_filter,
        command_data=request.command_data,
        priority=request.priority,
        expires_in_seconds=request.expires_in_seconds,
        created_by=user.user_id if user else None,
    )
    return {"command_id": command_id, "status": "pending", "broadcast": True}


@app.get("/api/v1/workers/{worker_id}", tags=["Monitoring"])
async def get_worker(
    worker_id: str,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """Get details for a single Celery worker node."""
    if worker_service is None:
        raise HTTPException(
            status_code=503,
            detail="Worker service not initialized (requires PostgreSQL backend)"
        )
    worker = await worker_service.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


@app.post("/api/v1/workers/{worker_id}/commands", tags=["Monitoring"])
async def send_worker_command(
    worker_id: str,
    request: WorkerCommandRequest,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """
    Send a command to a specific Celery worker.

    The worker polls the DB on every heartbeat (≤30s) and executes the command.

    Supported command types:
    - `restart` — cold restart via SIGTERM (in-flight tasks re-queue)
    - `pool_restart` — hot pool restart (reloads modules without full restart)
    - `drain` — stop consuming + wait for in-flight tasks + SIGTERM
    - `update_code` — pip install new version then restart
    - `update_config` — update worker capabilities in-memory + DB
    - `pause_queue` — stop consuming from a queue
    - `resume_queue` — resume consuming from a queue
    - `set_concurrency` — grow or shrink worker pool
    - `check_health` — collect platform info + Celery stats
    """
    if worker_service is None:
        raise HTTPException(
            status_code=503,
            detail="Worker service not initialized (requires PostgreSQL backend)"
        )
    worker = await worker_service.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    command_id = await worker_service.send_command(
        worker_id=worker_id,
        command_type=request.command_type,
        command_data=request.command_data,
        priority=request.priority,
        expires_in_seconds=request.expires_in_seconds,
        created_by=user.user_id if user else None,
    )
    return {"command_id": command_id, "worker_id": worker_id, "status": "pending"}


@app.get("/api/v1/workers/{worker_id}/commands", tags=["Monitoring"])
async def list_worker_commands(
    worker_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """List commands sent to a specific worker, ordered by created_at DESC."""
    if worker_service is None:
        raise HTTPException(
            status_code=503,
            detail="Worker service not initialized (requires PostgreSQL backend)"
        )
    commands = await worker_service.list_commands(
        worker_id=worker_id, status=status, limit=limit, offset=offset
    )
    return {"commands": commands, "total": len(commands)}


# ─────────────────────────────────────────────────────────────────────────────
# Background Pollers (definition hot-reload + server command execution)
# ─────────────────────────────────────────────────────────────────────────────

# Tracks the last seen version per workflow_type to avoid redundant reloads
_last_seen_versions: Dict[str, int] = {}


async def _definition_poller_loop():
    """
    Runs every 60 s.  Loads all active workflow definitions from DB and calls
    WorkflowBuilder.reload_workflow_type() for any type with a newer version.
    Also runs the server command poller every 30 s.
    """
    tick = 0
    while True:
        try:
            await asyncio.sleep(30)
            tick += 1

            # ── Server commands (every 30 s) ─────────────────────────────────
            if server_command_service and workflow_engine:
                await _process_server_commands()

            # ── Workflow definition reload (every 60 s = every 2 ticks) ─────
            if tick % 2 == 0 and workflow_definition_service and workflow_engine:
                await _reload_changed_definitions()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Definition poller error: {e}")


async def _process_server_commands():
    """Claim and execute pending server_commands rows."""
    try:
        pending = await server_command_service.claim_pending()
    except Exception as e:
        logger.error(f"Server command claim failed: {e}")
        return

    for cmd in pending:
        command_id = cmd["id"]
        command = cmd["command"]
        try:
            import json as _json
            payload = _json.loads(cmd["payload"]) if isinstance(cmd["payload"], str) else cmd["payload"]
        except Exception:
            payload = {}

        try:
            result = await _execute_server_command(command, payload)
            await server_command_service.mark_done(command_id, "completed", result)
        except Exception as e:
            logger.error(f"Server command {command_id} ({command}) failed: {e}")
            await server_command_service.mark_done(
                command_id, "failed", {"error": str(e)}
            )


async def _execute_server_command(command: str, payload: dict) -> dict:
    """Execute a single server command and return a result dict."""
    if command == "reload_workflows":
        if workflow_definition_service and workflow_engine:
            await _reload_changed_definitions(force=True)
        return {"reloaded": True}

    elif command == "gc_caches":
        if workflow_engine:
            from rufus.builder import WorkflowBuilder
            WorkflowBuilder._import_cache.clear()
            workflow_engine.workflow_builder._workflow_configs.clear()
        return {"caches_cleared": True}

    elif command == "update_code":
        package = payload.get("package", "rufus-sdk")
        version = payload.get("version", "")
        pkg_spec = f"{package}=={version}" if version else package
        import subprocess, sys
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg_spec, "--quiet"],
            capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pip install failed: {proc.stderr}")
        # Schedule graceful restart after response is sent
        asyncio.get_event_loop().call_later(2.0, _graceful_restart)
        return {"installed": pkg_spec, "restarting": True}

    elif command == "restart":
        asyncio.get_event_loop().call_later(2.0, _graceful_restart)
        return {"restarting": True}

    raise ValueError(f"Unknown command: {command}")


def _graceful_restart():
    """Send SIGTERM to the current process so the supervisor can restart it."""
    import signal, os
    os.kill(os.getpid(), signal.SIGTERM)


async def _reload_changed_definitions(force: bool = False):
    """Load active definitions from DB; reload builder only for changed versions."""
    try:
        active = await workflow_definition_service.get_all_active()
    except Exception as e:
        logger.warning(f"Failed to fetch active definitions: {e}")
        return

    for defn in active:
        wf_type = defn["workflow_type"]
        version = defn["version"]
        if force or _last_seen_versions.get(wf_type, -1) < version:
            try:
                workflow_engine.workflow_builder.reload_workflow_type(
                    wf_type, defn["yaml_content"]
                )
                _last_seen_versions[wf_type] = version
                logger.info(f"Hot-reloaded '{wf_type}' to v{version}")
            except Exception as e:
                logger.error(f"Hot-reload failed for '{wf_type}': {e}")


@app.delete("/api/v1/workers/commands/{command_id}", tags=["Monitoring"])
async def cancel_worker_command(
    command_id: str,
    user: Optional[UserContext] = Depends(get_current_user),
):
    """Cancel a pending worker command. Only works while status is 'pending'."""
    if worker_service is None:
        raise HTTPException(
            status_code=503,
            detail="Worker service not initialized (requires PostgreSQL backend)"
        )
    cancelled = await worker_service.cancel_command(command_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail="Command cannot be cancelled (not in pending state or not found)"
        )
    return {"command_id": command_id, "status": "cancelled"}


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Definitions API  (DB-backed YAML, hot-reload)
# ─────────────────────────────────────────────────────────────────────────────

def _require_definition_service():
    if workflow_definition_service is None:
        raise HTTPException(
            status_code=503,
            detail="WorkflowDefinitionService not initialized (requires PostgreSQL)"
        )
    return workflow_definition_service


@app.get("/api/v1/admin/workflow-definitions", tags=["Workflows"])
async def list_workflow_definitions(
    user: Optional[UserContext] = Depends(require_admin),
):
    """List all workflow types that have a DB-backed definition (summary, no YAML)."""
    svc = _require_definition_service()
    return await svc.list_definitions()


@app.post("/api/v1/admin/workflow-definitions", tags=["Workflows"])
async def upload_workflow_definition(
    body: WorkflowDefinitionUploadRequest,
    user: Optional[UserContext] = Depends(require_admin),
):
    """
    Upload a new workflow YAML definition.  Creates a new version row and
    triggers an immediate hot-reload on this server instance.

    Returns the stored definition plus the resolved (env-expanded) config.
    """
    svc = _require_definition_service()
    row = await svc.create_definition(
        workflow_type=body.workflow_type,
        yaml_content=body.yaml_content,
        description=body.description,
        uploaded_by=user.user_id if user else None,
    )

    resolved = None
    if workflow_engine:
        try:
            resolved = workflow_engine.workflow_builder.reload_workflow_type(
                body.workflow_type, body.yaml_content
            )
            _last_seen_versions[body.workflow_type] = row["version"]
        except Exception as e:
            logger.warning(f"Hot-reload after upload failed for '{body.workflow_type}': {e}")

    return {**row, "resolved_config": resolved}


@app.get("/api/v1/admin/workflow-definitions/{workflow_type}", tags=["Workflows"])
async def get_workflow_definition(
    workflow_type: str,
    user: Optional[UserContext] = Depends(require_admin),
):
    """Return the current active YAML content for a workflow type."""
    svc = _require_definition_service()
    defn = await svc.get_definition(workflow_type)
    if not defn:
        raise HTTPException(status_code=404, detail=f"No active definition for '{workflow_type}'")
    return defn


@app.patch("/api/v1/admin/workflow-definitions/{workflow_type}", tags=["Workflows"])
async def patch_workflow_definition(
    workflow_type: str,
    body: WorkflowDefinitionPatchRequest,
    user: Optional[UserContext] = Depends(require_admin),
):
    """
    Replace the active definition (creates a new version).  Triggers an
    immediate hot-reload so new workflow starts use the updated YAML within
    milliseconds.
    """
    svc = _require_definition_service()
    row = await svc.update_definition(
        workflow_type=workflow_type,
        yaml_content=body.yaml_content,
        uploaded_by=user.user_id if user else None,
    )

    resolved = None
    if workflow_engine:
        try:
            resolved = workflow_engine.workflow_builder.reload_workflow_type(
                workflow_type, body.yaml_content
            )
            _last_seen_versions[workflow_type] = row["version"]
        except Exception as e:
            logger.warning(f"Hot-reload after patch failed for '{workflow_type}': {e}")

    return {**row, "resolved_config": resolved}


@app.get("/api/v1/admin/workflow-definitions/{workflow_type}/history", tags=["Workflows"])
async def get_workflow_definition_history(
    workflow_type: str,
    user: Optional[UserContext] = Depends(require_admin),
):
    """Return all historical versions for a workflow type (newest first)."""
    svc = _require_definition_service()
    return await svc.get_history(workflow_type)


@app.delete("/api/v1/admin/workflow-definitions/{workflow_type}", tags=["Workflows"])
async def delete_workflow_definition(
    workflow_type: str,
    user: Optional[UserContext] = Depends(require_admin),
):
    """
    Soft-delete: marks all versions inactive.  The server falls back to the
    on-disk YAML on the next builder cache miss.
    """
    svc = _require_definition_service()
    deactivated = await svc.deactivate_definition(workflow_type)
    if not deactivated:
        raise HTTPException(status_code=404, detail=f"No active definition for '{workflow_type}'")
    # Evict builder cache so fallback to disk YAML takes effect immediately
    if workflow_engine:
        workflow_engine.workflow_builder._workflow_configs.pop(workflow_type, None)
        workflow_engine.workflow_registry.get(workflow_type, {}).pop("_yaml_content", None)
    return {"workflow_type": workflow_type, "status": "deactivated"}


# ─────────────────────────────────────────────────────────────────────────────
# Server Commands API
# ─────────────────────────────────────────────────────────────────────────────

def _require_server_command_service():
    if server_command_service is None:
        raise HTTPException(
            status_code=503,
            detail="ServerCommandService not initialized (requires PostgreSQL)"
        )
    return server_command_service


@app.post("/api/v1/admin/server/commands", tags=["Monitoring"])
async def send_server_command(
    body: ServerCommandRequest,
    user: Optional[UserContext] = Depends(require_admin),
):
    """
    Queue a command for the control-plane server process.

    Commands are picked up within 30 s by the background poller.

    - **reload_workflows** — force-reload all active DB definitions immediately
    - **gc_caches** — clear WorkflowBuilder import + config caches
    - **update_code** — `pip install <package==version>` then graceful restart
    - **restart** — graceful SIGTERM (supervisor/k8s brings it back)
    """
    svc = _require_server_command_service()
    command_id = await svc.send_command(
        command=body.command,
        payload=body.payload,
        created_by=user.user_id if user else None,
    )
    return {"id": command_id, "command": body.command, "status": "pending"}


@app.get("/api/v1/admin/server/commands", tags=["Monitoring"])
async def list_server_commands(
    limit: int = 50,
    offset: int = 0,
    user: Optional[UserContext] = Depends(require_admin),
):
    """List recent server commands (newest first)."""
    svc = _require_server_command_service()
    return await svc.list_commands(limit=limit, offset=offset)


@app.patch("/api/v1/admin/server/commands/{command_id}/cancel", tags=["Monitoring"])
async def cancel_server_command(
    command_id: str,
    user: Optional[UserContext] = Depends(require_admin),
):
    """Cancel a pending server command."""
    svc = _require_server_command_service()
    cancelled = await svc.cancel_command(command_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail="Command cannot be cancelled (not pending or not found)"
        )
    return {"id": command_id, "status": "cancelled"}


# To run: uvicorn rufus_server.main:app --reload
