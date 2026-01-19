from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Header, Depends, Request
from fastapi.responses import JSONResponse
import yaml
import asyncio
import json
import redis.asyncio as aredis
import os
from typing import Optional, Any
from pydantic import BaseModel

# Observability: prefer Postgres LISTEN/NOTIFY when available
from .observability import monitor
from .persistence import get_workflow_store, get_storage_backend
from .persistence_postgres import get_postgres_store
from .events import event_publisher

from .workflow_loader import WorkflowBuilder
from .persistence import save_workflow_state, load_workflow_state
from .models import (
    WorkflowStartRequest, WorkflowStartResponse, WorkflowStepRequest, WorkflowStepResponse,
    WorkflowStatusResponse, ResumeWorkflowRequest, RetryWorkflowRequest
)
from .workflow import WorkflowJumpDirective

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

# This router factory allows the user's application to initialize the router
# with its own configured WorkflowBuilder instance.


def get_workflow_router(workflow_builder: WorkflowBuilder, limiter: Any = None) -> APIRouter:

    router = APIRouter(prefix="/api/v1")

    # Helper for rate limiting (no-op if limiter is None)
    def limit(limit_value):
        def decorator(func):
            if limiter:
                return limiter.limit(limit_value)(func)
            return func
        return decorator

    async def _save_workflow(workflow_id: str, workflow):
        """Helper to save workflow, handling async task if needed"""
        save_task = save_workflow_state(workflow_id, workflow)
        if asyncio.iscoroutine(save_task) or asyncio.isfuture(save_task):
            await save_task

    def _check_access(workflow, user: Optional[UserContext]):
        """Enforce RBAC policies"""
        if not user:
            return # No user context, legacy mode (open)
        
        # If workflow has no owner, it's public/legacy
        if not workflow.owner_id:
            return

        # Check Owner
        if workflow.owner_id == user.user_id:
            return
        
        # Check Org
        if workflow.org_id and user.org_id and workflow.org_id == user.org_id:
            return
            
        raise HTTPException(status_code=403, detail="Access denied")

    @router.post("/internal/retry", response_model=WorkflowStepResponse)
    async def internal_retry_step(request_data: RetryWorkflowRequest):
        """
        Internal endpoint called by the Retry Service (BullMQ Worker) to re-trigger a step.
        """
        workflow_id = request_data.workflow_id
        workflow = load_workflow_state(workflow_id)
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
            
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Validate we are retrying the correct step
        if workflow.current_step != request_data.step_index:
             # If step index mismatch, maybe workflow advanced? Treat as success/ignore.
             raise HTTPException(status_code=409, detail=f"Step index mismatch. Current: {workflow.current_step}, Requested: {request_data.step_index}")

        current_step_obj = workflow.workflow_steps[workflow.current_step]
        
        # Reset status to ACTIVE to allow re-execution
        workflow.status = "ACTIVE"
        
        # We might want to store retry count in metadata
        workflow.metadata = workflow.metadata or {}
        workflow.metadata['last_retry_count'] = request_data.retry_count
        
        try:
            # Re-execute the step using next_step logic with empty input (or last input if we persisted it)
            # For now, we assume the step function can handle empty input or re-uses state
            result_dict, next_step_name = workflow.next_step(user_input={})
            
            await _save_workflow(workflow_id, workflow)
            
            # Publish updated event
            await event_publisher.publish_workflow_updated(workflow)
            
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
            await _save_workflow(workflow_id, workflow)
            return WorkflowStepResponse(
                workflow_id=workflow.id, current_step_name=current_step_obj.name, next_step_name=workflow.current_step_name,
                status=workflow.status, state=workflow.state.model_dump(), result={"message": f"Workflow branched to {e.target_step_name}"}
            )
        except Exception as e:
            workflow.status = "FAILED"
            await _save_workflow(workflow_id, workflow)
            from .events import event_publisher
            await event_publisher.publish_step_failed(workflow_id, current_step_obj.name, str(e))
            await event_publisher.publish_to_retry_queue(
                workflow_id, workflow.current_step, current_step_obj.name, str(e), 
                context={"retry_count": request_data.retry_count}
            )
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/workflows")
    async def get_available_workflows():
        """
        Returns a list of available workflows from the registry.
        """
        registry_path = workflow_builder.registry_path
        try:
            with open(registry_path, "r") as f:
                registry = yaml.safe_load(f)
        except FileNotFoundError:
            raise HTTPException(
                status_code=500, detail=f"Workflow registry not found at {registry_path}")

        workflow_examples = {
            "LoanApplication": {
                "application_id": "L12345", "requested_amount": 15000.50,
                "applicant_profile": {"user_id": "U-789", "name": "John Doe", "email": "j.doe@workplace.com", "country": "USA", "age": 22, "id_document_url": "s3://docs/id_valid.pdf"}
            },
            "KYC": {
                "user_name": "John Doe",
                "id_document_url": "s3://docs/id_valid.pdf"
            },
            "CustomerOnboarding": {"name": "Jane Smith", "email": "jane.smith@gmail.com"},
            "ComplianceReview": {"client_id": "C-5678"},
            "ImageComplianceWorkflow": {"compliance_text": "We sell puppies to China."},
            "SuperWorkflow": {"name": "Confucius"},
            "GearsTest": {
                "test_id": "GEARS-TEST-001",
                "items": ["Item A", "Item B", "Item C", "Item D", "Item E"]
            },
            "TodoProcessingWorkflow": {
                "todo_list_url": "https://jsonplaceholder.typicode.com/todos"
            },
            "TestScheduler": {
                "report_id": "TEST-SCHEDULER",
                "generated_at": "pending"
            }
        }

        for wf in registry.get("workflows", []):
            wf["initial_data_example"] = workflow_examples.get(wf["type"], {})

        return registry.get("workflows", [])

    @router.post("/workflow/start", response_model=WorkflowStartResponse)
    @limit("10/minute")
    async def start_workflow(request: Request, request_data: WorkflowStartRequest, user: Optional[UserContext] = Depends(get_current_user)):
        try:
            new_workflow = workflow_builder.create_workflow(
                workflow_type=request_data.workflow_type,
                initial_data=request_data.initial_data
            )
            
            # Apply Data Region
            if request_data.data_region:
                new_workflow.data_region = request_data.data_region
            
            # Apply RBAC
            if user:
                new_workflow.owner_id = user.user_id
                new_workflow.org_id = user.org_id
            
            await _save_workflow(new_workflow.id, new_workflow)
            
            # Publish workflow created event
            await event_publisher.publish_workflow_created(new_workflow)

            # Audit Log (Postgres only)
            try:
                backend = get_storage_backend()
                if backend in ("postgres", "postgresql"):
                    pg_store = await get_postgres_store()
                    await pg_store.log_audit_event(
                        workflow_id=new_workflow.id,
                        event_type='WORKFLOW_CREATED',
                        new_state=new_workflow.state.model_dump() if new_workflow.state else {},
                        metadata={'workflow_type': request_data.workflow_type},
                        user_id=user.user_id if user else None
                    )
            except Exception as e:
                # Don't fail the request if logging fails
                print(f"Warning: Failed to log WORKFLOW_CREATED audit event: {e}")
            
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

    @router.get("/workflow/{workflow_id}/current_step_info")
    async def get_current_step_info(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
        workflow = load_workflow_state(workflow_id)
        # Handle async Task if running in async context with PostgreSQL
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
        _check_access(workflow, user)

        if workflow.status == "COMPLETED" or workflow.current_step >= len(workflow.workflow_steps):
            return {"name": "Workflow Complete", "required_input": [], "input_schema": None}

        step = workflow.workflow_steps[workflow.current_step]
        response = {"name": step.name, "type": type(step).__name__}
        
        # Always include required_input for a stable API shape
        response["required_input"] = getattr(step, "required_input", []) or []

        if workflow.status == "WAITING_HUMAN":
            # For human steps, we use the ResumeWorkflowRequest model to build the schema
            response["input_schema"] = ResumeWorkflowRequest.model_json_schema()
        elif hasattr(step, "input_schema") and step.input_schema:
            try:
                response["input_schema"] = step.input_schema.model_json_schema()
            except AttributeError:
                response["input_schema"] = step.input_schema.schema()
        else:
            response["input_schema"] = None
            
        return response

    @router.post("/workflow/{workflow_id}/next", response_model=WorkflowStepResponse)
    async def next_workflow_step(workflow_id: str, request_data: WorkflowStepRequest, user: Optional[UserContext] = Depends(get_current_user)):
        workflow = load_workflow_state(workflow_id)
        # Handle async Task if running in async context with PostgreSQL
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
        _check_access(workflow, user)

        if workflow.status in ["PENDING_ASYNC", "WAITING_HUMAN", "COMPLETED", "FAILED"]:
            raise HTTPException(
                status_code=409, detail=f"Workflow is in '{workflow.status}' state. Cannot advance with /next.")

        current_step_obj = workflow.workflow_steps[workflow.current_step]

        try:
            result_dict, next_step_name = workflow.next_step(
                user_input=request_data.input_data)
            await _save_workflow(workflow_id, workflow)

            # Publish updated event
            await event_publisher.publish_workflow_updated(workflow)

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
            # Client errors (validation, etc) - DO NOT trigger automated retry
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            workflow.status = "FAILED"
            await _save_workflow(workflow_id, workflow)
            
            # Publish failure events
            await event_publisher.publish_step_failed(workflow_id, current_step_obj.name, str(e))
            await event_publisher.publish_workflow_failed(workflow, str(e))
            
            # Also Trigger Retry Loop (Channel #3)
            await event_publisher.publish_to_retry_queue(
                workflow_id=workflow.id,
                step_index=workflow.current_step,
                task_name=current_step_obj.name,
                error=str(e),
                context={"retry_count": 0}
            )
            
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/workflow/{workflow_id}/status", response_model=WorkflowStatusResponse)
    async def get_workflow_status(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
        workflow = load_workflow_state(workflow_id)
        # Handle async Task if running in async context with PostgreSQL
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
        _check_access(workflow, user)
        
        return WorkflowStatusResponse(
            workflow_id=workflow.id, status=workflow.status,
            current_step_name=workflow.current_step_name, state=workflow.state.model_dump(),
            workflow_type=workflow.workflow_type,
            parent_execution_id=workflow.parent_execution_id,
            blocked_on_child_id=workflow.blocked_on_child_id
        )

    @router.post("/workflow/{workflow_id}/resume", response_model=WorkflowStepResponse)
    async def resume_workflow(workflow_id: str, request_data: ResumeWorkflowRequest, user: Optional[UserContext] = Depends(get_current_user)):
        workflow = load_workflow_state(workflow_id)
        # Handle async Task if running in async context with PostgreSQL
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
        _check_access(workflow, user)
        
        if workflow.status != "WAITING_HUMAN":
            raise HTTPException(
                status_code=400, detail=f"Workflow is not awaiting human input. Current status: {workflow.status}")

        current_step_obj = workflow.workflow_steps[workflow.current_step]

        try:
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
            
            await _save_workflow(workflow_id, workflow)

            # Publish updated event
            await event_publisher.publish_workflow_updated(workflow)

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
            await _save_workflow(workflow_id, workflow)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/workflow/{workflow_id}/retry", response_model=WorkflowStatusResponse)
    async def retry_workflow(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
        workflow = load_workflow_state(workflow_id)
        # Handle async Task if running in async context with PostgreSQL
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
        _check_access(workflow, user)
        
        if workflow.status != "FAILED":
            raise HTTPException(
                status_code=400, detail=f"Workflow is not in a FAILED state. Current status: {workflow.status}")

        workflow.status = "ACTIVE"
        await _save_workflow(workflow_id, workflow)
        
        await event_publisher.publish_workflow_updated(workflow)

        return WorkflowStatusResponse(
            workflow_id=workflow.id, status=workflow.status,
            current_step_name=workflow.current_step_name, state=workflow.state.model_dump()
        )

    @router.post("/workflow/{workflow_id}/rewind", response_model=WorkflowStepResponse)
    async def rewind_workflow(workflow_id: str, user: Optional[UserContext] = Depends(get_current_user)):
        """
        Rewind the workflow to the previous step.
        Useful for recovering from logic errors or bad data input.
        """
        workflow = load_workflow_state(workflow_id)
        if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
            workflow = await workflow
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
        _check_access(workflow, user)
        
        if workflow.current_step <= 0:
            raise HTTPException(status_code=400, detail="Cannot rewind. Already at the first step.")

        # Decrement step
        workflow.current_step -= 1
        
        # Reset status to ACTIVE if it was failed or completed
        workflow.status = "ACTIVE"
        
        await _save_workflow(workflow_id, workflow)
        await event_publisher.publish_workflow_updated(workflow)
        
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
    @router.get("/workflow/{workflow_id}/audit")
    async def get_workflow_audit_log(workflow_id: str, limit: int = 100):
        """Get audit trail for workflow (Postgres backend required)"""
        backend = get_storage_backend()
        if backend not in ("postgres", "postgresql"):
            raise HTTPException(
                status_code=501, detail="Audit logs require PostgreSQL backend")

        try:
            store = await get_postgres_store()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not access Postgres store: {e}")

        async with store.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT workflow_id, event_type, step_name, user_id, worker_id,
                       old_state, new_state, decision_rationale, metadata, recorded_at
                FROM workflow_audit_log
                WHERE workflow_id = $1
                ORDER BY recorded_at DESC
                LIMIT $2
            """, workflow_id, limit)

            return [dict(row) for row in rows]

    @router.get("/workflow/{workflow_id}/logs")
    async def get_workflow_logs(workflow_id: str, level: str = None, limit: int = 500):
        """Get execution logs for debugging (Postgres backend required)"""
        backend = get_storage_backend()
        if backend not in ("postgres", "postgresql"):
            raise HTTPException(
                status_code=501, detail="Execution logs require PostgreSQL backend")

        try:
            store = await get_postgres_store()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not access Postgres store: {e}")

        async with store.pool.acquire() as conn:
            if level:
                rows = await conn.fetch("""
                    SELECT workflow_id, step_name, log_level, message, metadata, logged_at
                    FROM workflow_execution_logs
                    WHERE workflow_id = $1 AND log_level = $2
                    ORDER BY logged_at DESC
                    LIMIT $3
                """, workflow_id, level, limit)
            else:
                rows = await conn.fetch("""
                    SELECT workflow_id, step_name, log_level, message, metadata, logged_at
                    FROM workflow_execution_logs
                    WHERE workflow_id = $1
                    ORDER BY logged_at DESC
                    LIMIT $2
                """, workflow_id, limit)

            return [dict(row) for row in rows]

    @router.get("/workflow/{workflow_id}/metrics")
    async def get_workflow_metrics(workflow_id: str, limit: int = 500):
        """Get performance metrics for workflow (Postgres backend required)"""
        backend = get_storage_backend()
        if backend not in ("postgres", "postgresql"):
            raise HTTPException(
                status_code=501, detail="Metrics require PostgreSQL backend")

        try:
            store = await get_postgres_store()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not access Postgres store: {e}")

        async with store.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT step_name, metric_name, metric_value, unit, tags, recorded_at
                FROM workflow_metrics
                WHERE workflow_id = $1
                ORDER BY recorded_at DESC
                LIMIT $2
            """, workflow_id, limit)

            return [dict(row) for row in rows]

    @router.get("/workflows/executions")
    async def get_workflow_executions(status: str = None, exclude_status: str = None, limit: int = 50, offset: int = 0):
        """
        List active and recent workflow executions.
        """
        backend = get_storage_backend()
        if backend not in ("postgres", "postgresql"):
            raise HTTPException(status_code=501, detail="Listing executions requires PostgreSQL backend")

        try:
            store = await get_postgres_store()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not access Postgres store: {e}")

        async with store.pool.acquire() as conn:
            query = """
                SELECT id, workflow_type, status, current_step, updated_at
                FROM workflow_executions
            """
            conditions = []
            params = []
            
            if status:
                conditions.append(f"status = ${len(params) + 1}")
                params.append(status)
            
            if exclude_status:
                excluded = exclude_status.split(',')
                if len(excluded) == 1:
                    conditions.append(f"status != ${len(params) + 1}")
                    params.append(excluded[0])
                else:
                    placeholders = [f"${len(params) + i + 1}" for i in range(len(excluded))]
                    conditions.append(f"status NOT IN ({', '.join(placeholders)})")
                    params.extend(excluded)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += f" ORDER BY updated_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
            params.append(limit)
            params.append(offset)

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    @router.get("/metrics/summary")
    async def get_metrics_summary(hours: int = 24):
        """Get aggregated metrics across workflows (Postgres backend required)"""
        backend = get_storage_backend()
        if backend not in ("postgres", "postgresql"):
            raise HTTPException(
                status_code=501, detail="Metrics require PostgreSQL backend")

        try:
            store = await get_postgres_store()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not access Postgres store: {e}")

        async with store.pool.acquire() as conn:
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

    @router.get("/admin/workers")
    async def get_registered_workers(limit: int = 100):
        """List registered worker nodes (Postgres backend required)"""
        backend = get_storage_backend()
        if backend not in ("postgres", "postgresql"):
            raise HTTPException(
                status_code=501, detail="Worker registry requires PostgreSQL backend")

        try:
            store = await get_postgres_store()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not access Postgres store: {e}")

        async with store.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT worker_id, hostname, region, zone, capabilities, status, last_heartbeat, updated_at
                FROM worker_nodes
                ORDER BY last_heartbeat DESC
                LIMIT $1
            """, limit)

            return [dict(row) for row in rows]

    @router.websocket("/workflow/{workflow_id}/subscribe")
    async def workflow_subscribe(websocket: WebSocket, workflow_id: str):
        """
        WebSocket endpoint that forwards real-time workflow updates.
        """
        await websocket.accept()

        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_client = aredis.Redis(
            host=redis_host, port=6379, db=0, decode_responses=True)
        pubsub = redis_client.pubsub()
        channel = f"workflow:events:{workflow_id}"

        try:
            await pubsub.subscribe(channel)

            backend = get_storage_backend()
            initial_workflow = None
            
            if backend in ("postgres", "postgresql"):
                 store = await get_postgres_store()
                 initial_workflow = await store.load_workflow(workflow_id)
            else:
                 initial_state_json = await redis_client.get(f"workflow:{workflow_id}")
                 if initial_state_json:
                     await websocket.send_text(initial_state_json)
                     initial_workflow = None 

            if initial_workflow:
                await websocket.send_json({
                    "id": initial_workflow.id,
                    "status": initial_workflow.status,
                    "current_step": initial_workflow.current_step_name,
                    "state": initial_workflow.state.model_dump(),
                    "workflow_type": initial_workflow.workflow_type,
                    "steps_config": [s.to_dict() for s in initial_workflow.workflow_steps]
                })

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get('data'):
                    data_str = message['data']
                    try:
                         json.loads(data_str) 
                         await websocket.send_text(data_str)
                    except:
                         await websocket.send_text(json.dumps({"error": "Invalid JSON from pubsub", "raw": data_str}))
                
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass
                except WebSocketDisconnect:
                    raise

        except WebSocketDisconnect:
            print(f"Client disconnected from workflow {workflow_id}")
        except Exception as e:
            print(f"An error occurred in websocket for {workflow_id}: {e}")
        finally:
            if getattr(pubsub, "subscribed", False):
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    pass
            try:
                await redis_client.close()
            except Exception:
                pass
            print("Websocket connection closed.")

    return router