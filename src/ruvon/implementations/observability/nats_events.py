"""
NATSEventObserver — publishes workflow lifecycle events to NATS JetStream.

Implements WorkflowObserver ABC. All event_type strings exactly match those
used in events.py (Redis-based observer) for dashboard compatibility during
migration from Redis pub/sub to NATS WebSocket.

NATS subject: workflow.events.{workflow_id}  (WORKFLOW_EVENTS stream)

The dashboard subscribes to:
  workflow.events.{workflowId}   — per-workflow real-time updates
  workflow.events.>              — all workflow events (admin page)
  devices.*.heartbeat            — device fleet live view

Activated by passing NATSEventObserver as workflow_observer:

    from ruvon.implementations.observability.nats_events import NATSEventObserver
    observer = NATSEventObserver(nats_url="nats://localhost:4222")
    await observer.initialize()
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from ruvon.providers.observer import WorkflowObserver

logger = logging.getLogger(__name__)


class NATSEventObserver(WorkflowObserver):
    """
    Publishes workflow events to NATS JetStream WORKFLOW_EVENTS stream.

    Events are compatible with EventPublisherObserver (Redis) format so the
    dashboard can consume events from either backend without code changes.
    """

    def __init__(self, nats_url: Optional[str] = None, nats_credentials: Optional[str] = None):
        self.nats_url = nats_url or os.getenv("RUVON_NATS_URL", "nats://localhost:4222")
        self.nats_credentials = nats_credentials or os.getenv("RUVON_NATS_CREDENTIALS")

        self._nc = None
        self._js = None
        self._initialized = False

    async def initialize(self) -> None:
        """Connect to NATS. No-ops gracefully if nats-py is not installed."""
        if self._initialized:
            return
        try:
            import nats
            kwargs: Dict[str, Any] = {"servers": [self.nats_url]}
            if self.nats_credentials:
                kwargs["credentials"] = self.nats_credentials
            self._nc = await nats.connect(**kwargs)
            self._js = self._nc.jetstream()
            self._initialized = True
            logger.info(f"[NATSEventObserver] Connected to {self.nats_url}")
        except ImportError:
            logger.warning(
                "[NATSEventObserver] nats-py not installed — event publishing disabled. "
                "Install with: pip install nats-py"
            )
        except Exception as e:
            logger.error(f"[NATSEventObserver] Connect failed: {e}")

    async def close(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._nc = None
            self._initialized = False

    # ------------------------------------------------------------------
    # Internal publish
    # ------------------------------------------------------------------

    async def _publish(self, event_type: str, workflow_id: str, workflow_type: str,
                       payload: Dict[str, Any], stream_key: str = "") -> None:
        if not self._initialized or not self._js:
            return

        subject = f"workflow.events.{workflow_id}"
        timestamp = time.time()
        event = {
            "event_type": event_type,
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "timestamp": timestamp,
            "stream_key": stream_key,
            **payload,
        }

        try:
            from ruvon.utils.serialization import pack_message, _USING_PROTO
            if _USING_PROTO:
                try:
                    from ruvon.proto.gen import WorkflowEvent
                    msg = WorkflowEvent(
                        event_type=event_type,
                        workflow_id=workflow_id,
                        workflow_type=workflow_type,
                        timestamp=timestamp,
                        payload_json=json.dumps(payload).encode(),
                        stream_key=stream_key,
                    )
                    data = pack_message(event, msg)
                except ImportError:
                    data = pack_message(event)
            else:
                data = pack_message(event)

            await self._js.publish(subject, data)
        except Exception as e:
            logger.error(f"[NATSEventObserver] Publish failed ({event_type}): {e}")

    @staticmethod
    def _state_dict(state: Any) -> Any:
        if hasattr(state, "model_dump"):
            return state.model_dump()
        return state

    # ------------------------------------------------------------------
    # WorkflowObserver ABC implementation
    # (event_type strings match events.py exactly for dashboard compat)
    # ------------------------------------------------------------------

    async def on_workflow_started(self, workflow_id: str, workflow_type: str, initial_state: Any):
        await self._publish(
            "workflow.started", workflow_id, workflow_type,
            {"initial_state": self._state_dict(initial_state)},
            stream_key="ruvon:workflow_lifecycle",
        )

    async def on_step_executed(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        status: str,
        result: Optional[Dict[str, Any]],
        current_state: Any,
        duration_ms: Optional[float] = None,
    ):
        payload: Dict[str, Any] = {
            "step_name": step_name,
            "step_index": step_index,
            "status": status,
            "result": result,
            "current_state": self._state_dict(current_state),
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        await self._publish(
            "step.executed", workflow_id, "",
            payload, stream_key="ruvon:step_events",
        )

    async def on_workflow_completed(self, workflow_id: str, workflow_type: str, final_state: Any):
        await self._publish(
            "workflow.completed", workflow_id, workflow_type,
            {"final_state": self._state_dict(final_state)},
            stream_key="ruvon:workflow_lifecycle",
        )

    async def on_workflow_failed(
        self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any
    ):
        await self._publish(
            "workflow.failed", workflow_id, workflow_type,
            {"error_message": error_message, "current_state": self._state_dict(current_state)},
            stream_key="ruvon:workflow_lifecycle",
        )

    async def on_workflow_status_changed(
        self,
        workflow_id: str,
        old_status: str,
        new_status: str,
        current_step_name: Optional[str],
        final_result: Optional[Dict[str, Any]] = None,
    ):
        await self._publish(
            "workflow.status_changed", workflow_id, "",
            {
                "old_status": old_status,
                "new_status": new_status,
                "current_step_name": current_step_name,
                "final_result": final_result,
            },
            stream_key="ruvon:workflow_status_changes",
        )

    async def on_workflow_rolled_back(
        self,
        workflow_id: str,
        workflow_type: str,
        message: str,
        current_state: Any,
        completed_steps_stack: List[Dict[str, Any]],
    ):
        await self._publish(
            "workflow.rolled_back", workflow_id, workflow_type,
            {
                "message": message,
                "current_state": self._state_dict(current_state),
                "completed_steps_stack": completed_steps_stack,
            },
            stream_key="ruvon:workflow_lifecycle",
        )

    async def on_step_failed(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        error_message: str,
        current_state: Any,
    ):
        await self._publish(
            "step.failed", workflow_id, "",
            {
                "step_name": step_name,
                "step_index": step_index,
                "error_message": error_message,
                "current_state": self._state_dict(current_state),
            },
            stream_key="ruvon:step_events",
        )

    async def on_workflow_paused(self, workflow_id: str, step_name: str, reason: str):
        await self._publish(
            "workflow.paused", workflow_id, "",
            {"step_name": step_name, "reason": reason},
            stream_key="ruvon:workflow_lifecycle",
        )

    async def on_workflow_resumed(
        self, workflow_id: str, step_name: str, resume_data: Optional[Dict[str, Any]]
    ):
        await self._publish(
            "workflow.resumed", workflow_id, "",
            {"step_name": step_name, "resume_data": resume_data},
            stream_key="ruvon:workflow_lifecycle",
        )

    async def on_compensation_started(self, workflow_id: str, step_name: str, step_index: int):
        await self._publish(
            "compensation.started", workflow_id, "",
            {"step_name": step_name, "step_index": step_index},
            stream_key="ruvon:saga_events",
        )

    async def on_compensation_completed(
        self, workflow_id: str, step_name: str, success: bool, error: Optional[str] = None
    ):
        payload: Dict[str, Any] = {"step_name": step_name, "success": success}
        if error:
            payload["error"] = error
        await self._publish(
            "compensation.completed", workflow_id, "",
            payload, stream_key="ruvon:saga_events",
        )

    async def on_child_workflow_started(
        self, parent_id: str, child_id: str, child_type: str
    ):
        await self._publish(
            "workflow.child_started", parent_id, "",
            {"parent_id": parent_id, "child_id": child_id, "child_type": child_type},
            stream_key="ruvon:workflow_lifecycle",
        )
