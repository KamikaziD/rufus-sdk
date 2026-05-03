"""
OtelObserver tests — Sprint 3.

Tests span creation and attribute setting using the OTel in-process SDK.
Requires: pip install 'ruvon-sdk[otel]'

Skipped gracefully when opentelemetry-sdk is not installed.
"""

import pytest
from pydantic import BaseModel

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _OTEL_AVAILABLE,
    reason="opentelemetry-sdk not installed (pip install 'ruvon-sdk[otel]')"
)


class _State(BaseModel):
    x: int = 0


@pytest.fixture
def otel_setup():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    from ruvon.implementations.observability.otel import OtelObserver
    observer = OtelObserver(tracer_provider=provider)
    return observer, exporter


@pytest.mark.asyncio
async def test_workflow_span_created_on_start(otel_setup):
    observer, exporter = otel_setup
    await observer.on_workflow_started("wf-1", "OrderWF", _State())
    # Span not ended yet — still in _active_spans
    assert "wf-1" in observer._active_spans


@pytest.mark.asyncio
async def test_step_span_created_with_duration(otel_setup):
    observer, exporter = otel_setup
    await observer.on_workflow_started("wf-2", "TestWF", _State())
    await observer.on_step_executed(
        "wf-2", "StepA", 0, "COMPLETED", None, _State(), duration_ms=15.5
    )
    spans = exporter.get_finished_spans()
    step_spans = [s for s in spans if "StepA" in s.name]
    assert len(step_spans) == 1
    attrs = step_spans[0].attributes
    assert attrs["step.duration_ms"] == 15.5
    assert attrs["step.name"] == "StepA"
    assert attrs["workflow.id"] == "wf-2"


@pytest.mark.asyncio
async def test_workflow_span_ended_on_completed(otel_setup):
    observer, exporter = otel_setup
    await observer.on_workflow_started("wf-3", "TestWF", _State())
    await observer.on_workflow_completed("wf-3", "TestWF", _State())
    assert "wf-3" not in observer._active_spans
    spans = exporter.get_finished_spans()
    workflow_spans = [s for s in spans if "workflow.TestWF" in s.name]
    assert len(workflow_spans) == 1


@pytest.mark.asyncio
async def test_workflow_span_ended_on_failed(otel_setup):
    from opentelemetry.trace import StatusCode
    observer, exporter = otel_setup
    await observer.on_workflow_started("wf-4", "TestWF", _State())
    await observer.on_workflow_failed("wf-4", "TestWF", "something broke", _State())
    assert "wf-4" not in observer._active_spans
    spans = exporter.get_finished_spans()
    workflow_spans = [s for s in spans if "workflow.TestWF" in s.name]
    assert len(workflow_spans) == 1
    assert workflow_spans[0].status.status_code == StatusCode.ERROR
