from pydantic import BaseModel, validator
import re
from typing import Any, ClassVar, List, Dict

# Assuming bleach is installed. If not, add to requirements.txt
try:
    import bleach
except ImportError:
    print("Warning: 'bleach' not installed. Semantic firewall HTML sanitization will be disabled.")
    bleach = None

# Define allowed HTML tags and attributes for bleach
ALLOWED_TAGS: List[str] = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol', 'p',
    'strong', 'ul', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'span',
    'div'
]
ALLOWED_ATTRIBUTES: Dict[str, List[str]] = {
    'a': ['href', 'title'],
    'abbr': ['title'],
    'acronym': ['title'],
    'div': ['class', 'style'],
    'span': ['class', 'style'],
    'p': ['class', 'style']
}


class WorkflowInput(BaseModel):
    """
    Base class for all workflow inputs and states that requires
    input sanitization and context boundary enforcement.
    """

    class Config:
        # Fields that should be strictly whitelisted (no HTML, limited special chars)
        strict_fields: ClassVar[List[str]] = []
        # Fields that can contain safe HTML, will be bleached
        html_fields: ClassVar[List[str]] = []

    @validator('*', pre=True)
    def sanitize_strings(cls, v: Any, field) -> Any:
        if isinstance(v, str):
            # 1. Apply HTML sanitization with bleach for designated fields
            if field.name in cls.Config.html_fields and bleach:
                v = bleach.clean(v, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)

            # 2. Apply strict character whitelisting for designated fields
            if field.name in cls.Config.strict_fields:
                # Allow basic alphanumeric, spaces, and common punctuation
                if not re.match(r'^[a-zA-Z0-9\s\-_.,!?@#$%^&*()+\=\[\]{}|;:",.<>/?`~]+$', v):
                    raise ValueError(f"Field '{field.name}' contains prohibited characters.")

            # 3. Remove common injection patterns (fallback for other fields/additional layer)
            # These patterns are broad and should be used with caution if false positives are a concern
            # Whitelisting is generally safer than blacklisting.
            dangerous_patterns = [
                r'<script.*?>.*?</script>',  # Script tags
                r'javascript:',              # Javascript pseudo-protocol
                r'on\w+=',                   # Event handlers like onerror, onload
                r'eval\(',                   # eval() function
                r'__import__',               # __import__ builtin
                r'exec\(',                   # exec() function
                r';\s*DROP\s+TABLE',         # Basic SQL Injection (DROP)
                r';\s*DELETE\s+FROM',        # Basic SQL Injection (DELETE)
                r'UNION\s+SELECT',           # Basic SQL Injection (UNION SELECT)
                r'--.*'                      # SQL comments
            ]

            for pattern in dangerous_patterns:
                if re.search(pattern, v, re.IGNORECASE | re.DOTALL):
                    raise ValueError(f"Potentially malicious input detected in field '{field.name}': pattern '{pattern}' matched.")
        return v

    @validator('*')
    def validate_context_bounds(cls, v: Any, field) -> Any:
        """Prevent context overflow attacks by limiting string length."""
        if isinstance(v, str) and len(v) > 50000:  # 50KB limit per field
            raise ValueError(f"Input for field '{field.name}' exceeds maximum length of 50000 characters.")
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
