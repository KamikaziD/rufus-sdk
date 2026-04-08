from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, List, Dict, Optional, Callable
import importlib

from ruvon.providers.execution import ExecutionProvider
from ruvon.providers.persistence import PersistenceProvider
from ruvon.workflow import Workflow # To reconstruct workflow objects
from ruvon.builder import WorkflowBuilder # To recreate workflow objects with injected providers
from ruvon.providers.expression_evaluator import ExpressionEvaluator
from ruvon.providers.template_engine import TemplateEngine
from ruvon.models import StepContext, MergeStrategy, MergeConflictBehavior # Import Merge Enums

import asyncio
import os

class ThreadPoolExecutorProvider(ExecutionProvider):
    """
    An execution provider that uses a ThreadPoolExecutor to run async tasks
    in a separate thread but within the same process.
    Suitable for development, testing, and simple deployments.
    """
    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._persistence_provider: Optional[PersistenceProvider] = None # Will be set by WorkflowEngine
        self._workflow_engine_instance: Optional[Any] = None # Reference to WorkflowEngine to allow full workflow resumption

    async def initialize(self, persistence_provider: PersistenceProvider, workflow_engine_instance: Any):
        self._persistence_provider = persistence_provider
        self._workflow_engine_instance = workflow_engine_instance
        print(f"ThreadPoolExecutorProvider initialized with {self._executor._max_workers} workers.")

    async def close(self):
        self._executor.shutdown(wait=True)
        print("ThreadPoolExecutorProvider shut down.")

    def _run_async_in_thread(self, coro):
        """Helper to run an async coroutine in a dedicated loop within the thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(coro)
        loop.close()
        return result

    def execute_sync_step_function(self, step_func: Callable, state: Any, context: Any) -> Any:
        """Executes a synchronous step function immediately."""
        return step_func(state, context)

    def dispatch_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str], merge_strategy: str, merge_conflict_behavior: str, **kwargs) -> str:
        """
        Dispatches an asynchronous task to the thread pool.
        The task will execute the function and then call back into the workflow engine
        to resume the workflow.
        """
        if self._persistence_provider is None or self._workflow_engine_instance is None:
            raise RuntimeError("ThreadPoolExecutorProvider not initialized. Call initialize() first.")

        # Submit the actual execution of the function to the thread pool
        future: Future = self._executor.submit(
            self._execute_and_resume_async_task,
            func_path, state_data, workflow_id, current_step_index, data_region, merge_strategy, merge_conflict_behavior, kwargs
        )
        # Return a dummy task ID, as there's no external task queue
        return f"thread-pool-task-{workflow_id}-{current_step_index}-{id(future)}"

    def _execute_and_resume_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str], merge_strategy: str, merge_conflict_behavior: str, func_kwargs: Dict[str, Any]):
        """
        Internal method run in a worker thread to execute the step function and resume the workflow.
        """
        async def _internal_task():
            # Reconstruct workflow object and providers within the thread's event loop
            persistence_provider = self._persistence_provider # Use the injected one
            workflow_engine = self._workflow_engine_instance

            # Load the workflow (this will use the configured persistence_provider)
            workflow_dict = await persistence_provider.load_workflow(workflow_id)
            if not workflow_dict:
                raise ValueError(f"Workflow {workflow_id} not found.")

            # Get necessary providers from the engine
            expression_evaluator_cls = workflow_engine.expression_evaluator_cls
            template_engine_cls = workflow_engine.template_engine_cls
            workflow_observer = workflow_engine.observer
            workflow_builder = workflow_engine.workflow_builder
            
            # Reconstruct the full Workflow object
            workflow = Workflow.from_dict(
                workflow_dict,
                persistence_provider=persistence_provider,
                execution_provider=self, # Self reference
                workflow_builder=workflow_builder,
                expression_evaluator_cls=expression_evaluator_cls,
                template_engine_cls=template_engine_cls,
                workflow_observer=workflow_observer
            )

            # Get the step function
            module_path, func_name = func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            step_func = getattr(module, func_name)

            # Reconstruct state object
            state_model_class = workflow_builder._import_from_string(workflow.state_model_path)
            state_obj = state_model_class(**state_data)

            # Create a basic context for the step function call
            context_obj = StepContext(
                workflow_id=workflow_id,
                step_name=func_name,
                validated_input=func_kwargs.get("user_input"),
                previous_step_result=func_kwargs.get("_previous_step_result")
            )
            
            # Execute the step function
            step_result = step_func(state_obj, context_obj)

            # Apply merge strategy and resume workflow
            await workflow._apply_merge_strategy(workflow.state, step_result, MergeStrategy(merge_strategy), MergeConflictBehavior(merge_conflict_behavior))
            
            # Advance the workflow to the next step
            workflow.current_step = current_step_index + 1

            # Set status back to ACTIVE if it was PENDING_ASYNC
            if workflow.status == "PENDING_ASYNC":
                workflow.status = "ACTIVE"
            
            await persistence_provider.save_workflow(workflow.id, workflow.to_dict())

            # Auto-advance if the step has automate_next set or if it's a child workflow
            if workflow.status == "ACTIVE" and workflow.current_step > 0:
                previous_step = workflow.workflow_steps[current_step_index] # Use original index for 'previous' step
                if previous_step.automate_next or workflow.parent_execution_id:
                    await workflow.next_step(user_input={}, _previous_step_result=step_result)
                    await persistence_provider.save_workflow(workflow.id, workflow.to_dict())

        # Run the async internal task in the thread's own event loop
        return self._run_async_in_thread(_internal_task())


    def dispatch_parallel_tasks(self, tasks: List[Any], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str], data_region: Optional[str], merge_strategy: str, merge_conflict_behavior: str, allow_partial_success: bool = False) -> str:
        """
        Dispatches multiple tasks for parallel execution to the thread pool.
        """
        if self._persistence_provider is None or self._workflow_engine_instance is None:
            raise RuntimeError("ThreadPoolExecutorProvider not initialized. Call initialize() first.")

        futures = []
        for task_item in tasks:
            # Each parallel task runs its function
            future = self._executor.submit(
                self._execute_parallel_sub_task,
                task_item.func_path, state_data, workflow_id, task_item.name
            )
            futures.append(future)
        
        # Submit a final task to merge results and resume the workflow
        # This can be handled by another thread pool submission or directly by the main thread
        master_future = self._executor.submit(
            self._merge_and_resume_parallel_tasks,
            futures, state_data, workflow_id, current_step_index, merge_function_path, merge_strategy, merge_conflict_behavior, allow_partial_success
        )
        return f"thread-pool-parallel-group-{workflow_id}-{current_step_index}-{id(master_future)}"

    def _execute_parallel_sub_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, task_name: str) -> Any:
        """Internal method to execute a single parallel sub-task function."""
        async def _internal_sub_task():
            workflow_engine = self._workflow_engine_instance
            workflow_builder = workflow_engine.workflow_builder # For state model loading

            module_path, func_name = func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            step_func = getattr(module, func_name)

            state_model_class = workflow_builder._import_from_string(state_data['_state_model_path']) # Assuming path is in data
            state_obj = state_model_class(**state_data)
            context_obj = StepContext(workflow_id=workflow_id, step_name=task_name)
            
            return step_func(state_obj, context_obj)
        
        return self._run_async_in_thread(_internal_sub_task())

    def _merge_and_resume_parallel_tasks(self, futures: List[Future], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str], merge_strategy: str, merge_conflict_behavior: str, allow_partial_success: bool = False):
        """Internal method to merge results from parallel tasks and resume workflow."""
        import logging
        _logger = logging.getLogger(__name__)

        async def _internal_merge_and_resume():
            results = []
            for f in futures:
                try:
                    results.append(f.result())
                except Exception as e:
                    if allow_partial_success:
                        _logger.warning(f"Parallel sub-task failed (allow_partial_success=True): {e}")
                    else:
                        raise

            merged_result = {}
            if merge_function_path:
                module_path, func_name = merge_function_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                merge_func = getattr(module, func_name)
                merged_result = merge_func(state_data, results)
            else:
                for res in results:
                    if isinstance(res, dict):
                        merged_result.update(res)

            # Now, load workflow and apply the merged result
            persistence_provider = self._persistence_provider
            workflow_engine = self._workflow_engine_instance

            workflow_dict = await persistence_provider.load_workflow(workflow_id)
            if not workflow_dict:
                raise ValueError(f"Workflow {workflow_id} not found for parallel resumption.")

            expression_evaluator_cls = workflow_engine.expression_evaluator_cls
            template_engine_cls = workflow_engine.template_engine_cls
            workflow_observer = workflow_engine.observer
            workflow_builder = workflow_engine.workflow_builder

            workflow = Workflow.from_dict(
                workflow_dict,
                persistence_provider=persistence_provider,
                execution_provider=self,
                workflow_builder=workflow_builder,
                expression_evaluator_cls=expression_evaluator_cls,
                template_engine_cls=template_engine_cls,
                workflow_observer=workflow_observer
            )
            
            await workflow._apply_merge_strategy(workflow.state, merged_result, MergeStrategy(merge_strategy), MergeConflictBehavior(merge_conflict_behavior))
            
            workflow.current_step = current_step_index + 1
            if workflow.status == "PENDING_ASYNC": # Parallel tasks would have set this
                workflow.status = "ACTIVE"
            
            await persistence_provider.save_workflow(workflow.id, workflow.to_dict())

            if workflow.status == "ACTIVE" and workflow.current_step > 0:
                previous_step = workflow.workflow_steps[current_step_index]
                if previous_step.automate_next or workflow.parent_execution_id:
                    await workflow.next_step(user_input={}, _previous_step_result=merged_result)
                    await persistence_provider.save_workflow(workflow.id, workflow.to_dict())
        
        self._run_async_in_thread(_internal_merge_and_resume())


    def report_child_status_to_parent(self, child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str], child_result: Optional[Dict[str, Any]]):
        """
        Reports child status directly if WorkflowEngine reference is available, otherwise prints.
        """
        if self._workflow_engine_instance:
            # In ThreadPoolExecutor, we can often directly interact with the parent
            # if the parent is in the same process and accessible.
            # This is a simplified direct call for now.
            async def _report():
                parent_workflow = await self._workflow_engine_instance.get_workflow(parent_id)
                if parent_workflow:
                    old_parent_status = parent_workflow.status
                    if child_new_status == "WAITING_HUMAN":
                        parent_workflow.status = "WAITING_CHILD_HUMAN_INPUT"
                    elif child_new_status == "FAILED":
                        parent_workflow.status = "FAILED_CHILD_WORKFLOW"
                    elif child_new_status == "COMPLETED" and parent_workflow.status == "PENDING_SUB_WORKFLOW":
                        parent_workflow.status = "ACTIVE"
                        parent_workflow.blocked_on_child_id = None # Clear block
                        parent_workflow.current_step += 1 # Advance parent after child completes

                    if not hasattr(parent_workflow.metadata, 'children_status'):
                        parent_workflow.metadata['children_status'] = {}
                    parent_workflow.metadata['children_status'][child_id] = {
                        'status': child_new_status,
                        'step_name': child_current_step_name,
                        'result': child_result
                    }
                    await self._persistence_provider.save_workflow(parent_workflow.id, parent_workflow.to_dict())
                    parent_workflow._notify_status_change(old_parent_status, parent_workflow.status, parent_workflow.current_step_name)

                    if parent_workflow.status == "ACTIVE" and old_parent_status == "PENDING_SUB_WORKFLOW":
                         await parent_workflow.next_step(user_input={}, _previous_step_result=child_result)
                         await self._persistence_provider.save_workflow(parent_workflow.id, parent_workflow.to_dict())

            self._executor.submit(self._run_async_in_thread, _report())
        else:
            print(f"[ThreadPoolExecutor] Child {child_id} reported status {child_new_status} to parent {parent_id}")

    def dispatch_independent_workflow(self, workflow_id: str):
        """
        Dispatches an independent workflow to be run in the thread pool.
        """
        if self._workflow_engine_instance:
            async def _run_independent():
                workflow = await self._workflow_engine_instance.get_workflow(workflow_id)
                if workflow:
                    max_iterations = 1000
                    iterations = 0
                    while workflow.status == "ACTIVE" and iterations < max_iterations:
                        iterations += 1
                        await workflow.next_step(user_input={})
                        await self._persistence_provider.save_workflow(workflow.id, workflow.to_dict())
                        if workflow.status != "ACTIVE":
                            break
            self._executor.submit(self._run_async_in_thread, _run_independent())
        else:
            print(f"[ThreadPoolExecutor] Dispatching independent workflow {workflow_id} (no engine to run it).")


    def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any]):
        """
        For ThreadPoolExecutor, this just prints a message, as it doesn't have a scheduler.
        """
        print(f"[ThreadPoolExecutor] Registering scheduled workflow: {schedule_name} (Type: {workflow_type}, Cron: {cron_expression}). "
              "Note: ThreadPoolExecutor does not actively schedule workflows.")