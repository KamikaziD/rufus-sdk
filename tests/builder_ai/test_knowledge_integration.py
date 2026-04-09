"""Integration tests for AIWorkflowBuilder + RAFTRouter knowledge base wiring.

All tests use mocked KnowledgeBase and mocked LLM stage calls so they run
without fastembed, lancedb, or an API key.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_chunk(chunk_type: str = "yaml_example", score: float = 0.8):
    from ruvon.builder_ai.knowledge.indexer import Chunk
    return Chunk(
        id="chunk-1",
        text="workflow_type: BidEvaluation\nsteps:\n  - name: Validate\n    type: STANDARD",
        source="config/bid_evaluation.yaml",
        section="BidEvaluation",
        chunk_type=chunk_type,
        score=score,
    )


def _make_kb(chunks=None):
    """Return a MagicMock KnowledgeBase that returns given chunks on retrieve."""
    from ruvon.builder_ai.knowledge.indexer import KnowledgeBase
    kb = MagicMock(spec=KnowledgeBase)
    kb.retrieve = AsyncMock(return_value=chunks or [_make_chunk()])
    kb.retrieve_fast = AsyncMock(return_value=chunks or [_make_chunk()])
    return kb


def _make_rag_decision(strategy: str = "rag", chunks=None):
    """Return a RetrievalDecision with the given strategy."""
    from ruvon.builder_ai.knowledge.raft_router import (
        RetrievalDecision, RetrievalStrategy, PrivacyLevel
    )
    return RetrievalDecision(
        strategy=RetrievalStrategy(strategy),
        chunks=chunks or [_make_chunk()],
        confidence=0.65,
        model_override=None,
        privacy_level=PrivacyLevel.BALANCED,
        pii_redactions=0,
        chunks_sent_to_cloud=False,
    )


# ---------------------------------------------------------------------------
# with_knowledge() classmethod
# ---------------------------------------------------------------------------

def test_with_knowledge_returns_builder_with_raft_router():
    """with_knowledge() should wire a RAFTRouter onto the builder."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder

    kb = _make_kb()
    builder = AIWorkflowBuilder(backend="anthropic", knowledge_base=kb)
    assert builder.raft_router is not None
    assert builder.knowledge_base is kb


def test_builder_without_knowledge_has_no_raft_router():
    """Without a KnowledgeBase, raft_router should be None."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder

    builder = AIWorkflowBuilder(backend="anthropic")
    assert builder.raft_router is None


def test_with_knowledge_classmethod_uses_existing_index(tmp_path):
    """AIWorkflowBuilder.with_knowledge() loads existing KB without rebuilding."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder
    from ruvon.builder_ai.knowledge.indexer import KnowledgeBase

    # Patch KnowledgeBase so it doesn't try to open LanceDB
    with patch("ruvon.builder_ai.pipeline._try_import_knowledge") as mock_import:
        MockKB = MagicMock()
        mock_instance = _make_kb()
        mock_instance.db_path = tmp_path / "knowledge.lance"
        mock_instance.db_path.parent.mkdir(parents=True, exist_ok=True)
        mock_instance.db_path.mkdir()
        MockKB.return_value = mock_instance
        MockKB.DEFAULT_DB_PATH = mock_instance.db_path

        MockRAFTRouter = MagicMock()
        MockPrivacyLevel = MagicMock()

        mock_import.return_value = (MockKB, MockRAFTRouter, MockPrivacyLevel)

        builder = AIWorkflowBuilder.with_knowledge(backend="anthropic")
        assert builder is not None


# ---------------------------------------------------------------------------
# BuildResult — retrieval_decision populated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_result_has_retrieval_decision_when_kb_present():
    """result.retrieval_decision should be set when a KnowledgeBase is wired."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder

    decision = _make_rag_decision("rag")
    kb = _make_kb()

    builder = AIWorkflowBuilder(backend="anthropic", knowledge_base=kb)

    # Patch the router's decide() to return a known decision
    builder.raft_router.decide = AsyncMock(return_value=decision)

    # Patch all LLM stage calls so they return minimal valid output
    _mock_all_stages(builder)

    result = await builder.build("build a bid evaluation workflow")

    assert result.retrieval_decision is not None
    assert result.retrieval_decision.strategy.value == "rag"
    assert result.retrieval_decision.confidence == 0.65


@pytest.mark.asyncio
async def test_build_result_retrieval_decision_none_without_kb():
    """result.retrieval_decision should be None when no KnowledgeBase is wired."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder

    builder = AIWorkflowBuilder(backend="anthropic")
    _mock_all_stages(builder)

    result = await builder.build("create a simple workflow")

    assert result.retrieval_decision is None


# ---------------------------------------------------------------------------
# RAFT strategy — model override applied to all stages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raft_strategy_overrides_model_on_all_stages():
    """When strategy=RAFT, all stage .model attrs should be updated to model_override."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder
    from ruvon.builder_ai.knowledge.raft_router import (
        RetrievalDecision, RetrievalStrategy, PrivacyLevel
    )

    raft_decision = RetrievalDecision(
        strategy=RetrievalStrategy.RAFT,
        chunks=[_make_chunk()],
        confidence=0.85,
        model_override="ruvon-expert",
        privacy_level=PrivacyLevel.BALANCED,
        pii_redactions=0,
        chunks_sent_to_cloud=False,
    )

    kb = _make_kb()
    builder = AIWorkflowBuilder(backend="ollama", model="llama3", knowledge_base=kb)
    builder.raft_router.decide = AsyncMock(return_value=raft_decision)
    _mock_all_stages(builder)

    await builder.build("configure an EDGE_MODEL_CALL with llm_config.data_sovereignty")

    # All LLM stages should have received the overridden model
    for stage in [builder.intent_parser, builder.step_planner,
                  builder.workflow_generator, builder.stub_filler]:
        assert stage.model == "ruvon-expert", (
            f"Stage {type(stage).__name__} model not updated to ruvon-expert"
        )


# ---------------------------------------------------------------------------
# NONE strategy — prompt unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_none_strategy_does_not_inject_knowledge():
    """NONE strategy: _inject_knowledge should return the system prompt unchanged."""
    from ruvon.builder_ai.stages.base import LLMStageMixin
    from ruvon.builder_ai.knowledge.raft_router import (
        RetrievalDecision, RetrievalStrategy, PrivacyLevel
    )

    mixin = LLMStageMixin(backend="anthropic")
    none_decision = RetrievalDecision(
        strategy=RetrievalStrategy.NONE,
        chunks=[],
        confidence=0.1,
        model_override=None,
        privacy_level=PrivacyLevel.BALANCED,
        pii_redactions=0,
        chunks_sent_to_cloud=False,
    )

    original = "You are a Ruvon workflow generator."
    result = mixin._inject_knowledge(original, none_decision, focus_types=["yaml_example"])

    assert result == original


def test_inject_knowledge_with_none_decision_unchanged():
    """_inject_knowledge(decision=None) must return system unchanged."""
    from ruvon.builder_ai.stages.base import LLMStageMixin

    mixin = LLMStageMixin(backend="anthropic")
    original = "Base system prompt."
    assert mixin._inject_knowledge(original, None) == original


# ---------------------------------------------------------------------------
# Privacy fields in BuildResult
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_result_privacy_fields_from_decision():
    """privacy_level, pii_redactions, chunks_sent_to_cloud should mirror the decision."""
    from ruvon.builder_ai.pipeline import AIWorkflowBuilder
    from ruvon.builder_ai.knowledge.raft_router import (
        RetrievalDecision, RetrievalStrategy, PrivacyLevel
    )

    cloud_decision = RetrievalDecision(
        strategy=RetrievalStrategy.RAG,
        chunks=[_make_chunk()],
        confidence=0.55,
        model_override=None,
        privacy_level=PrivacyLevel.CLOUD,
        pii_redactions=2,
        chunks_sent_to_cloud=True,
    )

    kb = _make_kb()
    builder = AIWorkflowBuilder(backend="anthropic", knowledge_base=kb, privacy_level="cloud")
    builder.raft_router.decide = AsyncMock(return_value=cloud_decision)
    _mock_all_stages(builder)

    result = await builder.build("any prompt")

    assert result.pii_redactions == 2
    assert result.chunks_sent_to_cloud is True


# ---------------------------------------------------------------------------
# Helper — mock all LLM stage calls so they return minimal valid output
# ---------------------------------------------------------------------------

def _mock_all_stages(builder) -> None:
    """Patch all async LLM calls to return minimal valid JSON strings."""
    import json

    intent_json = json.dumps({
        "description": "A simple test workflow",
        "trigger": "manual",
        "domain": "test",
        "edge_required": False,
        "ambiguities": [],
    })
    plan_json = json.dumps({
        "steps": [{"id": "Step1", "type": "STANDARD", "label": "Do something"}],
        "edges": [],
    })
    workflow_yaml = (
        "workflow_type: TestWorkflow\n"
        "initial_state_model: myapp.models:TestState\n"
        "steps:\n"
        "  - name: Step1\n"
        "    type: STANDARD\n"
        "    function: myapp.steps:step1\n"
    )
    lint_json = json.dumps([
        {"rule_id": "GOV-001", "severity": "INFO", "message": "OK", "passed": True}
    ])
    clarification_json = json.dumps({"needs_clarification": False, "questions": []})

    for stage in [builder.intent_parser, builder.step_planner,
                  builder.workflow_generator, builder.governance_linter,
                  builder.clarification_checker, builder.stub_filler]:
        stage._call_llm = AsyncMock(return_value=intent_json)

    builder.intent_parser._call_llm = AsyncMock(return_value=intent_json)
    builder.clarification_checker._call_llm = AsyncMock(return_value=clarification_json)
    builder.step_planner._call_llm = AsyncMock(return_value=plan_json)
    builder.workflow_generator._call_llm = AsyncMock(return_value=workflow_yaml)
    builder.governance_linter._call_llm = AsyncMock(return_value=lint_json)
    builder.stub_filler._call_llm = AsyncMock(return_value="def step1(state, context, **kw):\n    return {}\n")
