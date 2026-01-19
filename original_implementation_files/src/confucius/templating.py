import re
from typing import Any, Dict, Union
from .secrets import get_secrets_provider

class TemplateEngine:
    def __init__(self, context: Dict[str, Any]):
        self.context = context
        self.secrets_provider = get_secrets_provider()

    def _resolve_path(self, path: str) -> Any:
        """
        Resolves a dot-notation path (e.g. 'state.user.id' or 'secrets.API_KEY').
        """
        path = path.strip()
        
        # Handle Secrets
        if path.startswith("secrets."):
            secret_key = path.split("secrets.", 1)[1]
            val = self.secrets_provider.get_secret(secret_key)
            return val if val is not None else f"{{{{MISSING_SECRET:{secret_key}}}}}"

        # Handle Context (State)
        # Remove optional 'state.' prefix if present in context keys, 
        # but often context IS the state dict or contains it.
        # If context is {'state': {...}, 'workflow_id': ...}
        
        parts = path.split('.')
        current = self.context
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            
            if current is None:
                return None # Or raise/return literal?
        
        return current

    def render(self, template: Any) -> Any:
        """
        Recursively renders strings in the input (dict, list, or str).
        """
        if isinstance(template, str):
            return self._render_string(template)
        elif isinstance(template, dict):
            return {k: self.render(v) for k, v in template.items()}
        elif isinstance(template, list):
            return [self.render(i) for i in template]
        else:
            return template

    def _render_string(self, template_str: str) -> Any:
        """
        Renders a single string. 
        If the string is exactly "{{var}}", returns the resolved value (preserving type).
        If it contains interpolation "Hello {{name}}", returns a string.
        """
        # Regex for {{ variable }}
        pattern = r'\{\{\s*([\w\.]+)\s*\}\}'
        
        # Check for exact match (to preserve types)
        match = re.fullmatch(pattern, template_str)
        if match:
            path = match.group(1)
            val = self._resolve_path(path)
            return val if val is not None else template_str

        # Interpolation
        def replace_match(match):
            path = match.group(1)
            val = self._resolve_path(path)
            return str(val) if val is not None else match.group(0)

        return re.sub(pattern, replace_match, template_str)

def render_template(template: Any, context: Dict[str, Any]) -> Any:
    """Helper function for one-off rendering."""
    engine = TemplateEngine(context)
    return engine.render(template)
