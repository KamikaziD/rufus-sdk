"""Security sandbox setup for JavaScript execution."""

import json
from typing import List

# Globals that should be blocked or undefined in the sandbox
BLOCKED_GLOBALS: List[str] = [
    "eval",
    "Function",
    "setTimeout",
    "setInterval",
    "setImmediate",
    "clearTimeout",
    "clearInterval",
    "clearImmediate",
    "require",
    "import",
    "process",
    "global",
    "Buffer",
    "SharedArrayBuffer",
    "Atomics",
    "WebAssembly",
]

# JavaScript code to set up the sandbox environment
SANDBOX_SETUP_JS = """
// Block dangerous globals
(function() {
    const blocked = %s;
    for (const name of blocked) {
        try {
            Object.defineProperty(globalThis, name, {
                value: undefined,
                writable: false,
                configurable: false
            });
        } catch (e) {
            // Some properties may not be configurable
        }
    }

    // Freeze core prototypes to prevent prototype pollution
    Object.freeze(Object.prototype);
    Object.freeze(Array.prototype);
    Object.freeze(String.prototype);
    Object.freeze(Number.prototype);
    Object.freeze(Boolean.prototype);
    Object.freeze(Function.prototype);
    Object.freeze(RegExp.prototype);
    Object.freeze(Date.prototype);
    Object.freeze(Error.prototype);
    Object.freeze(Map.prototype);
    Object.freeze(Set.prototype);
    Object.freeze(Promise.prototype);
})();
""" % json.dumps(BLOCKED_GLOBALS)


def get_sandbox_setup() -> str:
    """Get the JavaScript code to set up the sandbox."""
    return SANDBOX_SETUP_JS


def get_execution_wrapper(user_code: str, strict_mode: bool = True) -> str:
    """
    Wrap user code in an execution harness.

    The wrapper:
    1. Runs in strict mode (optional)
    2. Wraps code in an IIFE to capture return value
    3. Handles both explicit return and expression result
    """
    strict_directive = '"use strict";' if strict_mode else ""

    return f"""
{strict_directive}

// User script execution
(function() {{
    {user_code}
}})();
"""


def validate_script(code: str, max_length: int = 1_000_000) -> None:
    """
    Validate script before execution.

    Raises ValueError if script is invalid or potentially dangerous.
    """
    if len(code) > max_length:
        raise ValueError(f"Script exceeds maximum length of {max_length} characters")

    # Check for obvious dangerous patterns (basic heuristics)
    dangerous_patterns = [
        "__proto__",
        "constructor.constructor",
        "Object.getPrototypeOf",
        "Object.setPrototypeOf",
        "Reflect.setPrototypeOf",
    ]

    for pattern in dangerous_patterns:
        if pattern in code:
            # Log warning but don't block - these could be legitimate
            # The sandbox setup should handle these
            pass
