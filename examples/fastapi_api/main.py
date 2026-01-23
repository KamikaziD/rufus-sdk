"""
FastAPI REST API for Rufus Workflow Engine

This example demonstrates how to embed Rufus into a FastAPI application
to expose workflow operations via REST API endpoints with async support.

Features:
- Full async/await support
- Automatic API documentation (Swagger/OpenAPI)
- Pydantic models for request/response validation
- Dependency injection for workflow engine
- CORS support for frontend integration

Endpoints:
- POST /workflows - Start a new workflow
- GET /workflows/{workflow_id} - Get workflow status
- POST /workflows/{workflow_id}/resume - Resume a paused workflow
- GET /workflows - List all workflows
- POST /workflows/{workflow_id}/cancel - Cancel a workflow
"""

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import yaml
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.postgres import PostgresPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.models import WorkflowPauseDirective


# Global workflow engine instance
workflow_engine: Optional[WorkflowEngine] = None


# Pydantic Models for API
class OrderItemCreate(BaseModel):
    """Order item input model"""
    product_id: str
    name: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)


class WorkflowCreateRequest(BaseModel):
    """Request model for creating a workflow"""
    workflow_type: str = Field(..., description="Type of workflow to start")
    initial_data: Dict[str, Any] = Field(..., description="Initial data for the workflow")

    class Config:
        json_schema_extra = {
            "example": {
                "workflow_type": "OrderProcessing",
                "initial_data": {
                    "customer_id": "CUST123",
                    "customer_email": "customer@example.com",
                    "items": [
                        {
                            "product_id": "PROD001",
                            "name": "Widget",
                            "quantity": 2,
                            "price": 29.99
                        }
                    ]
                }
            }
        }


class WorkflowResumeRequest(BaseModel):
    """Request model for resuming a workflow"""
    user_input: Dict[str, Any] = Field(..., description="User input to resume the workflow")

    class Config:
        json_schema_extra = {
            "example": {
                "user_input": {
                    "approved": True,
                    "approver_id": "ADMIN001",
                    "notes": "Approved for processing"
                }
            }
        }


class WorkflowResponse(BaseModel):
    """Response model for workflow operations"""
    workflow_id: str
    status: str
    current_step: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)


class WorkflowDetailResponse(WorkflowResponse):
    """Detailed response model for workflow status"""
    workflow_type: str
    current_step_index: int
    total_steps: int


class WorkflowListItem(BaseModel):
    """List item for workflows"""
    workflow_id: str
    workflow_type: str
    status: str
    current_step: Optional[int] = None
    created_at: Optional[str] = None


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows"""
    workflows: List[WorkflowListItem]
    total: int


async def initialize_engine():
    """Initialize the workflow engine with providers"""
    global workflow_engine

    # Load workflow registry
    registry_path = Path(__file__).parent / "workflow_registry.yaml"
    with open(registry_path) as f:
        registry_config = yaml.safe_load(f)

    # Build workflow registry dict
    workflow_registry = {}
    for workflow in registry_config["workflows"]:
        workflow_file = Path(__file__).parent / workflow["config_file"]
        with open(workflow_file) as f:
            workflow_config = yaml.safe_load(f)
        workflow_registry[workflow["type"]] = {
            "initial_state_model_path": workflow["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version", "1.0"),
            "description": workflow.get("description", ""),
        }

    # Get database URL from environment variable
    db_url = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/rufus_db")

    # Initialize engine with PostgreSQL persistence
    persistence = PostgresPersistence(db_url=db_url)
    await persistence.initialize()

    workflow_engine = WorkflowEngine(
        persistence=persistence,
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await workflow_engine.initialize()
    print(f"✓ Workflow engine initialized with {len(workflow_registry)} workflow types")


async def shutdown_engine():
    """Cleanup on shutdown"""
    global workflow_engine
    if workflow_engine:
        # Close any open connections
        print("✓ Shutting down workflow engine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    await initialize_engine()
    yield
    # Shutdown
    await shutdown_engine()


# Initialize FastAPI app
app = FastAPI(
    title="Rufus Workflow API",
    description="REST API for managing workflows with the Rufus workflow engine",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_engine() -> WorkflowEngine:
    """Dependency to get the workflow engine"""
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow engine not initialized")
    return workflow_engine


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "rufus-workflow-api"}


@app.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    request: WorkflowCreateRequest,
    engine: WorkflowEngine = Depends(get_engine)
):
    """
    Start a new workflow

    The workflow will execute automatically until it completes or pauses
    for human input.
    """
    try:
        # Start workflow
        workflow = await engine.start_workflow(
            workflow_type=request.workflow_type,
            initial_data=request.initial_data
        )

        # Execute workflow steps until it pauses or completes
        while workflow.status == "ACTIVE":
            try:
                await workflow.next_step(user_input={})
            except WorkflowPauseDirective:
                # Workflow paused for human input
                break

        return WorkflowResponse(
            workflow_id=workflow.id,
            status=workflow.status,
            current_step=workflow.current_step_name,
            state=workflow.state.model_dump() if workflow.state else {}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflows/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(get_engine)
):
    """
    Get workflow status and details

    Returns the current state of the workflow including its status,
    current step, and full state data.
    """
    try:
        workflow = await engine.get_workflow(workflow_id)

        return WorkflowDetailResponse(
            workflow_id=workflow.id,
            workflow_type=workflow.workflow_type,
            status=workflow.status,
            current_step=workflow.current_step_name,
            current_step_index=workflow.current_step,
            total_steps=len(workflow.workflow_steps),
            state=workflow.state.model_dump() if workflow.state else {}
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workflows/{workflow_id}/resume", response_model=WorkflowResponse)
async def resume_workflow(
    workflow_id: str,
    request: WorkflowResumeRequest,
    engine: WorkflowEngine = Depends(get_engine)
):
    """
    Resume a paused workflow with user input

    Provide the required input data to continue execution of a workflow
    that is paused (WAITING_HUMAN status).
    """
    try:
        workflow = await engine.get_workflow(workflow_id)

        if workflow.status not in ["WAITING_HUMAN", "PENDING_ASYNC"]:
            raise HTTPException(
                status_code=400,
                detail=f"Workflow is not paused. Current status: {workflow.status}"
            )

        # Resume workflow with user input
        user_input = request.user_input
        while workflow.status in ["ACTIVE", "WAITING_HUMAN"]:
            try:
                await workflow.next_step(user_input=user_input)
                user_input = {}  # Only use input once
            except WorkflowPauseDirective:
                # Workflow paused again
                break

        return WorkflowResponse(
            workflow_id=workflow.id,
            status=workflow.status,
            current_step=workflow.current_step_name,
            state=workflow.state.model_dump() if workflow.state else {}
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by workflow status"),
    workflow_type: Optional[str] = Query(None, description="Filter by workflow type"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results"),
    engine: WorkflowEngine = Depends(get_engine)
):
    """
    List workflows with optional filtering

    Returns a paginated list of workflows. Use query parameters to filter
    by status or workflow type.
    """
    try:
        # Build filters
        filters = {}
        if status:
            filters['status'] = status
        if workflow_type:
            filters['workflow_type'] = workflow_type

        workflows_data = await engine.persistence.list_workflows(**filters)

        # Limit results
        workflows_data = workflows_data[:limit]

        # Format response
        workflows = []
        for wf_data in workflows_data:
            workflows.append(WorkflowListItem(
                workflow_id=wf_data.get("id"),
                workflow_type=wf_data.get("workflow_type"),
                status=wf_data.get("status"),
                current_step=wf_data.get("current_step"),
                created_at=wf_data.get("state", {}).get("created_at")
            ))

        return WorkflowListResponse(
            workflows=workflows,
            total=len(workflows)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workflows/{workflow_id}/cancel", response_model=dict)
async def cancel_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(get_engine)
):
    """
    Cancel a workflow

    Marks the workflow as CANCELLED. This does not execute compensation
    functions - use saga rollback for that.
    """
    try:
        workflow = await engine.get_workflow(workflow_id)

        if workflow.status in ["COMPLETED", "FAILED", "CANCELLED"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel workflow with status: {workflow.status}"
            )

        # Update status to CANCELLED
        old_status = workflow.status
        workflow.status = "CANCELLED"
        await workflow.persistence.save_workflow(workflow.id, workflow.to_dict())
        await workflow._notify_status_change(old_status, "CANCELLED", workflow.current_step_name)

        return {
            "workflow_id": workflow.id,
            "status": workflow.status,
            "message": "Workflow cancelled successfully"
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv('DEBUG', 'False').lower() == 'true'
    )
