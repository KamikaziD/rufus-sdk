"""
NATS Worker — subscribes to the WORKFLOW_TASKS JetStream workqueue and
executes step functions dispatched by NATSExecutionProvider.

Mirrors the structure of celery's tasks.py but uses NATS JetStream instead:
  - Durable push consumer on WORKFLOW_TASKS stream
  - Explicit ACK after successful execution
  - NAK on failure (JetStream retries up to max_deliver)
  - Reply to correlation-ID subject for parallel task results

Usage:
    python -m ruvon.implementations.workers.nats_worker --concurrency 4

Or programmatically:
    from ruvon.implementations.workers.nats_worker import NATSWorker
    worker = NATSWorker(nats_url="nats://localhost:4222", concurrency=4)
    await worker.run()
"""
import asyncio
import importlib
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SUBJECT_TASK_DISPATCH  = "workflows.tasks.dispatch"
_SUBJECT_SUBWF_START    = "workflows.subworkflow.start"
_SUBJECT_SUBWF_COMPLETE = "workflows.subworkflow.complete"
_CONSUMER_NAME = "ruvon-nats-worker"


class NATSWorker:
    """
    NATS JetStream workflow task worker.

    Subscribes to workflows.tasks.dispatch with a durable consumer.
    Each message is processed concurrently up to `concurrency` limit.
    """

    def __init__(
        self,
        nats_url: Optional[str] = None,
        nats_credentials: Optional[str] = None,
        concurrency: int = 4,
        workflow_registry_path: Optional[str] = None,
        config_dir: Optional[str] = None,
    ):
        self.nats_url = nats_url or os.getenv("RUVON_NATS_URL", "nats://localhost:4222")
        self.nats_credentials = nats_credentials or os.getenv("RUVON_NATS_CREDENTIALS")
        self.concurrency = concurrency
        self.workflow_registry_path = workflow_registry_path or os.getenv(
            "RUVON_WORKFLOW_REGISTRY_PATH", "config/workflow_registry.yaml"
        )
        self.config_dir = config_dir or os.getenv("RUVON_CONFIG_DIR", "config")

        self._nc = None
        self._js = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._workflow_builder = None
        self._running = False

    async def run(self) -> None:
        """Start the worker — blocks until interrupted."""
        import nats

        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._workflow_builder = self._build_workflow_builder()

        connect_kwargs: Dict[str, Any] = {"servers": [self.nats_url]}
        if self.nats_credentials:
            connect_kwargs["credentials"] = self.nats_credentials

        self._nc = await nats.connect(**connect_kwargs)
        self._js = self._nc.jetstream()
        self._running = True

        logger.info(
            f"[NATSWorker] Started — {self.nats_url} | concurrency={self.concurrency}"
        )

        # Subscribe to task dispatch (durable consumer)
        sub = await self._js.subscribe(
            _SUBJECT_TASK_DISPATCH,
            durable=_CONSUMER_NAME,
            cb=self._handle_task,
            manual_ack=True,
        )

        # Subscribe to sub-workflow starts
        sub_wf = await self._js.subscribe(
            _SUBJECT_SUBWF_START,
            durable=f"{_CONSUMER_NAME}-subwf",
            cb=self._handle_subworkflow,
            manual_ack=True,
        )

        logger.info("[NATSWorker] Listening for tasks...")
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await sub.unsubscribe()
            await sub_wf.unsubscribe()
            await self._nc.drain()
            logger.info("[NATSWorker] Stopped")

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Task handler
    # ------------------------------------------------------------------

    async def _handle_task(self, msg) -> None:
        """Handle a dispatched task message."""
        async with self._semaphore:
            try:
                from ruvon.utils.serialization import unpack_message, pack_message
                payload = unpack_message(msg.data)
                task_id = payload.get("task_id", "unknown")
                func_path = payload.get("func_path", "")
                state_data = payload.get("state_data", {})
                reply_subject = payload.get("reply_subject")

                logger.debug(f"[NATSWorker] Executing task {task_id}: {func_path}")

                # Execute the step function
                result, error = await self._execute_step(func_path, state_data)

                # Publish result to reply subject (parallel tasks)
                if reply_subject:
                    reply_payload = {
                        "task_id": task_id,
                        "success": error is None,
                        "result": result,
                        "error": error,
                    }
                    await self._nc.publish(reply_subject, pack_message(reply_payload))

                if error:
                    logger.warning(f"[NATSWorker] Task {task_id} failed: {error}")
                    await msg.nak()
                else:
                    logger.debug(f"[NATSWorker] Task {task_id} completed")
                    await msg.ack()

            except Exception as e:
                logger.error(f"[NATSWorker] Task handler error: {e}")
                await msg.nak()

    async def _handle_subworkflow(self, msg) -> None:
        """Handle a sub-workflow start request."""
        async with self._semaphore:
            try:
                from ruvon.utils.serialization import unpack_message
                payload = unpack_message(msg.data)
                child_type = payload.get("child_workflow_type", "")
                initial_data = payload.get("initial_data", {})
                parent_id = payload.get("parent_id", "")
                child_id = payload.get("child_id", "")

                logger.info(f"[NATSWorker] Starting sub-workflow {child_id} ({child_type})")
                # Sub-workflow execution is complex and delegates to persistence +
                # workflow_builder. For now, log and ACK — full implementation
                # in a follow-up using the same pattern as CeleryExecutionProvider.
                await msg.ack()
            except Exception as e:
                logger.error(f"[NATSWorker] Subworkflow handler error: {e}")
                await msg.nak()

    async def _execute_step(self, func_path: str, state_data: Dict[str, Any]):
        """Import and execute a step function by dotted path."""
        try:
            module_path, func_name = func_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)

            if asyncio.iscoroutinefunction(func):
                result = await func(state=state_data)
            else:
                result = func(state=state_data)

            return result if isinstance(result, dict) else {}, None
        except Exception as e:
            return {}, str(e)

    def _build_workflow_builder(self):
        """Bootstrap a WorkflowBuilder for sub-workflow execution."""
        try:
            import yaml
            from ruvon.builder import WorkflowBuilder
            from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
            from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine

            try:
                with open(self.workflow_registry_path) as f:
                    registry_config = yaml.safe_load(f)
                registry = {wf["type"]: wf for wf in registry_config.get("workflows", [])}
            except Exception:
                registry = {}

            return WorkflowBuilder(
                workflow_registry=registry,
                expression_evaluator_cls=SimpleExpressionEvaluator,
                template_engine_cls=Jinja2TemplateEngine,
                config_dir=self.config_dir,
            )
        except Exception as e:
            logger.warning(f"[NATSWorker] Could not build WorkflowBuilder: {e}")
            return None
