from abc import ABC, abstractmethod
from typing import Any, Dict

class ExpressionEvaluator(ABC):
    """Abstracts the evaluation of expressions within the workflow state."""

    def __init__(self, state: Dict[str, Any]):
        self.state = state

    @abstractmethod
    def evaluate(self, expression: str) -> Any:
        """Evaluates an expression against the current workflow state."""
        pass
