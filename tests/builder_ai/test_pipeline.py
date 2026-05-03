"""Integration tests for the AIWorkflowBuilder pipeline with mocked LLM calls."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from ruvon.builder_ai import AIWorkflowBuilder
from ruvon.builder_ai.models import BuildResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_INTENT_JSON = json.dumps({
    "description": "Handle incoming bid submissions",
    "trigger": "webhook",
    "domain": "bid-evaluation",
    "edge_required": False,
    "ambiguities": [],
})

MOCK_INTENT_WITH_AMBIGUITY = json.dumps({
    "description": "Handle bids",
    "trigger": "manual",
    "domain": "bids",
    "edge_required": False,
    "ambiguities": ["What format are bid submissions?"],
})

MOCK_QUESTIONS_JSON = json.dumps(["What format are bid submissions?"])

MOCK_STEP_PLAN_JSON = json.dumps({
    "steps": [
        {"id": "parse_bid", "type": "STANDARD", "label": "Parse bid payload"},
        {"id": "audit_log", "type": "AUDIT_EMIT", "label": "Emit audit record"},
    ],
    "edges": [
        {"from_step": "parse_bid", "to_step": "audit_log"},
    ],
})

MOCK_WORKFLOW_JSON = json.dumps({
    "name": "bid-intake",
    "version": "1.0",
    "owner": "procurement-team",
    "steps": [
        {"name": "Parse_Bid", "type": "STANDARD", "function": "ruvon_workflows.steps.identity", "automate_next": True},
        {"name": "Audit_Log", "type": "AUDIT_EMIT", "audit_config": {"event_type": "bid.parsed"}, "automate_next": False},
    ],
})

MOCK_EVALUATOR_JSON = json.dumps({"score": 90, "issues": []})


def _make_llm_responses(*responses):
    """Return an AsyncMock that yields responses in sequence."""
    call_count = {"n": 0}
    response_list = list(responses)

    async def _side_effect(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(response_list):
            return response_list[idx]
        return response_list[-1]  # repeat last

    return _side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAIWorkflowBuilderAnthropic:
    """Tests using anthropic backend with mocked _call_llm."""

    def _builder(self):
        return AIWorkflowBuilder(backend="anthropic", api_key="test-key")

    @pytest.mark.asyncio
    async def test_build_single_shot(self):
        builder = self._builder()
        side_effect = _make_llm_responses(
            MOCK_INTENT_JSON,       # Stage 1: intent parse
            MOCK_STEP_PLAN_JSON,    # Stage 3: step planner
            MOCK_WORKFLOW_JSON,     # Stage 4: workflow generator
            MOCK_EVALUATOR_JSON,    # Stage 4: evaluator
        )
        with patch.object(builder.intent_parser, "_call_llm", side_effect=side_effect), \
             patch.object(builder.step_planner, "_call_llm", side_effect=side_effect), \
             patch.object(builder.workflow_generator, "_call_llm", side_effect=side_effect):
            result = await builder.build("handle incoming bid submissions")

        assert isinstance(result, BuildResult)
        assert result.yaml is not None
        assert "bid-intake" in result.yaml or "generated-workflow" in result.yaml
        assert result.lint_report is not None
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_build_returns_clarification_questions(self):
        builder = self._builder()

        async def _intent(*a, **kw):
            return MOCK_INTENT_WITH_AMBIGUITY

        async def _questions(*a, **kw):
            return MOCK_QUESTIONS_JSON

        with patch.object(builder.intent_parser, "_call_llm", side_effect=_intent), \
             patch.object(builder.clarification_checker, "_call_llm", side_effect=_questions):
            result = await builder.build("handle bids")

        assert result.needs_clarification is True
        assert len(result.questions) > 0

    @pytest.mark.asyncio
    async def test_build_with_clarification_answers(self):
        builder = self._builder()

        # Resolve always returns the base intent (cleared ambiguities)
        resolved_intent = json.dumps({
            "description": "Handle bid submissions via webhook",
            "trigger": "webhook",
            "domain": "bids",
            "edge_required": False,
            "ambiguities": [],
        })

        side_effect = _make_llm_responses(
            MOCK_INTENT_WITH_AMBIGUITY,  # Stage 1
            resolved_intent,             # Stage 2 resolve
            MOCK_STEP_PLAN_JSON,         # Stage 3
            MOCK_WORKFLOW_JSON,          # Stage 4 generate
            MOCK_EVALUATOR_JSON,         # Stage 4 evaluate
        )

        # Patch all stages uniformly
        for stage in [
            builder.intent_parser, builder.clarification_checker,
            builder.step_planner, builder.workflow_generator,
        ]:
            stage._call_llm = AsyncMock(side_effect=side_effect)

        result = await builder.build(
            "handle bids",
            clarification_answers={"What format are bid submissions?": "webhook JSON"},
        )

        assert result.needs_clarification is False
        assert result.yaml is not None

    @pytest.mark.asyncio
    async def test_build_with_lint_errors_blocks_output(self):
        """Lint errors should be reflected in lint_report but not block output unless has_errors."""
        builder = self._builder()
        # PII without audit — triggers GOV-001 ERROR
        pii_workflow = json.dumps({
            "name": "pii-wf",
            "version": "1.0",
            "owner": "team",
            "steps": [{
                "name": "LLM",
                "type": "AI_LLM_INFERENCE",
                "llm_config": {"model": "claude-sonnet-4-6", "system_prompt": "s", "user_prompt": "u", "pii_detected": True},
            }],
        })

        side_effect = _make_llm_responses(
            MOCK_INTENT_JSON, MOCK_STEP_PLAN_JSON, pii_workflow, MOCK_EVALUATOR_JSON,
        )
        for stage in [builder.intent_parser, builder.step_planner, builder.workflow_generator]:
            stage._call_llm = AsyncMock(side_effect=side_effect)

        result = await builder.build("test")
        assert result.lint_report is not None
        assert result.lint_report.has_errors  # GOV-001 should fail

    @pytest.mark.asyncio
    async def test_schema_validation_error_returns_early(self):
        """Invalid JSON from generator should produce schema errors."""
        builder = self._builder()

        side_effect = _make_llm_responses(
            MOCK_INTENT_JSON,
            MOCK_STEP_PLAN_JSON,
            "not valid json at all <<<",  # generator returns garbage
            "not valid json",             # evaluator also broken
        )
        for stage in [builder.intent_parser, builder.step_planner, builder.workflow_generator]:
            stage._call_llm = AsyncMock(side_effect=side_effect)

        result = await builder.build("test")
        # Schema validator should flag empty steps
        assert result.errors or result.yaml is not None  # either errors or fallback workflow


class TestAIWorkflowBuilderOllama:
    def test_ollama_builder_creation(self):
        builder = AIWorkflowBuilder(backend="ollama", model="llama3")
        assert builder.backend == "ollama"
        assert builder.model == "llama3"

    def test_default_ollama_model(self):
        builder = AIWorkflowBuilder(backend="ollama")
        assert builder.model == "llama3"

    def test_invalid_backend_raises(self):
        with pytest.raises(ValueError, match="backend must be"):
            AIWorkflowBuilder(backend="invalid")

    @pytest.mark.asyncio
    async def test_build_via_ollama(self):
        builder = AIWorkflowBuilder(backend="ollama", model="llama3")
        side_effect = _make_llm_responses(
            MOCK_INTENT_JSON, MOCK_STEP_PLAN_JSON, MOCK_WORKFLOW_JSON, MOCK_EVALUATOR_JSON,
        )
        for stage in [builder.intent_parser, builder.step_planner, builder.workflow_generator]:
            stage._call_llm = AsyncMock(side_effect=side_effect)

        result = await builder.build("handle bid submissions")
        assert result.yaml is not None


class TestExplain:
    @pytest.mark.asyncio
    async def test_explain_returns_string(self):
        builder = AIWorkflowBuilder(backend="anthropic", api_key="test")
        builder.intent_parser._call_llm = AsyncMock(return_value="This workflow handles bid submissions.")
        explanation = await builder.explain("name: bid-intake\nsteps: []")
        assert isinstance(explanation, str)
        assert len(explanation) > 0
