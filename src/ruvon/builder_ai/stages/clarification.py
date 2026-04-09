"""Stage 2 — Clarification Checker: surfaces ambiguities and resolves them."""

from __future__ import annotations

import logging
from typing import Dict, List

from ruvon.builder_ai.models import RuvonIntent
from ruvon.builder_ai.stages.base import LLMStageMixin

logger = logging.getLogger(__name__)

_QUESTIONS_SYSTEM = """You are helping build a workflow definition. Given the user's intent and a list
of ambiguous parts, generate SHORT, numbered clarifying questions (1 sentence each).
Return ONLY a JSON array of strings. Example: ["What triggers the event?", "Who are the approvers?"]
"""

_RESOLVE_SYSTEM = """You are updating a workflow intent JSON based on user answers to clarifying questions.
Given the original intent JSON and a dict of question→answer pairs, update the intent to incorporate the answers.
Return ONLY the updated intent JSON (same schema as input). Do not add new keys.
Schema:
{
  "description": "string",
  "trigger": "manual|webhook|schedule|event",
  "domain": "string",
  "edge_required": bool,
  "ambiguities": []
}
"""


class ClarificationChecker(LLMStageMixin):
    """Stage 2: Generate clarifying questions and resolve answers into the intent."""

    async def generate_questions(self, intent: RuvonIntent) -> List[str]:
        if not intent.ambiguities:
            return []
        logger.debug("[Stage 2] Generating clarifying questions for %d ambiguities", len(intent.ambiguities))
        user_msg = (
            f"Intent: {intent.model_dump_json()}\n"
            f"Ambiguities: {intent.ambiguities}\n"
            "Generate one clarifying question per ambiguity."
        )
        import json
        raw = await self._call_llm(system=_QUESTIONS_SYSTEM, user=user_msg, temperature=0.2)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            questions = json.loads(raw)
            if isinstance(questions, list):
                return [str(q) for q in questions]
        except json.JSONDecodeError:
            pass
        # Fallback: return ambiguities as questions
        return intent.ambiguities

    async def resolve(self, intent: RuvonIntent, answers: Dict[str, str]) -> RuvonIntent:
        """Incorporate clarification answers into the intent, clearing ambiguities."""
        if not answers:
            return intent.model_copy(update={"ambiguities": []})
        import json
        user_msg = (
            f"Original intent: {intent.model_dump_json()}\n"
            f"Answers: {json.dumps(answers)}\n"
            "Return the updated intent JSON."
        )
        raw = await self._call_llm(system=_RESOLVE_SYSTEM, user=user_msg, temperature=0.1)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            data = json.loads(raw)
            data["ambiguities"] = []  # resolved
            return RuvonIntent(**data)
        except Exception:
            return intent.model_copy(update={"ambiguities": []})
