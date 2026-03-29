"""Tests for knowledge/retriever.py — two-stage retrieval public API."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — build a fake Chunk and KnowledgeBase
# ---------------------------------------------------------------------------

def _make_chunk(chunk_type: str = "explanation", score: float = 0.85, text: str = "Some text."):
    from rufus.builder_ai.knowledge.indexer import Chunk
    return Chunk(
        id="test-1",
        text=text,
        source="docs/test.md",
        section="## Test Section",
        chunk_type=chunk_type,
        score=score,
    )


def _make_kb(chunks_fast=None, chunks_full=None):
    """Return a mock KnowledgeBase whose retrieve* methods return the given lists."""
    kb = MagicMock()
    kb.retrieve_fast = AsyncMock(return_value=chunks_fast or [])
    kb.retrieve = AsyncMock(return_value=chunks_full or [])
    return kb


# ---------------------------------------------------------------------------
# retrieve_for_routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrieve_for_routing_calls_retrieve_fast():
    from rufus.builder_ai.knowledge.retriever import retrieve_for_routing
    chunks = [_make_chunk(score=0.9), _make_chunk(score=0.7)]
    kb = _make_kb(chunks_fast=chunks)

    result = await retrieve_for_routing(kb, "configure HUMAN_APPROVAL timeout")

    kb.retrieve_fast.assert_awaited_once_with("configure HUMAN_APPROVAL timeout", top_k=10)
    assert result == chunks


@pytest.mark.asyncio
async def test_retrieve_for_routing_custom_top_k():
    from rufus.builder_ai.knowledge.retriever import retrieve_for_routing
    kb = _make_kb(chunks_fast=[_make_chunk()])

    await retrieve_for_routing(kb, "query", top_k=5)

    kb.retrieve_fast.assert_awaited_once_with("query", top_k=5)


@pytest.mark.asyncio
async def test_retrieve_for_routing_returns_empty_on_no_match():
    from rufus.builder_ai.knowledge.retriever import retrieve_for_routing
    kb = _make_kb(chunks_fast=[])

    result = await retrieve_for_routing(kb, "create a workflow")
    assert result == []


# ---------------------------------------------------------------------------
# retrieve_for_injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrieve_for_injection_calls_retrieve():
    from rufus.builder_ai.knowledge.retriever import retrieve_for_injection
    chunks = [_make_chunk(chunk_type="yaml_example", score=0.88)]
    kb = _make_kb(chunks_full=chunks)

    result = await retrieve_for_injection(kb, "bid evaluation workflow")

    kb.retrieve.assert_awaited_once_with("bid evaluation workflow", top_k=5)
    assert result == chunks


@pytest.mark.asyncio
async def test_retrieve_for_injection_filters_by_focus_types():
    from rufus.builder_ai.knowledge.retriever import retrieve_for_injection
    yaml_chunk = _make_chunk(chunk_type="yaml_example", score=0.9)
    explanation_chunk = _make_chunk(chunk_type="explanation", score=0.8)
    kb = _make_kb(chunks_full=[yaml_chunk, explanation_chunk])

    result = await retrieve_for_injection(
        kb, "query", focus_types=["yaml_example"]
    )
    assert result == [yaml_chunk]
    assert all(c.chunk_type == "yaml_example" for c in result)


@pytest.mark.asyncio
async def test_retrieve_for_injection_falls_back_when_no_focus_match():
    """If focus_types filter produces nothing, return all chunks (safety fallback)."""
    from rufus.builder_ai.knowledge.retriever import retrieve_for_injection
    explanation_chunk = _make_chunk(chunk_type="explanation", score=0.8)
    kb = _make_kb(chunks_full=[explanation_chunk])

    result = await retrieve_for_injection(
        kb, "query", focus_types=["yaml_example"]  # none match
    )
    assert result == [explanation_chunk]  # falls back to all


@pytest.mark.asyncio
async def test_retrieve_for_injection_no_focus_types_returns_all():
    from rufus.builder_ai.knowledge.retriever import retrieve_for_injection
    chunks = [_make_chunk("yaml_example"), _make_chunk("lesson"), _make_chunk("explanation")]
    kb = _make_kb(chunks_full=chunks)

    result = await retrieve_for_injection(kb, "saga compensation")
    assert result == chunks


# ---------------------------------------------------------------------------
# max_similarity
# ---------------------------------------------------------------------------

def test_max_similarity_returns_highest_score():
    from rufus.builder_ai.knowledge.retriever import max_similarity
    from rufus.builder_ai.knowledge.indexer import Chunk

    chunks = [_make_chunk(score=0.5), _make_chunk(score=0.9), _make_chunk(score=0.3)]
    assert max_similarity(chunks) == pytest.approx(0.9)


def test_max_similarity_empty_returns_zero():
    from rufus.builder_ai.knowledge.retriever import max_similarity
    assert max_similarity([]) == 0.0


def test_max_similarity_single_chunk():
    from rufus.builder_ai.knowledge.retriever import max_similarity
    chunks = [_make_chunk(score=0.72)]
    assert max_similarity(chunks) == pytest.approx(0.72)


# ---------------------------------------------------------------------------
# Integration: routing uses retrieve_for_routing, injection uses retrieve_for_injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_stage_routing_does_not_call_full_hybrid():
    """retrieve_for_routing must NOT call kb.retrieve (only kb.retrieve_fast)."""
    from rufus.builder_ai.knowledge.retriever import retrieve_for_routing
    kb = _make_kb(chunks_fast=[_make_chunk(score=0.7)])

    await retrieve_for_routing(kb, "any query")

    kb.retrieve_fast.assert_awaited_once()
    kb.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_stage_injection_does_not_call_fast():
    """retrieve_for_injection must NOT call kb.retrieve_fast (only kb.retrieve)."""
    from rufus.builder_ai.knowledge.retriever import retrieve_for_injection
    kb = _make_kb(chunks_full=[_make_chunk(score=0.8)])

    await retrieve_for_injection(kb, "any query")

    kb.retrieve.assert_awaited_once()
    kb.retrieve_fast.assert_not_awaited()
