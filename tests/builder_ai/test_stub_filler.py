"""Tests for Stage 9 — StubFiller."""

import pytest
from unittest.mock import AsyncMock

from rufus.builder_ai.stages.stub_filler import StubFiller
from rufus.builder_ai.stages.stub_generator import StubGenerator


SAMPLE_STUBS = (
    '"""Auto-generated step stubs."""\n'
    "from rufus.models import StepContext\n\n\n"
    "def parse_bid(state, context: StepContext):\n"
    '    """Step: Parse_Bid"""\n'
    "    # TODO: implement\n"
    "    return {}\n\n\n"
    "def score_bid(state, context: StepContext):\n"
    '    """Step: Score_Bid"""\n'
    "    # TODO: implement\n"
    "    return {}\n"
)


def _filler(**kwargs):
    return StubFiller(backend="anthropic", model="claude-sonnet-4-6", api_key="test", **kwargs)


class TestStubFillerFill:
    @pytest.mark.asyncio
    async def test_fill_returns_string(self):
        filler = _filler()
        filler._call_llm = AsyncMock(return_value="    amount = state.amount\n    return {'amount': amount}")
        body = await filler.fill(
            func_name="parse_bid",
            signature="def parse_bid(state, context: StepContext):",
            description="Extract amount and currency from state",
        )
        assert isinstance(body, str)
        assert len(body) > 0

    @pytest.mark.asyncio
    async def test_fill_strips_trailing_whitespace(self):
        filler = _filler()
        filler._call_llm = AsyncMock(return_value="    return {}\n\n\n")
        body = await filler.fill("f", "def f(s, c):", "do nothing")
        assert not body.endswith("\n")


class TestStubFillerApplyBody:
    def test_replaces_todo_body(self):
        filler = _filler()
        new_body = "    amount = state.amount\n    return {'amount': amount}"
        updated = filler.apply_body(SAMPLE_STUBS, "parse_bid", new_body)
        assert "# TODO: implement" not in updated.split("def score_bid")[0]
        assert "amount = state.amount" in updated

    def test_does_not_affect_other_functions(self):
        filler = _filler()
        updated = filler.apply_body(SAMPLE_STUBS, "parse_bid", "    return {'ok': True}")
        # score_bid TODO should remain
        assert "# TODO: implement" in updated.split("def score_bid")[1]

    def test_function_not_found_returns_unchanged(self):
        filler = _filler()
        result = filler.apply_body(SAMPLE_STUBS, "nonexistent_func", "    return {}")
        assert result == SAMPLE_STUBS

    def test_auto_indents_body(self):
        filler = _filler()
        # Body without leading spaces — should be auto-indented
        updated = filler.apply_body(SAMPLE_STUBS, "parse_bid", "return {'x': 1}")
        assert "    return {'x': 1}" in updated


class TestStubFillerFillAndApply:
    @pytest.mark.asyncio
    async def test_fill_and_apply_end_to_end(self):
        filler = _filler()
        filler._call_llm = AsyncMock(return_value="    return {'parsed': True}")
        updated = await filler.fill_and_apply(
            stubs_py=SAMPLE_STUBS,
            func_name="parse_bid",
            signature="def parse_bid(state, context: StepContext):",
            description="Return a dict indicating the bid was parsed",
        )
        assert "parsed" in updated
        assert "# TODO: implement" not in updated.split("def score_bid")[0]

    @pytest.mark.asyncio
    async def test_generated_stubs_can_be_filled(self):
        """Full round-trip: generate stubs → fill one → validate."""
        steps = [
            {"name": "Parse_Bid", "type": "STANDARD", "function": "myapp.parse_bid"},
            {"name": "Score_Bid", "type": "STANDARD", "function": "myapp.score_bid"},
        ]
        stubs = StubGenerator().generate({"steps": steps})
        assert stubs is not None

        filler = _filler()
        filler._call_llm = AsyncMock(return_value="    return {'amount': 100}")
        updated = await filler.fill_and_apply(
            stubs_py=stubs,
            func_name="parse_bid",
            signature="def parse_bid(state, context: StepContext):",
            description="Return amount 100",
        )
        assert "amount" in updated
        # score_bid still has TODO
        assert "# TODO: implement" in updated.split("def score_bid")[1]

        # Updated stubs should still pass quality gates
        errors = StubGenerator().validate_stubs(updated)
        assert errors == [], f"Quality gate failed after fill: {errors}"
