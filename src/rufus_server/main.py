import sys
import os
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import importlib.resources
from dotenv import load_dotenv
import yaml
import asyncio
import redis.asyncio as aredis # For Redis pub/sub in WebSocket
from typing import Optional, Any, Dict, List, Type

# Load environment variables from .env file
load_dotenv()

# Add the project root to the Python path to allow importing rufus package.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Import Rufus SDK Components ---
from rufus.engine import WorkflowEngine, WorkflowJumpDirective, WorkflowPauseDirective, SagaWorkflowException, StartSubWorkflowDirective
from rufus.models import StepContext, BaseModel # Import BaseModel for Type hinting
from rufus.builder import WorkflowBuilder
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider, get_postgres_store # Correct import
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.persistence.redis import RedisPersistenceProvider
from rufus.implementations.execution.celery import CeleryExecutor, rufus_celery_app, get_celery_executor # Correct import
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.execution.thread_pool import ThreadPoolExecutorProvider # New executor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.observability.events import EventPublisherObserver # Event publisher for websockets
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

# --- API Models ---
from rufus_server.api_models import (
    WorkflowStartRequest, WorkflowStartResponse, WorkflowStepRequest, WorkflowStepResponse,
    WorkflowStatusResponse, ResumeWorkflowRequest, RetryWorkflowRequest
)

# --- FastAPI App Setup ---
from prometheus_client import make_asgi_app # If using Prometheus metrics
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Initialize limiter for rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Rufus Workflow Engine API", description="API for Rufus Workflow SDK")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# --- Global Instances (will be initialized in lifespan events) ---
# It's better to instantiate these once the app starts, not at module load.
persistence_provider: Optional[PersistenceProvider] = None
execution_provider: Optional[ExecutionProvider] = None
workflow_observer: Optional[WorkflowObserver] = None
workflow_engine: Optional[WorkflowEngine] = None
workflow_registry_config: Dict[str, Any] = {}


# --- Dependency Injection Setup (Global Instances for Server) ---
@app.on_event("startup")
async def startup_event():
    global persistence_provider, execution_provider, workflow_observer, workflow_engine, workflow_registry_config

    # Load workflow registry
    RUFUS_WORKFLOW_REGISTRY_PATH = os.getenv("RUFUS_WORKFLOW_REGISTRY_PATH", "config/workflow_registry.yaml")
    try:
        with open(RUFUS_WORKFLOW_REGISTRY_PATH, "r") as f:
            workflow_registry_config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: Workflow registry not found at {RUFUS_WORKFLOW_REGISTRY_PATH}. No workflows will be registered.")
        workflow_registry_config = {"workflows": []}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in workflow registry {RUFUS_WORKFLOW_REGISTRY_PATH}: {e}")

    # Persistence Provider
    persistence_backend = os.getenv('WORKFLOW_STORAGE', 'memory').lower()
    if persistence_backend == 'postgres':
        DATABASE_URL = os.getenv('DATABASE_URL')
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL must be set for PostgreSQL persistence.")
        persistence_provider = PostgresPersistenceProvider(DATABASE_URL)
    elif persistence_backend == 'redis':
        REDIS_URL = os.getenv('REDIS_URL', "redis://localhost:6379/0")
        persistence_provider = RedisPersistenceProvider(REDIS_URL)
    else: # Default to in-memory
        persistence_provider = InMemoryPersistence()
    
    await persistence_provider.initialize()


    # Workflow Observer
    # Using EventPublisherObserver for richer event handling, which can internally use logging and Prometheus
    REDIS_URL = os.getenv('REDIS_URL', "redis://localhost:6379/0")
    workflow_observer = EventPublisherObserver(REDIS_URL)
    await workflow_observer.initialize()


    # Execution Provider
    execution_backend = os.getenv('WORKFLOW_EXECUTION_BACKEND', 'sync').lower()
    if execution_backend == 'celery':
        execution_provider = get_celery_executor(rufus_celery_app, persistence_provider) # Pass celery_app and persistence
    elif execution_backend == 'threadpool':
        execution_provider = ThreadPoolExecutorProvider()
    else: # Default to sync
        execution_provider = SyncExecutor()
    
    # Execution provider's initialize method will be called by WorkflowEngine's __init__
    # as per the latest WorkflowEngine code
    
    # WorkflowEngine (which internally initializes WorkflowBuilder)
    workflow_engine = WorkflowEngine(
        persistence=persistence_provider,
        executor=execution_provider,
        observer=workflow_observer,
        # Flatten the registry from {"workflows": [...]} to a dict keyed by workflow_type
        workflow_registry={wf['type']: wf for wf in workflow_registry_config.get("workflows", [])},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    print("Rufus Server started and WorkflowEngine initialized.")


@app.on_event("shutdown")
async def shutdown_event():
    global persistence_provider, execution_provider, workflow_observer
    if persistence_provider:
        await persistence_provider.close()
    if workflow_observer:
        await workflow_observer.close()
    if execution_provider:
        await execution_provider.close() # Ensure executor is shut down

    print("Rufus Server shut down and providers closed.")


# --- API Endpoints ---

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

@app.post("/api/v1/internal/retry", response_model=WorkflowStepResponse)
async def internal_retry_step(request_data: RetryWorkflowRequest):
    """
    Internal endpoint called by the Retry Service (BullMQ Worker) to re-trigger a step.
    """
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow_id = request_data.workflow_id
    workflow_data = await persistence_provider.load_workflow(workflow_id)
        
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = Workflow.from_dict( # Use Workflow.from_dict
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_engine.workflow_builder, # Use engine's builder
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=workflow_observer
    )

    # Validate we are retrying the correct step
    if workflow.current_step != request_data.step_index:
         # If step index mismatch, maybe workflow advanced? Treat as success/ignore.
         raise HTTPException(status_code=409, detail=f"Step index mismatch. Current: {workflow.current_step}, Requested: {request_data.step_index}")

    current_step_obj = workflow.workflow_steps[workflow.current_step]
    
    # Reset status to ACTIVE to allow re-execution
    old_status = workflow.status
    workflow.status = "ACTIVE"
    
    # We might want to store retry count in metadata
    workflow.metadata = workflow.metadata or {}
    workflow.metadata['last_retry_count'] = request_data.retry_count
    
    try:
        result_dict, next_step_name = await workflow.next_step(user_input={}) # Await next_step
        
        await persistence_provider.save_workflow(workflow_id, workflow.to_dict()) # Await save
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call
        
        # If it went ASYNC, that's good.
        if workflow.status == "PENDING_ASYNC":
             return JSONResponse(status_code=202, content={
                "workflow_id": workflow.id, "current_step_name": current_step_obj.name, "next_step_name": None,
                "status": workflow.status, "state": workflow.state.model_dump(), "result": result_dict
            })

        return WorkflowStepResponse(
            workflow_id=workflow.id, current_step_name=current_step_obj.name, next_step_name=next_step_name,
            status=workflow.status, state=workflow.state.model_dump(), result=result_dict
        )
        
    except WorkflowJumpDirective as e:
        await persistence_provider.save_workflow(workflow_id, workflow.to_dict()) # Await save
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call
        return WorkflowStepResponse(
            workflow_id=workflow.id, current_step_name=current_step_obj.name, next_step_name=workflow.current_step_name,
            status=workflow.status, state=workflow.state.model_dump(), result={"message": f"Workflow branched to {e.target_step_name}"}
        )
    except Exception as e:
        workflow.status = "FAILED"
        await persistence_provider.save_workflow(workflow_id, workflow.to_dict()) # Await save
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call
        
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/workflows")
async def get_available_workflows():
    """
    Returns a list of available workflows from the registry.
    """
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    # Get workflow definitions from the engine's registry
    available_workflows = []
    for wf_type, wf_config in workflow_engine.workflow_registry.items():
        # Get the processed config from builder to ensure parameters and env vars are resolved
        processed_config = workflow_engine.workflow_builder.get_workflow_config(wf_type)
        available_workflows.append({
            "type": wf_type,
            "description": processed_config.get("description", "No description provided."),
            # Include processed parameters and example initial data
            "parameters": processed_config.get("parameters", {}),
            "initial_data_example": processed_config.get("initial_data_example", {}) # From config or default
        })
    return available_workflows


@app.post("/api/v1/workflow/start", response_model=WorkflowStartResponse)
@limiter.limit("10/minute") # Apply rate limiting
async def start_workflow(request: Request, request_data: WorkflowStartRequest, user: Optional[UserContext] = Depends(get_current_user)):
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    try:
        new_workflow = await workflow_engine.start_workflow( # Use engine.start_workflow
            workflow_type=request_data.workflow_type,
            initial_data=request_data.initial_data,
            # persistence_provider=persistence_provider, # These are handled by engine
            # execution_provider=execution_provider,
            # workflow_builder=workflow_engine.workflow_builder,
            # expression_evaluator_cls=workflow_engine.expression_evaluator_cls,
            # template_engine_cls=workflow_engine.template_engine_cls,
            # workflow_observer=workflow_observer,
            owner_id=user.user_id if user else None,
            org_id=user.org_id if user else None,
            data_region=request_data.data_region,
            idempotency_key=request_data.idempotency_key
        )
        
        # Data Region and RBAC are already handled by engine.start_workflow via kwargs
        
        await workflow_observer.on_workflow_started(new_workflow.id, new_workflow.workflow_type, new_workflow.state) # Await observer call

    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create workflow: {e}")

    return WorkflowStartResponse(
        workflow_id=new_workflow.id,
        current_step_name=new_workflow.current_step_name,
        status=new_workflow.status
    )

@app.get("/api/v1/workflow/{workflow_id}/current_step_info")
async def get_current_step_info(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id) # Use engine.get_workflow
    
    # _check_access(workflow, user) # Implement RBAC check here

    if workflow.status == "COMPLETED" or workflow.current_step >= len(workflow.workflow_steps):
        return {"name": "Workflow Complete", "required_input": [], "input_schema": None}

    step = workflow.workflow_steps[workflow.current_step]
    response = {"name": step.name, "type": type(step).__name__}
    
    response["required_input"] = getattr(step, "required_input", []) or []

    if workflow.status == "WAITING_HUMAN":
        response["input_schema"] = ResumeWorkflowRequest.model_json_schema()
    elif hasattr(step, "input_schema") and step.input_schema:
        try:
            response["input_schema"] = step.input_schema.model_json_schema()
        except AttributeError:
            response["input_schema"] = None # Or old Pydantic schema()
    else:
        response["input_schema"] = None
        
    return response

@app.post("/api/v1/workflow/{workflow_id}/next", response_model=WorkflowStepResponse)
async def next_workflow_step(workflow_id: str, request_data: WorkflowStepRequest, user: Optional[UserContext] = Depends(get_current_user)):
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id) # Use engine.get_workflow
        
    # _check_access(workflow, user) # Implement RBAC check here

    if workflow.status in ["PENDING_ASYNC", "WAITING_HUMAN", "COMPLETED", "FAILED", "FAILED_ROLLED_BACK", "PENDING_SUB_WORKFLOW"]:
        raise HTTPException(
            status_code=409, detail=f"Workflow is in '{workflow.status}' state. Cannot advance with /next.")

    current_step_obj = workflow.workflow_steps[workflow.current_step]

    try:
        old_status = workflow.status
        result_dict, next_step_name = await workflow.next_step(user_input=request_data.input_data) # Await next_step
        
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call

        if workflow.status == "PENDING_ASYNC":
            return JSONResponse(
                status_code=202,
                content={
                    "workflow_id": workflow.id, "current_step_name": current_step_obj.name, "next_step_name": None,
                    "status": workflow.status, "state": workflow.state.model_dump(), "result": result_dict
                }
            )

        return WorkflowStepResponse(
            workflow_id=workflow.id, current_step_name=current_step_obj.name, next_step_name=next_step_name,
            status=workflow.status, state=workflow.state.model_dump(), result=result_dict
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        workflow.status = "FAILED"
        await workflow_engine.persistence.save_workflow(workflow_id, workflow.to_dict()) # Await save
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call
        
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id) # Use engine.get_workflow
    # _check_access(workflow, user) # Implement RBAC check here
    
    return WorkflowStatusResponse(
        workflow_id=workflow.id, status=workflow.status,
        current_step_name=workflow.current_step_name, state=workflow.state.model_dump(),
        workflow_type=workflow.workflow_type,
        parent_execution_id=workflow.parent_execution_id,
        blocked_on_child_id=workflow.blocked_on_child_id
    )

@app.post("/api/v1/workflow/{workflow_id}/resume", response_model=WorkflowStepResponse)
async def resume_workflow(workflow_id: str, request_data: ResumeWorkflowRequest, user: Optional[UserContext] = Depends(get_current_user)):
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id) # Use engine.get_workflow
    # _check_access(workflow, user) # Implement RBAC check here
    
    if workflow.status != "WAITING_HUMAN":
        raise HTTPException(
            status_code=400, detail=f"Workflow is not awaiting human input. Current status: {workflow.status}")

    current_step_obj = workflow.workflow_steps[workflow.current_step]
    
    try:
        old_status = workflow.status
        # Advance to the step that handles the human input
        workflow.current_step += 1
        if workflow.current_step >= len(workflow.workflow_steps):
             raise HTTPException(
                 status_code=500, detail="Workflow ended unexpectedly after human review.")

        # Set status to ACTIVE so next_step will execute
        workflow.status = "ACTIVE"
        
        # Execute the next step using the resume data as input
        result_dict, next_step_name = await workflow.next_step( # Await next_step
            user_input=request_data.model_dump()
        )
        
        await workflow_engine.persistence.save_workflow(workflow.id, workflow.to_dict()) # Await save
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call


        return WorkflowStepResponse(
            workflow_id=workflow.id, 
            current_step_name=current_step_obj.name, # The one we resumed FROM
            next_step_name=next_step_name, 
            status=workflow.status,
            state=workflow.state.model_dump(), 
            result=result_dict
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        workflow.status = "FAILED"
        await workflow_engine.persistence.save_workflow(workflow.id, workflow.to_dict()) # Await save
        await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/workflow/{workflow_id}/retry", response_model=WorkflowStatusResponse)
async def retry_workflow(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id) # Use engine.get_workflow
    # _check_access(workflow, user) # Implement RBAC check here
    
    if workflow.status not in ["FAILED", "FAILED_ROLLED_BACK"]:
        raise HTTPException(
            status_code=400, detail=f"Workflow is not in a FAILED state. Current status: {workflow.status}")

    old_status = workflow.status
    workflow.status = "ACTIVE"
    await workflow_engine.persistence.save_workflow(workflow.id, workflow.to_dict()) # Await save
    await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call


    return WorkflowStatusResponse(
        workflow_id=workflow.id, status=workflow.status,
        current_step_name=workflow.current_step_name, state=workflow.state.model_dump()
    )

@app.post("/api/v1/workflow/{workflow_id}/rewind", response_model=WorkflowStepResponse)
async def rewind_workflow(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
    """
    Rewind the workflow to the previous step.
    Useful for recovering from logic errors or bad data input.
    """
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    workflow = await workflow_engine.get_workflow(workflow_id) # Use engine.get_workflow
    # _check_access(workflow, user) # Implement RBAC check here
    
    if workflow.current_step <= 0:
        raise HTTPException(status_code=400, detail="Cannot rewind. Already at the first step.")

    # Decrement step
    workflow.current_step -= 1
    
    # Reset status to ACTIVE if it was failed or completed
    old_status = workflow.status
    workflow.status = "ACTIVE"
    
    await workflow_engine.persistence.save_workflow(workflow.id, workflow.to_dict()) # Await save
    await workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name) # Await observer call

    current_step_obj = workflow.workflow_steps[workflow.current_step]
    
    return WorkflowStepResponse(
        workflow_id=workflow.id, current_step_name=current_step_obj.name, 
        next_step_name=None,
        status=workflow.status, state=workflow.state.model_dump(), 
        result={"message": f"Rewound to step {current_step_obj.name}"}
    )

# -------------------------------------------------------------------------
# Postgres-only observability / audit endpoints
# -------------------------------------------------------------------------
@app.get("/api/v1/workflow/{workflow_id}/audit")
async def get_workflow_audit_log(workflow_id: str, limit: int = 100):
    """Get audit trail for workflow (Postgres backend required)"""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(status_code=501, detail="Audit logs require PostgreSQL backend")

    # Use persistence_provider.list_audit_log once implemented
    # For now, this is a placeholder
    return await workflow_engine.persistence.get_audit_log(workflow_id=workflow_id, limit=limit)


@app.get("/api/v1/workflow/{workflow_id}/logs")
async def get_workflow_logs(workflow_id: str, level: Optional[str] = None, limit: int = 500):
    """Get execution logs for debugging (Postgres backend required)"""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(status_code=501, detail="Execution logs require PostgreSQL backend")

    return await workflow_engine.persistence.get_execution_logs(workflow_id=workflow_id, level=level, limit=limit)


@app.get("/api/v1/workflow/{workflow_id}/metrics")
async def get_workflow_metrics(workflow_id: str, limit: int = 500):
    """Get performance metrics for workflow (Postgres backend required)"""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(status_code=501, detail="Metrics require PostgreSQL backend")

    return await workflow_engine.persistence.get_workflow_metrics(workflow_id=workflow_id, limit=limit)


@app.get("/api/v1/workflows/executions")
async def get_workflow_executions(status: Optional[str] = None, exclude_status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """
    List active and recent workflow executions.
    """
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    filters = {}
    if status:
        filters['status'] = status
    
    workflow_list = await workflow_engine.persistence.list_workflows(**filters)
    
    # Apply exclude_status filter here if not handled by provider
    if exclude_status:
        excluded_statuses = exclude_status.split(',')
        workflow_list = [wf for wf in workflow_list if wf.get('status') not in excluded_statuses]

    return workflow_list[offset:offset+limit]


@app.get("/api/v1/metrics/summary")
async def get_metrics_summary(hours: int = 24):
    """Get aggregated metrics across workflows (Postgres backend required)"""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(status_code=501, detail="Summary metrics require PostgreSQL backend")
    
    return await workflow_engine.persistence.get_workflow_summary(hours=hours)

@app.get("/api/v1/admin/workers")
async def get_registered_workers(limit: int = 100):
    """List registered worker nodes (Postgres backend required)"""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow Engine not initialized.")

    if not isinstance(workflow_engine.persistence, PostgresPersistenceProvider):
        raise HTTPException(status_code=501, detail="Worker registry requires PostgreSQL backend")
    
    # Placeholder, assuming the persistence provider can list workers
    raise HTTPException(status_code=501, detail="Worker listing not yet implemented via PersistenceProvider.")

@app.websocket("/api/v1/workflow/{workflow_id}/subscribe")
async def workflow_subscribe(websocket: WebSocket, workflow_id: str):
    """
    WebSocket endpoint that forwards real-time workflow updates.
    """
    await websocket.accept()

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_client = aredis.Redis(
        host=redis_host, port=6379, db=0, decode_responses=True)
    pubsub = redis_client.pubsub()
    channel = f"rufus:events:{workflow_id}" # Using rufus specific channel defined in EventPublisherObserver

    try:
        # Send initial state first
        if workflow_engine is None:
            await websocket.send_text(json.dumps({"error": "Workflow Engine not initialized."}))
            return

        initial_workflow = await workflow_engine.get_workflow(workflow_id)
        if initial_workflow:
            await websocket.send_text(json.dumps(initial_workflow.to_dict()))


        await pubsub.subscribe(channel)
        
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get('data'):
                data_str = message['data']
                try:
                     json.loads(data_str) # Ensure it's valid JSON
                     await websocket.send_text(data_str)
                except json.JSONDecodeError:
                     await websocket.send_text(json.dumps({"error": "Invalid JSON from pubsub", "raw": data_str}))
            
            # Keep the connection alive, periodically checking for client disconnect
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except asyncio.TimeoutError:
                pass # No message from client, just continue
            except WebSocketDisconnect:
                raise # Client disconnected, break loop

    except WebSocketDisconnect:
        print(f"Client disconnected from workflow {workflow_id}")
    except Exception as e:
        print(f"An error occurred in websocket for {workflow_id}: {e}")
    finally:
        if pubsub.subscribed:
            await pubsub.unsubscribe(channel)
        await redis_client.close()
        print("Websocket connection closed.")

# --- Static Files and Debug UI ---
# The debug UI static files are now part of rufus_server.contrib
# The templates are also there.

# Get path to the static folder within rufus_server.contrib
contrib_static_path = Path(__file__).parent / "contrib" / "static"
if not contrib_static_path.is_dir():
    # Fallback if running from an installed package where files might be elsewhere
    try:
        with importlib.resources.path("rufus_server.contrib", "static") as p:
            contrib_static_path = p
    except Exception:
        print("Warning: Could not find rufus_server.contrib/static. UI might not load correctly.")

app.mount("/static", StaticFiles(directory=contrib_static_path), name="rufus_static")

# Debug UI Router
templates_path = Path(__file__).parent / "contrib" / "templates"
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=templates_path)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    """Serves the debug UI's main page."""
    return templates.TemplateResponse("index.html", {"request": request})

# To run this application:
# uvicorn src.rufus_server.main:app --reload