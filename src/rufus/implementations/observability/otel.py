"""
OtelObserver — OpenTelemetry tracing for Rufus workflow events.

Creates a parent span per workflow and a child span per step. Spans are exported
via the standard OTLP exporter configured through OTEL_EXPORTER_OTLP_ENDPOINT.

Install:
    pip install 'rufus-sdk[otel]'

Usage:
    from rufus.implementations.observability.otel import OtelObserver
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    observer = OtelObserver(tracer_provider=provider)
    workflow = await builder.create_workflow(..., workflow_observer=observer)
"""

from typing import Any, Dict, List, Optional

try:
    from opentelemetry import trace
    from opentelemetry.trace import Tracer, Span, StatusCode, NonRecordingSpan
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

from rufus.providers.observer import WorkflowObserver


class OtelObserver(WorkflowObserver):
    """
    OpenTelemetry tracing observer.

    One parent span is created when a workflow starts (keyed by workflow_id).
    Each step creates a child span under that parent, recording duration_ms as
    an attribute and setting the span status on completion or failure.

    If opentelemetry-sdk is not installed this observer silently no-ops.
    """

    def __init__(self, tracer_provider=None, service_name: str = "rufus"):
        if not _OTEL_AVAILABLE:
            self._tracer = None
            self._active_spans: Dict[str, Any] = {}
            return

        if tracer_provider is None:
            tracer_provider = trace.get_tracer_provider()

        self._tracer: Optional[Tracer] = tracer_provider.get_tracer(
            "rufus.workflow", schema_url="https://opentelemetry.io/schemas/1.11.0"
        )
        # Maps workflow_id → active parent Span
        self._active_spans: Dict[str, Any] = {}

    async def on_workflow_started(
        self, workflow_id: str, workflow_type: str, initial_state: Any
    ):
        if not self._tracer:
            return
        span = self._tracer.start_span(
            name=f"workflow.{workflow_type}",
            attributes={
                "workflow.id": workflow_id,
                "workflow.type": workflow_type,
            },
        )
        self._active_spans[workflow_id] = span

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
        if not self._tracer:
            return
        parent_span = self._active_spans.get(workflow_id)
        ctx = (
            trace.set_span_in_context(parent_span)
            if parent_span and not isinstance(parent_span, NonRecordingSpan)
            else None
        )
        attrs: Dict[str, Any] = {
            "workflow.id": workflow_id,
            "step.name": step_name,
            "step.index": step_index,
            "step.status": status,
        }
        if duration_ms is not None:
            attrs["step.duration_ms"] = duration_ms

        with self._tracer.start_as_current_span(
            name=f"step.{step_name}",
            context=ctx,
            attributes=attrs,
        ) as step_span:
            if status in ("COMPLETED", "JUMPED"):
                step_span.set_status(StatusCode.OK)
            else:
                step_span.set_status(StatusCode.ERROR, description=status)

    async def on_workflow_completed(
        self, workflow_id: str, workflow_type: str, final_state: Any
    ):
        span = self._active_spans.pop(workflow_id, None)
        if span and hasattr(span, "set_status"):
            span.set_status(StatusCode.OK)
            span.end()

    async def on_workflow_failed(
        self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any
    ):
        span = self._active_spans.pop(workflow_id, None)
        if span and hasattr(span, "set_status"):
            span.set_status(StatusCode.ERROR, description=error_message)
            span.record_exception(RuntimeError(error_message))
            span.end()

    async def on_workflow_rolled_back(
        self,
        workflow_id: str,
        workflow_type: str,
        message: str,
        current_state: Any,
        completed_steps_stack: List[Dict[str, Any]],
    ):
        span = self._active_spans.pop(workflow_id, None)
        if span and hasattr(span, "set_status"):
            span.set_status(StatusCode.ERROR, description="saga_rollback")
            span.set_attribute("saga.steps_rolled_back", len(completed_steps_stack))
            span.end()

    async def on_step_failed(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        error_message: str,
        current_state: Any,
    ):
        # Step errors are recorded inline; parent span is ended by on_workflow_failed.
        if not self._tracer:
            return
        parent_span = self._active_spans.get(workflow_id)
        ctx = (
            trace.set_span_in_context(parent_span)
            if parent_span and not isinstance(parent_span, NonRecordingSpan)
            else None
        )
        with self._tracer.start_as_current_span(
            name=f"step.{step_name}.error",
            context=ctx,
            attributes={
                "workflow.id": workflow_id,
                "step.name": step_name,
                "step.index": step_index,
            },
        ) as step_span:
            step_span.set_status(StatusCode.ERROR, description=error_message)
            step_span.record_exception(RuntimeError(error_message))
