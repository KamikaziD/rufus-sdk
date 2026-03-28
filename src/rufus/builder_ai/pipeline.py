"""AIWorkflowBuilder — orchestrates the 9-stage AI generation pipeline."""

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
from rufus.builder_ai.stages.stub_filler import StubFiller
from rufus.builder_ai.stages.stub_generator import StubGenerator
from rufus.builder_ai.stages.workflow_generator import WorkflowGenerator

logger = logging.getLogger(__name__)

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "ollama": "llama3",
    "edge": "bitnet-3b",
}

_MAX_RETRIES = 3


class AIWorkflowBuilder:
    """Orchestrates the 9-stage AI workflow generation pipeline.

    Supports three model backends:
    - "anthropic": Claude via Anthropic API (requires ANTHROPIC_API_KEY or api_key param)
    - "ollama":    Any local model via Ollama REST API at ollama_base_url
    - "edge":      Not supported for generation pipeline (use anthropic or ollama)

    Quality gates (browser_demo pattern):
    - YAML gate: 4-stage deterministic validation with up to _MAX_RETRIES regeneration attempts.
    - Stub gate: 3-stage deterministic validation with up to _MAX_RETRIES regeneration attempts.
    - Results include audit fields: yaml_gate_attempts, stub_gate_attempts, quality.

    Usage:
        builder = AIWorkflowBuilder(backend="ollama", model="llama3")
        result = await builder.build("handle incoming bid submissions")
        if result.needs_clarification:
            answers = {"What triggers the workflow?": "webhook POST /bids"}
            result = await builder.build("...", clarification_answers=answers)
        print(result.yaml)
        if result.stubs_py:
            print(result.stubs_py)
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
        self.stub_generator = StubGenerator()
        self.stub_filler = StubFiller(**llm_kwargs)

    async def build(
        self,
        prompt: str,
        clarification_answers: Optional[Dict[str, str]] = None,
        skip_lint: bool = False,
        skip_lint_force: bool = False,
    ) -> BuildResult:
        """Run the full 9-stage pipeline.

        Args:
            prompt: Natural language workflow description.
            clarification_answers: Dict mapping question text → answer. Provide this
                when a previous call returned needs_clarification=True.
            skip_lint: If True, skip governance linter (requires skip_lint_force=True
                to actually skip; otherwise only suppresses lint errors from blocking output).
            skip_lint_force: Must be True together with skip_lint to bypass the linter.

        Returns:
            BuildResult with yaml, stubs_py, lint_report, quality, or needs_clarification questions.
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

        # Stages 4-5: Workflow Generator + Schema Validator with quality-gate retry loop
        # Mirrors browser_demo WorkflowJumpDirective → FallbackExtract pattern:
        # on validation failure, inject errors back into the generator prompt and retry.
        validated: Dict[str, Any] = {}
        yaml_errors: List[str] = []
        yaml_gate_attempts = 0

        prior_errors: List[str] = []
        for attempt in range(_MAX_RETRIES):
            yaml_gate_attempts = attempt + 1
            logger.info("[Pipeline] Stage 4 — Workflow Generator (attempt %d)", yaml_gate_attempts)
            workflow_dict = await self.workflow_generator.generate(plan, intent, prior_errors=prior_errors)

            logger.info("[Pipeline] Stage 5 — Schema Validator (attempt %d)", yaml_gate_attempts)
            validated, yaml_errors = self.schema_validator.validate(workflow_dict)

            if not yaml_errors:
                logger.info("[Pipeline] YAML quality gate passed on attempt %d", yaml_gate_attempts)
                break

            logger.warning(
                "[Pipeline] YAML quality gate failed (attempt %d/%d): %s",
                yaml_gate_attempts, _MAX_RETRIES, yaml_errors,
            )
            prior_errors = yaml_errors

        if yaml_errors:
            logger.error("[Pipeline] YAML quality gate exhausted after %d attempts", _MAX_RETRIES)
            return BuildResult(
                errors=yaml_errors,
                yaml_gate_attempts=yaml_gate_attempts,
                quality="FAILED",
            )

        # Stage 6: Governance Linter
        lint_report = None
        if not (skip_lint and skip_lint_force):
            logger.info("[Pipeline] Stage 6 — Governance Linter")
            lint_report = self.governance_linter.lint(validated)
            logger.info("[Pipeline] Lint: %s", lint_report.summary())

        # Stage 7: Output Renderer
        logger.info("[Pipeline] Stage 7 — Output Renderer")
        yaml_output = self.output_renderer.render(validated, prompt, lint_report)

        # Stage 8: Stub Generator + quality-gate retry loop
        stubs_py: Optional[str] = None
        stub_gate_attempts = 1
        stub_errors: List[str] = []

        stubs_py = self.stub_generator.generate(validated)
        if stubs_py:
            for attempt in range(_MAX_RETRIES):
                stub_gate_attempts = attempt + 1
                stub_errors = self.stub_generator.validate_stubs(stubs_py)

                if not stub_errors:
                    logger.info("[Pipeline] Stub quality gate passed on attempt %d", stub_gate_attempts)
                    break

                logger.warning(
                    "[Pipeline] Stub quality gate failed (attempt %d/%d): %s",
                    stub_gate_attempts, _MAX_RETRIES, stub_errors,
                )
                if attempt < _MAX_RETRIES - 1:
                    # Stage 9 (repair): ask StubFiller to regenerate broken stubs
                    stubs_py = await self._repair_stubs(stubs_py, stub_errors)
                else:
                    logger.error("[Pipeline] Stub quality gate exhausted after %d attempts", _MAX_RETRIES)
                    # Surface errors but still return partial result with the YAML
                    return BuildResult(
                        yaml=yaml_output,
                        workflow_dict=validated,
                        lint_report=lint_report,
                        stubs_py=stubs_py,
                        errors=stub_errors,
                        yaml_gate_attempts=yaml_gate_attempts,
                        stub_gate_attempts=stub_gate_attempts,
                        quality="PARTIAL",
                    )

        quality = "GOOD" if not stub_errors else "PARTIAL"
        return BuildResult(
            yaml=yaml_output,
            workflow_dict=validated,
            lint_report=lint_report,
            stubs_py=stubs_py,
            yaml_gate_attempts=yaml_gate_attempts,
            stub_gate_attempts=stub_gate_attempts,
            quality=quality,
        )

    async def _repair_stubs(self, stubs_py: str, errors: List[str]) -> str:
        """Ask the LLM to fix stubs that failed the quality gate."""
        system = (
            "You are a Python expert. Fix the following Python source code so it passes "
            "these quality checks:\n"
            "1. No syntax errors\n"
            "2. All functions must return a dict\n"
            "3. from rufus.models import StepContext must be importable\n\n"
            "Return ONLY the corrected Python source. Nothing else."
        )
        error_summary = "\n".join(f"- {e}" for e in errors)
        user = f"Errors:\n{error_summary}\n\nSource:\n{stubs_py}"
        logger.info("[Pipeline] Requesting stub repair via LLM")
        repaired = await self.stub_filler._call_llm(system=system, user=user, temperature=0.1)
        return repaired.strip()

    async def explain(self, workflow_yaml: str) -> str:
        """Explain an existing workflow YAML in plain English."""
        system = (
            "You are a workflow expert. Given a Rufus workflow YAML definition, "
            "explain what it does in plain English. Be concise (3-5 sentences). "
            "Focus on the business purpose, not the technical implementation."
        )
        user = f"Explain this workflow:\n\n{workflow_yaml}"
        return await self.intent_parser._call_llm(system=system, user=user, temperature=0.3)
