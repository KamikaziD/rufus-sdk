"""
FastAPI REST API for Rufus Workflow Engine

This example demonstrates how to embed Rufus into a FastAPI application
to expose workflow operations via REST API endpoints with async support.

Features:
- Full async/await support with uvloop for optimal performance
- Automatic API documentation (Swagger/OpenAPI)
- Pydantic models for request/response validation
- Dependency injection for workflow engine
- CORS support for frontend integration
- High-performance JSON serialization (orjson)
- Optimized PostgreSQL connection pooling

Performance Optimizations:
- uvloop event loop (2-4x faster async I/O)
- orjson serialization (3-5x faster JSON operations)
- Connection pool tuning (configurable via environment variables)
- Import caching for step functions

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
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine


# Global workflow builder instance
workflow_builder: Optional[WorkflowBuilder] = None


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
    """Initialize the workflow builder with optimized providers"""
    global workflow_builder

    # Get configuration from environment variables
    registry_path = os.getenv("WORKFLOW_REGISTRY_PATH", str(Path(__file__).parent / "workflow_registry.yaml"))
    db_url = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/rufus_db")

    # Optional: Configure PostgreSQL pool settings for optimal performance
    # These can be tuned based on your workload
    pool_min_size = int(os.getenv("POSTGRES_POOL_MIN_SIZE", "10"))
    pool_max_size = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "50"))

    # Initialize persistence provider with optimized settings
    persistence = PostgresPersistenceProvider(
        db_url=db_url,
        pool_min_size=pool_min_size,
        pool_max_size=pool_max_size
    )
    await persistence.initialize()
    print(f"✓ PostgreSQL persistence initialized (pool: {pool_min_size}-{pool_max_size} connections)")

    # Initialize execution provider
    executor = SyncExecutor()
    await executor.initialize()

    # Initialize observer
    observer = LoggingObserver()

    # Create workflow builder
    workflow_builder = WorkflowBuilder(
        registry_path=registry_path,
        persistence_provider=persistence,
        execution_provider=executor,
        observer=observer,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # Check for performance optimizations
    import rufus
    from rufus.utils.serialization import get_backend
    print(f"✓ Performance optimizations:")
    print(f"  - Event loop: {rufus._event_loop_backend}")
    print(f"  - JSON backend: {get_backend()}")
    print(f"  - Import caching: Enabled")
    print(f"✓ Workflow builder ready")


async def shutdown_engine():
    """Cleanup on shutdown"""
    global workflow_builder
    if workflow_builder:
        # Close persistence connections
        if workflow_builder.persistence_provider:
            await workflow_builder.persistence_provider.close()
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


def get_builder() -> WorkflowBuilder:
    """Dependency to get the workflow builder"""
    if workflow_builder is None:
        raise HTTPException(status_code=503, detail="Workflow builder not initialized")
    return workflow_builder


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "rufus-workflow-api"}


@app.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    request: WorkflowCreateRequest,
    builder: WorkflowBuilder = Depends(get_builder)
):
    """
    Start a new workflow

    The workflow will execute automatically until it completes or pauses
    for human input.
    """
    try:
        # Create and start workflow
        workflow = builder.create_workflow(
            workflow_type=request.workflow_type,
            initial_data=request.initial_data
        )

        # Execute workflow steps until it pauses or completes
        while workflow.status == "ACTIVE":
            result = await workflow.next_step(user_input={})
            # Workflow automatically pauses when needed

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
    builder: WorkflowBuilder = Depends(get_builder)
):
    """
    Get workflow status and details

    Returns the current state of the workflow including its status,
    current step, and full state data.
    """
    try:
        workflow = builder.load_workflow(workflow_id)

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
    builder: WorkflowBuilder = Depends(get_builder)
):
    """
    Resume a paused workflow with user input

    Provide the required input data to continue execution of a workflow
    that is paused (WAITING_HUMAN status).
    """
    try:
        workflow = builder.load_workflow(workflow_id)

        if workflow.status not in ["WAITING_HUMAN", "PENDING_ASYNC"]:
            raise HTTPException(
                status_code=400,
                detail=f"Workflow is not paused. Current status: {workflow.status}"
            )

        # Resume workflow with user input
        user_input = request.user_input
        while workflow.status in ["ACTIVE", "WAITING_HUMAN"]:
            await workflow.next_step(user_input=user_input)
            user_input = {}  # Only use input once

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
    builder: WorkflowBuilder = Depends(get_builder)
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

        workflows_data = await builder.persistence_provider.list_workflows(**filters)

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
    builder: WorkflowBuilder = Depends(get_builder)
):
    """
    Cancel a workflow

    Marks the workflow as CANCELLED. This does not execute compensation
    functions - use saga rollback for that.
    """
    try:
        workflow = builder.load_workflow(workflow_id)

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
