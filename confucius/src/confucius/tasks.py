import importlib
import asyncio
from typing import Dict, Any, Optional
import httpx
import re
import os

from .celery_app import celery_app
from .persistence import load_workflow_state, save_workflow_state, get_workflow_store
from .events import event_publisher
from .postgres_executor import pg_executor
from .templating import render_template


def _sync_load_workflow(workflow_id: str):
    """Load workflow synchronously, using the persistence layer's sync capability"""
    return load_workflow_state(workflow_id, sync=True)


def _sync_save_workflow(workflow_id: str, workflow):
    """Save workflow synchronously, using the persistence layer's sync capability"""
    return save_workflow_state(workflow_id, workflow, sync=True)


def _publish_event_sync(coro):
    """
    Helper to run event publishing coroutines synchronously.
    Uses the PostgresExecutor's persistent loop to ensure connection reuse.
    """
    return pg_executor.run_coroutine_sync(coro)

def _log_task_execution(workflow_id: str, message: str, level: str = "INFO", step_name: str = None, metadata: Dict[str, Any] = None):
    """Helper to log execution details to persistent store from Celery tasks"""
    try:
        store = get_workflow_store()
        if hasattr(store, 'log_execution_sync'):
            store.log_execution_sync(
                workflow_id=workflow_id,
                log_level=level,
                message=message,
                step_name=step_name,
                metadata=metadata
            )
    except Exception as e:
        print(f"Failed to log to DB: {e}")


@celery_app.task
def execute_http_request(task_payload: Dict[str, Any]):
    """
    Generic HTTP Request Task.
    
    Expected keys in task_payload (configured in YAML):
    - method: GET, POST, etc.
    - url: Target URL (supports templating)
    - headers: Dict of headers (supports templating)
    - body: Dict or string body (supports templating)
    - timeout: Timeout in seconds (default 30)
    - output_key: Key to store the result in the state (default: 'http_response')
    
    The rest of task_payload is the workflow state.
    """
    method = task_payload.get('method', 'GET').upper()
    url_template = task_payload.get('url')
    headers_template = task_payload.get('headers', {})
    body_template = task_payload.get('body')
    timeout = task_payload.get('timeout', 30)
    output_key = task_payload.get('output_key', 'http_response')
    includes = task_payload.get('includes')
    workflow_id = task_payload.get('workflow_id')
    
    # Debug missing workflow_id
    if not workflow_id:
        print(f"[HTTP] WARNING: workflow_id missing in payload keys: {list(task_payload.keys())}")

    # Context for templating is the whole payload (state + config)
    context = task_payload
    
    # 1. Render URL
    url = render_template(url_template, context)
    
    _log_task_execution(workflow_id, f"Executing HTTP {method} {url}", level="INFO", metadata={"url": url, "method": method})

    # 2. Render Headers
    headers = render_template(headers_template, context)
        
    # 3. Render Body
    json_body = None
    data_body = None
    
    if isinstance(body_template, dict):
        json_body = render_template(body_template, context)
    elif isinstance(body_template, str):
        data_body = render_template(body_template, context)

    print(f"[HTTP] Executing {method} {url}")
    
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                data=data_body
            )
            
            # Raise for status? Maybe optional.
            # response.raise_for_status()
            
            try:
                response_data = response.json()
            except:
                response_data = response.text
            
            full_result = {
                "status_code": response.status_code,
                "body": response_data,
                "headers": dict(response.headers)
            }
            
            _log_task_execution(
                workflow_id, 
                f"HTTP Request completed: {response.status_code}", 
                level="INFO", 
                metadata={"status_code": response.status_code}
            )

            # Filter output if includes is specified
            if includes and isinstance(includes, list):
                filtered_result = {k: v for k, v in full_result.items() if k in includes}
                return {output_key: filtered_result}
                
            return {output_key: full_result}
            
    except Exception as e:
        print(f"[HTTP] Error: {e}")
        _log_task_execution(workflow_id, f"HTTP Request failed: {e}", level="ERROR", metadata={"error": str(e)})
        return {
            output_key: {
                "error": str(e),
                "status_code": 0
            }
        }


def resume_workflow_from_celery(workflow_id: str, step_result: Dict[str, Any], next_step_index_or_name: Any, completed_step_index: Optional[int] = None):
    """
    Core engine helper to load a workflow, merge state from an async result,
    advance the workflow, and save it.
    """
    _log_task_execution(workflow_id, "Resuming workflow from async task", level="DEBUG")
    
    workflow = _sync_load_workflow(workflow_id)
    if not workflow:
        print(f"Error: Workflow {workflow_id} not found for async resumption!")
        return

    # Generic state merging. The result of an async step is merged into the workflow state.
    if isinstance(step_result, dict):
        for key, value in step_result.items():
            if hasattr(workflow.state, key):
                setattr(workflow.state, key, value)

    # Before advancing, check for dynamic injections based on the new state.
    workflow._process_dynamic_injection()

    # Advance the step pointer
    next_step_index = -1
    if isinstance(next_step_index_or_name, str):  # It's a jump
        try:
            target_index = next(i for i, step in enumerate(workflow.workflow_steps) if step.name == next_step_index_or_name)
            workflow.current_step = target_index
            next_step_index = target_index
        except StopIteration:
            print(f"Error: Jump target step '{next_step_index_or_name}' not found for workflow {workflow_id}")
            workflow.status = "FAILED"
    elif isinstance(next_step_index_or_name, int):  # Linear progression
        workflow.current_step = next_step_index_or_name
        next_step_index = next_step_index_or_name

    # Check if the workflow is now complete
    if workflow.current_step >= len(workflow.workflow_steps):
        workflow.status = "COMPLETED"
        print(f"Workflow {workflow_id} completed after async task.")
    else:
        workflow.status = "ACTIVE"  # Mark workflow as active again

    _sync_save_workflow(workflow_id, workflow)
    
    # Publish updated event (async call from sync context)
    _publish_event_sync(event_publisher.publish_workflow_updated(workflow))
            
    print(f"Workflow {workflow_id} resumed and advanced to step {workflow.current_step_name}")

    # --- NEW AUTOMATION LOGIC ---
    if workflow.status == "ACTIVE" and completed_step_index is not None:
        should_auto_advance = False
        
        # Determine if we should auto-advance
        if 0 <= completed_step_index < len(workflow.workflow_steps):
            completed_step_obj = workflow.workflow_steps[completed_step_index]
            # Auto-advance if explicitly set OR if it's a sub-workflow (background process)
            if completed_step_obj.automate_next or workflow.parent_execution_id:
                should_auto_advance = True
        
        if should_auto_advance:
            print(f"Workflow {workflow_id}: Auto-advancing...")
            
            # Reload to ensure fresh state before execution loop
            workflow = _sync_load_workflow(workflow_id)
            if not workflow:
                print(f"Error: Could not reload workflow {workflow_id} for auto-advancement.")
                return

            # Loop to drive workflow forward until it stops (Async, Human, or Done)
            max_auto_steps = 100
            steps_run = 0
            
            while workflow.status == "ACTIVE" and steps_run < max_auto_steps:
                steps_run += 1
                try:
                    # Pass empty input as this is an automated transition
                    result, next_step = workflow.next_step(user_input={})
                    _sync_save_workflow(workflow_id, workflow)
                    
                    if workflow.status != "ACTIVE":
                        # Hit a blocking state (PENDING_ASYNC, WAITING_HUMAN, COMPLETED, etc.)
                        break
                        
                except Exception as e:
                    print(f"Error during auto-advancement of {workflow_id}: {e}")
                    # Error handling is done inside next_step (sets FAILED), so we just break
                    break
    # --- END NEW AUTOMATION LOGIC ---

    # --- NEW: NOTIFY PARENT ON COMPLETION ---
    # Reload to check final status after all advancements
    workflow = _sync_load_workflow(workflow_id)
    if workflow and workflow.status == "COMPLETED" and workflow.parent_execution_id:
        print(f"Child workflow {workflow_id} completed via async callback. Resuming parent {workflow.parent_execution_id}.")
        resume_parent_from_child.delay(workflow.parent_execution_id, workflow_id)
    # --- END NOTIFY PARENT ---


@celery_app.task
def trigger_scheduled_workflow(workflow_type: str, initial_data: Dict[str, Any]):
    """
    Task called by Celery Beat to instantiate and start a scheduled workflow.
    """
    # Import locally to avoid circular dependencies
    from .workflow_loader import workflow_builder
    from .events import event_publisher
    
    print(f"[SCHEDULER] Triggering scheduled workflow: {workflow_type}")
    try:
        workflow = workflow_builder.create_workflow(workflow_type, initial_data)
        _sync_save_workflow(workflow.id, workflow)
        
        # Publish creation event
        _publish_event_sync(event_publisher.publish_workflow_created(workflow))
        
        # Audit Log
        from .persistence import get_workflow_store
        store = get_workflow_store()
        if hasattr(store, 'log_audit_event_sync'):
             store.log_audit_event_sync(
                 workflow_id=workflow.id,
                 event_type='WORKFLOW_CREATED',
                 new_state=workflow.state.model_dump() if workflow.state else {},
                 metadata={'workflow_type': workflow_type, 'source': 'scheduler'}
             )
        
        print(f"[SCHEDULER] Workflow {workflow.id} created. Starting execution...")
        
        # Auto-start the workflow by executing the first step
        # Scheduled workflows are assumed to be fully automated at start
        result, next_step = workflow.next_step(user_input={})
        _sync_save_workflow(workflow.id, workflow)
        
        # Publish update event
        _publish_event_sync(event_publisher.publish_workflow_updated(workflow))
        
    except Exception as e:
        print(f"[SCHEDULER] Failed to trigger workflow {workflow_type}: {e}")

@celery_app.task
def poll_scheduled_workflows():
    """
    Periodic task to check DB for scheduled workflows that are due.
    Registered in Celery Beat to run every minute.
    """
    from .persistence import get_workflow_store
    import json
    
    # We need to run async code synchronously here
    store = get_workflow_store()
    
    # This task is intended to run inside Celery worker/beat which has an event loop
    # but to be safe and consistent with other tasks using pg_executor:
    def _do_poll():
        return pg_executor.run_coroutine_sync(_poll_async(store))
        
    async def _poll_async(store_wrapper):
        # Unwrap the wrapper to get the raw PostgresWorkflowStore which has the pool
        if hasattr(store_wrapper, '_get_initialized_store'):
            store = await store_wrapper._get_initialized_store()
        else:
            store = store_wrapper

        if not store._initialized:
            await store.initialize()
            
        async with store.pool.acquire() as conn:
            # Find enabled schedules where next_run_at <= NOW()
            # or next_run_at is NULL (first run)
            # Use FOR UPDATE SKIP LOCKED to prevent double-processing if multiple beat instances
            rows = await conn.fetch("""
                UPDATE scheduled_workflows
                SET last_run_at = NOW(),
                    run_count = run_count + 1,
                    next_run_at = NOW() + (
                        CASE 
                            WHEN interval_seconds IS NOT NULL THEN (interval_seconds || ' seconds')::INTERVAL
                            ELSE '1 hour'::INTERVAL -- Default fallback if cron calc is complex in SQL
                        END
                    )
                WHERE id IN (
                    SELECT id FROM scheduled_workflows
                    WHERE enabled = TRUE
                      AND (next_run_at IS NULL OR next_run_at <= NOW())
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, schedule_name, workflow_type, initial_data, cron_expression
            """)
            
            for row in rows:
                print(f"[SCHEDULER] Triggering due schedule: {row['schedule_name']}")
                
                # If cron expression exists, we should ideally calculate the REAL next_run_at here
                # and update the DB again. The SQL update above used a fallback.
                # For Phase 1, we just trigger the workflow.
                
                trigger_scheduled_workflow.delay(
                    row['workflow_type'],
                    json.loads(row['initial_data']) if row['initial_data'] else {}
                )
                
                # TODO: Integrate croniter library to calculate precise next_run_at
                
    try:
        _do_poll()
    except Exception as e:
        print(f"[SCHEDULER] Error polling schedules: {e}")

@celery_app.task
def merge_and_resume_parallel_tasks(results, workflow_id: str, current_step_index: int, merge_function_path: str = None):
    """
    Merges the results of parallel tasks and resumes the workflow.
    If a merge_function_path is provided, it will be used to merge the results.
    """
    if merge_function_path:
        module_path, func_name = merge_function_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        merge_function = getattr(module, func_name)
        merged_results = merge_function(results)
    else:
        # Default merge logic
        merged_results = {}
        for res in results:
            if isinstance(res, dict):
                merged_results.update(res)

    resume_workflow_from_celery(workflow_id, merged_results, current_step_index + 1, completed_step_index=current_step_index)
    
    return merged_results


@celery_app.task
def resume_from_async_task(result: dict, workflow_id: str, current_step_index: int):
    """
    Resumes a workflow after a single async task completes.
    """
    resume_workflow_from_celery(workflow_id, result, current_step_index + 1, completed_step_index=current_step_index)
    return result


@celery_app.task
def execute_sub_workflow(child_id: str, parent_id: str):
    """
    Execute child workflow to completion, then resume parent

    Args:
        child_id: UUID of the child workflow
        parent_id: UUID of the parent workflow
    """
    print(f"[SUB-WORKFLOW] Starting execution of child {child_id} for parent {parent_id}")

    child = _sync_load_workflow(child_id)
    if not child:
        print(f"[SUB-WORKFLOW] Error: Child workflow {child_id} not found")
        return

    # Run child until it blocks or completes
    max_iterations = 1000  # Safety limit
    iterations = 0

    while child.status == "ACTIVE" and iterations < max_iterations:
        iterations += 1
        try:
            result, next_step = child.next_step(user_input={})
            _sync_save_workflow(child_id, child)

            if child.status == "PENDING_ASYNC":
                # Child hit async step - it will resume itself later via celery callback
                print(f"[SUB-WORKFLOW] Child {child_id} is waiting for async task")
                return

            if child.status == "WAITING_HUMAN":
                # Child needs human input
                print(f"[SUB-WORKFLOW] Child {child_id} is waiting for human input")
                return

            if child.status == "PENDING_SUB_WORKFLOW":
                # Child started its own sub-workflow (nested)
                print(f"[SUB-WORKFLOW] Child {child_id} started a nested sub-workflow")
                return

        except Exception as e:
            child.status = "FAILED"
            _sync_save_workflow(child_id, child)
            print(f"[SUB-WORKFLOW] Error: Child workflow {child_id} failed: {e}")

            # Notify parent of child failure
            parent = _sync_load_workflow(parent_id)
            if parent:
                parent.status = "FAILED"
                parent.blocked_on_child_id = None
                _sync_save_workflow(parent_id, parent)

            return

    # Check if child completed
    if child.status == "COMPLETED":
        print(f"[SUB-WORKFLOW] Child {child_id} completed successfully, resuming parent {parent_id}")
        resume_parent_from_child.delay(parent_id, child_id)
    elif iterations >= max_iterations:
        print(f"[SUB-WORKFLOW] Error: Child {child_id} exceeded maximum iterations")
        child.status = "FAILED"
        _sync_save_workflow(child_id, child)


@celery_app.task
def execute_independent_workflow(workflow_id: str):
    """
    Execute a workflow to completion independently.
    Used for fire-and-forget patterns.
    """
    print(f"[FIRE-AND-FORGET] Starting independent execution of workflow {workflow_id}")
    workflow = _sync_load_workflow(workflow_id)
    if not workflow:
        print(f"[FIRE-AND-FORGET] Error: Workflow {workflow_id} not found")
        return

    # Run workflow until it blocks or completes
    max_iterations = 1000  # Safety limit
    iterations = 0

    while workflow.status == "ACTIVE" and iterations < max_iterations:
        iterations += 1
        try:
            # Pass empty input as these are typically background tasks
            result, next_step = workflow.next_step(user_input={})
            _sync_save_workflow(workflow_id, workflow)

            if workflow.status == "PENDING_ASYNC":
                print(f"[FIRE-AND-FORGET] Workflow {workflow_id} hit async step, will resume via callback")
                return

            if workflow.status == "WAITING_HUMAN":
                print(f"[FIRE-AND-FORGET] Workflow {workflow_id} waiting for human input")
                return
            
            if workflow.status == "PENDING_SUB_WORKFLOW":
                print(f"[FIRE-AND-FORGET] Workflow {workflow_id} started a sub-workflow")
                return

        except Exception as e:
            workflow.status = "FAILED"
            _sync_save_workflow(workflow_id, workflow)
            print(f"[FIRE-AND-FORGET] Error: Workflow {workflow_id} failed: {e}")
            return

    if workflow.status == "COMPLETED":
        print(f"[FIRE-AND-FORGET] Workflow {workflow_id} completed successfully")
    elif iterations >= max_iterations:
        print(f"[FIRE-AND-FORGET] Error: Workflow {workflow_id} exceeded maximum iterations")
        workflow.status = "FAILED"
        _sync_save_workflow(workflow_id, workflow)

@celery_app.task
def resume_parent_from_child(parent_id: str, child_id: str):
    """
    Merge child results into parent and continue execution

    Args:
        parent_id: UUID of the parent workflow
        child_id: UUID of the child workflow
    """
    print(f"[SUB-WORKFLOW] Resuming parent {parent_id} after child {child_id} completion")

    parent = _sync_load_workflow(parent_id)
    child = _sync_load_workflow(child_id)

    if not parent or not child:
        print("[SUB-WORKFLOW] Error: Could not load parent or child workflow")
        return

    # Merge child state into parent
    if not parent.state.sub_workflow_results:
        parent.state.sub_workflow_results = {}

    parent.state.sub_workflow_results[child.workflow_type] = child.state.model_dump()

    # Resume parent - ADVANCE to next step (sub-workflow step is done)
    parent.current_step += 1
    parent.status = "ACTIVE"
    parent.blocked_on_child_id = None
    _sync_save_workflow(parent_id, parent)

    # Publish updated event
    _publish_event_sync(event_publisher.publish_workflow_updated(parent))

    print(f"[SUB-WORKFLOW] Parent {parent_id} state updated with child results")

    # Continue parent execution
    try:
        result, next_step = parent.next_step(user_input={})
        _sync_save_workflow(parent_id, parent)
        print(f"[SUB-WORKFLOW] Parent {parent_id} advanced to step: {next_step}")
    except Exception as e:
        parent.status = "FAILED"
        _sync_save_workflow(parent_id, parent)
        print(f"[SUB-WORKFLOW] Error: Parent {parent_id} failed after child completion: {e}")
