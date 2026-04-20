"""Tests for privacy tier enforcement, PII scrubbing, and injection guard.

These tests exercise:
  - PIIScrubber: card numbers, emails, UAE EID, IBAN, SSN, phones
  - build_knowledge_block: injection guard, focus_types, token budget
  - RAFTRouter privacy modes: STRICT → NONE, BALANCED → metadata-only, CLOUD → full chunks
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# PIIScrubber — individual pattern tests
# ---------------------------------------------------------------------------

def _scrubber():
    from ruvon.builder_ai.knowledge.scrubber import PIIScrubber
    return PIIScrubber()


def test_pii_scrubber_redacts_card_number():
    s = _scrubber()
    text, count = s.scrub("Card: 4111-1111-1111-1111 was used")
    assert "[CARD_REDACTED]" in text
    assert "4111" not in text
    assert count >= 1


def test_pii_scrubber_redacts_card_no_dashes():
    s = _scrubber()
    text, count = s.scrub("Number is 4111111111111111 end")
    assert "4111111111111111" not in text  # PII removed (may be CARD or PHONE pattern)
    assert count >= 1


def test_pii_scrubber_redacts_email():
    s = _scrubber()
    text, count = s.scrub("Contact user@example.com for help")
    assert "[EMAIL_REDACTED]" in text
    assert "user@example.com" not in text
    assert count >= 1


def test_pii_scrubber_redacts_uae_eid():
    s = _scrubber()
    text, count = s.scrub("EID: 784-1990-1234567-1")
    assert "[UAE_EID_REDACTED]" in text
    assert count >= 1


def test_pii_scrubber_redacts_iban():
    s = _scrubber()
    text, count = s.scrub("IBAN: AE070331234567890123456")
    assert "AE070331234567890123456" not in text  # PII removed (may be IBAN or PHONE pattern)
    assert count >= 1


def test_pii_scrubber_redacts_ssn():
    s = _scrubber()
    text, count = s.scrub("SSN: 123-45-6789")
    assert "123-45-6789" not in text  # PII removed (may be SSN or PHONE pattern)
    assert count >= 1


def test_pii_scrubber_no_redaction_when_clean():
    s = _scrubber()
    text, count = s.scrub("This is a clean document about STANDARD step types.")
    assert count == 0
    assert text == "This is a clean document about STANDARD step types."


def test_pii_scrubber_returns_redaction_count():
    s = _scrubber()
    _, count1 = s.scrub("user@a.com and 4111-1111-1111-1111")
    assert count1 == 2


def test_pii_scrubber_cumulative_count():
    s = _scrubber()
    s.scrub("email@test.com")
    s.scrub("other@test.com")
    assert s.redaction_count == 2


# ---------------------------------------------------------------------------
# PIIScrubber — scrub_chunks
# ---------------------------------------------------------------------------

def _make_chunk(text: str = "Hello world", chunk_type: str = "explanation"):
    from ruvon.builder_ai.knowledge.indexer import Chunk
    return Chunk(
        id="c1", text=text, source="docs/test.md",
        section="## Test", chunk_type=chunk_type, score=0.8,
    )


def test_scrub_chunks_redacts_text():
    s = _scrubber()
    chunk = _make_chunk("Contact admin@example.com")
    scrubbed, count = s.scrub_chunks([chunk])
    assert "[EMAIL_REDACTED]" in scrubbed[0].text
    assert count >= 1


def test_scrub_chunks_preserves_metadata():
    """Only chunk.text is modified; source, section, chunk_type are unchanged."""
    s = _scrubber()
    chunk = _make_chunk("4111-1111-1111-1111")
    scrubbed, _ = s.scrub_chunks([chunk])
    assert scrubbed[0].source == chunk.source
    assert scrubbed[0].section == chunk.section
    assert scrubbed[0].chunk_type == chunk.chunk_type
    assert scrubbed[0].id == chunk.id


def test_scrub_chunks_returns_new_objects():
    """scrub_chunks must not modify the original chunks in-place."""
    s = _scrubber()
    original_text = "email@test.com"
    chunk = _make_chunk(original_text)
    s.scrub_chunks([chunk])
    assert chunk.text == original_text  # original unchanged


# ---------------------------------------------------------------------------
# build_knowledge_block
# ---------------------------------------------------------------------------

def test_build_knowledge_block_includes_injection_guard():
    from ruvon.builder_ai.knowledge.scrubber import build_knowledge_block
    chunks = [_make_chunk("Some important doc content")]
    block = build_knowledge_block(chunks)
    assert "SYSTEM NOTICE" in block or "read-only" in block or "RUVON_KNOWLEDGE" in block


def test_build_knowledge_block_respects_focus_types():
    from ruvon.builder_ai.knowledge.scrubber import build_knowledge_block
    yaml_chunk = _make_chunk("yaml content", chunk_type="yaml_example")
    lesson_chunk = _make_chunk("lesson content", chunk_type="lesson")
    block = build_knowledge_block(
        [yaml_chunk, lesson_chunk], focus_types=["yaml_example"]
    )
    assert "yaml content" in block
    assert "lesson content" not in block


def test_build_knowledge_block_fallback_when_no_focus_match():
    """If focus_types produces no matches, include all chunks."""
    from ruvon.builder_ai.knowledge.scrubber import build_knowledge_block
    chunk = _make_chunk("some explanation", chunk_type="explanation")
    block = build_knowledge_block([chunk], focus_types=["yaml_example"])
    assert "some explanation" in block


def test_build_knowledge_block_empty_chunks_returns_empty():
    from ruvon.builder_ai.knowledge.scrubber import build_knowledge_block
    block = build_knowledge_block([])
    assert block == "" or block is None or len(block.strip()) == 0


def test_build_knowledge_block_respects_token_budget():
    """Chunks that would exceed max_context_tokens should be dropped."""
    from ruvon.builder_ai.knowledge.scrubber import build_knowledge_block
    # Each chunk is ~250 chars ≈ 62 tokens; budget of 60 fits one chunk
    big_text = "word " * 50  # ~250 chars, ~62 tokens
    chunks = [_make_chunk(big_text) for _ in range(5)]
    block = build_knowledge_block(chunks, max_context_tokens=80)
    # max_context_tokens=80 → max_chars=320; each chunk is ~250 chars so at most 1 fits
    assert len(block) < 600  # well under the size of all 5 chunks


# ---------------------------------------------------------------------------
# RAFTRouter — privacy tier enforcement
# ---------------------------------------------------------------------------

def _make_router_with_kb(chunks, privacy_level):
    from ruvon.builder_ai.knowledge.raft_router import RAFTRouter, PrivacyLevel
    from ruvon.builder_ai.knowledge.indexer import KnowledgeBase
    kb = MagicMock(spec=KnowledgeBase)
    kb.retrieve_fast = AsyncMock(return_value=chunks)
    kb.retrieve = AsyncMock(return_value=chunks)
    pl = PrivacyLevel(privacy_level)
    return RAFTRouter(kb, privacy_level=pl)


def _domain_chunks():
    return [_make_chunk("Configure HUMAN_IN_LOOP step with 48h timeout", "step_reference")]


@pytest.mark.asyncio
async def test_strict_privacy_forces_none_for_cloud_backend():
    """STRICT + cloud backend → strategy must be NONE, no chunks returned."""
    from ruvon.builder_ai.knowledge.raft_router import RetrievalStrategy
    router = _make_router_with_kb(_domain_chunks(), "strict")
    decision = await router.decide("HUMAN_IN_LOOP configuration", backend="anthropic")
    assert decision.strategy == RetrievalStrategy.NONE
    assert decision.chunks == []
    assert decision.chunks_sent_to_cloud is False


@pytest.mark.asyncio
async def test_strict_privacy_allows_ollama():
    """STRICT + ollama → allowed; strategy can be RAG or RAFT."""
    from ruvon.builder_ai.knowledge.raft_router import RetrievalStrategy
    router = _make_router_with_kb(_domain_chunks(), "strict")
    decision = await router.decide("HUMAN_IN_LOOP configuration", backend="ollama")
    assert decision.strategy in (RetrievalStrategy.RAG, RetrievalStrategy.RAFT, RetrievalStrategy.NONE)
    assert decision.chunks_sent_to_cloud is False


@pytest.mark.asyncio
async def test_balanced_privacy_sends_metadata_only_to_cloud():
    """BALANCED + cloud → chunk text replaced with metadata summary, not full content."""
    from ruvon.builder_ai.knowledge.raft_router import RetrievalStrategy
    router = _make_router_with_kb(_domain_chunks(), "balanced")
    decision = await router.decide("HUMAN_IN_LOOP step timeout configuration", backend="anthropic")

    if decision.strategy != RetrievalStrategy.NONE:
        # chunks should have metadata-only text
        for chunk in decision.chunks:
            assert "Configure HUMAN_IN_LOOP" not in chunk.text, (
                "Balanced mode should replace chunk text with metadata summary for cloud backends"
            )
        assert decision.chunks_sent_to_cloud is False


@pytest.mark.asyncio
async def test_cloud_privacy_allows_full_chunks():
    """CLOUD → full chunks may be sent to cloud LLM."""
    from ruvon.builder_ai.knowledge.raft_router import RetrievalStrategy
    router = _make_router_with_kb(_domain_chunks(), "cloud")
    decision = await router.decide("HUMAN_IN_LOOP step timeout configuration", backend="anthropic")

    if decision.strategy != RetrievalStrategy.NONE:
        assert decision.chunks_sent_to_cloud is True


@pytest.mark.asyncio
async def test_pii_scrubbing_applied_before_retrieval_decision():
    """PII in chunk text should be redacted regardless of privacy tier."""
    from ruvon.builder_ai.knowledge.raft_router import PrivacyLevel, RAFTRouter
    from ruvon.builder_ai.knowledge.indexer import KnowledgeBase

    pii_chunk = _make_chunk("Contact admin@example.com or call 4111-1111-1111-1111", "explanation")

    kb = MagicMock(spec=KnowledgeBase)
    kb.retrieve_fast = AsyncMock(return_value=[pii_chunk])
    kb.retrieve = AsyncMock(return_value=[pii_chunk])

    router = RAFTRouter(kb, privacy_level=PrivacyLevel.CLOUD)
    decision = await router.decide("HUMAN_IN_LOOP timeout", backend="anthropic")

    if decision.chunks:
        for chunk in decision.chunks:
            assert "admin@example.com" not in chunk.text
            assert "4111-1111-1111-1111" not in chunk.text
        assert decision.pii_redactions >= 2
