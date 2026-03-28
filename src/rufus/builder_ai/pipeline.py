"""AIWorkflowBuilder — orchestrates the 7-stage AI generation pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from rufus.builder_ai.models import BuildResult
from rufus.builder_ai.stages.clarification import ClarificationChecker
from rufus.builder_ai.stages.governance_linter import GovernanceLinter
from rufus.builder_ai.stages.intent_parser import IntentParser
from rufus.builder_ai.stages.output_renderer import OutputRenderer
from rufus.builder_ai.stages.schema_validator import SchemaValidator
from rufus.builder_ai.stages.step_planner import StepPlanner
from rufus.builder_ai.stages.workflow_generator import WorkflowGenerator

logger = logging.getLogger(__name__)

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "ollama": "llama3",
    "edge": "bitnet-3b",
}


class AIWorkflowBuilder:
    """Orchestrates the 7-stage AI workflow generation pipeline.

    Supports three model backends:
    - "anthropic": Claude via Anthropic API (requires ANTHROPIC_API_KEY or api_key param)
    - "ollama":    Any local model via Ollama REST API at ollama_base_url
    - "edge":      Not supported for generation pipeline (use anthropic or ollama)

    Usage:
        builder = AIWorkflowBuilder(backend="ollama", model="llama3")
        result = await builder.build("handle incoming bid submissions")
        if result.needs_clarification:
            answers = {"What triggers the workflow?": "webhook POST /bids"}
            result = await builder.build("...", clarification_answers=answers)
        print(result.yaml)
    """

    def __init__(
        self,
        backend: str = "anthropic",
        model: Optional[str] = None,
        ollama_base_url: str = "http://localhost:11434",
        api_key: Optional[str] = None,
    ):
        if backend not in ("anthropic", "ollama"):
            raise ValueError(
                f"backend must be 'anthropic' or 'ollama', got '{backend}'. "
                "Edge backend is not supported for the generation pipeline."
            )
        self.backend = backend
        self.model = model or _DEFAULT_MODELS[backend]
        self.ollama_base_url = ollama_base_url
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        llm_kwargs = dict(
            backend=self.backend,
            model=self.model,
            api_key=self.api_key,
            ollama_base_url=self.ollama_base_url,
        )
        self.intent_parser = IntentParser(**llm_kwargs)
        self.clarification_checker = ClarificationChecker(**llm_kwargs)
        self.step_planner = StepPlanner(**llm_kwargs)
        self.workflow_generator = WorkflowGenerator(**llm_kwargs)
        self.schema_validator = SchemaValidator()
        self.governance_linter = GovernanceLinter()
        self.output_renderer = OutputRenderer()

    async def build(
        self,
        prompt: str,
        clarification_answers: Optional[Dict[str, str]] = None,
        skip_lint: bool = False,
        skip_lint_force: bool = False,
    ) -> BuildResult:
        """Run the full 7-stage pipeline.

        Args:
            prompt: Natural language workflow description.
            clarification_answers: Dict mapping question text → answer. Provide this
                when a previous call returned needs_clarification=True.
            skip_lint: If True, skip governance linter (requires skip_lint_force=True
                to actually skip; otherwise only suppresses lint errors from blocking output).
            skip_lint_force: Must be True together with skip_lint to bypass the linter.

        Returns:
            BuildResult with yaml, lint_report, or needs_clarification questions.
        """
        logger.info("[Pipeline] Starting build for prompt: %s", prompt[:80])

        # Stage 1: Parse intent
        logger.info("[Pipeline] Stage 1 — Intent Parse")
        intent = await self.intent_parser.parse(prompt)

        # Stage 2: Clarification check
        if intent.ambiguities and not clarification_answers:
            logger.info("[Pipeline] Stage 2 — Clarification needed (%d items)", len(intent.ambiguities))
            questions = await self.clarification_checker.generate_questions(intent)
            return BuildResult(needs_clarification=True, questions=questions)

        if clarification_answers:
            logger.info("[Pipeline] Stage 2 — Resolving clarification answers")
            intent = await self.clarification_checker.resolve(intent, clarification_answers)

        # Stage 3: Step Planner
        logger.info("[Pipeline] Stage 3 — Step Planner")
        plan = await self.step_planner.plan(intent)
        logger.info("[Pipeline] Planned %d steps", len(plan.steps))

        # Stage 4: Workflow Generator
        logger.info("[Pipeline] Stage 4 — Workflow Generator")
        workflow_dict = await self.workflow_generator.generate(plan, intent)

        # Stage 5: Schema Validator
        logger.info("[Pipeline] Stage 5 — Schema Validator")
        validated, errors = self.schema_validator.validate(workflow_dict)
        if errors:
            logger.warning("[Pipeline] Schema validation failed: %s", errors)
            return BuildResult(errors=errors)

        # Stage 6: Governance Linter
        lint_report = None
        if not (skip_lint and skip_lint_force):
            logger.info("[Pipeline] Stage 6 — Governance Linter")
            lint_report = self.governance_linter.lint(validated)
            logger.info("[Pipeline] Lint: %s", lint_report.summary())

        # Stage 7: Output Renderer
        logger.info("[Pipeline] Stage 7 — Output Renderer")
        yaml_output = self.output_renderer.render(validated, prompt, lint_report)

        return BuildResult(yaml=yaml_output, workflow_dict=validated, lint_report=lint_report)

    async def explain(self, workflow_yaml: str) -> str:
        """Explain an existing workflow YAML in plain English."""
        system = (
            "You are a workflow expert. Given a Rufus workflow YAML definition, "
            "explain what it does in plain English. Be concise (3-5 sentences). "
            "Focus on the business purpose, not the technical implementation."
        )
        user = f"Explain this workflow:\n\n{workflow_yaml}"
        return await self.intent_parser._call_llm(system=system, user=user, temperature=0.3)
