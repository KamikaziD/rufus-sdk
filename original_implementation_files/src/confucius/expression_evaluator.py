from typing import Any, Dict
import re

class SimpleExpressionEvaluator:
    """
    A minimal, safe expression evaluator for workflow routing conditions.
    Supports:
    - Comparison: >, <, >=, <=, ==, !=
    - Logic: AND, OR
    - String literals (single or double quoted)
    - Numbers (integer and float)
    - Variables from state (dot notation)
    """

    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def evaluate(self, expression: str) -> bool:
        """
        Evaluates a condition string against the current state.
        Example: "credit_score > 700 AND risk_level == 'low'"
        """
        # 1. Parse into tokens (simplistic approach: split by AND/OR)
        # This implementation is a "quick start" version. A full parser 
        # (like using `ast` or a library) would be more robust but heavier.
        
        # Split by OR first (lowest precedence)
        or_parts = [p.strip() for p in expression.split(" OR ")]
        
        for or_part in or_parts:
            # If any OR part is true, the whole expression is true
            if self._evaluate_and_group(or_part):
                return True
        
        return False

    def _evaluate_and_group(self, expression: str) -> bool:
        # Split by AND
        and_parts = [p.strip() for p in expression.split(" AND ")]
        
        for part in and_parts:
            # If any AND part is false, the group is false
            if not self._evaluate_condition(part):
                return False
        
        return True

    def _evaluate_condition(self, condition: str) -> bool:
        # Match "variable operator value"
        # Operators: ==, !=, >=, <=, >, <, in, not in
        # Regex captures: (variable) (operator) (value)
        match = re.match(r"^([\w\.]+)\s*(==|!=|>=|<=|>|<|in|not in)\s*(.*)$", condition)
        
        if not match:
            # Maybe it's a boolean variable reference? "is_active"
            val = self._get_value(condition)
            return bool(val)

        var_name, operator, target_val_str = match.groups()
        
        actual_value = self._get_value(var_name)
        target_value = self._parse_value(target_val_str)

        try:
            if operator == "==": return actual_value == target_value
            if operator == "!=": return actual_value != target_value
            if operator == ">": return actual_value > target_value
            if operator == "<": return actual_value < target_value
            if operator == ">=": return actual_value >= target_value
            if operator == "<=": return actual_value <= target_value
            if operator == "in": return actual_value in target_value
            if operator == "not in": return actual_value not in target_value
        except TypeError:
            # Handle type mismatch gracefully (e.g. comparing string to int)
            return False
            
        return False

    def _get_value(self, path: str) -> Any:
        """Resolve dot-notation path from state dict"""
        parts = path.split('.')
        curr = self.state
        for p in parts:
            if isinstance(curr, dict):
                curr = curr.get(p)
            elif hasattr(curr, p):
                curr = getattr(curr, p)
            else:
                return None # Path not found
        return curr

    def _parse_value(self, val_str: str) -> Any:
        """Parse literal string into python type"""
        val_str = val_str.strip()
        
        # String
        if (val_str.startswith("'" ) and val_str.endswith("'" )) or \
           (val_str.startswith('"') and val_str.endswith('"')):
            return val_str[1:-1]
        
        # Number
        try:
            if '.' in val_str:
                return float(val_str)
            return int(val_str)
        except ValueError:
            pass
            
        # Boolean
        if val_str.lower() == "true": return True
        if val_str.lower() == "false": return False
        if val_str.lower() == "null": return None
        if val_str.lower() == "none": return None
        
        # List (simple comma separated, wrapped in brackets)
        if val_str.startswith("[") and val_str.endswith("]"):
            inner = val_str[1:-1]
            return [self._parse_value(x) for x in inner.split(",")]

        # Variable reference (if not quoted)? 
        # For this simple version, assume unquoted non-numbers are strings or fail.
        # Let's treat them as strings for now if they don't look like vars we know?
        # Or better, just return the string.
        return val_str
