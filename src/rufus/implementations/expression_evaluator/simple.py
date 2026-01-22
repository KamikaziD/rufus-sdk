from typing import Any, Dict
from rufus.providers.expression_evaluator import ExpressionEvaluator

class SimpleExpressionEvaluator(ExpressionEvaluator):
    """A simple expression evaluator that supports basic dot notation and direct access."""

    def evaluate(self, expression: str) -> Any:
        """
        Evaluates a simple expression.
        Supports:
        - Direct key access: "key"
        - Nested key access: "key.nested_key"
        - Simple comparisons (limited for security)
        """
        # For simplicity and security, direct eval() is avoided.
        # This implementation supports basic dot notation lookup.

        if not isinstance(self.state, dict):
            return None

        # Handle simple dot notation for nested access
        keys = expression.split('.')
        current_value = self.state
        for key in keys:
            if isinstance(current_value, dict) and key in current_value:
                current_value = current_value[key]
            elif hasattr(current_value, key):
                current_value = getattr(current_value, key)
            else:
                return None # Key not found

        return current_value