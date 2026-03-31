"""RAFTRouter — runtime routing decision for the RAG/RAFT knowledge layer.

Runs once per AIWorkflowBuilder.build() call, before any pipeline stage.
Decides whether to:
  NONE  — skip retrieval (generic query; base model is sufficient)
  RAG   — inject retrieved chunks; use configured base model
  RAFT  — inject retrieved chunks; switch to the locally fine-tuned rufus-expert model

The router performs a fast ANN-only search (no BM25 re-rank) for speed; the
full hybrid search is used later only when chunks are actually injected into
stage prompts.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field

from rufus.builder_ai.knowledge.indexer import Chunk, KnowledgeBase
from rufus.builder_ai.knowledge.scrubber import PIIScrubber

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------

class RetrievalStrategy(str, Enum):
    NONE = "none"    # confidence < 0.35  — base model is enough
    RAG  = "rag"     # 0.35 ≤ conf < 0.70 — inject retrieved docs
    RAFT = "raft"    # conf ≥ 0.70 + ollama backend + rufus-expert present


class PrivacyLevel(str, Enum):
    STRICT   = "strict"    # 100% local — nothing leaves the machine
    BALANCED = "balanced"  # local RAG + cloud LLM (only metadata injected, not full chunks)
    CLOUD    = "cloud"     # full cloud — chunks and prompts may be sent to cloud LLMs


class RetrievalDecision(BaseModel):
    """Result of the RAFTRouter.decide() call. Shared across all pipeline stages."""
    strategy: RetrievalStrategy
    chunks: List[Chunk]          # pre-fetched; all stages share this list (no re-retrieval)
    confidence: float            # 0.0–1.0 composite score
    model_override: Optional[str] = None  # set to "rufus-expert" when strategy=RAFT
    privacy_level: PrivacyLevel = PrivacyLevel.BALANCED
    pii_redactions: int = 0      # number of PII redactions applied to chunk texts
    chunks_sent_to_cloud: bool = False


# ---------------------------------------------------------------------------
# RAFTRouter
# ---------------------------------------------------------------------------

class RAFTRouter:
    """Decides at runtime whether to use no retrieval, RAG, or the RAFT-tuned model.

    Decision algorithm:
      1. Compute query specificity score (no LLM, no network):
           - Rufus domain keyword match (step types, gov rules, YAML keys)  → up to 0.3
           - Phrase match: known anti-patterns from lessons  → up to 0.2 bonus
      2. Fast ANN-only retrieval → top-10 candidates → record max cosine similarity
      3. Domain match boost for fintech/edge/compliance terms → up to 0.2
      4. Composite confidence = 0.5 × max_sim + 0.3 × specificity + 0.2 × domain_match
      5. Apply thresholds:
           confidence < THRESHOLD_RAG  → NONE
           confidence < THRESHOLD_RAFT → RAG
           confidence ≥ THRESHOLD_RAFT → RAFT (if ollama + rufus-expert available)
      6. Privacy enforcement:
           strict:   strategy forced to NONE for any cloud backend
           balanced: full chunks NOT injected when backend is cloud; only metadata injected
           cloud:    no restriction
      7. PII scrubbing: applied to chunks before injection when privacy ≠ NONE
    """

    THRESHOLD_RAG  = 0.35
    THRESHOLD_RAFT = 0.70

    # Domain keywords that increase specificity score (case-insensitive)
    RUFUS_TERMS: Dict[str, Set[str]] = {
        "step_types": {
            "STANDARD", "ASYNC", "HTTP", "PARALLEL", "LOOP", "HUMAN_IN_LOOP",
            "AI_LLM_INFERENCE", "HUMAN_APPROVAL", "AUDIT_EMIT", "COMPLIANCE_CHECK",
            "EDGE_MODEL_CALL", "WORKFLOW_BUILDER_META", "FIRE_AND_FORGET", "WASM",
            "AI_INFERENCE", "CRON_SCHEDULE", "DECISION",
        },
        "gov_rules": {
            "GOV-001", "GOV-002", "GOV-003", "GOV-004", "GOV-005", "GOV-006", "GOV-007",
        },
        "yaml_keys": {
            "automate_next", "llm_config", "approval_config", "audit_config",
            "compliance_config", "edge_config", "merge_strategy", "required_input",
            "compensate_function", "workflow_version", "initial_state_model",
        },
        "architecture": {
            "saga", "compensation", "store-and-forward", "SAF", "heartbeat", "zombie",
            "persistence", "execution_provider", "inference_provider", "sub_workflow",
            "etag", "floor_limit", "edge_device", "pci", "pci-dss",
        },
    }

    # Domain-specific terms that boost the confidence score
    DOMAIN_BOOST_TERMS = {
        "bid", "payment", "compliance", "fraud", "uae", "procurement",
        "pos", "atm", "kiosk", "fintech", "pci", "offline", "edge",
        "settlement", "transaction", "approval", "audit", "regulatory",
    }

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        raft_model: str = "rufus-expert",
        ollama_base_url: str = "http://localhost:11434",
        privacy_level: PrivacyLevel = PrivacyLevel.BALANCED,
    ):
        self.kb = knowledge_base
        self.raft_model = raft_model
        self.ollama_base_url = ollama_base_url
        self.privacy_level = privacy_level
        self._raft_available: Optional[bool] = None   # lazy-checked once

    async def decide(self, query: str, backend: str = "anthropic") -> RetrievalDecision:
        """Run the routing decision for a query.

        Returns a RetrievalDecision with pre-fetched chunks, strategy, and
        privacy metadata. The caller shares this object with all pipeline stages.
        """
        # Privacy gate: strict mode never allows retrieval for cloud backends
        if self.privacy_level == PrivacyLevel.STRICT and backend != "ollama":
            logger.info(
                "[Router] privacy=strict, backend=%s → forcing NONE strategy", backend
            )
            return RetrievalDecision(
                strategy=RetrievalStrategy.NONE,
                chunks=[],
                confidence=0.0,
                privacy_level=self.privacy_level,
                chunks_sent_to_cloud=False,
            )

        # Step 1: Query specificity (no network, no LLM)
        specificity = self._specificity_score(query)

        # Step 2: Fast ANN-only retrieval for routing decision (speed-critical path)
        fast_chunks = await self.kb.retrieve_fast(query, top_k=10)
        max_sim = max((c.score for c in fast_chunks), default=0.0)

        # Step 3: Domain match boost
        domain_match = (
            0.2 if any(t in query.lower() for t in self.DOMAIN_BOOST_TERMS) else 0.0
        )

        # Composite confidence
        confidence = round(0.5 * max_sim + 0.3 * specificity + 0.2 * domain_match, 3)

        logger.debug(
            "[Router] specificity=%.2f max_sim=%.2f domain=%.2f → confidence=%.3f",
            specificity, max_sim, domain_match, confidence,
        )

        # Step 4: Strategy thresholds
        if confidence < self.THRESHOLD_RAG or not fast_chunks:
            return RetrievalDecision(
                strategy=RetrievalStrategy.NONE,
                chunks=[],
                confidence=confidence,
                privacy_level=self.privacy_level,
            )

        # Full hybrid retrieval for the actual context (only when we'll use it)
        full_chunks = await self.kb.retrieve(query, top_k=5)

        # Step 5: PII scrubbing (always, when chunks will be used)
        scrubber = PIIScrubber()
        full_chunks, pii_count = scrubber.scrub_chunks(full_chunks)

        # Privacy mode: balanced + cloud backend → send only metadata, not full chunk text
        chunks_sent_to_cloud = False
        if self.privacy_level == PrivacyLevel.BALANCED and backend != "ollama":
            # Replace full text with a metadata summary only
            full_chunks = [
                chunk.model_copy(update={
                    "text": f"[Reference: {chunk.source} § {chunk.section} — {chunk.chunk_type}]"
                })
                for chunk in full_chunks
            ]
            chunks_sent_to_cloud = False  # metadata only, not doc content
        elif self.privacy_level == PrivacyLevel.CLOUD:
            chunks_sent_to_cloud = True

        # RAFT vs RAG decision
        if (
            confidence >= self.THRESHOLD_RAFT
            and backend == "ollama"
            and self._raft_model_available()
        ):
            logger.info(
                "[Router] strategy=RAFT confidence=%.3f model=%s", confidence, self.raft_model
            )
            return RetrievalDecision(
                strategy=RetrievalStrategy.RAFT,
                chunks=full_chunks,
                confidence=confidence,
                model_override=self.raft_model,
                privacy_level=self.privacy_level,
                pii_redactions=pii_count,
                chunks_sent_to_cloud=chunks_sent_to_cloud,
            )

        logger.info("[Router] strategy=RAG confidence=%.3f", confidence)
        return RetrievalDecision(
            strategy=RetrievalStrategy.RAG,
            chunks=full_chunks,
            confidence=confidence,
            model_override=None,
            privacy_level=self.privacy_level,
            pii_redactions=pii_count,
            chunks_sent_to_cloud=chunks_sent_to_cloud,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _specificity_score(self, query: str) -> float:
        """Score 0.0–1.0 based on presence of Rufus-domain terms in query."""
        q_upper = query.upper()
        q_lower = query.lower()
        hits = 0
        total = len(self.RUFUS_TERMS)
        for terms in self.RUFUS_TERMS.values():
            if any(t in q_upper or t.lower() in q_lower for t in terms):
                hits += 1
        return round(hits / total, 3) if total else 0.0

    def _raft_model_available(self) -> bool:
        """Check Ollama tags endpoint once and cache the result."""
        if self._raft_available is not None:
            return self._raft_available
        try:
            import httpx
            resp = httpx.get(f"{self.ollama_base_url}/api/tags", timeout=2.0)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            self._raft_available = any(self.raft_model in m for m in models)
        except Exception as e:
            logger.debug("[Router] Could not check Ollama for rufus-expert: %s", e)
            self._raft_available = False
        return self._raft_available
