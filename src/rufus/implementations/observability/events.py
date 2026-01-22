import json
import logging
import time
import asyncio
from typing import Dict, Any, Optional, List
import redis.asyncio as redis
import os
from prometheus_client import Counter, REGISTRY # Assuming prometheus_client is installed

from rufus.providers.observer import WorkflowObserver

logger = logging.getLogger(__name__)

# Prometheus Metrics (ensure these are handled safely in a multi-process/multi-thread environment)
try:
    WORKFLOW_EVENTS_TOTAL = Counter(
        'rufus_workflow_events_total', 
        'Total number of rufus workflow events published',
        ['event_type'],
        registry=REGISTRY
    )
except ValueError:
    # If metric already exists (e.g. during reload or multiple imports), retrieve it
    WORKFLOW_EVENTS_TOTAL = REGISTRY._names_to_collectors.get('rufus_workflow_events_total', None)
    if WORKFLOW_EVENTS_TOTAL is None: # Fallback if not found after all
        logger.warning("Could not retrieve existing 'rufus_workflow_events_total' metric, some metric data might be lost on reload.")


class EventPublisherObserver(WorkflowObserver):
    """
    An implementation of WorkflowObserver that publishes workflow events to Redis Streams (for persistence) 
    and Redis Pub/Sub (for real-time updates).
    """
    
    def __init__(self, redis_url: str = None):
        if redis_url:
            self.redis_url = redis_url
        else:
            redis_host = os.getenv("REDIS_HOST", "redis")
            self.redis_url = os.getenv("REDIS_URL", f"redis://{redis_host}:6379/0")
        
        self._redis_client: Optional[redis.Redis] = None
        self._initialized = False

    async def initialize(self):
        """Connects to Redis."""
        if self._initialized and self._redis_client:
            return
        try:
            self._redis_client = redis.from_url(self.redis_url, decode_responses=True)
            await self._redis_client.ping()
            self._initialized = True
            logger.info(f"EventPublisherObserver connected to Redis at {self.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect EventPublisherObserver to Redis: {e}")
            self._redis_client = None
            raise

    async def close(self):
        """Closes the Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
            self._initialized = False

    async def _publish_event(self, stream_key: Optional[str], event_type: str, payload: Dict[str, Any], use_pubsub: bool = True):
        if not self._initialized or not self._redis_client:
            await self.initialize() # Attempt to initialize if not done
        
        if not self._redis_client:
            logger.error("Redis client not initialized for event publishing.")
            return

        timestamp = time.time()
        event_data = {
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": json.dumps(payload)
        }

        # Metrics
        if WORKFLOW_EVENTS_TOTAL: # Check if metric was successfully initialized
            try:
                WORKFLOW_EVENTS_TOTAL.labels(event_type=event_type).inc()
            except Exception as e:
                logger.warning(f"Failed to increment Prometheus metric: {e}")

        # 1. Publish to Redis Stream (Persistence/Audit Log)
        if stream_key:
            try:
                await self._redis_client.xadd(stream_key, event_data)
            except Exception as e:
                logger.error(f"Failed to publish to stream {stream_key}: {e}")

        # 2. Publish to Pub/Sub (Real-time)
        if use_pubsub:
            workflow_id = payload.get("workflow_id") or payload.get("id")
            if workflow_id:
                channel = f"rufus:events:{workflow_id}" # Use rufus specific channel
                pubsub_message = {
                    "event_type": event_type,
                    "timestamp": timestamp,
                    **payload
                }
                try:
                    await self._redis_client.publish(channel, json.dumps(pubsub_message))
                except Exception as e:
                    logger.error(f"Failed to publish to channel {channel}: {e}")

    async def on_workflow_started(self, workflow_id: str, workflow_type: str, initial_state: Any):
        payload = {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "initial_state": initial_state.model_dump() if hasattr(initial_state, 'model_dump') else initial_state
        }
        await self._publish_event('rufus:workflow_lifecycle', 'workflow.started', payload)

    async def on_step_executed(self, workflow_id: str, step_name: str, step_index: int, status: str, result: Optional[Dict[str, Any]], current_state: Any):
        payload = {
            "workflow_id": workflow_id,
            "step_name": step_name,
            "step_index": step_index,
            "status": status,
            "result": result,
            "current_state": current_state.model_dump() if hasattr(current_state, 'model_dump') else current_state
        }
        await self._publish_event('rufus:step_events', 'step.executed', payload)

    async def on_workflow_completed(self, workflow_id: str, workflow_type: str, final_state: Any):
        payload = {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "final_state": final_state.model_dump() if hasattr(final_state, 'model_dump') else final_state
        }
        await self._publish_event('rufus:workflow_lifecycle', 'workflow.completed', payload)

    async def on_workflow_failed(self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any):
        payload = {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "error_message": error_message,
            "current_state": current_state.model_dump() if hasattr(current_state, 'model_dump') else current_state
        }
        await self._publish_event('rufus:workflow_lifecycle', 'workflow.failed', payload)

    async def on_workflow_status_changed(self, workflow_id: str, old_status: str, new_status: str, current_step_name: Optional[str], final_result: Optional[Dict[str, Any]] = None):
        payload = {
            "workflow_id": workflow_id,
            "old_status": old_status,
            "new_status": new_status,
            "current_step_name": current_step_name,
            "final_result": final_result
        }
        # Publish to Pub/Sub for real-time, Stream for audit
        await self._publish_event('rufus:workflow_status_changes', 'workflow.status_changed', payload)

    async def on_workflow_rolled_back(self, workflow_id: str, workflow_type: str, message: str, current_state: Any, completed_steps_stack: List[Dict[str, Any]]):
        payload = {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "message": message,
            "current_state": current_state.model_dump() if hasattr(current_state, 'model_dump') else current_state,
            "completed_steps_stack": completed_steps_stack
        }
        await self._publish_event('rufus:workflow_lifecycle', 'workflow.rolled_back', payload)

    async def on_step_failed(self, workflow_id: str, step_name: str, step_index: int, error_message: str, current_state: Any):
        payload = {
            "workflow_id": workflow_id,
            "step_name": step_name,
            "step_index": step_index,
            "error_message": error_message,
            "current_state": current_state.model_dump() if hasattr(current_state, 'model_dump') else current_state
        }
        await self._publish_event('rufus:step_events', 'step.failed', payload)


# Global instance (can be replaced/configured by DI framework)
_event_publisher_instance: Optional[EventPublisherObserver] = None

def get_event_publisher_observer(redis_url: str = None) -> EventPublisherObserver:
    global _event_publisher_instance
    if _event_publisher_instance is None:
        _event_publisher_instance = EventPublisherObserver(redis_url)
        # Assuming initialize will be called externally
    return _event_publisher_instance