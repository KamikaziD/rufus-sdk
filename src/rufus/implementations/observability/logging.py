"""
LoggingObserver — structured JSON logging for workflow events.

Uses Python's standard logging module with structured dict extras so that
log aggregators (Fluent Bit, syslog, CloudWatch) can parse fields directly.

StructuredLogFormatter emits JSON lines; configure it on the root logger for
edge device deployments that forward logs to a central aggregator.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from rufus.providers.observer import WorkflowObserver

logger = logging.getLogger(__name__)


class StructuredLogFormatter(logging.Formatter):
    """
    JSON-line formatter for structured log aggregation.

    Usage:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredLogFormatter())
        logging.root.addHandler(handler)
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record, self.datefmt),
        }
        # Merge any structured extras (added via logger.info("msg", extra={...}))
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


class LoggingObserver(WorkflowObserver):
    """
    Structured-logging implementation of WorkflowObserver.

    All events are emitted as logger calls with structured 'extra' dicts.
    result and current_state are deliberately omitted from logs to avoid
    large payloads — use the persistence layer for full state snapshots.
    """

    async def on_workflow_started(
        self, workflow_id: str, workflow_type: str, initial_state: Any
    ):
        logger.info(
            "workflow.started",
            extra={"workflow_id": workflow_id, "workflow_type": workflow_type},
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
        extra: Dict[str, Any] = {
            "workflow_id": workflow_id,
            "step_name": step_name,
            "step_index": step_index,
            "status": status,
        }
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        logger.info("step.executed", extra=extra)

    async def on_workflow_completed(
        self, workflow_id: str, workflow_type: str, final_state: Any
    ):
        logger.info(
            "workflow.completed",
            extra={"workflow_id": workflow_id, "workflow_type": workflow_type},
        )

    async def on_workflow_failed(
        self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any
    ):
        logger.error(
            "workflow.failed",
            extra={
                "workflow_id": workflow_id,
                "workflow_type": workflow_type,
                "error": error_message,
            },
        )

    async def on_workflow_status_changed(
        self,
        workflow_id: str,
        old_status: str,
        new_status: str,
        current_step_name: Optional[str],
        final_result: Optional[Dict[str, Any]] = None,
    ):
        logger.info(
            "workflow.status_changed",
            extra={
                "workflow_id": workflow_id,
                "old_status": old_status,
                "new_status": new_status,
                "step_name": current_step_name,
            },
        )

    async def on_workflow_rolled_back(
        self,
        workflow_id: str,
        workflow_type: str,
        message: str,
        current_state: Any,
        completed_steps_stack: List[Dict[str, Any]],
    ):
        logger.warning(
            "workflow.rolled_back",
            extra={
                "workflow_id": workflow_id,
                "workflow_type": workflow_type,
                "rollback_message": message,
                "steps_rolled_back": len(completed_steps_stack),
            },
        )

    async def on_step_failed(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        error_message: str,
        current_state: Any,
    ):
        logger.error(
            "step.failed",
            extra={
                "workflow_id": workflow_id,
                "step_name": step_name,
                "step_index": step_index,
                "error": error_message,
            },
        )

    async def on_workflow_paused(
        self, workflow_id: str, step_name: str, reason: str
    ):
        logger.info(
            "workflow.paused",
            extra={
                "workflow_id": workflow_id,
                "step_name": step_name,
                "reason": reason,
            },
        )

    async def on_workflow_resumed(
        self,
        workflow_id: str,
        step_name: str,
        resume_data: Optional[Dict[str, Any]],
    ):
        logger.info(
            "workflow.resumed",
            extra={"workflow_id": workflow_id, "step_name": step_name},
        )

    async def on_compensation_started(
        self, workflow_id: str, step_name: str, step_index: int
    ):
        logger.info(
            "saga.compensation_started",
            extra={
                "workflow_id": workflow_id,
                "step_name": step_name,
                "step_index": step_index,
            },
        )

    async def on_compensation_completed(
        self,
        workflow_id: str,
        step_name: str,
        success: bool,
        error: Optional[str] = None,
    ):
        level = logging.INFO if success else logging.WARNING
        extra: Dict[str, Any] = {
            "workflow_id": workflow_id,
            "step_name": step_name,
            "success": success,
        }
        if error:
            extra["error"] = error
        logger.log(level, "saga.compensation_completed", extra=extra)

    async def on_child_workflow_started(
        self, parent_id: str, child_id: str, child_type: str
    ):
        logger.info(
            "workflow.child_started",
            extra={
                "parent_id": parent_id,
                "child_id": child_id,
                "child_type": child_type,
            },
        )
