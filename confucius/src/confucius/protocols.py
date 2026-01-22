from typing import Protocol, Dict, Any
from pydantic import BaseModel
from .models import StepContext

class StepFunction(Protocol):
    """
    Protocol defining the standard signature for all workflow step functions.

    This ensures that all executable steps conform to a contract where they
    receive the current workflow state and a context object, and return a
    dictionary of results to be merged back into the state.
    """
    def __call__(self, state: BaseModel, context: StepContext) -> Dict[str, Any]: ...

class MetricsCollector(Protocol):
    """
    Protocol defining the interface for a metrics collector.

    This allows the workflow engine to be instrumented for observability without
    being coupled to a specific metrics implementation (e.g., Prometheus, Datadog).
    """
    def record_step_success(self, workflow_type: str, step_name: str, duration: float) -> None: ...
    def record_step_failure(self, workflow_type: str, step_name: str, exception_type: str) -> None: ...
    def record_workflow_started(self, workflow_type: str) -> None: ...
    def record_workflow_completed(self, workflow_type: str, duration: float) -> None: ...
    def record_workflow_failed(self, workflow_type: str, duration: float) -> None: ...
    def record_workflow_compensated(self, workflow_type: str, duration: float) -> None: ...
