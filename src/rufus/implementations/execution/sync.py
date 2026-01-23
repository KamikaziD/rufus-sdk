from typing import Dict, Any, List, Optional, Callable
from rufus.providers.execution import ExecutionProvider
from rufus.models import (
    BaseModel, StepContext, ParallelExecutionTask,
    MergeStrategy, MergeConflictBehavior
)
import asyncio
import concurrent.futures
import threading
import traceback

class SyncExecutor(ExecutionProvider):
    """
    A synchronous implementation of the ExecutionProvider.
    Executes steps directly in the current process/thread.
    Useful for local development, testing, and simple synchronous workflows.
    Parallel tasks are simulated using ThreadPoolExecutor.
    """
    def __init__(self):
        self._engine = None # Reference to the WorkflowEngine
        self._thread_pool_executor = None
        self._loop = None # To store the main event loop

    async def initialize(self, engine: Any):
        """Initializes the executor, providing it with a reference to the WorkflowEngine."""
        self._engine = engine
        self._thread_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        # Store the event loop where initialize was called
        self._loop = asyncio.get_running_loop()
        print("[SyncExecutor] Initialized.")

    async def close(self):
        """Shuts down the executor."""
        if self._thread_pool_executor:
            self._thread_pool_executor.shutdown(wait=True)
        print("[SyncExecutor] Closed.")

    async def execute_sync_step_function(self, func: Callable, state: BaseModel, context: StepContext) -> Dict[str, Any]:
        """Executes a synchronous step function directly."""
        # Ensure that the function itself is awaited if it's an async function
        if asyncio.iscoroutinefunction(func):
            result = await func(state=state, context=context)
        else:
            result = func(state=state, context=context)
        
        # Ensure result is a dict
        return result if isinstance(result, dict) else {}

    async def dispatch_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str] = None, merge_strategy: str = "SHALLOW", merge_conflict_behavior: str = "PREFER_NEW", **kwargs) -> Dict[str, Any]:
        """
        Simulates dispatching an asynchronous task.
        For SyncExecutor, this is processed immediately as if it were a deferred task.
        """
        # Load the function dynamically using WorkflowBuilder
        func = self._engine.workflow_builder._import_from_string(func_path)
        if not func:
            raise ValueError(f"Function not found at path: {func_path}")

        # Reconstruct state for the task context
        state_model_class = self._engine.workflow_builder._import_from_string(self._engine.get_workflow(workflow_id).state_model_path)
        state_instance = state_model_class(**state_data)
        context = StepContext(workflow_id=workflow_id, step_name=func.__name__, previous_step_result=kwargs.get('_previous_step_result')) # Revisit context for async tasks

        # Execute the function (ensure it's awaited if async)
        if asyncio.iscoroutinefunction(func):
            task_result = await func(state=state_instance, context=context, **kwargs)
        else:
            task_result = func(state=state_instance, context=context, **kwargs)

        # In a real async executor, this would involve Celery or similar.
        # Here, we simulate the 'callback' to WorkflowEngine's resume_workflow
        # with the result. For testing, we just return the result directly.
        
        # The WorkflowEngine's next_step expects a special dict if it's async dispatched
        return {"_async_dispatch": True, "task_id": "simulated_async_task", "result": task_result}


    def _run_task_in_thread(self, func_path: str, state_data: Dict[str, Any], context_data: Dict[str, Any], state_model_path: str):
        """Helper to run a step function in a separate thread."""
        loop = self._loop # Get the event loop from the main thread

        # Reconstruct function and context within the new thread
        func = self._engine.workflow_builder._import_from_string(func_path)
        context = StepContext(**context_data)

        try:
            # For parallel tasks, pass state_data as a dict (not a Pydantic model)
            # The parallel task functions expect state: dict parameter
            if asyncio.iscoroutinefunction(func):
                # Run async function in the main event loop
                result = asyncio.run_coroutine_threadsafe(func(state_data, context), loop).result()
            else:
                result = func(state_data, context)
            return {"result": result if isinstance(result, dict) else {}}
        except Exception as e:
            return {"error": str(e), "traceback": traceback.format_exc()}


    async def dispatch_parallel_tasks(self, tasks: List[ParallelExecutionTask], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str] = None, data_region: Optional[str] = None, merge_strategy: str = "SHALLOW", merge_conflict_behavior: str = "PREFER_NEW", timeout_seconds: Optional[int] = None, allow_partial_success: bool = False) -> Dict[str, Any]:
        """
        Simulates dispatching multiple tasks in parallel using a ThreadPoolExecutor.
        """
        if not self._thread_pool_executor:
            raise RuntimeError("ThreadPoolExecutor not initialized. Call initialize() first.")

        # Get the state_model_path from the workflow before spawning threads
        workflow = await self._engine.get_workflow(workflow_id)
        state_model_path = workflow.state_model_path

        futures = []
        for task in tasks:
            context_data = { # Create context data for each task
                "workflow_id": workflow_id,
                "step_name": task.name,
                "validated_input": None, # Parallel tasks don't usually take user_input directly
                "previous_step_result": None
            }
            future = self._thread_pool_executor.submit(self._run_task_in_thread, task.func_path, state_data, context_data, state_model_path)
            futures.append((task.name, future))

        results_map = {}
        errors_map = {}
        for task_name, future in futures:
            try:
                # Await the result of the thread-run function
                thread_result = await asyncio.wrap_future(future)
                if "error" in thread_result:
                    errors_map[task_name] = thread_result
                else:
                    results_map[task_name] = thread_result["result"]
            except Exception as e:
                errors_map[task_name] = {"error": str(e), "traceback": traceback.format_exc()}
        
        if errors_map and not allow_partial_success:
            # If any task failed and partial success is not allowed, raise an exception
            error_messages = [f"Task {name} failed: {err['error']}" for name, err in errors_map.items()]
            raise RuntimeError(f"Parallel tasks failed: {'; '.join(error_messages)}")

        final_result = {}
        if merge_function_path:
            merge_func = self._engine.workflow_builder._import_from_string(merge_function_path)
            if not merge_func:
                raise ValueError(f"Merge function not found at path: {merge_function_path}")
            
            # Reconstruct current workflow state for the merge function
            workflow_state_model_class = self._engine.workflow_builder.get_state_model_class(self._engine.get_workflow(workflow_id).workflow_type)
            current_workflow_state = workflow_state_model_class(**state_data)
            
            # Call custom merge function
            final_result = merge_func(results_map, current_workflow_state)
        else:
            # Default shallow merge
            for res in results_map.values():
                if isinstance(res, dict):
                    final_result.update(res) # Last write wins for simplicity

        # The WorkflowEngine's next_step expects a special dict if it's async dispatched
        # and has immediate results
        return {"_async_dispatch": False, "_sync_parallel_result": final_result, "task_results": results_map, "errors": errors_map}


    async def dispatch_sub_workflow(self, child_id: str, parent_id: str, sub_workflow_type: str, initial_data: Dict[str, Any], owner_id: Optional[str] = None, org_id: Optional[str] = None, data_region: Optional[str] = None) -> Dict[str, Any]:
        """
        Dispatches a sub-workflow. For SyncExecutor, this simulates the async dispatch
        and immediately returns a result indicating a PENDING_SUB_WORKFLOW state.
        The actual execution of the child is handled by the parent's next_step once resumed.
        """
        # In a real async executor, this would queue the child workflow for execution.
        # For SyncExecutor, we just acknowledge the dispatch. The WorkflowEngine
        # manages the state transition.
        return {"_async_dispatch": True, "child_workflow_id": child_id, "status": "PENDING_SUB_WORKFLOW"}


    async def dispatch_independent_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Dispatches an independent workflow without blocking the current one.
        For SyncExecutor, this simulates the dispatch.
        """
        # In a real async executor, this would queue the independent workflow for execution.
        # For SyncExecutor, we just acknowledge the dispatch.
        print(f"[SyncExecutor] Independent workflow {workflow_id} dispatched.")
        return {"_async_dispatch": True, "independent_workflow_id": workflow_id}


    async def report_child_status_to_parent(self, child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str] = None, child_result: Optional[Dict[str, Any]] = None):
        """
        Simulates reporting a child workflow's status to its parent.
        In SyncExecutor, this directly calls the parent engine's method.
        """
        print(f"[SyncExecutor] Child {child_id} reporting status {child_new_status} to parent {parent_id}")
        # Get the parent workflow engine instance
        parent_engine = self._engine # The main engine is always the entry point
        
        # This will trigger the parent to process the child's status update
        await parent_engine.report_child_status(
            child_id=child_id,
            parent_id=parent_id,
            child_new_status=child_new_status,
            child_current_step_name=child_current_step_name,
            child_result=child_result
        )

    async def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any]):
        """
        Simulates registering a scheduled workflow.
        For SyncExecutor, this is a no-op but logs the registration.
        """
        print(f"[SyncExecutor] Registered scheduled workflow: {schedule_name} ({workflow_type}) for cron '{cron_expression}' with data {initial_data}")
        return {"_async_dispatch": True, "scheduled": True}
