from typing import Any
from rufus.models import StepContext

def noop(state: Any, context: StepContext):
    """A no-op function that does nothing. Used as a placeholder step for dynamic injection."""
    return {}
