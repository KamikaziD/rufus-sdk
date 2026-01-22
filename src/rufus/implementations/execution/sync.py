from typing import Any, List, Dict, Optional, Callable
from rufus.providers.execution import ExecutionProvider
import importlib # Needed for dynamic import of step functions

class SyncExecutor(ExecutionProvider):
    """A synchronous execution provider that executes tasks immediately."""

    def __init__(self, workflow_engine_instance=None):
        # We need a reference to the WorkflowEngine to load workflows from the persistence layer
        # This creates a circular dependency, so it must be handled carefully.
        # For SyncExecutor, we'll store a factory or the instance itself if available.
        self._workflow_engine_instance = workflow_engine_instance
        self._scheduled_workflows = {} # For register_scheduled_workflow

    def execute_sync_step_function(self, step_func: Callable, state: Any, context: Any) -> Any:
        """Executes a synchronous step function immediately."""
        return step_func(state, context)

    def dispatch_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str], **kwargs) -> str:
        """
        Executes an asynchronous task synchronously for testing/simple cases.
        Loads the function, prepares state, and calls it.
        """
        module_path, func_name = func_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        step_func = getattr(module, func_name)

        # Reconstruct state model from state_data
        # This requires the original state model class, which SyncExecutor doesn't inherently have.
        # For now, we'll pass state_data as a dict directly. A more robust solution
        # would involve passing the state_model_path and dynamically loading it,
        # or having the WorkflowEngine re-create the full state object.
        # For simplicity in SyncExecutor, we assume step_func can handle dict state.
        state_obj = state_data # Placeholder

        # Create a basic context. Full context requires more WorkflowEngine knowledge.
        context = {
            "workflow_id": workflow_id,
            "current_step_index": current_step_index,
            "data_region": data_region,
            "additional_args": kwargs
        }

        result = step_func(state_obj, context) # Execute directly

        # Simulate async dispatch completion by returning a result indicating it
        return {"_async_dispatch": True, "task_id": f"sync-async-task-{workflow_id}-{current_step_index}", "result": result}


    def dispatch_parallel_tasks(self, tasks: List[Any], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str], data_region: Optional[str]) -> str:
        """
        Executes parallel tasks synchronously for testing/simple cases.
        Loads each function, prepares state, and calls it. Merges results if a merge function is provided.
        """
        results = []
        for task_config in tasks:
            func_path = task_config.func_path
            module_path, func_name = func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            step_func = getattr(module, func_name)

            state_obj = state_data # Placeholder as above
            context = {
                "workflow_id": workflow_id,
                "current_step_index": current_step_index,
                "data_region": data_region,
                "task_name": task_config.name
            }
            results.append(step_func(state_obj, context))
        
        merged_result = {}
        if merge_function_path:
            module_path, func_name = merge_function_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            merge_func = getattr(module, func_name)
            merged_result = merge_func(state_data, results) # Assuming merge_func takes state and list of results
        else:
            # Default merge strategy: simply combine results if they are dicts
            for res in results:
                if isinstance(res, dict):
                    merged_result.update(res)

        return {"_async_dispatch": True, "group_id": f"sync-parallel-group-{workflow_id}-{current_step_index}", "result": merged_result}

    def get_task_status(self, task_id: str) -> str:
        """Returns 'COMPLETED' for any task ID, as execution is synchronous."""
        return "COMPLETED"

    def report_child_status_to_parent(self, child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str], child_result: Optional[Dict[str, Any]]):
        """
        For SyncExecutor, this is a no-op as parent/child workflows run in the same context.
        In a real async executor, this would trigger a task to update the parent.
        """
        print(f"[SyncExecutor] Child {child_id} reported status {child_new_status} to parent {parent_id}")
        # In a real system, you'd fetch the parent, update its state, and resume it.
        # For in-memory sync, we simulate it by calling a method on the parent if available.
        if self._workflow_engine_instance:
            parent_workflow = self._workflow_engine_instance.get_workflow(parent_id)
            if parent_workflow:
                # Assuming the parent workflow has a method to handle child completion
                parent_workflow._handle_child_completion(child_id, child_new_status, child_current_step_name, child_result)


    def dispatch_independent_workflow(self, workflow_id: str):
        """
        For SyncExecutor, this starts the independent workflow immediately.
        """
        print(f"[SyncExecutor] Dispatching independent workflow {workflow_id}")
        if self._workflow_engine_instance:
            workflow = self._workflow_engine_instance.get_workflow(workflow_id)
            if workflow:
                # Immediately execute the independent workflow
                workflow.next_step(user_input={})


    def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any]):
        """
        For SyncExecutor, this simply stores the scheduled workflow information.
        It does not actually schedule it for future execution.
        """
        print(f"[SyncExecutor] Registered scheduled workflow: {schedule_name} (Type: {workflow_type}, Cron: {cron_expression})")
        self._scheduled_workflows[schedule_name] = {
            "workflow_type": workflow_type,
            "cron_expression": cron_expression,
            "initial_data": initial_data
        }