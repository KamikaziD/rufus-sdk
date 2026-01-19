from pydantic import BaseModel, validator
import re
from typing import Any

class WorkflowInput(BaseModel):
    """
    Base class for all workflow inputs and states that requires 
    input sanitization and context boundary enforcement.
    """
    
    @validator('*', pre=True)
    def sanitize_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            # Remove common injection patterns
            # 1. Script tags
            # 2. Javascript: pseudo-protocol
            # 3. onerror/onload handlers
            # 4. Dangerous python builtins like __import__
            
            dangerous_patterns = [
                r'<script.*?>.*?</script>',
                r'javascript:',
                r'on\w+=',
                r'eval\(',
                r'__import__',
                r'exec\(',
                # Basic SQL Injection patterns (generic)
                r';\s*DROP\s+TABLE',
                r';\s*DELETE\s+FROM',
                r'UNION\s+SELECT'
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, v, re.IGNORECASE | re.DOTALL):
                    raise ValueError(f"Potentially malicious input detected: pattern '{pattern}' matched.")
        return v
    
    @validator('*')
    def validate_context_bounds(cls, v: Any) -> Any:
        """Prevent context overflow attacks"""
        if isinstance(v, str) and len(v) > 50000: # 50KB limit per field
            raise ValueError(f"Input exceeds maximum length of 50000 characters.")
        return v

class SovereignWorkerInput(WorkflowInput):
    """
    Additional checks for workers processing sensitive data where region locking is required.
    """
    data_region: str
    
    @validator('data_region')
    def validate_region(cls, v: str) -> str:
        allowed_regions = ['us-east-1', 'eu-central-1', 'ap-south-1', 'us-west-2']
        if v not in allowed_regions:
            raise ValueError(f"Invalid region: {v}. Must be one of {allowed_regions}")
        return v
