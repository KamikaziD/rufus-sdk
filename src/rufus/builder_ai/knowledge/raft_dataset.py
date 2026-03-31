"""RAFT Dataset Generator — creates fine-tuning data from indexed Rufus docs.

RAFT = Retrieval Augmented Fine-Tuning (Gorman et al., 2024).

Each training sample:
  - question:  generated from a doc chunk by the LLM
  - context:   1 relevant "oracle" chunk + N distractor chunks
  - answer:    chain-of-thought answer citing the oracle with ##begin_quote## markers

25% of samples (p=0.25) have NO oracle in the context, teaching the model to
say "I don't know" when the retrieved docs don't contain the answer.

Output format: Alpaca JSONL, compatible with Ollama Modelfile training.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import List, Optional

from rufus.builder_ai.knowledge.indexer import Chunk, KnowledgeBase

logger = logging.getLogger(__name__)

_QUESTION_SYSTEM = """You are generating training data for a Rufus workflow SDK assistant.
Given a documentation chunk, generate {n} distinct questions a developer might ask
that this chunk directly answers.

Rules:
- Questions must be specific and answerable from the chunk alone
- Vary question style: how-to, why, what, when
- Do not generate questions that require external context

Return a JSON array of question strings only. No explanation."""

_ANSWER_SYSTEM = """You are a Rufus SDK expert assistant.
Answer the developer's question using ONLY the provided context documents.

Rules:
- Cite relevant passages using ##begin_quote## ... ##end_quote## markers
- Think step-by-step before answering
- If the context does not contain the answer, respond with exactly: "I don't know."
- Keep answers concise and actionable

Return only your answer. No preamble."""

_NO_ORACLE_ANSWER = "I don't know."


class RAFTDatasetGenerator:
    """Generates RAFT training data from indexed Rufus docs.

    Requires a stage LLM mixin to call the LLM for Q&A generation.
    """

    def __init__(
        self,
        llm_call,  # callable: async (system, user, temperature) -> str
        p_no_oracle: float = 0.25,   # RAFT paper: 25% no-oracle samples
        n_distractors: int = 3,
        questions_per_chunk: int = 3,
        seed: int = 42,
    ):
        self._call_llm = llm_call
        self.p_no_oracle = p_no_oracle
        self.n_distractors = n_distractors
        self.questions_per_chunk = questions_per_chunk
        random.seed(seed)

    async def generate(
        self,
        kb: KnowledgeBase,
        output_path: Path,
        max_chunks: Optional[int] = None,
    ) -> int:
        """Generate RAFT training samples and write Alpaca JSONL to output_path.

        Args:
            kb:          Populated KnowledgeBase instance.
            output_path: Where to write the JSONL file.
            max_chunks:  Limit number of oracle chunks processed (useful for dry runs).

        Returns:
            Number of samples written.
        """
        all_chunks = await self._load_all_chunks(kb)
        if not all_chunks:
            logger.warning("[RAFTDataset] No chunks found in KnowledgeBase")
            return 0

        if max_chunks:
            all_chunks = all_chunks[:max_chunks]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0

        with output_path.open("w", encoding="utf-8") as fh:
            for i, oracle_chunk in enumerate(all_chunks):
                logger.debug("[RAFTDataset] Processing chunk %d/%d: %s", i + 1, len(all_chunks), oracle_chunk.source)

                # Generate questions for this oracle chunk
                questions = await self._generate_questions(oracle_chunk)
                if not questions:
                    continue

                # Distractor chunks: random sample from all chunks excluding oracle
                distractors = self._sample_distractors(all_chunks, oracle_chunk, self.n_distractors)

                for question in questions:
                    # p_no_oracle samples: remove oracle from context
                    use_no_oracle = random.random() < self.p_no_oracle
                    context_chunks = distractors if use_no_oracle else [oracle_chunk] + distractors
                    random.shuffle(context_chunks)

                    answer = await self._generate_answer(question, context_chunks, use_no_oracle)

                    sample = {
                        "instruction": question,
                        "input": _format_context(context_chunks),
                        "output": answer,
                    }
                    fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    written += 1

        logger.info("[RAFTDataset] Wrote %d samples to %s", written, output_path)
        return written

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _generate_questions(self, chunk: Chunk) -> List[str]:
        system = _QUESTION_SYSTEM.format(n=self.questions_per_chunk)
        user = f"Documentation chunk:\n\n{chunk.text}"
        try:
            raw = await self._call_llm(system=system, user=user, temperature=0.7)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            questions = json.loads(raw)
            if isinstance(questions, list):
                return [str(q) for q in questions if q]
        except Exception as e:
            logger.warning("[RAFTDataset] Question generation failed for %s: %s", chunk.source, e)
        return []

    async def _generate_answer(
        self,
        question: str,
        context_chunks: List[Chunk],
        no_oracle: bool,
    ) -> str:
        if no_oracle:
            # For no-oracle samples, sometimes generate a proper "I don't know" with reasoning
            return _NO_ORACLE_ANSWER
        context_str = _format_context(context_chunks)
        user = f"Context:\n{context_str}\n\nQuestion: {question}"
        try:
            return await self._call_llm(system=_ANSWER_SYSTEM, user=user, temperature=0.2)
        except Exception as e:
            logger.warning("[RAFTDataset] Answer generation failed: %s", e)
            return _NO_ORACLE_ANSWER

    async def _load_all_chunks(self, kb: KnowledgeBase) -> List[Chunk]:
        """Load all chunks from the knowledge base for dataset generation."""
        try:
            if kb._backend == "lancedb":
                tbl = kb._get_table()
                if tbl is None:
                    return []
                rows = tbl.to_pandas()
                return [
                    Chunk(
                        id=r["id"],
                        text=r["text"],
                        source=r["source"],
                        section=r["section"],
                        chunk_type=r["chunk_type"],
                    )
                    for _, r in rows.iterrows()
                ]
        except Exception as e:
            logger.warning("[RAFTDataset] Failed to load chunks: %s", e)
        return []

    @staticmethod
    def _sample_distractors(
        all_chunks: List[Chunk],
        oracle: Chunk,
        n: int,
    ) -> List[Chunk]:
        """Return n random chunks that are not the oracle."""
        pool = [c for c in all_chunks if c.id != oracle.id]
        return random.sample(pool, min(n, len(pool)))


def _format_context(chunks: List[Chunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"Document {i} [{chunk.source} § {chunk.section}]:\n{chunk.text}")
    return "\n\n".join(parts)
