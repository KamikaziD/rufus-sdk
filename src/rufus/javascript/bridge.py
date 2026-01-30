"""Runtime bridge for state injection and result extraction."""

import json
from typing import Dict, Any, Optional

from .builtins import BuiltinsBridge, get_builtins_js
from .sandbox import get_sandbox_setup, get_execution_wrapper


class RuntimeBridge:
    """
    Bridge between Python and JavaScript runtime.

    Handles:
    - State injection (Python -> JS)
    - Result extraction (JS -> Python)
    - Built-in function callbacks
    """

    def __init__(self):
        self.builtins = BuiltinsBridge()

    def prepare_context_code(
        self,
        state: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        Generate JavaScript code to set up the execution context.

        This code is executed before the user script to:
        1. Set up the sandbox (block dangerous globals)
        2. Inject workflow state as frozen object
        3. Inject step context as frozen object
        4. Inject rufus utilities
        """
        # Serialize state and context to JSON
        state_json = json.dumps(state, default=str)
        context_json = json.dumps(context, default=str)

        # Build the context setup code
        setup_code = f"""
// Sandbox setup
{get_sandbox_setup()}

// Inject workflow state (read-only)
const state = Object.freeze({state_json});

// Inject step context (read-only)
const context = Object.freeze({context_json});

// Internal bridge functions (will be replaced by Python callbacks)
let __rufus_logs__ = [];
function __rufus_log__(level, message) {{
    __rufus_logs__.push([level, message]);
}}

let __rufus_uuid_counter__ = 0;
function __rufus_uuid__() {{
    // Fallback UUID generation (replaced by Python callback when available)
    __rufus_uuid_counter__++;
    const timestamp = Date.now().toString(16);
    const random = Math.random().toString(16).slice(2, 10);
    return `${{timestamp}}-${{random}}-${{__rufus_uuid_counter__.toString(16).padStart(4, '0')}}-0000-000000000000`;
}}

// Rufus utilities
{get_builtins_js()}
"""
        return setup_code

    def wrap_user_code(self, user_code: str, strict_mode: bool = True) -> str:
        """Wrap user code in execution harness."""
        return get_execution_wrapper(user_code, strict_mode)

    def extract_result(self, raw_result: Any) -> Optional[Dict[str, Any]]:
        """
        Extract and validate result from JavaScript execution.

        The result must be a JSON-serializable object (dict).
        """
        if raw_result is None:
            return None

        # If result is already a dict, return it
        if isinstance(raw_result, dict):
            return raw_result

        # If result is a primitive, wrap it
        if isinstance(raw_result, (str, int, float, bool)):
            return {"result": raw_result}

        # If result is a list, wrap it
        if isinstance(raw_result, list):
            return {"result": raw_result}

        # Try to convert to dict
        try:
            if hasattr(raw_result, "__dict__"):
                return dict(raw_result.__dict__)
        except Exception:
            pass

        # Fallback: wrap as result
        return {"result": str(raw_result)}

    def extract_logs(self, ctx: Any) -> list:
        """
        Extract captured logs from JavaScript context.

        Args:
            ctx: PyMiniRacer context after execution

        Returns:
            List of log entry dicts with 'level' and 'message' keys
        """
        try:
            logs = ctx.eval("__rufus_logs__")
            if isinstance(logs, list):
                return [{"level": str(level), "message": str(msg)} for level, msg in logs]
        except Exception:
            pass
        return []

    def get_full_script(
        self,
        user_code: str,
        state: Dict[str, Any],
        context: Dict[str, Any],
        strict_mode: bool = True,
    ) -> str:
        """
        Generate the complete script to execute.

        Combines:
        1. Context setup (sandbox, state, context, rufus)
        2. User code wrapped in execution harness
        """
        context_code = self.prepare_context_code(state, context)
        wrapped_code = self.wrap_user_code(user_code, strict_mode)

        return f"{context_code}\n\n{wrapped_code}"
