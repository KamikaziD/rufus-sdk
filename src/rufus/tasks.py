"""
Celery tasks for Rufus workflow execution.

These tasks handle async operations, parallel execution, sub-workflows,
and workflow resumption from Celery workers.
"""
import importlib
import asyncio
from typing import Dict, Any, Optional
import httpx
import re
import os
import logging

logger = logging.getLogger(__name__)

# Import Celery app (will be created in celery_app.py)
# Using try/except to allow module import before celery is configured
try:
    from rufus.celery_app import celery_app
except ImportError:
    celery_app = None
    logger.warning("Celery app not yet available - tasks will be registered later")

from rufus.utils.postgres_executor import pg_executor
from rufus.events import event_publisher

# Global providers (set by celery_app on worker init)
_persistence_provider = None
_execution_provider = None
_workflow_builder = None
_expression_evaluator_cls = None
_template_engine_cls = None
_workflow_observer = None


def set_persistence_provider(provider):
    """Set the global persistence provider for tasks"""
    global _persistence_provider
    _persistence_provider = provider


def set_providers(persistence, execution, workflow_builder, expression_evaluator_cls, template_engine_cls, observer):
    """Set all global providers for tasks"""
    global _persistence_provider, _execution_provider, _workflow_builder
    global _expression_evaluator_cls, _template_engine_cls, _workflow_observer

    _persistence_provider = persistence
    _execution_provider = execution
    _workflow_builder = workflow_builder
    _expression_evaluator_cls = expression_evaluator_cls
    _template_engine_cls = template_engine_cls
    _workflow_observer = observer


def _publish_event_sync(coro):
    """
    Helper to run event publishing coroutines synchronously.
    Uses the PostgresExecutor's persistent loop to ensure connection reuse.
    """
    return pg_executor.run_coroutine_sync(coro)


def _log_task_execution(workflow_id: str, message: str, level: str = "INFO", step_name: str = None, metadata: Dict[str, Any] = None):
    """Helper to log execution details to persistent store from Celery tasks"""
    try:
        if _persistence_provider:
            pg_executor.run_coroutine_sync(
                _persistence_provider.log_execution(
                    workflow_id=workflow_id,
                    log_level=level,
                    message=message,
                    step_name=step_name,
                    metadata=metadata
                )
            )
    except Exception as e:
        logger.error(f"Failed to log to DB: {e}")


def _sync_load_workflow(workflow_id: str):
    """Load workflow synchronously from persistence provider"""
    if not _persistence_provider:
        raise RuntimeError("Persistence provider not initialized in Celery worker")
    if not _execution_provider:
        raise RuntimeError("Execution provider not initialized in Celery worker")
    if not _workflow_builder:
        raise RuntimeError("Workflow builder not initialized in Celery worker")

    # Use pg_executor to run async load in dedicated thread
    workflow_dict = pg_executor.run_coroutine_sync(
        _persistence_provider.load_workflow(workflow_id)
    )

    if not workflow_dict:
        return None

    # Import here to avoid circular import
    from rufus.workflow import Workflow

    # Reconstruct Workflow object from dict with all required providers
    return Workflow.from_dict(
        workflow_dict,
        persistence_provider=_persistence_provider,
        execution_provider=_execution_provider,
        workflow_builder=_workflow_builder,
        expression_evaluator_cls=_expression_evaluator_cls,
        template_engine_cls=_template_engine_cls,
        workflow_observer=_workflow_observer
    )


def _sync_save_workflow(workflow_id: str, workflow):
    """Save workflow synchronously to persistence provider"""
    if not _persistence_provider:
        raise RuntimeError("Persistence provider not initialized in Celery worker")

    # Convert workflow to dict
    workflow_dict = workflow.to_dict()

    # Use pg_executor to run async save in dedicated thread
    pg_executor.run_coroutine_sync(
        _persistence_provider.save_workflow(workflow_id, workflow_dict)
    )


def _sync_next_step(workflow, user_input: Dict[str, Any] = None):
    """Execute workflow next_step synchronously"""
    if user_input is None:
        user_input = {}

    # Use pg_executor to run async next_step in dedicated thread
    return pg_executor.run_coroutine_sync(
        workflow.next_step(user_input=user_input)
    )


@celery_app.task(bind=True) if celery_app else lambda f: f
def execute_http_request(self, task_payload: Dict[str, Any]):
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
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

    template_engine = Jinja2TemplateEngine()

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
        logger.warning(f"[HTTP] WARNING: workflow_id missing in payload keys: {list(task_payload.keys())}")

    # Context for templating is the whole payload (state + config)
    context = task_payload

    # 1. Render URL
    url = template_engine.render(url_template, context)

    _log_task_execution(workflow_id, f"Executing HTTP {method} {url}", level="INFO", metadata={"url": url, "method": method})

    # 2. Render Headers
    headers = template_engine.render(headers_template, context)

    # 3. Render Body
    json_body = None
    data_body = None

    if isinstance(body_template, dict):
        json_body = template_engine.render(body_template, context)
    elif isinstance(body_template, str):
        data_body = template_engine.render(body_template, context)

    logger.info(f"[HTTP] Executing {method} {url}")

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
        logger.error(f"[HTTP] Error: {e}")
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

    Args:
        workflow_id: ID of workflow to resume
        step_result: Result dict from async task (may contain error info)
        next_step_index_or_name: Next step to execute
        completed_step_index: Index of completed step (for auto-advance check)
    """
    _log_task_execution(workflow_id, "Resuming workflow from async task", level="DEBUG")

    workflow = _sync_load_workflow(workflow_id)
    if not workflow:
        logger.error(f"Error: Workflow {workflow_id} not found for async resumption!")
        return

    # Check if async task failed (indicated by error in result)
    if isinstance(step_result, dict) and "error" in step_result:
        logger.error(f"[ASYNC-TASK] Async task failed for workflow {workflow_id}: {step_result.get('error')}")
        workflow.status = "FAILED"
        # Store error metadata
        if not hasattr(workflow, 'metadata') or workflow.metadata is None:
            workflow.metadata = {}
        workflow.metadata["async_task_error"] = step_result.get("error")
        workflow.metadata["failed_at_step"] = workflow.current_step_name
        _sync_save_workflow(workflow_id, workflow)

        # Publish failure event
        _publish_event_sync(event_publisher.publish_workflow_updated(workflow))
        logger.error(f"[ASYNC-TASK] Workflow {workflow_id} marked as FAILED due to async task error")
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
            logger.error(f"Error: Jump target step '{next_step_index_or_name}' not found for workflow {workflow_id}")
            workflow.status = "FAILED"
            _sync_save_workflow(workflow_id, workflow)
            _publish_event_sync(event_publisher.publish_workflow_updated(workflow))
            return
    elif isinstance(next_step_index_or_name, int):  # Linear progression
        workflow.current_step = next_step_index_or_name
        next_step_index = next_step_index_or_name

    # Check if the workflow is now complete
    if workflow.current_step >= len(workflow.workflow_steps):
        workflow.status = "COMPLETED"
        logger.info(f"Workflow {workflow_id} completed after async task.")
    else:
        workflow.status = "ACTIVE"  # Mark workflow as active again

    _sync_save_workflow(workflow_id, workflow)

    # Publish updated event (async call from sync context)
    _publish_event_sync(event_publisher.publish_workflow_updated(workflow))

    logger.info(f"Workflow {workflow_id} resumed and advanced to step {workflow.current_step_name}")

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
            logger.info(f"Workflow {workflow_id}: Auto-advancing...")

            # Reload to ensure fresh state before execution loop
            workflow = _sync_load_workflow(workflow_id)
            if not workflow:
                logger.error(f"Error: Could not reload workflow {workflow_id} for auto-advancement.")
                return

            # Loop to drive workflow forward until it stops (Async, Human, or Done)
            max_auto_steps = 100
            steps_run = 0

            while workflow.status == "ACTIVE" and steps_run < max_auto_steps:
                steps_run += 1
                try:
                    # Pass empty input as this is an automated transition
                    result, next_step = _sync_next_step(workflow, user_input={})
                    _sync_save_workflow(workflow_id, workflow)

                    if workflow.status != "ACTIVE":
                        # Hit a blocking state (PENDING_ASYNC, WAITING_HUMAN, COMPLETED, etc.)
                        break

                except Exception as e:
                    logger.error(f"Error during auto-advancement of {workflow_id}: {e}")
                    # Error handling is done inside next_step (sets FAILED), so we just break
                    break
    # --- END NEW AUTOMATION LOGIC ---

    # --- NEW: NOTIFY PARENT ON COMPLETION ---
    # Reload to check final status after all advancements
    workflow = _sync_load_workflow(workflow_id)
    if workflow and workflow.status == "COMPLETED" and workflow.parent_execution_id:
        logger.info(f"Child workflow {workflow_id} completed via async callback. Resuming parent {workflow.parent_execution_id}.")
        resume_parent_from_child.delay(workflow.parent_execution_id, workflow_id)
    # --- END NOTIFY PARENT ---


@celery_app.task if celery_app else lambda f: f
def trigger_scheduled_workflow(workflow_type: str, initial_data: Dict[str, Any] = None):
    """
    Task called by Celery Beat to instantiate and start a scheduled workflow.

    Args:
        workflow_type: Type of workflow to create and start
        initial_data: Initial data for the workflow state
    """
    logger.info(f"[SCHEDULER] Triggering scheduled workflow: {workflow_type}")

    if not _workflow_builder:
        logger.error(f"[SCHEDULER] Cannot trigger {workflow_type}: WorkflowBuilder not initialized")
        return

    if initial_data is None:
        initial_data = {}

    try:
        # Create workflow using the global workflow builder
        workflow = pg_executor.run_coroutine_sync(
            _workflow_builder.create_workflow(workflow_type, initial_data)
        )

        # Save workflow to persistence
        _sync_save_workflow(workflow.id, workflow)

        # Publish creation event
        _publish_event_sync(event_publisher.publish_workflow_created(workflow))

        logger.info(f"[SCHEDULER] Created scheduled workflow {workflow_type}: {workflow.id}")

        # Auto-advance workflow if it's in ACTIVE state
        if workflow.status == "ACTIVE":
            max_auto_steps = 100
            steps_run = 0

            while workflow.status == "ACTIVE" and steps_run < max_auto_steps:
                steps_run += 1
                try:
                    result, next_step = _sync_next_step(workflow, user_input={})
                    _sync_save_workflow(workflow.id, workflow)

                    if workflow.status != "ACTIVE":
                        # Hit a blocking state (PENDING_ASYNC, WAITING_HUMAN, COMPLETED, etc.)
                        logger.info(f"[SCHEDULER] Workflow {workflow.id} reached status: {workflow.status}")
                        break

                except Exception as e:
                    logger.error(f"[SCHEDULER] Error during execution of {workflow.id}: {e}")
                    workflow.status = "FAILED"
                    _sync_save_workflow(workflow.id, workflow)
                    break

        return {"workflow_id": str(workflow.id), "status": workflow.status}

    except Exception as e:
        logger.error(f"[SCHEDULER] Failed to trigger workflow {workflow_type}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": str(e)}


@celery_app.task if celery_app else lambda f: f
def poll_scheduled_workflows():
    """
    Periodic task to check DB for scheduled workflows that are due.
    Registered in Celery Beat to run every minute.
    """
    # TODO: Implement scheduled workflow polling
    logger.info("[SCHEDULER] poll_scheduled_workflows not yet implemented")


@celery_app.task if celery_app else lambda f: f
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


@celery_app.task if celery_app else lambda f: f
def resume_from_async_task(result: dict, workflow_id: str, current_step_index: int):
    """
    Resumes a workflow after a single async task completes.
    """
    resume_workflow_from_celery(workflow_id, result, current_step_index + 1, completed_step_index=current_step_index)
    return result


@celery_app.task if celery_app else lambda f: f
def execute_sub_workflow(child_id: str, parent_id: str):
    """
    Execute child workflow to completion, then resume parent

    Args:
        child_id: UUID of the child workflow
        parent_id: UUID of the parent workflow
    """
    logger.info(f"[SUB-WORKFLOW] Starting execution of child {child_id} for parent {parent_id}")

    child = _sync_load_workflow(child_id)
    if not child:
        logger.error(f"[SUB-WORKFLOW] Error: Child workflow {child_id} not found")
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
                logger.info(f"[SUB-WORKFLOW] Child {child_id} is waiting for async task")
                return

            if child.status == "WAITING_HUMAN":
                # Child needs human input
                logger.info(f"[SUB-WORKFLOW] Child {child_id} is waiting for human input")
                return

            if child.status == "PENDING_SUB_WORKFLOW":
                # Child started its own sub-workflow (nested)
                logger.info(f"[SUB-WORKFLOW] Child {child_id} started a nested sub-workflow")
                return

        except Exception as e:
            child.status = "FAILED"
            _sync_save_workflow(child_id, child)
            logger.error(f"[SUB-WORKFLOW] Error: Child workflow {child_id} failed: {e}")

            # Notify parent of child failure
            parent = _sync_load_workflow(parent_id)
            if parent:
                # Use FAILED_CHILD_WORKFLOW status to distinguish from parent failure
                parent.status = "FAILED_CHILD_WORKFLOW"
                # Store failure metadata for debugging
                if not hasattr(parent, 'metadata') or parent.metadata is None:
                    parent.metadata = {}
                parent.metadata["failed_child_id"] = str(child_id)
                parent.metadata["failed_child_status"] = child.status
                parent.blocked_on_child_id = None
                _sync_save_workflow(parent_id, parent)

                # Publish workflow updated event
                _publish_event_sync(event_publisher.publish_workflow_updated(parent))
                logger.error(f"[SUB-WORKFLOW] Parent {parent_id} marked as FAILED_CHILD_WORKFLOW due to child {child_id} failure")

            return

    # Check if child completed
    if child.status == "COMPLETED":
        logger.info(f"[SUB-WORKFLOW] Child {child_id} completed successfully, resuming parent {parent_id}")
        resume_parent_from_child.delay(parent_id, child_id)
    elif iterations >= max_iterations:
        logger.error(f"[SUB-WORKFLOW] Error: Child {child_id} exceeded maximum iterations")
        child.status = "FAILED"
        _sync_save_workflow(child_id, child)


@celery_app.task if celery_app else lambda f: f
def execute_independent_workflow(workflow_id: str):
    """
    Execute a workflow to completion independently.
    Used for fire-and-forget patterns.
    """
    logger.info(f"[FIRE-AND-FORGET] Starting independent execution of workflow {workflow_id}")
    workflow = _sync_load_workflow(workflow_id)
    if not workflow:
        logger.error(f"[FIRE-AND-FORGET] Error: Workflow {workflow_id} not found")
        return

    # Run workflow until it blocks or completes
    max_iterations = 1000  # Safety limit
    iterations = 0

    while workflow.status == "ACTIVE" and iterations < max_iterations:
        iterations += 1
        try:
            # Pass empty input as these are typically background tasks
            result, next_step = _sync_next_step(workflow, user_input={})
            _sync_save_workflow(workflow_id, workflow)

            if workflow.status == "PENDING_ASYNC":
                logger.info(f"[FIRE-AND-FORGET] Workflow {workflow_id} hit async step, will resume via callback")
                return

            if workflow.status == "WAITING_HUMAN":
                logger.info(f"[FIRE-AND-FORGET] Workflow {workflow_id} waiting for human input")
                return

            if workflow.status == "PENDING_SUB_WORKFLOW":
                logger.info(f"[FIRE-AND-FORGET] Workflow {workflow_id} started a sub-workflow")
                return

        except Exception as e:
            workflow.status = "FAILED"
            _sync_save_workflow(workflow_id, workflow)
            logger.error(f"[FIRE-AND-FORGET] Error: Workflow {workflow_id} failed: {e}")
            return

    if workflow.status == "COMPLETED":
        logger.info(f"[FIRE-AND-FORGET] Workflow {workflow_id} completed successfully")
    elif iterations >= max_iterations:
        logger.error(f"[FIRE-AND-FORGET] Error: Workflow {workflow_id} exceeded maximum iterations")
        workflow.status = "FAILED"
        _sync_save_workflow(workflow_id, workflow)


@celery_app.task if celery_app else lambda f: f
def resume_parent_from_child(parent_id: str, child_id: str):
    """
    Merge child results into parent and continue execution

    Args:
        parent_id: UUID of the parent workflow
        child_id: UUID of the child workflow
    """
    logger.info(f"[SUB-WORKFLOW] Resuming parent {parent_id} after child {child_id} completion")

    parent = _sync_load_workflow(parent_id)
    child = _sync_load_workflow(child_id)

    if not parent or not child:
        logger.error("[SUB-WORKFLOW] Error: Could not load parent or child workflow")
        return

    # Check child status before resuming parent
    if child.status == "FAILED" or child.status == "FAILED_ROLLED_BACK":
        logger.error(f"[SUB-WORKFLOW] Child {child_id} failed with status {child.status}, failing parent {parent_id}")
        parent.status = "FAILED_CHILD_WORKFLOW"
        # Store failure metadata
        if not hasattr(parent, 'metadata') or parent.metadata is None:
            parent.metadata = {}
        parent.metadata["failed_child_id"] = str(child_id)
        parent.metadata["failed_child_status"] = child.status
        parent.blocked_on_child_id = None
        _sync_save_workflow(parent_id, parent)

        # Publish updated event
        _publish_event_sync(event_publisher.publish_workflow_updated(parent))
        return

    # Merge child state into parent
    if not hasattr(parent.state, 'sub_workflow_results') or parent.state.sub_workflow_results is None:
        parent.state.sub_workflow_results = {}

    parent.state.sub_workflow_results[child.workflow_type] = child.state.model_dump()

    # Resume parent - ADVANCE to next step (sub-workflow step is done)
    parent.current_step += 1
    parent.status = "ACTIVE"
    parent.blocked_on_child_id = None
    _sync_save_workflow(parent_id, parent)

    # Publish updated event
    _publish_event_sync(event_publisher.publish_workflow_updated(parent))

    logger.info(f"[SUB-WORKFLOW] Parent {parent_id} state updated with child results")

    # Continue parent execution
    try:
        result, next_step = parent.next_step(user_input={})
        _sync_save_workflow(parent_id, parent)
        logger.info(f"[SUB-WORKFLOW] Parent {parent_id} advanced to step: {next_step}")
    except Exception as e:
        parent.status = "FAILED"
        _sync_save_workflow(parent_id, parent)
        # Publish workflow failed event
        _publish_event_sync(event_publisher.publish_workflow_updated(parent))
        logger.error(f"[SUB-WORKFLOW] Error: Parent {parent_id} failed after child completion: {e}")


def set_persistence_provider(provider):
    """
    Called by celery_app.py on worker init to inject persistence provider.
    """
    global _persistence_provider
    _persistence_provider = provider
    logger.info(f"Persistence provider set: {type(provider).__name__}")
