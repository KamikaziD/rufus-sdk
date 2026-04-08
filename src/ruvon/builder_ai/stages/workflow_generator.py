"""Stage 4 — Workflow Generator: expands a step plan into a full Rufus workflow dict."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ruvon.builder_ai.models import RufusIntent, StepPlan
from ruvon.builder_ai.stages.base import LLMStageMixin

if TYPE_CHECKING:
    from ruvon.builder_ai.knowledge.raft_router import RetrievalDecision

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a Rufus workflow definition generator. Given a step plan, generate a
complete Rufus workflow YAML structure as JSON.

The output must be a JSON object with this structure:
{
  "name": "workflow-name",
  "version": "1.0",
  "owner": "generated",
  "trigger": {"type": "webhook|schedule|manual", "path": "/optional/path"},
  "steps": [
    {
      "name": "StepName",
      "type": "STEP_TYPE",
      "automate_next": true,
      ... type-specific config ...
    }
  ]
}

Step type config requirements:
- STANDARD: "function": "module.path.function_name"
- AI_LLM_INFERENCE: "llm_config": {"model": "claude-sonnet-4-6", "model_location": "cloud", "system_prompt": "...", "user_prompt": "..."}
- HUMAN_APPROVAL: "approval_config": {"title": "...", "approvers": ["role:..."], "timeout_hours": 24, "channels": ["email", "dashboard"]}
- AUDIT_EMIT: "audit_config": {"event_type": "domain.action", "severity": "INFO", "retention_days": 2555}
- COMPLIANCE_CHECK: "compliance_config": {"ruleset": "./rulesets/default.yaml", "jurisdiction": []}
- EDGE_MODEL_CALL: "edge_config": {"model_id": "local-model", "prompt": "..."}
- HTTP: "http_config": {"url": "https://...", "method": "POST"}

Rules:
- Use PascalCase for step names
- Set automate_next: true for steps that should flow automatically
- The last step should have automate_next: false (or omit it)
- For STANDARD steps without a real function, use "function": "rufus_workflows.steps.identity"
- Keep step names short but descriptive

Return ONLY valid JSON. No markdown, no explanation.
"""

_EVALUATOR_SYSTEM = """You are reviewing a generated Rufus workflow definition.
Score the workflow against the original intent (0-100) and list any issues.
Return JSON: {"score": 85, "issues": ["issue 1", "issue 2"]}
A score >= 80 is acceptable. Focus only on structural/semantic correctness.
"""


class WorkflowGenerator(LLMStageMixin):
    """Stage 4: Generate a full workflow dict from a step plan, with evaluator-optimizer loop."""

    async def generate(
        self,
        plan: StepPlan,
        intent: RufusIntent,
        max_iterations: int = 3,
        prior_errors: "list[str] | None" = None,
        decision: "Optional[RetrievalDecision]" = None,
    ) -> Dict[str, Any]:
        logger.debug("[Stage 4] Generating workflow for %d steps", len(plan.steps))
        system = self._inject_knowledge(
            _SYSTEM_PROMPT, decision, focus_types=["yaml_example"]
        )
        user_msg = (
            f"Intent: {intent.model_dump_json()}\n"
            f"Step plan: {plan.model_dump_json()}\n"
            "Generate the complete workflow definition JSON."
        )
        if prior_errors:
            user_msg += (
                "\n\nPrevious attempt was rejected by the schema validator with these errors. "
                "Fix ALL of them:\n" + "\n".join(f"- {e}" for e in prior_errors)
            )
        workflow_dict = None
        feedback = ""
        for attempt in range(max_iterations):
            if feedback:
                user_msg_with_feedback = user_msg + f"\n\nPrevious attempt issues to fix:\n{feedback}"
            else:
                user_msg_with_feedback = user_msg
            raw = await self._call_llm(system=system, user=user_msg_with_feedback, temperature=0.1)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            try:
                workflow_dict = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning("[Stage 4] Attempt %d: JSON parse error: %s", attempt + 1, e)
                feedback = f"JSON parse error: {e}. Return valid JSON only."
                continue

            # Evaluator pass
            eval_msg = (
                f"Original intent: {intent.model_dump_json()}\n"
                f"Generated workflow: {json.dumps(workflow_dict)}\n"
                "Score and list issues."
            )
            eval_raw = await self._call_llm(system=_EVALUATOR_SYSTEM, user=eval_msg, temperature=0.1)
            eval_raw = eval_raw.strip()
            if eval_raw.startswith("```"):
                eval_raw = eval_raw.split("```")[1]
                if eval_raw.startswith("json"):
                    eval_raw = eval_raw[4:]
                eval_raw = eval_raw.strip()
            try:
                eval_result = json.loads(eval_raw)
                score = eval_result.get("score", 100)
                issues = eval_result.get("issues", [])
                logger.debug("[Stage 4] Attempt %d: evaluator score=%d, issues=%s", attempt + 1, score, issues)
                if score >= 80 or not issues:
                    break
                feedback = "\n".join(issues)
            except json.JSONDecodeError:
                # Evaluator failed to parse — accept the workflow as-is
                break

        return workflow_dict or {"name": "generated-workflow", "version": "1.0", "steps": []}
