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
# This might be needed for local development setup if rufus is not installed via pip.
# Adjust as necessary for your project structure.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Import Rufus SDK Components ---
from rufus.engine import WorkflowEngine, WorkflowJumpDirective, WorkflowPauseDirective, SagaWorkflowException, StartSubWorkflowDirective
from rufus.models import StepContext, BaseModel # Import BaseModel for Type hinting
from rufus.builder import WorkflowBuilder
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.implementations.persistence.postgres import PostgresProvider
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.celery import CeleryExecutor, _get_celery_app_instance # For initializing Celery
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating import Jinja2TemplateEngine

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


# --- Dependency Injection Setup (Global Instances for Server) ---
# In a larger application, these would be managed by a proper DI framework.
# For this example server, we'll instantiate them globally.

# Persistence Provider
persistence_backend = os.getenv('WORKFLOW_STORAGE', 'memory').lower()
if persistence_backend == 'postgres':
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL must be set for PostgreSQL persistence.")
    persistence_provider: PersistenceProvider = PostgresProvider(DATABASE_URL)
else:
    persistence_provider: PersistenceProvider = InMemoryPersistence()

# Execution Provider
execution_backend = os.getenv('WORKFLOW_EXECUTION_BACKEND', 'sync').lower()
if execution_backend == 'celery':
    _get_celery_app_instance() # Initialize Celery app
    execution_provider: ExecutionProvider = CeleryExecutor(
        broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
        persistence_provider=persistence_provider,
        observer=LoggingObserver() # Temp observer, could be a real one
    )
else:
    execution_provider: ExecutionProvider = SyncExecutor()

# Workflow Observer
workflow_observer: WorkflowObserver = LoggingObserver() # Using simple logging for now

# Workflow Builder
# The builder needs to know where the registry file is.
RUFUS_WORKFLOW_REGISTRY_PATH = os.getenv("RUFUS_WORKFLOW_REGISTRY_PATH", "config/workflow_registry.yaml")
workflow_builder_instance = WorkflowBuilder(registry_path=RUFUS_WORKFLOW_REGISTRY_PATH)

# Expression Evaluator and Template Engine classes
expression_evaluator_cls = SimpleExpressionEvaluator
template_engine_cls = Jinja2TemplateEngine

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
    workflow_id = request_data.workflow_id
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
        
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
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
        result_dict, next_step_name = workflow.next_step(user_input={})
        
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)
        
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
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)
        return WorkflowStepResponse(
            workflow_id=workflow.id, current_step_name=current_step_obj.name, next_step_name=workflow.current_step_name,
            status=workflow.status, state=workflow.state.model_dump(), result={"message": f"Workflow branched to {e.target_step_name}"}
        )
    except Exception as e:
        workflow.status = "FAILED"
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)
        
        # Need to re-trigger the retry mechanism if the retry fails again
        # This part assumes a separate retry service that pushes to this endpoint
        # For a full SDK, this re-trigger would be handled by the ExecutionProvider or a dedicated RetryProvider.
        # For now, it simply fails.
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/workflows")
async def get_available_workflows():
    """
    Returns a list of available workflows from the registry.
    """
    registry_path = workflow_builder_instance.registry_path
    try:
        with open(registry_path, "r") as f:
            registry = yaml.safe_load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500, detail=f"Workflow registry not found at {registry_path}")

    # Dummy examples for UI (if needed, otherwise remove)
    workflow_examples = {
        "LoanApplication": {"application_id": "L12345", "requested_amount": 15000.50},
    }

    for wf in registry.get("workflows", []):
        wf["initial_data_example"] = workflow_examples.get(wf["type"], {})

    return registry.get("workflows", [])

@app.post("/api/v1/workflow/start", response_model=WorkflowStartResponse)
@limiter.limit("10/minute") # Apply rate limiting
async def start_workflow(request: Request, request_data: WorkflowStartRequest, user: Optional[UserContext] = Depends(get_current_user)):
    try:
        new_workflow = workflow_builder_instance.create_workflow(
            workflow_type=request_data.workflow_type,
            initial_data=request_data.initial_data,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder_instance,
            expression_evaluator_cls=expression_evaluator_cls,
            template_engine_cls=template_engine_cls,
            workflow_observer=workflow_observer
        )
        
        # Apply Data Region
        if request_data.data_region:
            new_workflow.data_region = request_data.data_region
        
        # Apply RBAC
        if user:
            new_workflow.owner_id = user.user_id
            new_workflow.org_id = user.org_id
        
        persistence_provider.save_workflow(new_workflow.id, new_workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_started(new_workflow.id, new_workflow.workflow_type, new_workflow.state)

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
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
        
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
        workflow_observer=workflow_observer
    )

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
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
        workflow_observer=workflow_observer
    )
        
    # _check_access(workflow, user) # Implement RBAC check here

    if workflow.status in ["PENDING_ASYNC", "WAITING_HUMAN", "COMPLETED", "FAILED", "FAILED_ROLLED_BACK", "PENDING_SUB_WORKFLOW"]:
        raise HTTPException(
            status_code=409, detail=f"Workflow is in '{workflow.status}' state. Cannot advance with /next.")

    current_step_obj = workflow.workflow_steps[workflow.current_step]

    try:
        old_status = workflow.status
        result_dict, next_step_name = workflow.next_step(user_input=request_data.input_data)
        
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)

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
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)
        # TODO: Trigger retry if ExecutionProvider supports it
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
        
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
        workflow_observer=workflow_observer
    )
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
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
        workflow_observer=workflow_observer
    )
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
        result_dict, next_step_name = workflow.next_step(
            user_input=request_data.model_dump()
        )
        
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)


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
        persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
        workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/workflow/{workflow_id}/retry", response_model=WorkflowStatusResponse)
async def retry_workflow(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
        workflow_observer=workflow_observer
    )
    # _check_access(workflow, user) # Implement RBAC check here
    
    if workflow.status not in ["FAILED", "FAILED_ROLLED_BACK"]:
        raise HTTPException(
            status_code=400, detail=f"Workflow is not in a FAILED state. Current status: {workflow.status}")

    old_status = workflow.status
    workflow.status = "ACTIVE"
    persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
    workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)


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
    workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    workflow = WorkflowEngine.from_dict(
        workflow_data,
        persistence_provider=persistence_provider,
        execution_provider=execution_provider,
        workflow_builder=workflow_builder_instance,
        expression_evaluator_cls=expression_evaluator_cls,
        template_engine_cls=template_engine_cls,
        workflow_observer=workflow_observer
    )
    # _check_access(workflow, user) # Implement RBAC check here
    
    if workflow.current_step <= 0:
        raise HTTPException(status_code=400, detail="Cannot rewind. Already at the first step.")

    # Decrement step
    workflow.current_step -= 1
    
    # Reset status to ACTIVE if it was failed or completed
    old_status = workflow.status
    workflow.status = "ACTIVE"
    
    persistence_provider.save_workflow(workflow_id, workflow.to_dict(), sync=True)
    workflow_observer.on_workflow_status_changed(workflow.id, old_status, workflow.status, workflow.current_step_name)

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
    if not isinstance(persistence_provider, PostgresProvider):
        raise HTTPException(status_code=501, detail="Audit logs require PostgreSQL backend")

    # Use persistence_provider.list_audit_log once implemented
    # For now, this is a placeholder
    raise HTTPException(status_code=501, detail="Audit log listing not yet implemented via Provider.")

@app.get("/api/v1/workflow/{workflow_id}/logs")
async def get_workflow_logs(workflow_id: str, level: Optional[str] = None, limit: int = 500):
    """Get execution logs for debugging (Postgres backend required)"""
    if not isinstance(persistence_provider, PostgresProvider):
        raise HTTPException(status_code=501, detail="Execution logs require PostgreSQL backend")

    # Use persistence_provider.list_execution_logs once implemented
    # For now, this is a placeholder
    raise HTTPException(status_code=501, detail="Execution log listing not yet implemented via Provider.")


@app.get("/api/v1/workflow/{workflow_id}/metrics")
async def get_workflow_metrics(workflow_id: str, limit: int = 500):
    """Get performance metrics for workflow (Postgres backend required)"""
    if not isinstance(persistence_provider, PostgresProvider):
        raise HTTPException(status_code=501, detail="Metrics require PostgreSQL backend")

    # Use persistence_provider.list_metrics once implemented
    # For now, this is a placeholder
    raise HTTPException(status_code=501, detail="Metrics listing not yet implemented via Provider.")


@app.get("/api/v1/workflows/executions")
async def get_workflow_executions(status: Optional[str] = None, exclude_status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """
    List active and recent workflow executions.
    """
    # Use persistence_provider.list_workflows with filters
    filters = {}
    if status:
        filters['status'] = status
    if exclude_status:
        # This logic needs to be handled by the provider implementation
        pass # Placeholder for now

    workflow_list = persistence_provider.list_workflows(filters=filters)
    # Apply exclude_status filter here if not handled by provider
    if exclude_status:
        excluded_statuses = exclude_status.split(',')
        workflow_list = [wf for wf in workflow_list if wf.get('status') not in excluded_statuses]

    # Apply limit and offset for in-memory, or delegate to provider for DB
    return workflow_list[offset:offset+limit]


@app.get("/api/v1/metrics/summary")
async def get_metrics_summary(hours: int = 24):
    """Get aggregated metrics across workflows (Postgres backend required)"""
    if not isinstance(persistence_provider, PostgresProvider):
        raise HTTPException(status_code=501, detail="Metrics require PostgreSQL backend")
    # Placeholder for summary metrics
    raise HTTPException(status_code=501, detail="Summary metrics not yet implemented via Provider.")

@app.get("/api/v1/admin/workers")
async def get_registered_workers(limit: int = 100):
    """List registered worker nodes (Postgres backend required)"""
    if not isinstance(persistence_provider, PostgresProvider):
        raise HTTPException(status_code=501, detail="Worker registry requires PostgreSQL backend")
    # Placeholder for worker listing
    raise HTTPException(status_code=501, detail="Worker listing not yet implemented via Provider.")

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
    channel = f"workflow:events:{workflow_id}" # Assuming events are published to this channel

    try:
        # Send initial state first
        initial_workflow_data = persistence_provider.load_workflow(workflow_id, sync=True)
        if initial_workflow_data:
            initial_workflow_data['status'] = initial_workflow_data['status'] # ensure status is not None
            # Need steps_config to re-construct current_step_name properly
            # For now, sending raw data
            await websocket.send_text(json.dumps(initial_workflow_data))


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
