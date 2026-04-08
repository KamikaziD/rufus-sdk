"""Stage 8 — Stub Generator: STANDARD steps → Python function skeletons."""

from __future__ import annotations

import ast
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _snake(name: str) -> str:
    """Convert a step name like 'Parse_Bid' or 'ParseBid' to 'parse_bid'."""
    s = re.sub(r"[-\s]+", "_", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_")


class StubGenerator:
    """Stage 8: Scans a validated workflow dict for STANDARD steps and emits a .py file.

    For each STANDARD step that has a ``function`` field, one stub function is
    generated with the correct Rufus signature:

        def <func_name>(state, context: StepContext, **kwargs) -> dict:

    Duplicate function names are de-duplicated (only the first occurrence is emitted).
    Built-in-only workflows (no STANDARD steps) return ``None``.

    Quality gates (``validate_stubs``):
        1. AST parse — catches SyntaxError before execution
        2. Import resolution — ``from ruvon.models import StepContext`` importable
        3. Each stub callable with ``(None, None)`` returns a dict
    """

    def generate(
        self,
        workflow_dict: Dict[str, Any],
        module_name: str = "workflow_steps",
    ) -> Optional[str]:
        """Return a Python source string with stub functions, or None if no STANDARD steps."""
        steps = workflow_dict.get("steps", [])
        standard_steps = [
            s for s in steps
            if s.get("type", "STANDARD").upper() == "STANDARD" and s.get("function")
        ]
        if not standard_steps:
            logger.debug("[Stage 8] No STANDARD steps with function paths — skipping stub generation")
            return None

        lines = [
            '"""Auto-generated step stubs — fill in the TODO bodies.',
            "",
            f"Module: {module_name}",
            '"""',
            "from ruvon.models import StepContext",
            "",
        ]

        seen_functions: set = set()
        for step in standard_steps:
            func_path: str = step["function"]
            func_name = func_path.rsplit(".", 1)[-1]

            if func_name in seen_functions:
                logger.debug("[Stage 8] Skipping duplicate function: %s", func_name)
                continue
            seen_functions.add(func_name)

            required = step.get("required_input", [])
            sig_extras = ""
            if required:
                sig_extras = ", " + ", ".join(f"{k}=None" for k in required)

            step_label = step.get("name", func_name)
            lines += [
                "",
                f"def {func_name}(state, context: StepContext{sig_extras}):",
                f'    """Step: {step_label}"""',
                "    # TODO: implement",
                "    return {}",
            ]

        return "\n".join(lines) + "\n"

    def validate_stubs(self, stubs_py: str) -> List[str]:
        """Run quality gates against the generated Python source.

        Returns a list of error strings; empty list means all gates passed.
        """
        errors: List[str] = []

        # Gate 1 — AST parse (catches SyntaxError before any execution)
        try:
            ast.parse(stubs_py)
        except SyntaxError as exc:
            errors.append(f"SYNTAX: {exc}")
            return errors  # short-circuit: further gates require parseable code

        # Gate 2 — Import resolution
        try:
            exec("from ruvon.models import StepContext", {})  # noqa: S102
        except ImportError as exc:
            errors.append(f"IMPORT: {exc}")

        # Gate 3 — Each stub function called with (None, None) returns a dict
        # Only test objects that are actual functions (not imported classes like StepContext)
        import types as _types
        try:
            ns: Dict[str, Any] = {}
            exec(stubs_py, ns)  # noqa: S102
            for name, obj in ns.items():
                if isinstance(obj, _types.FunctionType) and not name.startswith("_"):
                    result = obj(None, None)
                    if not isinstance(result, dict):
                        errors.append(
                            f"RETURN_TYPE: '{name}' must return dict, got {type(result).__name__}"
                        )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"EXEC: {exc}")

        return errors
