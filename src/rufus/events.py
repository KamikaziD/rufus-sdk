import json
import logging
import time
import asyncio
from typing import Dict, Any, Optional
import redis.asyncio as redis
import os
logger = logging.getLogger(__name__)

# Prometheus Metrics (optional — only available when prometheus_client is installed)
try:
    from prometheus_client import Counter, REGISTRY
    try:
        WORKFLOW_EVENTS_TOTAL = Counter(
            'workflow_events_total',
            'Total number of workflow events published',
            ['event_type'],
            registry=REGISTRY
        )
    except ValueError:
        # Metric already registered (e.g. reload or multiple imports)
        WORKFLOW_EVENTS_TOTAL = REGISTRY._names_to_collectors['workflow_events_total']
except ImportError:
    WORKFLOW_EVENTS_TOTAL = None

class EventPublisher:
    """
    Publishes workflow events to Redis Streams (for persistence)
    and Redis Pub/Sub (for real-time updates).
    """

    def __init__(self, redis_url: str = None):
        if redis_url:
            self.redis_url = redis_url
        else:
            redis_host = os.getenv("REDIS_HOST", "redis") # Changed default from localhost to redis
            self.redis_url = os.getenv("REDIS_URL", f"redis://{redis_host}:6379/0")

        # Registry of Redis clients per event loop
        self._clients: Dict[asyncio.AbstractEventLoop, redis.Redis] = {}

    def reset(self):
        """Reset the clients registry (e.g. after fork)"""
        self._clients.clear()

    async def get_redis(self) -> redis.Redis:
        """Get or create a Redis client for the current running loop"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Fallback if no loop is running (shouldn't happen in async context)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop not in self._clients:
            # Create a new client for this loop
            logger.info(f"Creating new Redis client for loop {id(loop)}")
            client = redis.from_url(self.redis_url, decode_responses=True)
            self._clients[loop] = client

        return self._clients[loop]

    async def _publish(self, stream_key: str, event_type: str, payload: Dict[str, Any], use_pubsub: bool = True):
        try:
            redis_client = await self.get_redis()
        except Exception as e:
            logger.error(f"Failed to get Redis client: {e}")
            return

        timestamp = time.time()
        event_data = {
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": json.dumps(payload)
        }

        # Metrics
        if WORKFLOW_EVENTS_TOTAL is not None:
            try:
                WORKFLOW_EVENTS_TOTAL.labels(event_type=event_type).inc()
            except:
                pass

        # 1. Publish to Redis Stream (Persistence)
        if stream_key:
            try:
                await redis_client.xadd(stream_key, event_data)
            except Exception as e:
                if "Event loop is closed" in str(e):
                    logger.warning(f"Redis client loop closed for {id(redis_client)}, invalidating.")
                    # Invalidate current loop's client
                    try:
                        loop = asyncio.get_running_loop()
                        if loop in self._clients:
                            del self._clients[loop]
                    except:
                        pass
                logger.error(f"Failed to publish to stream {stream_key}: {e}")

        # 2. Publish to Pub/Sub (Real-time)
        if use_pubsub:
            workflow_id = payload.get("workflow_id") or payload.get("id")
            if workflow_id:
                channel = f"rufus:events:{workflow_id}"  # Changed from workflow:events to rufus:events
                pubsub_message = {
                    "event_type": event_type,
                    "timestamp": timestamp,
                    **payload
                }
                try:
                    await redis_client.publish(channel, json.dumps(pubsub_message))
                except Exception as e:
                    logger.error(f"Failed to publish to channel {channel}: {e}")

    async def publish_workflow_created(self, workflow: Any):
        payload = workflow.to_dict()
        await self._publish('workflow:persistence', 'workflow.created', payload)

    async def publish_workflow_updated(self, workflow: Any):
        payload = workflow.to_dict()
        await self._publish('workflow:persistence', 'workflow.updated', payload)

        # Also publish full workflow state for UI (in the format UI expects)
        workflow_dict = workflow.to_dict()
        ui_payload = {
            "id": workflow_dict.get("id"),
            "status": workflow_dict.get("status"),
            "current_step": workflow_dict.get("current_step", 0),
            "state": workflow_dict.get("state", {}),
            "workflow_type": workflow_dict.get("workflow_type"),
            "steps_config": workflow_dict.get("steps_config", []),
            "parent_execution_id": workflow_dict.get("parent_execution_id"),
            "blocked_on_child_id": workflow_dict.get("blocked_on_child_id")
        }

        # Publish directly to the workflow's channel (bypassing _publish to avoid event envelope)
        workflow_id = workflow_dict.get("id")
        if workflow_id:
            try:
                redis_client = await self.get_redis()
                channel = f"rufus:events:{workflow_id}"
                await redis_client.publish(channel, json.dumps(ui_payload))
            except Exception as e:
                logger.error(f"Failed to publish full workflow state for {workflow_id}: {e}")

    async def publish_step_started(self, workflow_id: str, step_name: str, step_index: int):
        payload = {"workflow_id": workflow_id, "step_name": step_name, "step_index": step_index}
        # Step started might not need persistence if we only persist state changes (completed/failed)
        # But for full audit, we might want it. The log says "To pub/sub only (real-time)"
        await self._publish(None, 'step.started', payload)

    async def publish_step_completed(self, workflow_id: str, step_name: str, result: Dict):
        payload = {"workflow_id": workflow_id, "step_name": step_name, "result": result}
        # Log says "To pub/sub only"
        await self._publish(None, 'step.completed', payload)

    async def publish_step_failed(self, workflow_id: str, step_name: str, error: str, task_id: str = None):
        payload = {"workflow_id": workflow_id, "step_name": step_name, "error": error, "task_id": task_id}
        # Log says "To both (audit + real-time)"
        await self._publish('workflow:persistence', 'step.failed', payload)

    async def publish_workflow_completed(self, workflow: Any):
        payload = workflow.to_dict()
        await self._publish('workflow:persistence', 'workflow.completed', payload)

        # Also publish full workflow state for UI
        workflow_dict = workflow.to_dict()
        ui_payload = {
            "id": workflow_dict.get("id"),
            "status": workflow_dict.get("status"),
            "current_step": workflow_dict.get("current_step", 0),
            "state": workflow_dict.get("state", {}),
            "workflow_type": workflow_dict.get("workflow_type"),
            "steps_config": workflow_dict.get("steps_config", []),
            "parent_execution_id": workflow_dict.get("parent_execution_id"),
            "blocked_on_child_id": workflow_dict.get("blocked_on_child_id")
        }

        workflow_id = workflow_dict.get("id")
        if workflow_id:
            try:
                redis_client = await self.get_redis()
                channel = f"rufus:events:{workflow_id}"
                await redis_client.publish(channel, json.dumps(ui_payload))
            except Exception as e:
                logger.error(f"Failed to publish full workflow state for {workflow_id}: {e}")

    async def publish_workflow_failed(self, workflow: Any, error: str):
        payload = workflow.to_dict()
        payload['error'] = error
        await self._publish('workflow:persistence', 'workflow.failed', payload)

    # --- RETRY CHANNEL (Week 2) ---
    async def publish_to_retry_queue(self, workflow_id: str, step_index: int, task_name: str, error: str, context: Dict = None):
        """
        Publishes a failed task to the BullMQ retry queue.
        Note: BullMQ expects specific structures, but here we are just pushing a job
        to a Redis list or letting the Node.js service pick it up.

        However, to interop with BullMQ *natively* from Python is hard because BullMQ uses Lua scripts and specific hash structures.

        STRATEGY: We will publish a standard message to a Redis Stream (or List) named 'workflow:retry:input'.
        The Node.js service will consume this Stream/List and *add* the job to the BullMQ queue itself.
        This decouples the internal BullMQ implementation details from Python.
        """
        payload = {
            "workflow_id": workflow_id,
            "step_index": step_index,
            "task_name": task_name,
            "error": error,
            "context": context or {},
            "retry_count": 0 # Initial retry count
        }
        # We use a dedicated stream for the "Retry Bridge"
        await self._publish('workflow:retry:bridge', 'retry.requested', payload, use_pubsub=False)

# Global instance
event_publisher = EventPublisher()
