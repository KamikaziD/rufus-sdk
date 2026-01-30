"""Type definitions for JavaScript step execution."""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class JSExecutionResult:
    """Result of JavaScript execution."""

    success: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # 'timeout', 'memory', 'syntax', 'runtime', 'file_not_found', 'transpile'
    error_line: Optional[int] = None
    error_column: Optional[int] = None
    stack_trace: Optional[str] = None
    execution_time_ms: float = 0.0
    memory_used_mb: float = 0.0
    logs: List[Dict[str, str]] = field(default_factory=list)  # [{"level": "info", "message": "..."}]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "error_type": self.error_type,
            "error_line": self.error_line,
            "error_column": self.error_column,
            "stack_trace": self.stack_trace,
            "execution_time_ms": self.execution_time_ms,
            "memory_used_mb": self.memory_used_mb,
            "logs": self.logs,
        }


@dataclass
class CompiledScript:
    """Cached compiled script."""

    source: str
    original_path: Optional[str] = None
    is_typescript: bool = False
    transpiled_source: Optional[str] = None
    compiled_at: float = 0.0
    file_mtime: Optional[float] = None  # For cache invalidation
