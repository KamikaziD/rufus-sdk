"""Two-stage retrieval interface for the Rufus knowledge base.

Provides a clean separation between:
  - Stage A (routing):   fast ANN-only search used by RAFTRouter to decide
                         retrieval strategy.  ~5ms.  No BM25.
  - Stage B (injection): full hybrid BM25 + vector search used by pipeline
                         stages to get high-quality context chunks.  ~20ms.

Both functions delegate to KnowledgeBase methods and are provided here as
standalone callables so they can be imported, mocked, or replaced in tests
without touching KnowledgeBase directly.

Usage::

    from ruvon.builder_ai.knowledge.retriever import retrieve_for_routing, retrieve_for_injection

    # Routing (fast, ANN-only)
    top_chunks = await retrieve_for_routing(kb, "configure HUMAN_APPROVAL timeout")

    # Injection (full hybrid, re-ranked)
    context_chunks = await retrieve_for_injection(kb, "configure HUMAN_APPROVAL timeout")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ruvon.builder_ai.knowledge.indexer import Chunk, KnowledgeBase


async def retrieve_for_routing(
    kb: "KnowledgeBase",
    query: str,
    top_k: int = 10,
) -> "List[Chunk]":
    """Fast ANN-only retrieval used by RAFTRouter to compute confidence scores.

    Uses ``KnowledgeBase.retrieve_fast()`` which skips BM25 re-ranking.
    Call this during the routing decision step — before any LLM stage runs —
    to minimise latency on the critical path.

    Args:
        kb:     A loaded KnowledgeBase instance.
        query:  The user's workflow description or builder prompt.
        top_k:  Number of candidates to retrieve (default 10, wider net for
                confidence scoring).

    Returns:
        List of Chunk objects sorted by vector similarity (descending).
        Each chunk has ``.score`` populated.
    """
    return await kb.retrieve_fast(query, top_k=top_k)


async def retrieve_for_injection(
    kb: "KnowledgeBase",
    query: str,
    top_k: int = 5,
    focus_types: Optional[List[str]] = None,
) -> "List[Chunk]":
    """Full hybrid (BM25 + vector) retrieval used by pipeline stages.

    Uses ``KnowledgeBase.retrieve()`` which applies BM25 re-ranking on top of
    ANN candidates for higher precision.  Optionally filters by ``chunk_type``
    so each stage gets the most relevant content type.

    Args:
        kb:          A loaded KnowledgeBase instance.
        query:       The user's workflow description or stage-specific query.
        top_k:       Final number of chunks to return (default 5).
        focus_types: If provided, only chunks whose ``chunk_type`` is in this
                     list are returned.  Falls back to all types if no chunks
                     match.  Example: ``["yaml_example"]`` for WorkflowGenerator.

    Returns:
        List of Chunk objects sorted by combined BM25+vector score (descending).
    """
    chunks = await kb.retrieve(query, top_k=top_k)
    if focus_types:
        focused = [c for c in chunks if c.chunk_type in focus_types]
        if focused:
            return focused
    return chunks


def max_similarity(chunks: "List[Chunk]") -> float:
    """Return the highest similarity score from a list of chunks.

    Convenience helper for RAFTRouter confidence calculation::

        chunks = await retrieve_for_routing(kb, query)
        max_sim = max_similarity(chunks)   # 0.0–1.0

    Returns 0.0 if the list is empty.
    """
    if not chunks:
        return 0.0
    return max(c.score for c in chunks)
