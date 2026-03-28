"""Stage 1 — Intent Parser: converts a natural language prompt into a RufusIntent."""

from __future__ import annotations

import json
import logging

from rufus.builder_ai.models import RufusIntent
from rufus.builder_ai.stages.base import LLMStageMixin

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert at understanding workflow requirements for enterprise software.
Convert the user's natural language prompt into a structured JSON intent object.

Available Rufus step types (for reference when identifying domain):
STANDARD, ASYNC, HTTP, PARALLEL, LOOP, HUMAN_IN_LOOP, AI_INFERENCE (TFLite/ONNX edge ML),
AI_LLM_INFERENCE (cloud/local LLM), HUMAN_APPROVAL (multi-channel approval gate),
AUDIT_EMIT (immutable audit record), COMPLIANCE_CHECK (regulatory ruleset evaluation),
EDGE_MODEL_CALL (local-only inference, data sovereignty), WORKFLOW_BUILDER_META (provenance),
FIRE_AND_FORGET, CRON_SCHEDULE, WASM

Return ONLY valid JSON matching this schema (no markdown, no explanation):
{
  "description": "concise paraphrase of user's intent",
  "trigger": "manual|webhook|schedule|event",
  "domain": "short domain name e.g. bid-evaluation",
  "edge_required": false,
  "ambiguities": ["list of unclear things that need clarification"]
}

Rules:
- Set edge_required=true only if the user explicitly mentions offline, edge, or no network
- Only include ambiguities that are ESSENTIAL to generate the workflow; skip nice-to-haves
- Keep ambiguities list short (max 3 items)
"""


class IntentParser(LLMStageMixin):
    """Stage 1: Parse a natural language prompt into a structured RufusIntent."""

    async def parse(self, prompt: str) -> RufusIntent:
        logger.debug("[Stage 1] Parsing intent from prompt: %s", prompt[:80])
        raw = await self._call_llm(system=_SYSTEM_PROMPT, user=prompt, temperature=0.2)
        raw = raw.strip()
        # Strip markdown code fences if the model wrapped the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("[Stage 1] Failed to parse JSON from LLM response: %s", e)
            # Fallback: minimal intent with the prompt as description
            return RufusIntent(description=prompt, trigger="manual", domain="unknown", ambiguities=[])
        return RufusIntent(**data)
