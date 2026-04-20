from typing import Any, Dict, Optional, List
from ruvon.providers.observer import WorkflowObserver


class NoopWorkflowObserver(WorkflowObserver):
    """
    No-operation implementation of WorkflowObserver.

    All methods are inherited as no-ops from the base class.
    Useful as a default or when no observability is required.
    Explicitly listed here for documentation purposes.
    """
    # All methods are inherited from WorkflowObserver (which provides no-op defaults).
    # Override any method here if a specific no-op behaviour is needed in future.
