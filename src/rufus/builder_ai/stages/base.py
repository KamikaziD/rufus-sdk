"""Shared LLM calling utilities for all pipeline stages."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from rufus.builder_ai.knowledge.raft_router import RetrievalDecision


class LLMStageMixin:
    """Mixin that provides a _call_llm() method routing to Anthropic, Ollama, or raising for edge."""

    def __init__(
        self,
        backend: str = "anthropic",
        model: str = "claude-sonnet-4-6",
        api_key: Optional[str] = None,
        ollama_base_url: str = "http://localhost:11434",
    ):
        self.backend = backend
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.ollama_base_url = ollama_base_url

    async def _call_llm(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Route an LLM call to Anthropic cloud or Ollama local server."""
        if self.backend == "anthropic":
            return await self._call_anthropic(system, user, temperature)
        elif self.backend == "ollama":
            return await self._call_ollama(system, user)
        else:
            raise ValueError(
                f"Unsupported backend for AI pipeline: '{self.backend}'. "
                "Use 'anthropic' or 'ollama'."
            )

    async def _call_anthropic(self, system: str, user: str, temperature: float) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package is required for backend='anthropic'. "
                "Install it with: pip install 'rufus-sdk[builder]'"
            )
        # Anthropic SDK is sync; run in executor to avoid blocking the event loop
        import asyncio
        loop = asyncio.get_event_loop()

        def _sync_call():
            client = anthropic.Anthropic(api_key=self.api_key)
            msg = client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return msg.content[0].text

        return await loop.run_in_executor(None, _sync_call)

    def _inject_knowledge(
        self,
        system: str,
        decision: "RetrievalDecision | None",
        focus_types: Optional[List[str]] = None,
        max_context_tokens: int = 2500,
    ) -> str:
        """Augment a system prompt with pre-fetched knowledge chunks.

        Args:
            system:             Original system prompt.
            decision:           RetrievalDecision from RAFTRouter (or None to skip).
            focus_types:        Only include chunks of these chunk_type values.
                                Falls back to all chunks if none match.
            max_context_tokens: Approximate token budget for injected context.

        Returns:
            Augmented system prompt, or original if no retrieval was performed.
        """
        if decision is None or decision.strategy.value == "none" or not decision.chunks:
            return system

        from rufus.builder_ai.knowledge.scrubber import build_knowledge_block
        block = build_knowledge_block(
            decision.chunks,
            max_context_tokens=max_context_tokens,
            focus_types=focus_types,
        )
        if not block:
            return system
        return system + block

    async def _call_ollama(self, system: str, user: str) -> str:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.ollama_base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
