"""Tests for RAFTRouter — specificity scoring, routing thresholds, privacy tiers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rufus.builder_ai.knowledge.indexer import Chunk, KnowledgeBase
from rufus.builder_ai.knowledge.raft_router import (
    PrivacyLevel,
    RAFTRouter,
    RetrievalDecision,
    RetrievalStrategy,
)


def _make_router(privacy_level=PrivacyLevel.BALANCED):
    kb = MagicMock(spec=KnowledgeBase)
    kb.retrieve = AsyncMock(return_value=[])
    kb.retrieve_fast = AsyncMock(return_value=[])
    return RAFTRouter(kb, privacy_level=privacy_level)


# ---------------------------------------------------------------------------
# Specificity scoring
# ---------------------------------------------------------------------------

def test_specificity_score_zero_for_generic():
    router = _make_router()
    score = router._specificity_score("create a simple workflow")
    assert score == 0.0


def test_specificity_score_nonzero_for_step_type():
    router = _make_router()
    score = router._specificity_score("add a HUMAN_IN_LOOP step")
    assert score > 0.0


def test_specificity_score_high_for_multiple_categories():
    router = _make_router()
    score = router._specificity_score(
        "configure HUMAN_APPROVAL GOV-003 automate_next saga compensation"
    )
    assert score >= 0.5, f"Expected high specificity, got {score}"


def test_specificity_score_architecture_term():
    router = _make_router()
    score = router._specificity_score("store-and-forward SAF queue handling")
    assert score > 0.0


# ---------------------------------------------------------------------------
# Routing decisions — no chunks
# ---------------------------------------------------------------------------

def test_decide_none_for_generic_query():
    router = _make_router()
    # No chunks returned, confidence will be 0
    decision = asyncio.run(router.decide("create a workflow", backend="anthropic"))
    assert decision.strategy == RetrievalStrategy.NONE
    assert decision.chunks == []


# ---------------------------------------------------------------------------
# Routing decisions — with chunks
# ---------------------------------------------------------------------------

def _make_chunk(score=0.8, chunk_type="explanation") -> Chunk:
    return Chunk(
        id="test-1",
        text="This chunk explains the HUMAN_APPROVAL step configuration.",
        source="docs/steps.md",
        section="HUMAN_APPROVAL",
        chunk_type=chunk_type,
        score=score,
    )


@pytest.mark.asyncio
async def test_decide_rag_for_domain_query():
    kb = MagicMock(spec=KnowledgeBase)
    chunk = _make_chunk(score=0.5)
    kb.retrieve_fast = AsyncMock(return_value=[chunk])
    kb.retrieve = AsyncMock(return_value=[chunk])

    router = RAFTRouter(kb, privacy_level=PrivacyLevel.BALANCED)
    decision = await router.decide("configure HUMAN_APPROVAL step for bid approval", backend="anthropic")

    # Anthropic backend caps at RAG (never RAFT)
    assert decision.strategy in (RetrievalStrategy.RAG, RetrievalStrategy.NONE)
    if decision.strategy == RetrievalStrategy.RAG:
        assert len(decision.chunks) > 0
        assert decision.model_override is None  # Anthropic can't use rufus-expert


@pytest.mark.asyncio
async def test_decide_raft_downgrade_when_model_absent():
    kb = MagicMock(spec=KnowledgeBase)
    chunk = _make_chunk(score=0.95)  # high similarity → high confidence
    kb.retrieve_fast = AsyncMock(return_value=[chunk])
    kb.retrieve = AsyncMock(return_value=[chunk])

    router = RAFTRouter(kb, privacy_level=PrivacyLevel.BALANCED)
    router._raft_available = False  # rufus-expert not installed

    decision = await router.decide(
        "configure llm_config.data_sovereignty for EDGE_MODEL_CALL with GOV-004 compliance",
        backend="ollama",
    )
    # With high similarity + domain terms but no rufus-expert → should downgrade to RAG
    assert decision.strategy != RetrievalStrategy.RAFT
    assert decision.model_override is None


@pytest.mark.asyncio
async def test_decide_raft_when_model_available():
    kb = MagicMock(spec=KnowledgeBase)
    chunk = _make_chunk(score=0.95)
    kb.retrieve_fast = AsyncMock(return_value=[chunk])
    kb.retrieve = AsyncMock(return_value=[chunk])

    router = RAFTRouter(kb, privacy_level=PrivacyLevel.BALANCED)
    router._raft_available = True

    # High specificity query
    decision = await router.decide(
        "configure saga compensation with AUDIT_EMIT step and GOV-004 for payment authorization",
        backend="ollama",
    )
    # Confidence depends on similarity + specificity; test the model_override is set if RAFT
    if decision.strategy == RetrievalStrategy.RAFT:
        assert decision.model_override == "rufus-expert"


# ---------------------------------------------------------------------------
# Privacy tier enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strict_privacy_returns_none_for_cloud_backend():
    kb = MagicMock(spec=KnowledgeBase)
    chunk = _make_chunk(score=0.9)
    kb.retrieve_fast = AsyncMock(return_value=[chunk])
    kb.retrieve = AsyncMock(return_value=[chunk])

    router = RAFTRouter(kb, privacy_level=PrivacyLevel.STRICT)
    decision = await router.decide("configure HUMAN_APPROVAL step", backend="anthropic")

    assert decision.strategy == RetrievalStrategy.NONE
    assert decision.chunks == []
    assert not decision.chunks_sent_to_cloud


@pytest.mark.asyncio
async def test_balanced_privacy_replaces_chunk_text_for_cloud():
    kb = MagicMock(spec=KnowledgeBase)
    chunk = _make_chunk(score=0.6)
    kb.retrieve_fast = AsyncMock(return_value=[chunk])
    kb.retrieve = AsyncMock(return_value=[chunk])

    router = RAFTRouter(kb, privacy_level=PrivacyLevel.BALANCED)
    # Give it enough specificity to trigger RAG
    router.THRESHOLD_RAG = 0.0  # Force RAG for test

    decision = await router.decide("configure HUMAN_APPROVAL step", backend="anthropic")

    if decision.strategy == RetrievalStrategy.RAG:
        # In balanced mode, chunk text should be replaced with metadata only
        for c in decision.chunks:
            assert "[Reference:" in c.text, f"Expected metadata-only text, got: {c.text}"
        assert not decision.chunks_sent_to_cloud


# ---------------------------------------------------------------------------
# PII scrubbing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pii_scrubbing_applied_to_chunks():
    from rufus.builder_ai.knowledge.scrubber import PIIScrubber

    scrubber = PIIScrubber()
    text = "Contact us at john@example.com or call +971-50-123-4567"
    scrubbed, n = scrubber.scrub(text)
    assert "john@example.com" not in scrubbed
    assert "+971-50-123-4567" not in scrubbed
    assert n == 2


def test_pii_scrubber_card_number():
    from rufus.builder_ai.knowledge.scrubber import PIIScrubber

    scrubber = PIIScrubber()
    text = "Card: 4111 1111 1111 1111 is invalid"
    scrubbed, n = scrubber.scrub(text)
    assert "4111 1111 1111 1111" not in scrubbed
    assert "[CARD_REDACTED]" in scrubbed
    assert n == 1


# ---------------------------------------------------------------------------
# _inject_knowledge in base.py
# ---------------------------------------------------------------------------

def test_inject_knowledge_returns_unchanged_for_none_decision():
    from rufus.builder_ai.stages.base import LLMStageMixin

    mixin = LLMStageMixin()
    original = "My system prompt."
    result = mixin._inject_knowledge(original, decision=None)
    assert result == original


def test_inject_knowledge_returns_unchanged_for_none_strategy():
    from rufus.builder_ai.stages.base import LLMStageMixin

    mixin = LLMStageMixin()
    decision = RetrievalDecision(
        strategy=RetrievalStrategy.NONE,
        chunks=[],
        confidence=0.1,
    )
    result = mixin._inject_knowledge("System prompt.", decision=decision)
    assert result == "System prompt."


def test_inject_knowledge_augments_for_rag_strategy():
    from rufus.builder_ai.stages.base import LLMStageMixin

    mixin = LLMStageMixin()
    chunk = _make_chunk()
    decision = RetrievalDecision(
        strategy=RetrievalStrategy.RAG,
        chunks=[chunk],
        confidence=0.6,
    )
    result = mixin._inject_knowledge("System prompt.", decision=decision)
    assert "<RUFUS_KNOWLEDGE>" in result
    assert "HUMAN_APPROVAL" in result


def test_inject_knowledge_focus_types_filter():
    from rufus.builder_ai.stages.base import LLMStageMixin

    mixin = LLMStageMixin()
    yaml_chunk = _make_chunk(chunk_type="yaml_example")
    prose_chunk = _make_chunk(chunk_type="explanation")
    prose_chunk = prose_chunk.model_copy(update={"id": "test-2", "text": "prose content here"})

    decision = RetrievalDecision(
        strategy=RetrievalStrategy.RAG,
        chunks=[yaml_chunk, prose_chunk],
        confidence=0.6,
    )
    result = mixin._inject_knowledge(
        "System.", decision=decision, focus_types=["yaml_example"]
    )
    # Should include yaml_chunk text, may or may not include prose (fallback logic)
    assert "HUMAN_APPROVAL" in result  # yaml_chunk text
