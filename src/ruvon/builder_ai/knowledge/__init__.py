"""Ruvon AI Builder — Knowledge Base (RAG + RAFT) module.

Provides:
  KnowledgeBase  — local vector store built from Ruvon docs
  Chunk          — a single retrievable document chunk
  RAFTRouter     — runtime routing: NONE / RAG / RAFT
  RetrievalDecision — result of routing, shared across all pipeline stages
  RetrievalStrategy — enum of routing strategies
"""

from ruvon.builder_ai.knowledge.indexer import Chunk, KnowledgeBase
from ruvon.builder_ai.knowledge.raft_router import (
    RAFTRouter,
    RetrievalDecision,
    RetrievalStrategy,
)

__all__ = [
    "KnowledgeBase",
    "Chunk",
    "RAFTRouter",
    "RetrievalDecision",
    "RetrievalStrategy",
]
