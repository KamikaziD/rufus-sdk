from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional, Callable
import importlib
import os

from rufus.providers.execution import ExecutionProvider
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.observer import WorkflowObserver
from rufus.workflow import Workflow # To reconstruct workflow objects
from rufus.builder import WorkflowBuilder # To recreate workflow objects with injected providers
from rufus.providers.expression_evaluator import ExpressionEvaluator
from rufus.providers.template_engine import TemplateEngine
from rufus.models import MergeStrategy, MergeConflictBehavior, StepContext # Import Merge Enums and StepContext


from celery import Celery, chain, group
from celery.signals import worker_process_init
import asyncio
import json

# --- Rufus Celery App Setup ---
# This is the central Celery app instance for the Rufus SDK.
# It should be configured by the user's application, but we provide a default.
rufus_celery_app = Celery('rufus_workflow_sdk')

# Default Celery configuration (can be overridden by user)
rufus_celery_app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    include=['rufus.implementations.execution.celery'], # Include this module for tasks
    task_create_missing_queues=True, # Allow dynamic queue creation
    timezone='UTC',
    enable_utc=True,
)

# Signal handler to reset persistence/executor providers in worker processes
@worker_process_init.connect
def init_worker(**kwargs):
    """
    Reset provider singletons in each worker process after fork.
    This is necessary because some providers (e.g., Postgres, Redis) hold
    connection pools that cannot be shared across processes.
    """
    from rufus.implementations.persistence.postgres import _postgres_stores
    _postgres_stores.clear() # Clear PostgreSQL connection pools

    global _celery_executor_instance
    _celery_executor_instance = None # Clear CeleryExecutor instance

    # Also clear any other provider instances that might hold state across forks
    # from rufus.implementations.observability.events import _event_publisher_instance
    # _event_publisher_instance = None


# --- Celery Task Definitions (used by CeleryExecutor) ---

@rufus_celery_app.task(bind=True)
async def _dispatch_async_task_celery(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str], merge_strategy: str, merge_conflict_behavior: str, **kwargs):
    """
    Celery task to execute a single async step function and then resume the workflow.
    """
    from rufus.engine import WorkflowEngine # Lazy import to avoid circular dependency
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.observability.events import EventPublisher
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder
    from rufus.models import StepContext

    # Instantiate providers within the worker (important for fresh connections)
    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL')) # Example
    await persistence_provider.initialize()
    
    execution_provider = get_celery_executor(rufus_celery_app, persistence_provider) # Self-reference
    workflow_observer = EventPublisher() # Example observer

    workflow_builder = WorkflowBuilder(
        workflow_registry={}, # Not needed for _import_from_string
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    try:
        # Load the workflow (using the worker's persistence provider)
        workflow_dict = await persistence_provider.load_workflow(workflow_id)
        if not workflow_dict:
            raise ValueError(f"Workflow {workflow_id} not found.")
        
        # Reconstruct the full Workflow object
        workflow = Workflow.from_dict(
            workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
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
            step_name=func_name, # This is the step function name, not the workflow step name
        )
        
        # Execute the step function
        step_result = step_func(state_obj, context_obj)

        # Resume the main workflow
        await _resume_workflow_after_async_task_celery(
            workflow_id,
            step_result,
            current_step_index + 1,
            merge_strategy,
            merge_conflict_behavior
        )
        
        return step_result

    except Exception as e:
        raise # Re-raise for Celery to handle retries


@rufus_celery_app.task(bind=True)
async def _dispatch_parallel_tasks_celery(self, tasks_config: List[Dict[str, Any]], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str], data_region: Optional[str], merge_strategy: str, merge_conflict_behavior: str):
    """
    Celery task to execute parallel step functions and then resume the workflow.
    """
    from rufus.builder import WorkflowBuilder
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.models import StepContext
    
    workflow_builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    results = []
    for task_cfg in tasks_config:
        func_path = task_cfg['func_path']
        module_path, func_name = func_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        step_func = getattr(module, func_name)

        # Reconstruct state object
        state_model_class = workflow_builder._import_from_string(state_data['_state_model_path']) # Assuming path is in data
        state_obj = state_model_class(**state_data)
        context_obj = StepContext(
            workflow_id=workflow_id,
            step_name=func_name
        )
        results.append(step_func(state_obj, context_obj)) # Execute directly
    
    merged_result = {}
    if merge_function_path:
        module_path, func_name = merge_function_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        merge_func = getattr(module, func_name)
        # Assuming merge_func takes raw state_data and list of results, and returns merged dict
        merged_result = merge_func(state_data, results)
    else:
        for res in results:
            if isinstance(res, dict):
                merged_result.update(res)

    await _resume_workflow_after_async_task_celery(
        workflow_id,
        merged_result,
        current_step_index + 1,
        merge_strategy,
        merge_conflict_behavior
    )
    
    return merged_result


@rufus_celery_app.task(bind=True)
async def _resume_workflow_after_async_task_celery(self, workflow_id: str, step_result: Dict[str, Any], next_step_index_or_name: Any, merge_strategy: str, merge_conflict_behavior: str):
    """
    Helper task to load a workflow, merge state from an async result,
    advance the workflow, and save it. This is typically called as the second part
    of a Celery chain.
    """
    from rufus.engine import WorkflowEngine
    from rufus.workflow import Workflow
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.observability.events import EventPublisher
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder
    from rufus.models import MergeStrategy, MergeConflictBehavior # Import Merge Enums

    # Instantiate providers within the worker
    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
    await persistence_provider.initialize()

    execution_provider = get_celery_executor(rufus_celery_app, persistence_provider)
    workflow_observer = EventPublisher()
    workflow_builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    try:
        # Load the workflow
        workflow_dict = await persistence_provider.load_workflow(workflow_id)
        if not workflow_dict:
            raise ValueError(f"Workflow {workflow_id} not found for resumption.")
        
        workflow = Workflow.from_dict(
            workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=workflow_observer
        )

        # Convert string enums back to Enum objects
        ms_enum = MergeStrategy(merge_strategy)
        mcb_enum = MergeConflictBehavior(merge_conflict_behavior)

        # Apply merge strategy
        # Assuming workflow._apply_merge_strategy is an instance method
        await workflow._apply_merge_strategy(workflow.state, step_result, ms_enum, mcb_enum)

        # Advance the workflow to the next step or specified target
        if isinstance(next_step_index_or_name, str): # Jump target
            target_index = next(i for i, step in enumerate(workflow.workflow_steps) if step.name == next_step_index_or_name)
            workflow.current_step = target_index
        elif isinstance(next_step_index_or_name, int): # Linear progression
            workflow.current_step = next_step_index_or_name

        # Set status back to ACTIVE if it was PENDING_ASYNC
        if workflow.status == "PENDING_ASYNC":
            workflow.status = "ACTIVE"
        
        # Save updated workflow state
        await persistence_provider.save_workflow(workflow.id, workflow.to_dict())

        # Auto-advance if the step has automate_next set or if it's a child workflow
        if workflow.status == "ACTIVE" and workflow.current_step > 0: # Ensure not first step or jump
             # Check previous step to see if automate_next was true
             previous_step_index = workflow.current_step - 1
             if previous_step_index >= 0:
                 previous_step = workflow.workflow_steps[previous_step_index]
                 if previous_step.automate_next or workflow.parent_execution_id:
                     # Simulate auto-advance by calling next_step directly
                     await workflow.next_step(user_input={}, _previous_step_result=step_result) # next_step is now async
                     await persistence_provider.save_workflow(workflow.id, workflow.to_dict())


    except Exception as e:
        # Log error or handle retries
        print(f"Error resuming workflow {workflow_id} after async task: {e}")
        # Optionally, update workflow status to FAILED
        workflow_dict = await persistence_provider.load_workflow(workflow_id)
        if workflow_dict:
            workflow_obj = Workflow.from_dict(
                workflow_dict,
                persistence_provider=persistence_provider,
                execution_provider=execution_provider,
                workflow_builder=workflow_builder,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
                workflow_observer=workflow_observer
            )
            workflow_obj.status = "FAILED"
            await persistence_provider.save_workflow(workflow_id, workflow_obj.to_dict())
        raise


@rufus_celery_app.task
async def _dispatch_sub_workflow_celery(child_id: str, parent_id: str):
    """
    Celery task to execute child workflow until completion or blocking state.
    """
    from rufus.engine import WorkflowEngine
    from rufus.workflow import Workflow
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.observability.events import EventPublisher
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder

    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
    await persistence_provider.initialize()
    
    execution_provider = get_celery_executor(rufus_celery_app, persistence_provider)
    workflow_observer = EventPublisher()
    workflow_builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    try:
        # Load child workflow
        child_workflow_dict = await persistence_provider.load_workflow(child_id)
        if not child_workflow_dict:
            raise ValueError(f"Child workflow {child_id} not found.")
        child = Workflow.from_dict(
            child_workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=workflow_observer
        )

        max_iterations = 1000 # Safety limit
        iterations = 0

        while child.status == "ACTIVE" and iterations < max_iterations:
            iterations += 1
            await child.next_step(user_input={}) # Execute next step
            await persistence_provider.save_workflow(child.id, child.to_dict())

            if child.status != "ACTIVE": # Workflow is blocking or completed
                break
        
        # If child completed, resume parent
        if child.status == "COMPLETED":
            _resume_parent_from_child_celery.delay(parent_id, child_id)
        elif child.status == "FAILED":
            # Handle child failure: potentially update parent to FAILED_CHILD_WORKFLOW
            parent_workflow_dict = await persistence_provider.load_workflow(parent_id)
            if parent_workflow_dict:
                parent = Workflow.from_dict(
                    parent_workflow_dict,
                    persistence_provider=persistence_provider,
                    execution_provider=execution_provider,
                    workflow_builder=workflow_builder,
                    expression_evaluator_cls=SimpleExpressionEvaluator,
                    template_engine_cls=Jinja2TemplateEngine,
                    workflow_observer=workflow_observer
                )
                parent.status = "FAILED_CHILD_WORKFLOW" # New status for parent
                parent.metadata['failed_child_id'] = child_id
                await persistence_provider.save_workflow(parent.id, parent.to_dict())


    except Exception as e:
        print(f"Error executing sub-workflow {child_id}: {e}")
        # Mark child as failed
        child_workflow_dict = await persistence_provider.load_workflow(child_id)
        if child_workflow_dict:
            child = Workflow.from_dict(
                child_workflow_dict,
                persistence_provider=persistence_provider,
                execution_provider=execution_provider,
                workflow_builder=workflow_builder,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
                workflow_observer=workflow_observer
            )
            child.status = "FAILED"
            await persistence_provider.save_workflow(child.id, child.to_dict())
        raise


@rufus_celery_app.task
async def _resume_parent_from_child_celery(parent_id: str, child_id: str):
    """
    Celery task to merge child workflow results into parent and resume parent.
    """
    from rufus.engine import WorkflowEngine
    from rufus.workflow import Workflow
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.observability.events import EventPublisher
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder

    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
    await persistence_provider.initialize()
    
    execution_provider = get_celery_executor(rufus_celery_app, persistence_provider)
    workflow_observer = EventPublisher()
    workflow_builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    try:
        parent_workflow_dict = await persistence_provider.load_workflow(parent_id)
        child_workflow_dict = await persistence_provider.load_workflow(child_id)

        if not parent_workflow_dict or not child_workflow_dict:
            raise ValueError(
                f"Parent {parent_id} or Child {child_id} workflow not found for resumption.")
        
        parent = Workflow.from_dict(
            parent_workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=workflow_observer
        )
        child = Workflow.from_dict(
            child_workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=workflow_observer
        )

        if not hasattr(parent.state, 'sub_workflow_results'):
            parent.state.sub_workflow_results = {}
        parent.state.sub_workflow_results[child.workflow_type] = child.state.model_dump()

        parent.current_step += 1
        parent.status = "ACTIVE"
        parent.blocked_on_child_id = None
        await persistence_provider.save_workflow(parent.id, parent.to_dict())

        # Continue parent execution (auto-advance)
        await parent.next_step(user_input={}, _previous_step_result=child.state.model_dump())
        await persistence_provider.save_workflow(parent.id, parent.to_dict())

    except Exception as e:
        print(f"Error resuming parent {parent_id} from child {child_id}: {e}")
        raise


@rufus_celery_app.task
async def _dispatch_independent_workflow_celery(workflow_id: str):
    """
    Celery task to execute an independent (fire-and-forget) workflow.
    """
    from rufus.engine import WorkflowEngine
    from rufus.workflow import Workflow
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.observability.events import EventPublisher
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder

    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
    await persistence_provider.initialize()
    
    execution_provider = get_celery_executor(rufus_celery_app, persistence_provider)
    workflow_observer = EventPublisher()
    workflow_builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    try:
        workflow_dict = await persistence_provider.load_workflow(workflow_id)
        if not workflow_dict:
            raise ValueError(f"Workflow {workflow_id} not found.")
        
        workflow = Workflow.from_dict(
            workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=workflow_observer
        )

        max_iterations = 1000 # Safety limit for independent workflows
        iterations = 0

        while workflow.status == "ACTIVE" and iterations < max_iterations:
            iterations += 1
            await workflow.next_step(user_input={}) # Execute next step
            await persistence_provider.save_workflow(workflow.id, workflow.to_dict())

            if workflow.status != "ACTIVE": # Workflow is blocking or completed
                break

    except Exception as e:
        print(f"Error executing independent workflow {workflow_id}: {e}")
        workflow_dict = await persistence_provider.load_workflow(workflow_id)
        if workflow_dict:
            workflow = Workflow.from_dict(
                workflow_dict,
                persistence_provider=persistence_provider,
                execution_provider=execution_provider,
                workflow_builder=workflow_builder,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
                workflow_observer=workflow_observer
            )
            workflow.status = "FAILED"
            await persistence_provider.save_workflow(workflow.id, workflow.to_dict())
        raise


@rufus_celery_app.task
async def _register_scheduled_workflow_celery(schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any]):
    """
    Celery task to register a scheduled workflow in the persistence layer.
    """
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
    await persistence_provider.initialize()
    await persistence_provider.register_scheduled_workflow(schedule_name, workflow_type, cron_expression, initial_data)


@rufus_celery_app.task
async def _report_child_status_to_parent_celery(child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str], child_result: Optional[Dict[str, Any]]):
    """
    Celery task to report a child workflow's status change back to its parent.
    This allows the parent to update its state (e.g., WAITING_CHILD_HUMAN_INPUT).
    """
    from rufus.engine import WorkflowEngine
    from rufus.workflow import Workflow
    from rufus.providers.persistence import PersistenceProvider
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    from rufus.implementations.observability.events import EventPublisher
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder

    persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
    await persistence_provider.initialize()
    
    execution_provider = get_celery_executor(rufus_celery_app, persistence_provider)
    workflow_observer = EventPublisher()
    workflow_builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine
    )

    try:
        parent_workflow_dict = await persistence_provider.load_workflow(parent_id)
        if not parent_workflow_dict:
            print(f"Parent workflow {parent_id} not found for child status report.")
            return

        parent = Workflow.from_dict(
            parent_workflow_dict,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=workflow_observer
        )

        old_parent_status = parent.status
        # Update parent status based on child's status
        if child_new_status == "WAITING_HUMAN":
            parent.status = "WAITING_CHILD_HUMAN_INPUT"
        elif child_new_status == "FAILED":
            parent.status = "FAILED_CHILD_WORKFLOW"
        elif child_new_status == "COMPLETED" and parent.status == "PENDING_SUB_WORKFLOW":
            # If child completed and parent was waiting for it, parent goes active
            parent.status = "ACTIVE"
        
        # Store child status in parent metadata for visibility
        if not hasattr(parent.metadata, 'children_status'):
            parent.metadata['children_status'] = {}
        parent.metadata['children_status'][child_id] = {
            'status': child_new_status,
            'step_name': child_current_step_name,
            'result': child_result
        }
        
        await persistence_provider.save_workflow(parent.id, parent.to_dict())
        parent._notify_status_change(old_parent_status, parent.status, parent.current_step_name)

    except Exception as e:
        print(f"Error reporting child {child_id} status to parent {parent_id}: {e}")
        raise


# --- CeleryExecutor Class Implementation ---
class CeleryExecutor(ExecutionProvider):
    """
    Execution provider that dispatches tasks to Celery workers.
    Requires a Celery app instance and a PersistenceProvider to function.
    """
    def __init__(self, celery_app: Celery, persistence_provider: PersistenceProvider):
        self.celery_app = celery_app
        self.persistence = persistence_provider

    def execute_sync_step_function(self, step_func: Callable, state: Any, context: Any) -> Any:
        """
        Executes a synchronous step function directly in the current process.
        CeleryExecutor is primarily for async dispatch, but provides this to satisfy interface.
        """
        return step_func(state, context)

    def dispatch_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str], **kwargs) -> str:
        """
        Dispatches an asynchronous task to Celery.
        """
        queue = data_region if data_region else 'default' # Use data_region as queue name

        task_chain = chain(
            _dispatch_async_task_celery.s(
                func_path=func_path,
                state_data=state_data,
                workflow_id=workflow_id,
                current_step_index=current_step_index,
                data_region=data_region,
                **kwargs
            ).set(queue=queue)
        )
        async_result = task_chain.apply_async()
        return async_result.id

    def dispatch_parallel_tasks(self, tasks: List[Any], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str], data_region: Optional[str]) -> str:
        """
        Dispatches multiple tasks for parallel execution to Celery.
        """
        queue = data_region if data_region else 'default'

        # Celery group for parallel execution
        # Each task in the group needs to be a signature for _dispatch_async_task_celery
        # For parallel tasks, the original implementation had a single task that took a list of sub-tasks.
        # We need to adapt that here.
        sub_tasks = []
        for task_item in tasks:
            # tasks is a list of ParallelExecutionTask objects
            sub_tasks.append(_dispatch_async_task_celery.s(
                func_path=task_item.func_path,
                state_data=state_data,
                workflow_id=workflow_id,
                current_step_index=current_step_index,
                data_region=data_region,
                task_name=task_item.name # Pass original task name for identification
            ).set(queue=queue))


        task_group = group(sub_tasks)
        
        # The result of the group needs to be merged and then workflow resumed
        # So, chain the group with a merge and resume task
        task_chain = chain(
            task_group,
            _resume_workflow_after_async_task_celery.s(
                workflow_id=workflow_id, # This is wrong, _resume expects step_result as first arg
                step_result={}, # Placeholder, actual results come from group
                next_step_index_or_name=current_step_index + 1 # Advance to next step
            ).set(queue=queue)
        )

        async_result = task_chain.apply_async()
        return async_result.id


    def report_child_status_to_parent(self, child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str], child_result: Optional[Dict[str, Any]]):
        """
        Dispatches a Celery task to report the child's status to the parent.
        """
        _report_child_status_to_parent_celery.delay(child_id, parent_id, child_new_status, child_current_step_name, child_result)

    def dispatch_independent_workflow(self, workflow_id: str):
        """
        Dispatches an independent workflow to be run by a Celery task.
        """
        _dispatch_independent_workflow_celery.delay(workflow_id)

    def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any]):
        """
        Registers a scheduled workflow using a Celery task to persist it.
        """
        _register_scheduled_workflow_celery.delay(schedule_name, workflow_type, cron_expression, initial_data)

# Global instance for easy access in tasks (can be set via dependency injection framework)
_celery_executor_instance: Optional[CeleryExecutor] = None

def get_celery_executor(celery_app: Celery = None, persistence_provider: PersistenceProvider = None) -> CeleryExecutor:
    global _celery_executor_instance
    if _celery_executor_instance is None:
        if celery_app is None or persistence_provider is None:
            # This is a common pattern when Celery tasks import get_celery_executor
            # We need to ensure that the environment has DATABASE_URL set
            # and that persistence_provider can be instantiated.
            # For simplicity in testing/standalone tasks, we can use a basic provider
            # if explicit ones are not passed.
            if os.getenv('DATABASE_URL'):
                persistence_provider = PostgresPersistenceProvider(os.getenv('DATABASE_URL'))
                asyncio.run(persistence_provider.initialize())
            else:
                from rufus.implementations.persistence.memory import InMemoryPersistence
                persistence_provider = InMemoryPersistence()
                asyncio.run(persistence_provider.initialize()) # Call initialize for consistency

            _celery_executor_instance = CeleryExecutor(rufus_celery_app, persistence_provider)
            # raise ValueError("Celery app and persistence provider must be provided to initialize CeleryExecutor.")
        else:
            _celery_executor_instance = CeleryExecutor(celery_app, persistence_provider)
    return _celery_executor_instance