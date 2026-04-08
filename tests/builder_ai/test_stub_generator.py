"""Tests for Stage 8 — StubGenerator."""

import pytest
from ruvon.builder_ai.stages.stub_generator import StubGenerator, _snake


# ---------------------------------------------------------------------------
# _snake helper
# ---------------------------------------------------------------------------

class TestSnake:
    def test_pascal_case(self):
        assert _snake("ParseBid") == "parse_bid"

    def test_screaming_snake(self):
        assert _snake("Parse_Bid") == "parse_bid"

    def test_already_lower(self):
        assert _snake("parse_bid") == "parse_bid"

    def test_with_spaces(self):
        assert _snake("Parse Bid") == "parse_bid"

    def test_acronym(self):
        assert _snake("ParseHTTPRequest") == "parse_http_request"


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestStubGeneratorGenerate:
    def _gen(self, steps):
        return StubGenerator().generate({"steps": steps})

    def test_no_standard_steps_returns_none(self):
        steps = [
            {"name": "Audit", "type": "AUDIT_EMIT", "audit_config": {"event_type": "x"}},
        ]
        assert self._gen(steps) is None

    def test_standard_step_without_function_returns_none(self):
        steps = [{"name": "Parse", "type": "STANDARD"}]
        assert self._gen(steps) is None

    def test_single_standard_step(self):
        steps = [{"name": "Parse_Bid", "type": "STANDARD", "function": "myapp.steps.parse_bid"}]
        result = self._gen(steps)
        assert result is not None
        assert "def parse_bid(state, context: StepContext)" in result
        assert "# TODO: implement" in result
        assert "return {}" in result

    def test_dedup_same_function_used_twice(self):
        steps = [
            {"name": "Step1", "type": "STANDARD", "function": "myapp.steps.validate"},
            {"name": "Step2", "type": "STANDARD", "function": "myapp.steps.validate"},
        ]
        result = self._gen(steps)
        assert result is not None
        # Only one definition
        assert result.count("def validate(") == 1

    def test_required_input_in_signature(self):
        steps = [{
            "name": "Score",
            "type": "STANDARD",
            "function": "myapp.steps.score_bid",
            "required_input": ["threshold", "currency"],
        }]
        result = self._gen(steps)
        assert "threshold=None" in result
        assert "currency=None" in result

    def test_import_line_present(self):
        steps = [{"name": "X", "type": "STANDARD", "function": "m.x"}]
        result = self._gen(steps)
        assert "from ruvon.models import StepContext" in result

    def test_mixed_step_types_only_standard_get_stubs(self):
        steps = [
            {"name": "Parse", "type": "STANDARD", "function": "myapp.parse"},
            {"name": "Audit", "type": "AUDIT_EMIT", "audit_config": {"event_type": "e"}},
            {"name": "Score", "type": "STANDARD", "function": "myapp.score"},
        ]
        result = self._gen(steps)
        assert result is not None
        assert "def parse(" in result
        assert "def score(" in result
        # No mention of AuditEmit logic
        assert "audit" not in result.lower() or "Step: Audit" not in result

    def test_empty_steps_returns_none(self):
        assert self._gen([]) is None

    def test_module_name_in_docstring(self):
        steps = [{"name": "X", "type": "STANDARD", "function": "m.x"}]
        result = StubGenerator().generate({"steps": steps}, module_name="myapp.steps")
        assert "myapp.steps" in result


# ---------------------------------------------------------------------------
# validate_stubs()
# ---------------------------------------------------------------------------

class TestStubGeneratorValidate:
    def _validator(self):
        return StubGenerator()

    def test_valid_stubs_pass(self):
        stubs = (
            "from ruvon.models import StepContext\n\n"
            "def parse_bid(state, context: StepContext):\n"
            "    return {}\n"
        )
        errors = self._validator().validate_stubs(stubs)
        assert errors == []

    def test_syntax_error_caught(self):
        stubs = "def broken(state context):\n    return {}\n"
        errors = self._validator().validate_stubs(stubs)
        assert any("SYNTAX" in e for e in errors)

    def test_wrong_return_type_caught(self):
        stubs = (
            "from ruvon.models import StepContext\n\n"
            "def bad_return(state, context):\n"
            "    return 'not a dict'\n"
        )
        errors = self._validator().validate_stubs(stubs)
        assert any("RETURN_TYPE" in e for e in errors)

    def test_exec_error_caught(self):
        stubs = (
            "from ruvon.models import StepContext\n\n"
            "def crasher(state, context):\n"
            "    raise RuntimeError('boom')\n"
        )
        errors = self._validator().validate_stubs(stubs)
        assert any("EXEC" in e for e in errors)

    def test_todo_stubs_pass_gate(self):
        """Stubs with only TODO bodies should pass all gates — {} is a valid dict."""
        steps = [
            {"name": "Parse", "type": "STANDARD", "function": "myapp.parse"},
            {"name": "Score", "type": "STANDARD", "function": "myapp.score"},
        ]
        stubs = StubGenerator().generate({"steps": steps})
        assert stubs is not None
        errors = StubGenerator().validate_stubs(stubs)
        assert errors == [], f"Unexpected errors: {errors}"
