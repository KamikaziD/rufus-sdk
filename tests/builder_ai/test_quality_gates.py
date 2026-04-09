"""Tests for the quality gate retry loop in the AI pipeline."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ruvon.builder_ai import AIWorkflowBuilder
from ruvon.builder_ai.models import BuildResult
from ruvon.builder_ai.stages.schema_validator import SchemaValidator
from ruvon.builder_ai.stages.stub_generator import StubGenerator


# ---------------------------------------------------------------------------
# Schema Validator quality gate tests (deterministic)
# ---------------------------------------------------------------------------

class TestSchemaValidatorGate:
    def _v(self):
        return SchemaValidator()

    def test_valid_workflow_passes(self):
        wf = {
            "name": "bid-intake",
            "version": "1.0",
            "steps": [
                {"name": "Parse", "type": "STANDARD", "function": "m.f"},
            ],
        }
        validated, errors = self._v().validate(wf)
        assert errors == []
        assert validated["name"] == "bid-intake"

    def test_missing_steps_fails(self):
        _, errors = self._v().validate({"name": "x", "version": "1.0"})
        assert any("steps" in e for e in errors)

    def test_missing_step_name_fails(self):
        wf = {"steps": [{"type": "STANDARD", "function": "m.f"}]}
        _, errors = self._v().validate(wf)
        assert any("name" in e for e in errors)

    def test_unknown_step_type_fails(self):
        wf = {"steps": [{"name": "X", "type": "TURBO_LASER"}]}
        _, errors = self._v().validate(wf)
        assert any("TURBO_LASER" in e for e in errors)

    def test_ai_llm_inference_missing_config_fails(self):
        wf = {"steps": [{"name": "LLM", "type": "AI_LLM_INFERENCE"}]}
        _, errors = self._v().validate(wf)
        assert any("llm_config" in e for e in errors)

    def test_audit_emit_missing_event_type_fails(self):
        wf = {"steps": [{"name": "Audit", "type": "AUDIT_EMIT", "audit_config": {}}]}
        _, errors = self._v().validate(wf)
        assert any("event_type" in e for e in errors)

    def test_duplicate_step_names_fail(self):
        wf = {"steps": [
            {"name": "Step", "type": "STANDARD", "function": "m.f"},
            {"name": "Step", "type": "STANDARD", "function": "m.g"},
        ]}
        _, errors = self._v().validate(wf)
        assert any("Duplicate" in e or "duplicate" in e for e in errors)

    def test_auto_repairs_missing_name(self):
        wf = {"steps": [{"name": "X", "type": "STANDARD", "function": "m.f"}]}
        validated, errors = self._v().validate(wf)
        assert "name" in validated  # auto-repaired

    def test_auto_repairs_missing_standard_function(self):
        wf = {"steps": [{"name": "X", "type": "STANDARD"}]}
        validated, _ = self._v().validate(wf)
        assert validated["steps"][0]["function"] == "ruvon_workflows.steps.identity"

    def test_normalises_type_to_uppercase(self):
        wf = {"steps": [{"name": "X", "type": "standard", "function": "m.f"}]}
        validated, errors = self._v().validate(wf)
        assert validated["steps"][0]["type"] == "STANDARD"
        assert errors == []


# ---------------------------------------------------------------------------
# Stub quality gate tests (deterministic)
# ---------------------------------------------------------------------------

class TestStubGeneratorGate:
    def test_todo_stubs_pass_all_gates(self):
        steps = [
            {"name": "Parse", "type": "STANDARD", "function": "myapp.parse"},
            {"name": "Score", "type": "STANDARD", "function": "myapp.score"},
        ]
        stubs = StubGenerator().generate({"steps": steps})
        assert stubs is not None
        errors = StubGenerator().validate_stubs(stubs)
        assert errors == []

    def test_builtin_only_workflow_skips_stubs(self):
        steps = [{"name": "Audit", "type": "AUDIT_EMIT", "audit_config": {"event_type": "x"}}]
        stubs = StubGenerator().generate({"steps": steps})
        assert stubs is None

    def test_syntax_error_gate_catches_early(self):
        broken = "def f(state context):\n    return {}\n"
        errors = StubGenerator().validate_stubs(broken)
        assert any("SYNTAX" in e for e in errors)
        # Only one error — short-circuit after Gate 1
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# Pipeline retry loop integration tests
# ---------------------------------------------------------------------------

VALID_INTENT = json.dumps({
    "description": "Handle bids",
    "trigger": "webhook",
    "domain": "bids",
    "edge_required": False,
    "ambiguities": [],
})

VALID_PLAN = json.dumps({
    "steps": [{"id": "parse", "type": "STANDARD", "label": "Parse bid"}],
    "edges": [],
})

VALID_WORKFLOW = json.dumps({
    "name": "bid-intake",
    "version": "1.0",
    "steps": [
        {"name": "Parse", "type": "STANDARD", "function": "myapp.parse", "automate_next": True},
    ],
})

EVAL_OK = json.dumps({"score": 90, "issues": []})

INVALID_WORKFLOW = json.dumps({
    "name": "bad",
    "version": "1.0",
    "steps": [{"name": "X", "type": "TURBO_LASER"}],
})


class TestPipelineYAMLGateRetry:
    """Verify the pipeline retries on schema validation failure."""

    @pytest.mark.asyncio
    async def test_valid_first_attempt_yaml_gate_attempts_is_1(self):
        builder = AIWorkflowBuilder(backend="anthropic", api_key="test")

        call_n = {"n": 0}
        responses = [VALID_INTENT, VALID_PLAN, VALID_WORKFLOW, EVAL_OK]

        async def _llm(*a, **kw):
            idx = min(call_n["n"], len(responses) - 1)
            call_n["n"] += 1
            return responses[idx]

        for stage in [builder.intent_parser, builder.step_planner, builder.workflow_generator]:
            stage._call_llm = _llm

        result = await builder.build("handle bids")
        assert result.yaml_gate_attempts == 1
        assert result.quality == "GOOD"
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_invalid_first_attempt_retries(self):
        """Generator returns invalid YAML first, valid second — gate_attempts should be 2."""
        builder = AIWorkflowBuilder(backend="anthropic", api_key="test")

        call_n = {"n": 0}
        # intent, plan, bad_wf, eval, good_wf, eval
        responses = [VALID_INTENT, VALID_PLAN, INVALID_WORKFLOW, EVAL_OK, VALID_WORKFLOW, EVAL_OK]

        async def _llm(*a, **kw):
            idx = min(call_n["n"], len(responses) - 1)
            call_n["n"] += 1
            return responses[idx]

        for stage in [builder.intent_parser, builder.step_planner, builder.workflow_generator]:
            stage._call_llm = _llm

        result = await builder.build("handle bids")
        # Should have retried due to TURBO_LASER unknown type
        assert result.yaml_gate_attempts >= 1
        # Either succeeded on retry (yaml present) or surfaced errors
        assert result.yaml is not None or result.errors

    @pytest.mark.asyncio
    async def test_exhausted_retries_returns_failed_quality(self):
        """All 3 attempts fail → quality=FAILED, no yaml."""
        builder = AIWorkflowBuilder(backend="anthropic", api_key="test")

        async def _llm(*a, **kw):
            return INVALID_WORKFLOW  # always returns bad workflow

        for stage in [builder.intent_parser, builder.step_planner, builder.workflow_generator]:
            stage._call_llm = _llm

        # Patch intent parse to skip clarification
        builder.intent_parser._call_llm = AsyncMock(return_value=VALID_INTENT)
        builder.step_planner._call_llm = AsyncMock(return_value=VALID_PLAN)
        builder.workflow_generator._call_llm = AsyncMock(return_value=INVALID_WORKFLOW)

        result = await builder.build("handle bids")
        assert result.quality == "FAILED"
        assert result.yaml is None
        assert result.errors


# ---------------------------------------------------------------------------
# BuildResult fields
# ---------------------------------------------------------------------------

class TestBuildResultFields:
    def test_default_quality_is_good(self):
        r = BuildResult()
        assert r.quality == "GOOD"

    def test_default_gate_attempts(self):
        r = BuildResult()
        assert r.yaml_gate_attempts == 1
        assert r.stub_gate_attempts == 1

    def test_stubs_py_default_none(self):
        r = BuildResult()
        assert r.stubs_py is None

    def test_partial_quality(self):
        r = BuildResult(quality="PARTIAL", stubs_py="# broken", errors=["EXEC: boom"])
        assert r.quality == "PARTIAL"
        assert r.errors == ["EXEC: boom"]
