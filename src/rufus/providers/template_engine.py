from abc import ABC, abstractmethod
from typing import Any, Dict

class TemplateEngine(ABC):
    """Abstracts the rendering of templates within the workflow state."""

    def __init__(self, context: Dict[str, Any]):
        self.context = context

    @abstractmethod
    def render(self, template: Any) -> Any:
        """Renders a template using the current workflow context."""
        pass
