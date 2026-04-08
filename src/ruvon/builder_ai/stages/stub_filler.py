"""Stage 9 — Stub Filler: plain-English description → filled Python function body (LLM)."""

from __future__ import annotations

import logging
import re
from typing import Optional

from ruvon.builder_ai.stages.base import LLMStageMixin

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Python expert writing step functions for the Rufus workflow engine.

A Rufus step function has this signature:
    def func_name(state, context: StepContext, **kwargs) -> dict:

Rules:
- ``state`` is a Pydantic BaseModel; access fields as ``state.field_name``.
- Return a dict whose keys are merged into the workflow state (use {} for no changes).
- Do NOT include import statements, the def line, or docstring — only the function body.
- Indent the body 4 spaces.
- Be concise. Use only stdlib + the description provided; do not invent external APIs.
- End with a ``return`` statement that returns a dict.

Only output the indented function body. Nothing else."""


class StubFiller(LLMStageMixin):
    """Stage 9: Takes a stub skeleton + plain-English description → filled function body.

    Used by the interactive REPL to let users describe what each STANDARD step
    should do, then have the LLM write the implementation.

    Usage::

        filler = StubFiller(backend="anthropic", model="claude-sonnet-4-6", api_key="...")
        body = await filler.fill(
            func_name="validate_payment",
            signature="def validate_payment(state, context: StepContext):",
            description="Check that state.amount > 0 and state.currency is in the allowed list",
        )
    """

    async def fill(
        self,
        func_name: str,
        signature: str,
        description: str,
    ) -> str:
        """Generate a function body from a plain-English description.

        Returns the indented body string (4-space indent, no def line).
        """
        user = (
            f"Function name: {func_name}\n"
            f"Signature: {signature}\n"
            f"Description: {description}"
        )
        logger.info("[Stage 9] Filling stub for function '%s'", func_name)
        body = await self._call_llm(system=_SYSTEM_PROMPT, user=user, temperature=0.2)
        return body.rstrip()

    def apply_body(self, stubs_py: str, func_name: str, new_body: str) -> str:
        """Replace the ``# TODO: implement`` placeholder for ``func_name`` in ``stubs_py``.

        Finds the function definition, replaces the body lines up to the next
        blank line or EOF.  Returns the updated source string unchanged if the
        function is not found.
        """
        # Match: def func_name(... any signature ...) through the TODO body
        pattern = re.compile(
            r"(def " + re.escape(func_name) + r"\([^)]*\):[^\n]*\n"
            r'(?:    """[^"]*"""\n)?)'     # optional docstring
            r"    # TODO: implement\n"
            r"    return \{\}",
            re.DOTALL,
        )

        def _replacement(m: re.Match) -> str:  # type: ignore[type-arg]
            header = m.group(1)
            # Indent each line of new_body by 4 spaces if not already
            indented = "\n".join(
                "    " + line if line and not line.startswith("    ") else line
                for line in new_body.splitlines()
            )
            return header + indented

        updated, count = pattern.subn(_replacement, stubs_py)
        if count == 0:
            logger.warning("[Stage 9] Could not find TODO placeholder for '%s'", func_name)
        return updated

    async def fill_and_apply(
        self,
        stubs_py: str,
        func_name: str,
        signature: str,
        description: str,
    ) -> str:
        """Convenience: fill + apply in one call. Returns updated stubs source."""
        body = await self.fill(func_name=func_name, signature=signature, description=description)
        return self.apply_body(stubs_py, func_name, body)
