"""Stage 3 — Step Planner: turns a resolved intent into an ordered step plan with edges."""

from __future__ import annotations

import json
import logging

from rufus.builder_ai.models import RufusIntent, StepPlan, StepPlanEdge, StepPlanEntry
from rufus.builder_ai.stages.base import LLMStageMixin

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a workflow architect. Convert the user's workflow intent into a step plan.

Available Rufus step types:
- STANDARD: simple synchronous Python function
- AI_LLM_INFERENCE: call Claude, Ollama, or local LLM for text generation/analysis
- HUMAN_APPROVAL: pause for human decision (multi-channel: slack, email, dashboard)
- AUDIT_EMIT: write immutable audit record (required after PII-touching AI steps)
- COMPLIANCE_CHECK: evaluate regulatory ruleset against data
- EDGE_MODEL_CALL: local-only model call (data stays on device)
- HTTP: call external REST API
- PARALLEL: fan-out multiple tasks concurrently
- LOOP: iterate over a collection
- HUMAN_IN_LOOP: simple human pause
- FIRE_AND_FORGET: async child workflow
- CRON_SCHEDULE: schedule recurring workflow
- ASYNC: long-running async task

Return ONLY valid JSON:
{
  "steps": [
    {"id": "step_id", "type": "STEP_TYPE", "label": "What this step does"}
  ],
  "edges": [
    {"from_step": "step_a", "to_step": "step_b"},
    {"from_step": "step_c", "to_step": "step_d", "condition": "$.steps.check.output.passed == true"}
  ]
}

Rules:
- Use snake_case for step ids
- Add AUDIT_EMIT after any AI_LLM_INFERENCE step that could touch sensitive data
- Add HUMAN_APPROVAL before irreversible actions (sends, payments, notifications)
- Prefer COMPLIANCE_CHECK for regulated domains (finance, healthcare, procurement)
- Keep the plan minimal — only steps that are essential to the intent
"""


class StepPlanner(LLMStageMixin):
    """Stage 3: Generate a step plan from a resolved intent."""

    async def plan(self, intent: RufusIntent) -> StepPlan:
        logger.debug("[Stage 3] Planning steps for domain: %s", intent.domain)
        user_msg = (
            f"Intent: {intent.model_dump_json()}\n"
            "Generate the minimal step plan for this workflow."
        )
        raw = await self._call_llm(system=_SYSTEM_PROMPT, user=user_msg, temperature=0.2)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("[Stage 3] Failed to parse step plan JSON: %s", e)
            # Fallback: single standard step
            return StepPlan(
                steps=[StepPlanEntry(id="main_step", type="STANDARD", label=intent.description)],
                edges=[],
            )
        steps = [StepPlanEntry(**s) for s in data.get("steps", [])]
        edges = []
        for e in data.get("edges", []):
            # Handle both "from" and "from_step" keys from the LLM
            from_step = e.get("from_step") or e.get("from", "")
            to_step = e.get("to_step") or e.get("to", "")
            edges.append(StepPlanEdge(from_step=from_step, to_step=to_step, condition=e.get("condition")))
        return StepPlan(steps=steps, edges=edges)
