"""
JavaScript step execution for Rufus workflows.

This module provides embedded JavaScript/TypeScript execution
in a sandboxed V8 environment for workflow steps.

Example:
    from rufus.javascript import JavaScriptExecutor, JSExecutionResult

    executor = JavaScriptExecutor()

    # Execute inline code
    result = executor.execute(
        code="return { doubled: state.value * 2 };",
        state={"value": 21},
        context={"workflow_id": "abc123"}
    )

    if result.success:
        print(result.result)  # {"doubled": 42}

    # Execute file
    result = executor.execute_file(
        script_path="scripts/process.ts",
        state=workflow_state,
        context=step_context
    )
"""

from .types import JSExecutionResult, CompiledScript
from .executor import JavaScriptExecutor
from .loader import ScriptLoader
from .context_pool import (
    V8ContextPool,
    V8Context,
    get_default_pool,
    is_mini_racer_available,
)
from .bridge import RuntimeBridge
from .builtins import BuiltinsBridge, get_builtins_js
from .sandbox import get_sandbox_setup, validate_script

__all__ = [
    # Main classes
    "JavaScriptExecutor",
    "JSExecutionResult",
    "CompiledScript",
    # Loader
    "ScriptLoader",
    # Context pool
    "V8ContextPool",
    "V8Context",
    "get_default_pool",
    "is_mini_racer_available",
    # Bridge
    "RuntimeBridge",
    "BuiltinsBridge",
    "get_builtins_js",
    # Sandbox
    "get_sandbox_setup",
    "validate_script",
]
