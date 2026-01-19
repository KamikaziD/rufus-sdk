from pydantic import BaseModel, ValidationError
from typing import Dict, Any, Optional, List, Callable, Type
import uuid
import importlib
import os
from .expression_evaluator import SimpleExpressionEvaluator
from .models import StepContext


class WorkflowStep:
    def __init__(self, name: str, func: Callable, required_input: List[str] = None, input_schema: Optional[Type[BaseModel]] = None, automate_next: bool = False, routes: List[Dict[str, str]] = None):
        self.name = name
        self.func = func
        self.required_input = required_input or []
        self.input_schema = input_schema
        self.automate_next = automate_next
        self.routes = routes or []

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.__class__.__name__,
            "required_input": self.required_input,
            "automate_next": self.automate_next,
            "routes": self.routes
        }


class CompensatableStep(WorkflowStep):
    """Extended WorkflowStep with saga compensation logic"""

    def __init__(
        self,
        name: str,
        func: Callable,
        compensate_func: Optional[Callable] = None,
        required_input: List[str] = None,
        input_schema: Optional[Type[BaseModel]] = None,
        automate_next: bool = False,
        routes: List[Dict[str, str]] = None
    ):
        super().__init__(name, func, required_input, input_schema, automate_next, routes)
        self.compensate_func = compensate_func
        self.compensation_executed = False

    def compensate(self, state: BaseModel, context: StepContext) -> Dict[str, Any]:
        """Execute compensation if available"""
        if not self.compensate_func:
            return {"message": f"No compensation defined for {self.name}"}

        if self.compensation_executed:
            return {"message": f"Compensation already executed for {self.name}"}

        try:
            result = self.compensate_func(state=state, context=context)
            self.compensation_executed = True
            return result if isinstance(result, dict) else {"compensated": True}
        except Exception as e:
            return {"error": f"Compensation failed: {str(e)}"}

    def to_dict(self):
        data = super().to_dict()
        data["has_compensation"] = self.compensate_func is not None
        return data

class WorkflowJumpDirective(Exception):
    def __init__(self, target_step_name: str):
        self.target_step_name = target_step_name
        super().__init__(f"Jumping to step: {target_step_name}")

class WorkflowNextStepDirective:
    def __init__(self, next_step_name: str):
        self.next_step_name = next_step_name

class WorkflowPauseDirective(Exception):
    def __init__(self, result: Dict[str, Any]):
        self.result = result
        super().__init__("Workflow paused for external input")


class SagaWorkflowException(Exception):
    """Raised when a saga workflow fails and needs rollback"""
    def __init__(self, failed_step: str, original_error: Exception):
        self.failed_step = failed_step
        self.original_error = original_error
        super().__init__(f"Saga failed at {failed_step}: {original_error}")


class StartSubWorkflowDirective(Exception):
    """Raised to pause parent workflow and start a child workflow"""
    def __init__(self, workflow_type: str, initial_data: Dict[str, Any], data_region: str = None):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.data_region = data_region
        super().__init__(f"Starting sub-workflow: {workflow_type}")

class AsyncWorkflowStep(WorkflowStep):
    def __init__(self, name: str, func_path: str, required_input: List[str] = None, input_schema: Optional[Type[BaseModel]] = None, automate_next: bool = False):
        # For async steps, 'func' is the path, not the callable.
        super().__init__(name, None, required_input, input_schema, automate_next=automate_next)
        self.func_path = func_path

    def dispatch_async_task(self, state: BaseModel, workflow_id: str, current_step_index: int, **kwargs):
        from .tasks import resume_from_async_task
        from celery import chain
        from .persistence import create_task_record

        # Dynamically import the task
        module_path, func_name = self.func_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        task_func = getattr(module, func_name)
        
        # Async tasks receive the full state and validated kwargs.
        task_payload = state.model_dump()
        task_payload.update(kwargs)

        # Regional Routing
        data_region = kwargs.get('data_region')
        queue = data_region if data_region else 'celery'

        # Create task record and get idempotency key
        task_record = create_task_record(
            execution_id=workflow_id,
            step_name=self.name,
            step_index=current_step_index,
            task_data=task_payload
        )
        idempotency_key = task_record.get("idempotency_key")


        task_chain = chain(
            task_func.s(task_payload).set(queue=queue),
            resume_from_async_task.s(
                workflow_id=workflow_id, 
                current_step_index=current_step_index
            ).set(queue=queue) # Resume task must also run in correct region to be safe? Or default?
            # Ideally resume runs where persistence is available. Assuming all regions can reach DB.
        )
        
        async_result = task_chain.apply_async()

        if hasattr(state, 'async_task_id'):
            state.async_task_id = async_result.id

        return {"_async_dispatch": True, "message": f"Async task {func_name} dispatched to {queue}.", "task_id": async_result.id, "idempotency_key": idempotency_key}

class HttpWorkflowStep(AsyncWorkflowStep):
    def __init__(self, name: str, http_config: Dict[str, Any], required_input: List[str] = None, input_schema: Optional[Type[BaseModel]] = None, automate_next: bool = False):
        super().__init__(
            name=name,
            func_path="confucius.tasks.execute_http_request",
            required_input=required_input,
            input_schema=input_schema,
            automate_next=automate_next
        )
        self.http_config = http_config

    def dispatch_async_task(self, state: BaseModel, workflow_id: str, current_step_index: int, **kwargs):
        # Merge http_config into kwargs so they are available in the task payload
        kwargs.update(self.http_config)
        return super().dispatch_async_task(state, workflow_id, current_step_index, **kwargs)

    def to_dict(self):
        data = super().to_dict()
        data["http_config"] = self.http_config
        return data

class FireAndForgetWorkflowStep(WorkflowStep):
    """Spawns an independent workflow that doesn't block the parent."""
    def __init__(self, name: str, target_workflow_type: str, initial_data_template: Dict[str, Any] = None, automate_next: bool = False):
        super().__init__(name=name, func=self._spawn_workflow, automate_next=automate_next)
        self.target_workflow_type = target_workflow_type
        self.initial_data_template = initial_data_template or {}

    def _spawn_workflow(self, state: BaseModel, context: StepContext):
        from .tasks import execute_independent_workflow
        from .workflow_loader import workflow_builder
        from .persistence import save_workflow_state
        from .templating import render_template
        import json

        # Context for templating is the state dict
        template_context = state.model_dump()
        
        # Render initial data using the new template engine
        initial_data = render_template(self.initial_data_template, template_context)

        # Create child workflow
        child_workflow = workflow_builder.create_workflow(
            workflow_type=self.target_workflow_type,
            initial_data=initial_data
        )

        # Inherit data region from parent
        child_workflow.data_region = self.data_region

        # Set metadata for tracking
        child_workflow.metadata["spawned_by"] = context.workflow_id
        child_workflow.metadata["spawn_reason"] = self.name

        # Save child workflow
        save_workflow_state(child_workflow.id, child_workflow, sync=True)

        # Dispatch child to Celery for independent execution
        queue = child_workflow.data_region if child_workflow.data_region else 'celery'
        execute_independent_workflow.apply_async(args=[child_workflow.id], queue=queue)

        from datetime import datetime

        # Record reference in parent state if 'spawned_workflows' field exists
        spawn_record = {
            "workflow_id": child_workflow.id,
            "workflow_type": self.target_workflow_type,
            "status": child_workflow.status,
            "spawned_at": child_workflow.metadata.get("created_at") or datetime.now().isoformat()
        }

        if hasattr(state, "spawned_workflows"):
            if state.spawned_workflows is None:
                state.spawned_workflows = []
            state.spawned_workflows.append(spawn_record)

        return {
            "spawned_workflow_id": child_workflow.id,
            "message": f"Independent workflow {self.target_workflow_type} spawned in {queue}."
        }

    def to_dict(self):
        data = super().to_dict()
        data["target_workflow_type"] = self.target_workflow_type
        data["initial_data_template"] = self.initial_data_template
        return data

class LoopStep(WorkflowStep):
    """
    Executes a body of steps repeatedly based on a condition or a list.
    """
    def __init__(
        self,
        name: str,
        loop_body: List[WorkflowStep],
        mode: str = "ITERATE", # ITERATE, WHILE, INFINITE
        iterate_over: Optional[str] = None,
        item_var_name: str = "item",
        while_condition: Optional[str] = None,
        max_iterations: int = 1000,
        automate_next: bool = False
    ):
        super().__init__(name=name, func=self._execute_loop, automate_next=automate_next)
        self.loop_body = loop_body
        self.mode = mode
        self.iterate_over = iterate_over
        self.item_var_name = item_var_name
        self.while_condition = while_condition
        self.max_iterations = max_iterations

    def _execute_loop(self, state: BaseModel, context: StepContext):
        state_dict = state.model_dump()
        evaluator = SimpleExpressionEvaluator(state_dict)

        iterations = 0
        
        if self.mode == "ITERATE" and self.iterate_over:
            items = self._get_value_by_path(state_dict, self.iterate_over)
            if not isinstance(items, list):
                return {"error": f"Value at {self.iterate_over} is not a list"}
            
            for item in items:
                if iterations >= self.max_iterations:
                    break
                
                # Set item in state for access within the loop body
                if hasattr(state, self.item_var_name):
                    setattr(state, self.item_var_name, item)
                
                # Execute loop body
                for step in self.loop_body:
                    if isinstance(step, (AsyncWorkflowStep, ParallelWorkflowStep)):
                        print(f"Warning: Step {step.name} of type {type(step).__name__} is not supported in synchronous loops and will be skipped.")
                        continue
                    
                    # Create a new context for the inner step with loop variables
                    loop_context = context.model_copy(deep=True)
                    loop_context.loop_item = item
                    loop_context.loop_index = iterations

                    # Execute and merge results
                    result = step.func(state=state, context=loop_context)
                    if isinstance(result, dict):
                        for key, value in result.items():
                            if hasattr(state, key) and not key.startswith('_'):
                                setattr(state, key, value)
                
                iterations += 1

        elif self.mode == "WHILE" and self.while_condition:
            while evaluator.evaluate(self.while_condition) and iterations < self.max_iterations:
                for step in self.loop_body:
                    result = step.func(state=state, context=context) # No special context for 'while'
                    if isinstance(result, dict):
                        for key, value in result.items():
                            if hasattr(state, key) and not key.startswith('_'):
                                setattr(state, key, value)
                iterations += 1
                evaluator.state = state.model_dump()

        return {"iterations": iterations, "message": f"Loop {self.name} completed."}

    def _get_value_by_path(self, data, path):
        if path.startswith("state."):
            path = path[6:]
            
        parts = path.split('.')
        curr = data
        for p in parts:
            if isinstance(curr, dict):
                curr = curr.get(p)
            else:
                curr = getattr(curr, p, None)
        return curr

    def to_dict(self):
        data = super().to_dict()
        data["mode"] = self.mode
        data["loop_body"] = [s.to_dict() for s in self.loop_body]
        return data

class CronScheduleWorkflowStep(WorkflowStep):
    """
    Schedules a new recurring workflow.
    """
    def __init__(
        self,
        name: str,
        target_workflow_type: str,
        cron_expression: str,
        initial_data_template: Dict[str, Any] = None,
        schedule_name: str = None,
        automate_next: bool = False
    ):
        super().__init__(name=name, func=self._register_schedule, automate_next=automate_next)
        self.target_workflow_type = target_workflow_type
        self.cron_expression = cron_expression
        self.initial_data_template = initial_data_template or {}
        self.schedule_name = schedule_name

    def _register_schedule(self, state: BaseModel, context: StepContext):
        from .persistence import get_workflow_store
        from .templating import render_template
        import json

        store = get_workflow_store()
        
        # Prepare context for templating
        template_context = state.model_dump()
        template_context['workflow_id'] = context.workflow_id
        
        # Render initial data
        initial_data = render_template(self.initial_data_template, template_context)

        # Render schedule name
        raw_sched_name = self.schedule_name or f"sched_{self.target_workflow_type}_{{workflow_id}}"
        sched_name = render_template(raw_sched_name, template_context)

        if hasattr(store, 'register_scheduled_workflow_sync'):
            store.register_scheduled_workflow_sync(
                schedule_name=sched_name,
                workflow_type=self.target_workflow_type,
                cron_expression=self.cron_expression,
                initial_data=initial_data
            )
            return {"message": f"Workflow {self.target_workflow_type} scheduled as {sched_name}", "schedule_name": sched_name}
        else:
            print("Warning: Store does not support register_scheduled_workflow_sync")
            return {"error": "Store does not support dynamic scheduling"}

    def to_dict(self):
        data = super().to_dict()
        data["target_workflow_type"] = self.target_workflow_type
        data["cron_expression"] = self.cron_expression
        return data

class ParallelExecutionTask:
    def __init__(self, name: str, func_path: str):
        self.name = name
        self.func_path = func_path

    def to_dict(self):
        return {"name": self.name, "func_path": self.func_path}


class ParallelWorkflowStep(WorkflowStep):
    def __init__(self, name: str, tasks: List[ParallelExecutionTask], merge_function_path: str = None, automate_next: bool = False):
        super().__init__(name=name, func=self.dispatch_parallel_tasks, automate_next=automate_next)
        self.tasks = tasks
        self.merge_function_path = merge_function_path

    def dispatch_parallel_tasks(self, state: BaseModel, workflow_id: str, current_step_index: int, data_region: str = None):
        from .tasks import merge_and_resume_parallel_tasks
        from celery import group, chain
        
        TESTING = os.environ.get("TESTING", "False").lower() == "true"
        queue = data_region if data_region else 'celery'

        celery_tasks = []
        for task_def in self.tasks:
            module_path, func_name = task_def.func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            task_func = getattr(module, func_name)
            celery_tasks.append(task_func.s(state.model_dump()).set(queue=queue))

        task_group = group(celery_tasks)
        
        if TESTING:
            result_group = task_group.apply()
            results = result_group.get()
            
            if self.merge_function_path:
                module_path, func_name = self.merge_function_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                merge_function = getattr(module, func_name)
                merged_results = merge_function(results)
            else:
                merged_results = {}
                for res in results:
                    if isinstance(res, dict):
                        merged_results.update(res)

            return {"_sync_parallel_result": merged_results}
        else:
            callback = merge_and_resume_parallel_tasks.s(
                workflow_id=workflow_id, 
                current_step_index=current_step_index,
                merge_function_path=self.merge_function_path
            ).set(queue=queue)
            
            chain(task_group, callback).apply_async()

            return {"_async_dispatch": True, "message": f"Parallel tasks dispatched to {queue}."}


class Workflow:
    def __init__(self, id: str = None, workflow_steps: List[WorkflowStep] = None, initial_state_model: BaseModel = None, workflow_type: str = None, steps_config: List[Dict[str, Any]] = None, state_model_path: str = None, owner_id: str = None, org_id: str = None):
        self.id = id or str(uuid.uuid4())
        self.workflow_steps = workflow_steps or []
        self.current_step = 0
        self.state = initial_state_model
        self.status = "ACTIVE"
        self.workflow_type = workflow_type
        self.steps_config = steps_config or []
        self.state_model_path = state_model_path

        # RBAC
        self.owner_id = owner_id
        self.org_id = org_id

        # Saga pattern support
        self.saga_mode = False
        self.completed_steps_stack = []  # Track completed steps for rollback

        # Sub-workflow support
        self.parent_execution_id = None
        self.blocked_on_child_id = None

        # Regional data sovereignty
        self.data_region = None

        # Priority for task queuing
        self.priority = 5

        # Idempotency
        self.idempotency_key = None

        # Metadata
        self.metadata = {}

    @property
    def current_step_name(self) -> Optional[str]:
        if 0 <= self.current_step < len(self.workflow_steps):
            return self.workflow_steps[self.current_step].name
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_type": self.workflow_type,
            "current_step": self.current_step,
            "status": self.status,
            "state": self.state.model_dump() if self.state else {},
            "steps_config": self.steps_config,
            "state_model_path": self.state_model_path,
            "owner_id": self.owner_id,
            "org_id": self.org_id,
            "saga_mode": self.saga_mode,
            "completed_steps_stack": self.completed_steps_stack,
            "parent_execution_id": self.parent_execution_id,
            "blocked_on_child_id": self.blocked_on_child_id,
            "data_region": self.data_region,
            "priority": self.priority,
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]):
        from .workflow_loader import _build_steps_from_config, _import_from_string
        
        workflow_type = data.get("workflow_type")
        state_model_path = data.get("state_model_path")
        if not workflow_type or not state_model_path:
            raise ValueError("Missing workflow_type or state_model_path in data.")

        try:
            state_model_class = _import_from_string(state_model_path)
            steps_config = data.get('steps_config', [])
            workflow_steps = _build_steps_from_config(steps_config)
        except (ValueError, ImportError) as e:
            raise ValueError(f"Could not load workflow configuration for type '{workflow_type}': {e}")

        instance = Workflow(
            id=data["id"],
            workflow_steps=workflow_steps,
            workflow_type=workflow_type,
            steps_config=steps_config,
            state_model_path=state_model_path
        )
        instance.current_step = data["current_step"]
        instance.status = data["status"]

        if "state" in data and data["state"]:
            instance.state = state_model_class(**data["state"])

        # RBAC
        instance.owner_id = data.get("owner_id")
        instance.org_id = data.get("org_id")

        # Restore saga and sub-workflow fields
        instance.saga_mode = data.get("saga_mode", False)
        instance.completed_steps_stack = data.get("completed_steps_stack", [])
        instance.parent_execution_id = data.get("parent_execution_id")
        instance.blocked_on_child_id = data.get("blocked_on_child_id")
        instance.data_region = data.get("data_region")
        instance.priority = data.get("priority", 5)
        instance.idempotency_key = data.get("idempotency_key")
        instance.metadata = data.get("metadata", {})

        return instance

    def enable_saga_mode(self):
        """Activate saga mode for automatic rollback on failure"""
        self.saga_mode = True
        print(f"[SAGA] Saga mode enabled for workflow {self.id}")

    def _log_execution(self, level: str, message: str, step_name: str = None, metadata: Dict[str, Any] = None):
        """Helper to log execution details to persistent store"""
        try:
            from .persistence import get_workflow_store
            store = get_workflow_store()
            
            if hasattr(store, 'log_execution_sync'):
                store.log_execution_sync(
                    workflow_id=self.id,
                    execution_id=self.id,  # Assuming workflow ID is the execution ID
                    step_name=step_name,
                    event_type=level,
                    message=message,
                    metadata=metadata
                )
        except Exception as e:
            # Fallback to print if logging fails
            print(f"[{level}] {message} (Failed to persist log: {e})")

    def _execute_saga_rollback(self):
        """Compensate all completed steps in reverse order"""
        from .persistence import save_workflow_state, get_workflow_store

        print(f"[SAGA] Rolling back {len(self.completed_steps_stack)} steps for workflow {self.id}...")
        
        # Save state before starting rollback
        save_workflow_state(self.id, self, sync=True)

        store = get_workflow_store()

        for entry in reversed(self.completed_steps_stack):
            step_index = entry['step_index']
            step_name = entry['step_name']
            state_snapshot = entry.get('state_snapshot', {})
            
            # Create a context for the compensation function
            context = StepContext(workflow_id=self.id, step_name=step_name)

            if 0 <= step_index < len(self.workflow_steps):
                step = self.workflow_steps[step_index]

                if isinstance(step, CompensatableStep):
                    try:
                        print(f"[SAGA] Compensating step {step_index}: {step_name}")
                        compensation_result = step.compensate(self.state, context=context)
                        print(f"[SAGA] Compensated {step_name}: {compensation_result}")
                        
                        # Log compensation to DB
                        if hasattr(store, 'log_compensation_sync'):
                            store.log_compensation_sync(
                                execution_id=self.id,
                                step_name=step_name,
                                step_index=step_index,
                                action_type='COMPENSATE',
                                action_result=compensation_result,
                                state_before=state_snapshot,
                                state_after=self.state.model_dump() if self.state else {}
                            )

                    except Exception as comp_error:
                        print(f"[SAGA] Compensation failed for {step_name}: {comp_error}")
                        
                        # Log failed compensation to DB
                        if hasattr(store, 'log_compensation_sync'):
                            store.log_compensation_sync(
                                execution_id=self.id,
                                step_name=step_name,
                                step_index=step_index,
                                action_type='COMPENSATE_FAILED',
                                action_result={},
                                error_message=str(comp_error),
                                state_before=state_snapshot
                            )

                else:
                    print(f"[SAGA] Step {step_name} is not compensatable, skipping")

        # Save final state after rollback
        self.status = "FAILED_ROLLED_BACK"
        save_workflow_state(self.id, self, sync=True)
        print(f"[SAGA] Rollback complete for workflow {self.id}")


    def _handle_sub_workflow(self, directive: StartSubWorkflowDirective):
        """Launch child workflow and pause parent"""
        from .workflow_loader import _import_from_string, _build_steps_from_config
        from .persistence import save_workflow_state

        print(f"[SUB-WORKFLOW] Starting {directive.workflow_type} as child of {self.id}")

        # Get workflow builder to create child workflow
        # We need to import the registry and create workflow properly
        try:
            # Import workflow registry to get config
            import yaml
            registry_path = "config/workflow_registry.yaml"
            with open(registry_path, 'r') as f:
                registry_data = yaml.safe_load(f)

            # Find workflow config
            workflow_config = None
            for item in registry_data.get('workflows', []):
                if item['type'] == directive.workflow_type:
                    workflow_config = item
                    break

            if not workflow_config:
                raise ValueError(f"Sub-workflow type '{directive.workflow_type}' not found in registry")

            # Load workflow YAML
            import os
            config_path = workflow_config['config_file']
            if not os.path.isabs(config_path):
                config_path = os.path.join(os.path.dirname(registry_path), os.path.basename(config_path))

            with open(config_path, 'r') as f:
                workflow_yaml = yaml.safe_load(f)

            # Create child workflow
            state_model_path = workflow_config['initial_state_model']
            state_model_class = _import_from_string(state_model_path)
            steps_config = workflow_yaml.get('steps', [])
            workflow_steps = _build_steps_from_config(steps_config)

            # Initialize state with provided data
            initial_state = state_model_class(**directive.initial_data)

            child_workflow = Workflow(
                workflow_steps=workflow_steps,
                initial_state_model=initial_state,
                workflow_type=directive.workflow_type,
                steps_config=steps_config,
                state_model_path=state_model_path
            )

            # Set parent relationship
            child_workflow.parent_execution_id = self.id

            # Inherit or set data region
            if directive.data_region:
                child_workflow.data_region = directive.data_region
            else:
                child_workflow.data_region = self.data_region

            # Pause parent workflow
            self.status = "PENDING_SUB_WORKFLOW"
            self.blocked_on_child_id = child_workflow.id

            # Save both workflows
            save_workflow_state(self.id, self, sync=True)
            save_workflow_state(child_workflow.id, child_workflow, sync=True)

            print(f"[SUB-WORKFLOW] Created child workflow {child_workflow.id}, parent {self.id} is now paused")

            # In test mode, execute child synchronously; otherwise use Celery
            if os.environ.get("TESTING", "False").lower() == "true":
                print(f"[SUB-WORKFLOW] Test mode: Executing child workflow synchronously")
                # Don't dispatch to Celery, let the test handle child execution manually
            else:
                # Dispatch child execution as async task
                from .tasks import execute_sub_workflow
                execute_sub_workflow.delay(child_workflow.id, self.id)

            return {
                "message": f"Sub-workflow {directive.workflow_type} started",
                "child_workflow_id": child_workflow.id,
                "parent_workflow_id": self.id
            }, None

        except Exception as e:
            print(f"[SUB-WORKFLOW] Error creating sub-workflow: {e}")
            raise

    def _get_nested_state_value(self, key_path: str):
        keys = key_path.split('.')
        value = self.state
        for key in keys:
            if hasattr(value, key):
                value = getattr(value, key)
            elif isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def _process_dynamic_injection(self):
        from .workflow_loader import _build_steps_from_config as builder_func

        if not (0 <= self.current_step < len(self.steps_config)):
            return False

        current_step_config = self.steps_config[self.current_step]
        injection_block = current_step_config.get('dynamic_injection')
        if not injection_block:
            return False

        injection_occurred = False
        rules = injection_block.get('rules', [])
        for rule in rules:
            condition_key = rule.get('condition_key')
            expected_value = rule.get('value_match')
            excluded_values = rule.get('value_is_not') # Retrieve excluded values

            action = rule.get('action')
            steps_to_insert_config = rule.get('steps_to_insert')

            if not all([condition_key, action, steps_to_insert_config]):
                continue

            actual_value = self._get_nested_state_value(condition_key)
            
            print(f"[DYNAMIC INJECTION] Checking rule: {condition_key} == {expected_value} (Actual: {actual_value})")

            condition_met = False
            if expected_value is not None:
                if actual_value == expected_value:
                    condition_met = True
            elif excluded_values is not None:
                # Handle value_is_not: condition met if actual_value is NOT in the list of excluded_values
                if actual_value not in excluded_values:
                    condition_met = True
            
            if condition_met: # Only inject if the condition is met
                print(f"[DYNAMIC INJECTION] Rule met. Injecting steps...")
                new_steps = builder_func(steps_to_insert_config)
                print(f"[DYNAMIC INJECTION] Built {len(new_steps)} new steps.")
                
                if action == 'INSERT_AFTER_CURRENT':
                    insert_at = self.current_step + 1
                    # Insert into config list
                    self.steps_config[insert_at:insert_at] = steps_to_insert_config
                    # Insert into actual step objects list
                    self.workflow_steps[insert_at:insert_at] = new_steps
                    injection_occurred = True
                # Could add other actions here like 'REPLACE_CURRENT', etc.

        return injection_occurred

    def evaluate_routes(self, routes: List[Dict[str, str]]) -> Optional[str]:
        """Evaluates a list of routes and returns the target step name if a match is found."""
        evaluator = SimpleExpressionEvaluator(self.state.model_dump())
        
        for route in routes:
            # Check for 'condition'
            if 'condition' in route and 'next_step' in route:
                if evaluator.evaluate(route['condition']):
                    print(f"[ROUTING] Route matched: {route['condition']} -> {route['next_step']}")
                    return route['next_step']
            
            # Check for 'default'
            elif 'default' in route:
                print(f"[ROUTING] Default route matched: {route['default']}")
                return route['default']
        
        return None

    def next_step(self, user_input: Dict[str, Any], _previous_step_result: Optional[Dict[str, Any]] = None) -> (Dict[str, Any], Optional[str]):
        if self.current_step >= len(self.workflow_steps):
            self.status = "COMPLETED"
            return {"status": "Workflow completed"}, None

        step = self.workflow_steps[self.current_step]
        
        self._log_execution("INFO", f"Starting step: {step.name}", step_name=step.name)
        
        # --- New Input Validation and Context Creation ---
        validated_model = None
        try:
            if step.input_schema:
                # Use user_input for steps that expect external data
                validated_model = step.input_schema(**user_input)
        except ValidationError as e:
            raise ValueError(f"Invalid input for step '{step.name}': {e}")
        
        # Create the context for the step execution
        context = StepContext(
            workflow_id=self.id,
            step_name=step.name,
            validated_input=validated_model,
            previous_step_result=_previous_step_result
        )
        # --- End New Input Handling ---

        try:
            # Save state snapshot BEFORE execution for potential rollback
            state_snapshot_before = None
            if self.saga_mode and isinstance(step, CompensatableStep):
                state_snapshot_before = self.state.model_dump()

            # --- Step Execution ---
            result = {}
            if step.routes:
                if step.func:
                     result = step.func(state=self.state, context=context)
                     if isinstance(result, dict):
                        for key, value in result.items():
                            if hasattr(self.state, key) and not key.startswith('_'):
                                setattr(self.state, key, value)
                
                target_step = self.evaluate_routes(step.routes)
                if target_step:
                    raise WorkflowJumpDirective(target_step_name=target_step)

            elif isinstance(step, AsyncWorkflowStep):
                # This part is NOT yet refactored to use StepContext.
                kwargs = user_input.copy()
                if _previous_step_result:
                    kwargs.update(_previous_step_result)
                kwargs['state'] = self.state
                kwargs['workflow_id'] = self.id
                kwargs['current_step_index'] = self.current_step
                kwargs['data_region'] = self.data_region
                result = step.dispatch_async_task(**kwargs)
            elif isinstance(step, ParallelWorkflowStep):
                result = step.dispatch_parallel_tasks(
                    state=self.state, 
                    workflow_id=self.id, 
                    current_step_index=self.current_step,
                    data_region=self.data_region
                )
            elif step.func:
                result = step.func(state=self.state, context=context)

            # Track completed compensatable step AFTER successful execution
            if self.saga_mode and isinstance(step, CompensatableStep) and state_snapshot_before is not None:
                self.completed_steps_stack.append({
                    'step_index': self.current_step,
                    'step_name': step.name,
                    'state_snapshot': state_snapshot_before
                })

            is_async_dispatch = isinstance(result, dict) and result.get("_async_dispatch")

            if is_async_dispatch:
                self.status = "PENDING_ASYNC"
                if os.environ.get("TESTING", "False").lower() == "true":
                    from .persistence import load_workflow_state
                    reloaded_workflow = load_workflow_state(self.id)
                    if reloaded_workflow:
                        self.__dict__.update(reloaded_workflow.__dict__)
                    return result, self.current_step_name
                return result, None

            # Merge results back into state
            if isinstance(result, dict):
                if "_sync_parallel_result" in result:
                    merged_result = result["_sync_parallel_result"]
                    for key, value in merged_result.items():
                        if hasattr(self.state, key):
                             setattr(self.state, key, value)
                
                for key, value in result.items():
                    if hasattr(self.state, key) and not key.startswith('_'):
                        setattr(self.state, key, value)

            if isinstance(result, WorkflowNextStepDirective):
                try:
                    target_index = next(i for i, s in enumerate(self.workflow_steps) if s.name == result.next_step_name)
                    self.current_step = target_index
                    return {"message": f"Dynamically routing to step {result.next_step_name}"}, self.current_step_name
                except StopIteration:
                    raise ValueError(f"Dynamic route target step '{result.next_step_name}' not found.")

            self._log_execution("INFO", f"Step completed: {step.name}", step_name=step.name)
            
            injection_occurred = self._process_dynamic_injection()
            if injection_occurred and isinstance(result, dict):
                result.setdefault("message", "")
                result["message"] += " (Note: Dynamic steps were injected.)"
            
            just_completed_step_index = self.current_step
            self.current_step += 1

            if self.current_step >= len(self.workflow_steps):
                self.status = "COMPLETED"
                return result, None
            
            next_step_name = self.workflow_steps[self.current_step].name

            # --- Automation Logic ---
            should_automate = self.workflow_steps[just_completed_step_index].automate_next
            if self.parent_execution_id:
                should_automate = True
            
            if should_automate and self.status == "ACTIVE":
                next_input = result if isinstance(result, dict) else {}
                # When automating, the user_input is empty, and the previous result is passed internally.
                return self.next_step(user_input={}, _previous_step_result=next_input)

            return result, next_step_name

        except StartSubWorkflowDirective as sub_directive:
            return self._handle_sub_workflow(sub_directive)
        except WorkflowJumpDirective as e:
            try:
                target_index = next(i for i, s in enumerate(self.workflow_steps) if s.name == e.target_step_name)
                self.current_step = target_index
                return {"message": f"Jumped to step {e.target_step_name}"}, self.current_step_name
            except StopIteration:
                raise ValueError(f"Jump target step '{e.target_step_name}' not found.")
        except WorkflowPauseDirective as e:
            self.status = "WAITING_HUMAN"
            return e.result, self.current_step_name
        except Exception as e:
            self._log_execution("ERROR", f"Step failed: {e}", step_name=step.name, metadata={"error": str(e)})
            if self.saga_mode and self.completed_steps_stack:
                print(f"[SAGA] Workflow {self.id} failed at step {step.name}, triggering rollback")
                self._execute_saga_rollback()
                self.status = "FAILED_ROLLED_BACK"
                raise SagaWorkflowException(step.name, e)
            else:
                self.status = "FAILED"
                raise
