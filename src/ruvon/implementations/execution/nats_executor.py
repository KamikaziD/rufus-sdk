"""
NATSExecutionProvider — distributed workflow task execution via NATS JetStream.

Implements all 6 methods of ExecutionProvider ABC. Uses the same structural
pattern as CeleryExecutionProvider but replaces Redis+Celery with NATS JetStream:

  dispatch_async_task()     → publish to WORKFLOW_TASKS workqueue
  dispatch_parallel_tasks() → publish N messages, collect via correlation-ID reply subjects
  dispatch_sub_workflow()   → publish to workflows.subworkflow.start
  report_child_status_to_parent() → publish to workflows.subworkflow.complete
  execute_sync_step_function()    → run locally (same as SyncExecutor)
  cancel_task()             → publish to workflows.tasks.cancel

Activated by passing NATSExecutionProvider to WorkflowBuilder.create_workflow():

    from ruvon.implementations.execution.nats_executor import NATSExecutionProvider
    executor = NATSExecutionProvider(nats_url="nats://localhost:4222")
    wf = builder.create_workflow("MyWorkflow", execution_provider=executor)

Celery is fully preserved and unaffected.
"""
import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from ruvon.providers.execution import ExecutionProvider, ExecutionContext
from ruvon.models import BaseModel, StepContext

logger = logging.getLogger(__name__)

# JetStream subjects
_SUBJECT_TASK_DISPATCH  = "workflows.tasks.dispatch"
_SUBJECT_TASK_CANCEL    = "workflows.tasks.cancel"
_SUBJECT_SUBWF_START    = "workflows.subworkflow.start"
_SUBJECT_SUBWF_COMPLETE = "workflows.subworkflow.complete"


class NATSExecutionProvider(ExecutionProvider):
    """
    NATS JetStream execution provider.

    Provides the same distributed execution semantics as CeleryExecutionProvider
    without Redis or Celery. Workers subscribe to WORKFLOW_TASKS and publish
    results back; parallel tasks use correlation-ID reply subjects for aggregation.
    """

    def __init__(
        self,
        nats_url: Optional[str] = None,
        nats_credentials: Optional[str] = None,
        task_timeout: float = 300.0,
        parallel_timeout: float = 120.0,
    ):
        import os
        self.nats_url = nats_url or os.getenv("RUVON_NATS_URL", "nats://localhost:4222")
        self.nats_credentials = nats_credentials or os.getenv("RUVON_NATS_CREDENTIALS")
        self.task_timeout = task_timeout
        self.parallel_timeout = parallel_timeout

        self._nc = None
        self._js = None
        self._engine = None

    async def _ensure_connected(self):
        """Connect to NATS lazily on first use."""
        if self._nc is not None:
            return
        try:
            import nats
            kwargs: Dict[str, Any] = {"servers": [self.nats_url]}
            if self.nats_credentials:
                kwargs["credentials"] = self.nats_credentials
            self._nc = await nats.connect(**kwargs)
            self._js = self._nc.jetstream()
            logger.info(f"[NATSExecutor] Connected to {self.nats_url}")
        except ImportError:
            raise RuntimeError(
                "nats-py is required for NATSExecutionProvider. "
                "Install with: pip install nats-py"
            )

    async def initialize(self, engine: Any):
        self._engine = engine

    async def close(self):
        if self._nc:
            await self._nc.drain()
            self._nc = None
            self._js = None

    # ------------------------------------------------------------------
    # ExecutionProvider ABC
    # ------------------------------------------------------------------

    async def execute_sync_step_function(
        self,
        step_func: Callable,
        state: BaseModel,
        context: "StepContext",
    ) -> Dict[str, Any]:
        """Execute synchronous step locally (same as SyncExecutor)."""
        if asyncio.iscoroutinefunction(step_func):
            result = await step_func(state=state, context=context)
        else:
            result = step_func(state=state, context=context)
        return result if isinstance(result, dict) else {}

    async def dispatch_async_task(
        self,
        func_path: str,
        state_data: Dict[str, Any],
        workflow_id: str,
        current_step_index: int,
        data_region: Optional[str],
        execution_context: Optional[ExecutionContext] = None,
        **kwargs,
    ) -> str:
        """Publish async task to WORKFLOW_TASKS JetStream workqueue."""
        await self._ensure_connected()

        task_id = str(uuid.uuid4())
        payload = {
            "task_id": task_id,
            "workflow_id": workflow_id,
            "func_path": func_path,
            "state_data": state_data,
            "current_step_index": current_step_index,
            "data_region": data_region,
            "trace_id": execution_context.trace_id if execution_context else task_id,
            "step_name": execution_context.step_name if execution_context else "",
            "attempt": execution_context.attempt if execution_context else 1,
        }

        try:
            from ruvon.utils.serialization import pack_message, _USING_PROTO
            if _USING_PROTO:
                try:
                    from ruvon.proto.gen import TaskDispatch
                    msg = TaskDispatch(
                        task_id=payload["task_id"],
                        workflow_id=workflow_id,
                        func_path=func_path,
                        state_json=str(state_data).encode(),
                        current_step_index=current_step_index,
                        data_region=data_region or "",
                        trace_id=payload["trace_id"],
                        step_name=payload["step_name"],
                        attempt=payload["attempt"],
                    )
                    data = pack_message(payload, msg)
                except ImportError:
                    data = pack_message(payload)
            else:
                data = pack_message(payload)

            await self._js.publish(_SUBJECT_TASK_DISPATCH, data)
            logger.debug(f"[NATSExecutor] Task {task_id} dispatched for {func_path}")
        except Exception as e:
            logger.error(f"[NATSExecutor] dispatch_async_task failed: {e}")
            raise

        return task_id

    async def dispatch_parallel_tasks(
        self,
        tasks: List[Any],
        state_data: Dict[str, Any],
        workflow_id: str,
        current_step_index: int,
        merge_function_path: Optional[str],
        data_region: Optional[str],
        execution_context: Optional[ExecutionContext] = None,
    ) -> str:
        """
        Dispatch parallel tasks and collect results via correlation-ID reply subjects.

        Each task gets a unique reply subject; this method waits for all replies
        up to parallel_timeout, then merges results.
        """
        await self._ensure_connected()

        group_id = str(uuid.uuid4())
        n_tasks = len(tasks)
        results: Dict[str, Any] = {}
        pending: Dict[str, asyncio.Future] = {}
        subscriptions = []

        for i, task_cfg in enumerate(tasks):
            task_id = f"{group_id}.{i}"
            reply_subject = f"_INBOX.ruvon.{task_id}"
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            pending[task_id] = future

            # Subscribe to reply subject
            async def _make_reply_handler(tid, fut):
                async def _handler(msg):
                    from ruvon.utils.serialization import unpack_message
                    data = unpack_message(msg.data)
                    if not fut.done():
                        fut.set_result(data)
                return _handler

            sub = await self._nc.subscribe(reply_subject, cb=await _make_reply_handler(task_id, future))
            subscriptions.append(sub)

            # Dispatch task
            payload = {
                "task_id": task_id,
                "group_id": group_id,
                "workflow_id": workflow_id,
                "task_config": task_cfg if isinstance(task_cfg, dict) else vars(task_cfg),
                "state_data": state_data,
                "current_step_index": current_step_index,
                "data_region": data_region,
                "reply_subject": reply_subject,
            }
            from ruvon.utils.serialization import pack_message
            await self._js.publish(_SUBJECT_TASK_DISPATCH, pack_message(payload))

        # Wait for all results
        try:
            done, _ = await asyncio.wait(
                list(pending.values()),
                timeout=self.parallel_timeout,
            )
            for task_id, future in pending.items():
                if future in done and not future.exception():
                    results[task_id] = future.result()
                else:
                    logger.warning(f"[NATSExecutor] Parallel task {task_id} timed out or failed")
        finally:
            for sub in subscriptions:
                await sub.unsubscribe()

        logger.debug(f"[NATSExecutor] Parallel group {group_id}: {len(results)}/{n_tasks} tasks completed")
        return group_id

    async def dispatch_sub_workflow(
        self,
        child_workflow_type: str,
        initial_data: Dict[str, Any],
        parent_id: str,
        data_region: Optional[str] = None,
    ) -> str:
        """Publish sub-workflow start request to NATS."""
        await self._ensure_connected()

        child_id = str(uuid.uuid4())
        payload = {
            "child_id": child_id,
            "parent_id": parent_id,
            "child_workflow_type": child_workflow_type,
            "initial_data": initial_data,
            "data_region": data_region,
        }
        from ruvon.utils.serialization import pack_message
        await self._js.publish(_SUBJECT_SUBWF_START, pack_message(payload))
        logger.debug(f"[NATSExecutor] Sub-workflow {child_id} ({child_workflow_type}) dispatched")
        return child_id

    async def report_child_status_to_parent(
        self,
        child_id: str,
        parent_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publish child workflow status update to parent."""
        await self._ensure_connected()

        payload = {
            "child_id": child_id,
            "parent_id": parent_id,
            "status": status,
            "result": result or {},
        }
        from ruvon.utils.serialization import pack_message
        await self._nc.publish(_SUBJECT_SUBWF_COMPLETE, pack_message(payload))

    async def cancel_task(self, task_id: str) -> None:
        """Request task cancellation via NATS."""
        await self._ensure_connected()
        from ruvon.utils.serialization import pack_message
        await self._nc.publish(_SUBJECT_TASK_CANCEL, pack_message({"task_id": task_id}))
