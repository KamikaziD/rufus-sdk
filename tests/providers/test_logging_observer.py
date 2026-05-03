"""
LoggingObserver tests — Sprint 3.

Verifies structured logging output is parseable and duration_ms appears in
step.executed events.
"""

import json
import logging
import pytest
from io import StringIO
from pydantic import BaseModel

from ruvon.implementations.observability.logging import (
    LoggingObserver,
    StructuredLogFormatter,
)


class _State(BaseModel):
    x: int = 0


def _capture_logs() -> tuple:
    """Return (handler, stream) for capturing log output."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredLogFormatter())
    return handler, stream


@pytest.mark.asyncio
async def test_step_executed_includes_duration_ms():
    observer = LoggingObserver()
    handler, stream = _capture_logs()
    observer_logger = logging.getLogger("ruvon.implementations.observability.logging")
    observer_logger.addHandler(handler)
    observer_logger.setLevel(logging.DEBUG)

    try:
        await observer.on_step_executed(
            "wf-1", "StepA", 0, "COMPLETED", None, _State(), duration_ms=42.0
        )
        output = stream.getvalue().strip()
        assert output, "Expected log output"
        parsed = json.loads(output)
        assert parsed.get("duration_ms") == 42.0
    finally:
        observer_logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_step_executed_without_duration_no_duration_key():
    observer = LoggingObserver()
    handler, stream = _capture_logs()
    observer_logger = logging.getLogger("ruvon.implementations.observability.logging")
    observer_logger.addHandler(handler)
    observer_logger.setLevel(logging.DEBUG)

    try:
        await observer.on_step_executed(
            "wf-1", "StepA", 0, "COMPLETED", None, _State()
        )
        output = stream.getvalue().strip()
        assert output
        parsed = json.loads(output)
        # When duration_ms is None (not passed), it should not appear in the log
        assert "duration_ms" not in parsed
    finally:
        observer_logger.removeHandler(handler)


def test_structured_log_formatter_emits_valid_json():
    formatter = StructuredLogFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="test message", args=(), exc_info=None
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["message"] == "test message"
    assert parsed["level"] == "INFO"
