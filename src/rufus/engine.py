from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Type
import uuid
import asyncio

# Use string literal type hints for providers to avoid circular import issues
# from rufus.providers.persistence import PersistenceProvider
# from rufus.providers.execution import ExecutionProvider
# from rufus.providers.observer import WorkflowObserver
# from rufus.providers.expression_evaluator import ExpressionEvaluator
# from rufus.providers.template_engine import TemplateEngine

class WorkflowEngine:
    def __init__(self,
                 persistence: 'PersistenceProvider', # Use string literal
                 executor: 'ExecutionProvider', # Use string literal
                 observer: 'WorkflowObserver', # Use string literal
                 workflow_registry: Dict[str, Any],
                 expression_evaluator_cls: Type['ExpressionEvaluator'], # Use string literal
                 template_engine_cls: Type['TemplateEngine'] # Use string literal
                 ):
        self.persistence: 'PersistenceProvider' = persistence
        self.executor: 'ExecutionProvider' = executor
        self.observer: 'WorkflowObserver' = observer
        self.workflow_registry = workflow_registry
        self.expression_evaluator_cls = expression_evaluator_cls
        self.template_engine_cls = template_engine_cls

        # Initialize WorkflowBuilder here, it needs access to the registry and other classes
        from rufus.builder import WorkflowBuilder # Local import to avoid circular dependency
        self.workflow_builder = WorkflowBuilder(
            workflow_registry=self.workflow_registry,
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls
        )

        # Do NOT call executor.initialize here, as __init__ cannot be async.
        # It must be called by an explicit `await engine.initialize()` after engine creation.

    async def initialize(self):
        """
        Initializes the WorkflowEngine's components that require an async context
        or a reference to the fully constructed engine.
        """
        await self.executor.initialize(self) # Pass self (engine instance)
        # self.persistence and self.observer should ideally be initialized by the caller
        # but if they have internal dependencies on the engine, they could be initialized here too.

    async def get_workflow(self, workflow_id: str) -> 'Workflow':
        """Loads a workflow from persistence and reconstructs the Workflow object."""
        workflow_data = await self.persistence.load_workflow(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow with ID {workflow_id} not found.")
        
        from rufus.workflow import Workflow # Local import to avoid circular dependency
        return Workflow.from_dict(
            workflow_data,
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            workflow_builder=self.workflow_builder,
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls,
            workflow_observer=self.observer
        )

    async def start_workflow(self,
                             workflow_type: str,
                             initial_data: Optional[Dict[str, Any]] = None,
                             owner_id: Optional[str] = None,
                             org_id: Optional[str] = None,
                             data_region: Optional[str] = None,
                             priority: Optional[int] = None,
                             idempotency_key: Optional[str] = None,
                             metadata: Optional[Dict[str, Any]] = None
                             ) -> 'Workflow':
        """
        Starts a new workflow execution.
        """
        # The WorkflowBuilder's create_workflow already fetches config and builds steps
        from rufus.workflow import Workflow # Local import to avoid circular dependency
        new_workflow = await self.workflow_builder.create_workflow(
            workflow_type=workflow_type,
            initial_data=initial_data,
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            workflow_builder=self.workflow_builder, # Pass self.workflow_builder here
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls,
            workflow_observer=self.observer,
            owner_id=owner_id,
            org_id=org_id,
            data_region=data_region,
            priority=priority,
            idempotency_key=idempotency_key,
            metadata=metadata
        )
        
        await self.persistence.save_workflow(new_workflow.id, new_workflow.to_dict())
        await self.observer.on_workflow_started(new_workflow.id, new_workflow.workflow_type, new_workflow.state)
        return new_workflow

    async def report_child_status(self,
                                  child_id: str,
                                  parent_id: str,
                                  child_new_status: str,
                                  child_current_step_name: Optional[str] = None,
                                  child_result: Optional[Dict[str, Any]] = None):
        """
        Callback from the ExecutionProvider to report a child workflow's status change to its parent.
        """
        parent_workflow = await self.get_workflow(parent_id)
        
        if parent_workflow.blocked_on_child_id != child_id:
            # This can happen if the parent unblocked already or a different child is blocking
            # Log a warning but don't error out.
            print(f"Warning: Parent workflow {parent_id} not blocked on child {child_id}. Current blocked: {parent_workflow.blocked_on_child_id}")
            return
            
        old_parent_status = parent_workflow.status

        # Update parent status based on child's status
        if child_new_status == "COMPLETED":
            # Merge child's final state and result into parent's state
            if not hasattr(parent_workflow.state, "sub_workflow_results"):
                setattr(parent_workflow.state, "sub_workflow_results", {})
            parent_workflow.state.sub_workflow_results[child_id] = {
                "workflow_type": await self.get_workflow_type(child_id), # Need to get type from child
                "status": child_new_status,
                "state": (await self.get_workflow(child_id)).state.model_dump() if await self.get_workflow(child_id) else {}, # Re-load child to get final state
                "final_result": child_result
            }
            parent_workflow.status = "ACTIVE" # Parent resumes
            parent_workflow.blocked_on_child_id = None
            await self.persistence.save_workflow(parent_id, parent_workflow.to_dict())
            await parent_workflow._notify_status_change(old_parent_status, parent_workflow.status, parent_workflow.current_step_name)
            
            # Resume the parent workflow
            await parent_workflow.next_step(user_input={})

        elif child_new_status == "FAILED" or child_new_status == "FAILED_ROLLED_BACK":
            parent_workflow.status = "FAILED_CHILD_WORKFLOW"
            # Store failure details in metadata
            parent_workflow.metadata["failed_child_id"] = child_id
            parent_workflow.metadata["failed_child_status"] = child_new_status
            parent_workflow.blocked_on_child_id = None
            await self.persistence.save_workflow(parent_id, parent_workflow.to_dict())
            await parent_workflow._notify_status_change(old_parent_status, parent_workflow.status, parent_workflow.current_step_name)

        elif child_new_status == "WAITING_HUMAN":
            parent_workflow.status = "WAITING_CHILD_HUMAN_INPUT"
            parent_workflow.metadata["waiting_child_id"] = child_id
            parent_workflow.metadata["waiting_child_step"] = child_current_step_name
            await self.persistence.save_workflow(parent_id, parent_workflow.to_dict())
            await parent_workflow._notify_status_change(old_parent_status, parent_workflow.status, parent_workflow.current_step_name)
        
        # Save parent workflow after status update
        await self.persistence.save_workflow(parent_id, parent_workflow.to_dict())

    async def get_workflow_type(self, workflow_id: str) -> str:
        """Helper to get workflow type by ID."""
        workflow_data = await self.persistence.load_workflow(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow with ID {workflow_id} not found.")
        return workflow_data.get("workflow_type")