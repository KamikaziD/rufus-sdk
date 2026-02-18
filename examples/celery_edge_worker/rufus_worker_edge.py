"""
Rufus Edge-Enabled Celery Worker

This module integrates RufusEdgeAgent into Celery workers, enabling:
- Hot config push without worker restart
- Store-and-forward resilience when Redis is down
- Fleet management via device registry
- Model updates without downtime

Usage:
    celery -A rufus_worker_edge worker --loglevel=info

Environment Variables:
    RUFUS_CONTROL_PLANE_URL - Control plane API URL
    RUFUS_API_KEY - Worker API key (from registration)
    RUFUS_ENCRYPTION_KEY - Encryption key for SAF data
    WORKER_GPU_ENABLED - "true" if GPU available
    WORKER_MEMORY_GB - Worker memory in GB
    WORKER_REGION - AWS region or data center
    WORKER_ZONE - Availability zone
"""

import asyncio
import os
import threading
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from celery import Celery
from celery.signals import worker_ready, worker_shutdown, task_prerun, task_postrun

from rufus_edge.agent import RufusEdgeAgent
from rufus_edge.models import DeviceConfig, SAFTransaction, TransactionStatus

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Celery app
app = Celery('rufus_worker_edge')
app.config_from_object('celeryconfig')

# Global state
edge_agent: Optional[RufusEdgeAgent] = None
edge_loop: Optional[asyncio.AbstractEventLoop] = None
edge_thread: Optional[threading.Thread] = None

# Hot-reloadable config
FRAUD_RULES: list = []
FEATURE_FLAGS: dict = {}
CURRENT_MODEL_VERSIONS: dict = {}
TASK_ROUTES: dict = {}


# ============================================================================
# Celery Lifecycle Hooks
# ============================================================================

@worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    """
    Initialize RufusEdgeAgent when Celery worker starts.

    This runs once when the worker boots up. The edge agent runs
    in a background thread with its own asyncio event loop.
    """
    global edge_agent, edge_loop, edge_thread

    # Extract worker metadata
    worker_id = sender.hostname  # e.g., "celery@worker-gpu-01"
    worker_capabilities = {
        "gpu": os.getenv("WORKER_GPU_ENABLED", "false").lower() == "true",
        "memory_gb": int(os.getenv("WORKER_MEMORY_GB", "8")),
        "cpu_cores": os.cpu_count(),
        "region": os.getenv("WORKER_REGION", "us-east-1"),
        "zone": os.getenv("WORKER_ZONE", "us-east-1a"),
        "worker_pool": os.getenv("WORKER_POOL", "default"),
        "celery_version": sender.app.VERSION,
    }

    logger.info(f"[RufusEdge] Starting worker {worker_id} with capabilities: {worker_capabilities}")

    # Create event loop for edge agent
    edge_loop = asyncio.new_event_loop()

    # Initialize edge agent
    edge_agent = RufusEdgeAgent(
        device_id=worker_id,
        cloud_url=os.getenv("RUFUS_CONTROL_PLANE_URL", "http://localhost:8000"),
        api_key=os.getenv("RUFUS_API_KEY"),
        db_path=os.getenv("WORKER_DB_PATH", f"/tmp/rufus_worker_{worker_id}.db"),
        encryption_key=os.getenv("RUFUS_ENCRYPTION_KEY"),
        config_poll_interval=int(os.getenv("CONFIG_POLL_INTERVAL", "60")),
        sync_interval=int(os.getenv("SYNC_INTERVAL", "30")),
        heartbeat_interval=int(os.getenv("HEARTBEAT_INTERVAL", "60")),
    )

    # Register config change callback
    edge_agent.config_manager.register_on_config_change(_on_config_update)

    # Start edge agent in background thread
    def run_edge_agent():
        """Run edge agent in dedicated thread."""
        asyncio.set_event_loop(edge_loop)
        try:
            edge_loop.run_until_complete(edge_agent.start())
        except Exception as e:
            logger.error(f"[RufusEdge] Edge agent error: {e}", exc_info=True)

    edge_thread = threading.Thread(target=run_edge_agent, daemon=True, name="RufusEdgeAgent")
    edge_thread.start()

    logger.info(f"[RufusEdge] Worker {worker_id} registered as edge device")


@worker_shutdown.connect
def on_worker_shutdown(sender=None, **kwargs):
    """
    Cleanup RufusEdgeAgent when Celery worker stops.

    Gracefully stops the edge agent and closes the event loop.
    """
    global edge_agent, edge_loop

    logger.info("[RufusEdge] Shutting down worker...")

    if edge_agent and edge_loop:
        try:
            # Schedule graceful shutdown
            future = asyncio.run_coroutine_threadsafe(edge_agent.stop(), edge_loop)
            future.result(timeout=10)  # Wait up to 10 seconds

            # Stop event loop
            edge_loop.call_soon_threadsafe(edge_loop.stop)

        except Exception as e:
            logger.error(f"[RufusEdge] Error during shutdown: {e}", exc_info=True)

    logger.info("[RufusEdge] Worker shutdown complete")


@task_prerun.connect
def on_task_prerun(sender=None, task_id=None, task=None, **kwargs):
    """
    Called before each task execution.

    Logs task start and checks for config updates.
    """
    logger.debug(f"[Task] Starting {task.name} (id: {task_id})")


@task_postrun.connect
def on_task_postrun(sender=None, task_id=None, task=None, retval=None, **kwargs):
    """
    Called after each task execution.

    Logs task completion and metrics.
    """
    logger.debug(f"[Task] Completed {task.name} (id: {task_id})")


# ============================================================================
# Config Hot-Reload
# ============================================================================

def _on_config_update(config: DeviceConfig):
    """
    Called when control plane pushes new config.

    This callback fires whenever the ConfigManager detects a config
    change (via ETag polling). It updates global state that tasks
    can access without worker restart.

    Args:
        config: New device configuration from control plane
    """
    global FRAUD_RULES, FEATURE_FLAGS, TASK_ROUTES

    logger.info(f"[ConfigHotReload] Received config version {config.version}")

    # Update fraud rules
    if config.fraud_rules:
        old_count = len(FRAUD_RULES)
        FRAUD_RULES = config.fraud_rules
        logger.info(f"[ConfigHotReload] Updated fraud rules: {old_count} -> {len(FRAUD_RULES)}")

    # Update feature flags
    if config.features:
        old_flags = FEATURE_FLAGS.copy()
        FEATURE_FLAGS = config.features
        changed_flags = {
            k: (old_flags.get(k), v)
            for k, v in FEATURE_FLAGS.items()
            if old_flags.get(k) != v
        }
        if changed_flags:
            logger.info(f"[ConfigHotReload] Updated feature flags: {changed_flags}")

    # Update model configs
    if config.models:
        for model_name, model_config in config.models.items():
            _check_model_update(model_name, model_config)

    # Update task routing
    if config.workflows:
        _update_task_routes(config.workflows)

    logger.info(f"[ConfigHotReload] Config update complete (version {config.version})")


def _check_model_update(model_name: str, model_config: dict):
    """
    Check if model needs to be updated and trigger download.

    Args:
        model_name: Name of the model (e.g., "llama3.1")
        model_config: Model configuration dict from control plane
    """
    global CURRENT_MODEL_VERSIONS

    new_version = model_config.get("version")
    current_version = CURRENT_MODEL_VERSIONS.get(model_name)

    if current_version == new_version:
        logger.debug(f"[ModelUpdate] {model_name} already at version {new_version}")
        return

    if not model_config.get("auto_load", True):
        logger.debug(f"[ModelUpdate] {model_name} auto_load disabled, skipping")
        return

    logger.info(f"[ModelUpdate] Updating {model_name}: {current_version} -> {new_version}")

    # Download model in background (non-blocking)
    if edge_agent and edge_loop:
        model_path = model_config.get("path", f"/models/{model_name}.onnx")

        future = asyncio.run_coroutine_threadsafe(
            edge_agent.config_manager.download_model(
                model_name=model_name,
                destination_path=model_path,
                use_delta=True,
            ),
            edge_loop
        )

        # Don't block task execution - model will be available after download
        # Tasks can check CURRENT_MODEL_VERSIONS to see if update is complete
        def on_download_complete(fut):
            try:
                fut.result()
                CURRENT_MODEL_VERSIONS[model_name] = new_version
                logger.info(f"[ModelUpdate] {model_name} updated to {new_version}")

                # Optional: Hot-swap model in task globals
                # This depends on your model loading strategy
                # _swap_model(model_name, model_path)

            except Exception as e:
                logger.error(f"[ModelUpdate] Failed to update {model_name}: {e}", exc_info=True)

        future.add_done_callback(on_download_complete)


def _update_task_routes(workflows: dict):
    """
    Update Celery task routing based on workflow config.

    Args:
        workflows: Workflow definitions from control plane
    """
    global TASK_ROUTES

    for workflow_type, workflow_config in workflows.items():
        # Example: Route GPU tasks to GPU-capable workers only
        if workflow_config.get("requires_gpu"):
            worker_has_gpu = os.getenv("WORKER_GPU_ENABLED", "false").lower() == "true"

            if worker_has_gpu:
                logger.info(f"[TaskRouting] Worker can handle GPU workflow: {workflow_type}")
                TASK_ROUTES[workflow_type] = {"queue": "gpu"}
            else:
                logger.info(f"[TaskRouting] Worker cannot handle GPU workflow: {workflow_type}")
                TASK_ROUTES[workflow_type] = {"queue": "non-gpu"}


# ============================================================================
# Store-and-Forward (SAF) Task Queue
# ============================================================================

class CelerySAFBridge:
    """
    Bridges Celery task queue with SQLite SAF queue.

    When Redis is down:
    - Tasks queued to SQLite
    - Worker processes from SQLite queue

    When Redis recovers:
    - SQLite tasks synced to Redis
    - Resume normal operation
    """

    def __init__(self, edge_agent: RufusEdgeAgent, celery_app: Celery):
        self.edge_agent = edge_agent
        self.celery_app = celery_app
        self._saf_mode = False
        self._last_redis_check = datetime.utcnow()

    async def queue_task_with_saf(
        self,
        task_name: str,
        args: tuple = (),
        kwargs: dict = None,
        task_id: str = None,
    ) -> dict:
        """
        Queue task with automatic SAF fallback.

        Args:
            task_name: Celery task name
            args: Task positional arguments
            kwargs: Task keyword arguments
            task_id: Optional task ID (auto-generated if not provided)

        Returns:
            dict: Status info with task_id and queue location
        """
        kwargs = kwargs or {}

        try:
            # Try Redis first
            result = self.celery_app.send_task(
                task_name,
                args=args,
                kwargs=kwargs,
                task_id=task_id,
                expires=3600,
            )

            if self._saf_mode:
                logger.info("[SAF] Redis recovered, resuming normal operation")
                self._saf_mode = False

            return {
                "status": "QUEUED_REDIS",
                "task_id": result.id,
                "queue": "redis"
            }

        except Exception as e:
            # Redis unavailable - use SAF
            if not self._saf_mode:
                logger.warning(f"[SAF] Redis unavailable, switching to SAF mode: {e}")
                self._saf_mode = True

            # Queue to SQLite
            saf_task = SAFTransaction(
                transaction_id=task_id or f"task_{datetime.utcnow().timestamp()}",
                idempotency_key=f"{task_name}:{task_id}",
                status=TransactionStatus.PENDING,
                amount=0,  # Not a payment transaction
                encrypted_blob={
                    "task_name": task_name,
                    "args": args,
                    "kwargs": kwargs,
                    "queued_at": datetime.utcnow().isoformat(),
                },
                encryption_key_id="saf_v1",
            )

            await self.edge_agent.sync_manager.queue_for_sync(saf_task)

            return {
                "status": "QUEUED_SAF",
                "task_id": saf_task.transaction_id,
                "queue": "sqlite"
            }

    async def sync_saf_to_redis(self) -> dict:
        """
        Sync SQLite SAF queue to Redis when connectivity recovers.

        Returns:
            dict: Sync statistics (synced, failed, total)
        """
        if not self._saf_mode:
            return {"synced": 0, "failed": 0, "total": 0}

        # Check if Redis is back
        try:
            self.celery_app.broker_connection().connect()
            redis_available = True
        except Exception:
            redis_available = False

        if not redis_available:
            return {"synced": 0, "failed": 0, "total": 0, "error": "Redis still unavailable"}

        logger.info("[SAF] Redis recovered, syncing SAF queue to Redis...")

        # Get pending tasks from SQLite
        sync_report = await self.edge_agent.sync_manager.sync_all_pending()

        if sync_report.synced_count > 0:
            logger.info(f"[SAF] Synced {sync_report.synced_count} tasks from SAF queue to Redis")
            self._saf_mode = False

        return {
            "synced": sync_report.synced_count,
            "failed": sync_report.failed_count,
            "total": sync_report.total_pending,
            "status": sync_report.status.value
        }


# Global SAF bridge instance
saf_bridge: Optional[CelerySAFBridge] = None


def get_saf_bridge() -> CelerySAFBridge:
    """
    Get global SAF bridge instance.

    Returns:
        CelerySAFBridge: Initialized SAF bridge
    """
    global saf_bridge, edge_agent

    if saf_bridge is None:
        if edge_agent is None:
            raise RuntimeError("Edge agent not initialized. Worker not ready?")
        saf_bridge = CelerySAFBridge(edge_agent, app)

    return saf_bridge


# ============================================================================
# Example Tasks
# ============================================================================

@app.task(bind=True, acks_late=True)
def process_with_saf(self, task_data: dict):
    """
    Example task with store-and-forward resilience.

    If Redis is down, task is queued to SQLite SAF.
    When Redis recovers, SAF tasks are synced.

    Args:
        task_data: Task input data

    Returns:
        dict: Processing result
    """
    global edge_agent

    logger.info(f"[Task] Processing task {self.request.id} with SAF support")

    try:
        # Check if we're online
        is_online = edge_agent and edge_agent._is_online

        if not is_online:
            logger.warning(f"[Task] Offline mode, task {self.request.id} queued to SAF")

            # Queue to SAF for later processing
            if edge_agent:
                asyncio.run_coroutine_threadsafe(
                    edge_agent.sync_manager.queue_for_sync({
                        "task_id": self.request.id,
                        "task_data": task_data,
                        "queued_at": datetime.utcnow().isoformat(),
                    }),
                    edge_loop
                ).result(timeout=5)

            return {
                "status": "QUEUED_SAF",
                "task_id": self.request.id,
                "will_retry": True
            }

        # Normal execution
        result = _execute_task(task_data)
        return result

    except Exception as e:
        logger.error(f"[Task] Error processing task {self.request.id}: {e}", exc_info=True)

        # On error, queue to SAF for retry
        if edge_agent:
            asyncio.run_coroutine_threadsafe(
                edge_agent.sync_manager.queue_for_sync({
                    "task_id": self.request.id,
                    "task_data": task_data,
                    "error": str(e),
                    "retry_count": self.request.retries,
                    "queued_at": datetime.utcnow().isoformat(),
                }),
                edge_loop
            ).result(timeout=5)

        raise


@app.task
def check_fraud(transaction: dict):
    """
    Example fraud check task using hot-reloaded fraud rules.

    Fraud rules are updated via config push without worker restart.

    Args:
        transaction: Transaction data

    Returns:
        dict: Fraud check result
    """
    global FRAUD_RULES

    logger.info(f"[FraudCheck] Checking transaction with {len(FRAUD_RULES)} rules")

    for rule in FRAUD_RULES:
        if _violates_rule(transaction, rule):
            return {
                "fraud": True,
                "rule_violated": rule,
                "transaction_id": transaction.get("id")
            }

    return {
        "fraud": False,
        "transaction_id": transaction.get("id")
    }


@app.task
def llm_inference(prompt: str, model_name: str = "llama3.1"):
    """
    Example LLM inference task with hot-swappable models.

    Models are updated via config push without worker restart.

    Args:
        prompt: Input prompt
        model_name: Model to use

    Returns:
        dict: Inference result
    """
    global CURRENT_MODEL_VERSIONS

    model_version = CURRENT_MODEL_VERSIONS.get(model_name, "unknown")
    logger.info(f"[LLMInference] Using {model_name} v{model_version}")

    # In real implementation, this would call actual model
    # model = MODELS[model_name]
    # result = model.generate(prompt)

    return {
        "model": model_name,
        "version": model_version,
        "prompt": prompt,
        "result": f"Generated response using {model_name} v{model_version}"
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _execute_task(task_data: dict) -> dict:
    """
    Execute task logic.

    This is a placeholder - replace with actual task logic.
    """
    import time
    time.sleep(0.1)  # Simulate work

    return {
        "status": "COMPLETED",
        "task_data": task_data,
        "processed_at": datetime.utcnow().isoformat()
    }


def _violates_rule(transaction: dict, rule: dict) -> bool:
    """
    Check if transaction violates fraud rule.

    This is a placeholder - replace with actual fraud detection logic.
    """
    rule_type = rule.get("type")

    if rule_type == "velocity":
        # Example: Check transaction velocity
        limit = rule.get("limit", 5)
        # In real implementation, query recent transactions
        return False

    return False


# ============================================================================
# Periodic Tasks (Optional)
# ============================================================================

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    Setup periodic tasks for SAF sync and health checks.

    This runs every 60 seconds to sync SAF queue to Redis.
    """
    # Sync SAF queue every 60 seconds
    sender.add_periodic_task(60.0, sync_saf_periodic.s(), name='sync-saf-queue')


@app.task
def sync_saf_periodic():
    """
    Periodic task to sync SAF queue to Redis.

    This ensures queued tasks are processed when Redis recovers.
    """
    global edge_agent, edge_loop

    if edge_agent and edge_loop:
        try:
            future = asyncio.run_coroutine_threadsafe(
                get_saf_bridge().sync_saf_to_redis(),
                edge_loop
            )
            result = future.result(timeout=10)

            if result.get("synced", 0) > 0:
                logger.info(f"[SAF] Periodic sync completed: {result}")

        except Exception as e:
            logger.error(f"[SAF] Periodic sync failed: {e}", exc_info=True)


if __name__ == '__main__':
    # For development/testing
    app.start()
