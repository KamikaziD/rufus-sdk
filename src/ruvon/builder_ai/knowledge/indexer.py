"""Knowledge base indexer — loads Ruvon docs, chunks them, and stores embeddings.

Storage backends (auto-selected by available RAM + installed packages):
  - LanceDB   (~60 MB footprint) — preferred for cloud/dev machines
  - sqlite-vec (~2 MB footprint)  — fallback for constrained edge devices

Embedding models (auto-selected by available RAM):
  - sentence-transformers/all-MiniLM-L6-v2  (22 MB)   — POS/ATM (≤256 MB RAM)
  - BAAI/bge-small-en-v1.5                  (130 MB)  — mid-tier edge / dev
  - BAAI/bge-base-en-v1.5                   (430 MB)  — cloud / workstation
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Chunk(BaseModel):
    """A single retrievable piece of documentation."""
    id: str
    text: str
    source: str            # file path relative to project root
    section: str           # nearest heading context
    chunk_type: str        # "yaml_example" | "explanation" | "lesson" | "step_reference"
    score: float = 0.0     # populated during retrieval


# ---------------------------------------------------------------------------
# Helpers — file discovery and chunking
# ---------------------------------------------------------------------------

_MAX_CHUNK_TOKENS = 512    # ~2048 chars (1 token ≈ 4 chars)
_YAML_FENCE_RE = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def _default_source_roots(base: Path) -> List[Path]:
    """Return the priority-ordered list of doc roots relative to the project base."""
    candidates = [
        base / "docs",
        base / "config",
        base / ".claude",
        base / "CLAUDE.md",
    ]
    return [p for p in candidates if p.exists()]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _chunk_type_from_path(path: Path) -> str:
    name = path.name.lower()
    if "lesson" in name or "lesson" in str(path).lower():
        return "lesson"
    if path.suffix in (".yaml", ".yml"):
        return "yaml_example"
    if "step" in name or "step-type" in name:
        return "step_reference"
    return "explanation"


def _split_text(text: str, max_chars: int = _MAX_CHUNK_TOKENS * 4) -> List[str]:
    """Split text at paragraph boundaries, staying under max_chars each."""
    parts = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) + 2 <= max_chars:
            current = (current + "\n\n" + part).strip()
        else:
            if current:
                chunks.append(current)
            if len(part) > max_chars:
                # Hard split on sentence boundary, word boundary as last resort
                current = ""
                for sentence in re.split(r"(?<=[.!?])\s+", part):
                    if len(current) + len(sentence) + 1 <= max_chars:
                        current = (current + " " + sentence).strip()
                    else:
                        if current:
                            chunks.append(current)
                        current = ""
                        if len(sentence) > max_chars:
                            # No sentence boundary — split by words
                            for word in sentence.split():
                                if len(current) + len(word) + 1 <= max_chars:
                                    current = (current + " " + word).strip()
                                else:
                                    if current:
                                        chunks.append(current)
                                    current = word
                        else:
                            current = sentence
            else:
                current = part
    if current:
        chunks.append(current)
    return chunks


def _chunk_markdown(path: Path, default_type: str) -> List[Chunk]:
    """Chunk a markdown file, extracting YAML fences as atomic chunks."""
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks: List[Chunk] = []
    source = str(path)

    # Extract YAML fences first (never split mid-block)
    for i, match in enumerate(_YAML_FENCE_RE.finditer(text)):
        yaml_text = match.group(1).strip()
        if not yaml_text:
            continue
        # Find nearest heading before this match
        section = _nearest_heading(text, match.start())
        chunk_id = f"{_file_hash(path)}_yaml_{i}"
        chunks.append(Chunk(
            id=chunk_id,
            text=yaml_text,
            source=source,
            section=section,
            chunk_type="yaml_example",
        ))

    # Remove YAML fences from prose text to avoid duplication
    prose = _YAML_FENCE_RE.sub("", text)

    # Split prose by heading, then by paragraph
    sections = re.split(_HEADING_RE, prose)
    current_heading = ""
    # re.split with a capturing group produces alternating [content, heading, content, ...]
    # Odd indices are captured heading titles; even indices are content between headings.
    for i, piece in enumerate(sections):
        piece = piece.strip()
        if not piece:
            continue
        if i % 2 == 1:  # captured heading group
            current_heading = piece
            continue
        for j, part in enumerate(_split_text(piece)):
            if not part.strip():
                continue
            chunk_id = f"{_file_hash(path)}_prose_{abs(hash(current_heading + part)) % 1_000_000}"
            chunks.append(Chunk(
                id=chunk_id,
                text=part,
                source=source,
                section=current_heading or "top",
                chunk_type=default_type,
            ))

    return chunks


def _nearest_heading(text: str, pos: int) -> str:
    """Return the last heading that appears before `pos` in `text`."""
    headings = list(_HEADING_RE.finditer(text[:pos]))
    if headings:
        return headings[-1].group(1)
    return "top"


def _chunk_yaml_file(path: Path) -> List[Chunk]:
    """Treat an entire YAML config file as a single yaml_example chunk."""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    return [Chunk(
        id=f"{_file_hash(path)}_full",
        text=text,
        source=str(path),
        section="full file",
        chunk_type="yaml_example",
    )]


def _load_and_chunk(source_roots: List[Path]) -> List[Chunk]:
    """Walk source roots and return all chunks, deduplicating by id."""
    seen: set = set()
    all_chunks: List[Chunk] = []

    for root in source_roots:
        if root.is_file():
            paths = [root]
        else:
            paths = sorted(root.rglob("*"))

        for path in paths:
            if path.is_dir():
                continue
            if path.suffix in (".pyc", ".pyo", ".png", ".jpg", ".gif", ".ico"):
                continue
            try:
                if path.suffix in (".yaml", ".yml"):
                    new_chunks = _chunk_yaml_file(path)
                elif path.suffix == ".md":
                    new_chunks = _chunk_markdown(path, _chunk_type_from_path(path))
                else:
                    continue

                for c in new_chunks:
                    if c.id not in seen:
                        seen.add(c.id)
                        all_chunks.append(c)
            except Exception as e:
                logger.warning("Failed to chunk %s: %s", path, e)

    logger.info("[Indexer] Loaded %d chunks from %d source roots", len(all_chunks), len(source_roots))
    return all_chunks


# ---------------------------------------------------------------------------
# Embedding model selection
# ---------------------------------------------------------------------------

def _auto_select_model() -> str:
    """Pick the best embedding model that fits in available RAM."""
    try:
        import psutil
        ram_mb = psutil.virtual_memory().available // 1_048_576
    except ImportError:
        ram_mb = 512  # Conservative default if psutil not available

    if ram_mb < 200:
        return "sentence-transformers/all-MiniLM-L6-v2"
    elif ram_mb < 600:
        return "BAAI/bge-small-en-v1.5"
    return "BAAI/bge-base-en-v1.5"


def _lancedb_available() -> bool:
    try:
        import lancedb  # noqa: F401
        return True
    except ImportError:
        return False


def _fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """Local vector store backed by LanceDB or sqlite-vec.

    Usage — one-time index build:
        kb = KnowledgeBase.build()          # indexes all Ruvon docs
        kb = KnowledgeBase.build(force=True) # full rebuild

    Usage — retrieve:
        chunks = await kb.retrieve("how to configure HUMAN_APPROVAL step")
    """

    DEFAULT_DB_PATH = Path.home() / ".ruvon" / "knowledge.lance"
    DEFAULT_MANIFEST_PATH = Path.home() / ".ruvon" / "index_manifest.json"

    def __init__(
        self,
        db_path: Optional[Path] = None,
        model_name: Optional[str] = None,
    ):
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self.model_name = model_name or _auto_select_model()
        self._backend: str = "lancedb" if _lancedb_available() else "sqlite-vec"
        self._table = None       # lazy-loaded
        self._model = None       # lazy-loaded embedding model
        self._bm25_corpus: List[str] = []
        self._bm25_chunks: List[Chunk] = []

    # ------------------------------------------------------------------
    # Build (index)
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        source_roots: Optional[List[Path]] = None,
        db_path: Optional[Path] = None,
        model_name: Optional[str] = None,
        force: bool = False,
        project_root: Optional[Path] = None,
    ) -> "KnowledgeBase":
        """Index Ruvon documentation and persist to local vector store.

        Args:
            source_roots: Override default doc directories.
            db_path:      Override default DB path (~/.ruvon/knowledge.lance).
            model_name:   Override embedding model selection.
            force:        Rebuild even if nothing changed.
            project_root: Base path for resolving default source roots.
        """
        if not _fastembed_available():
            raise RuntimeError(
                "fastembed is required to build the knowledge index. "
                "Install with: pip install 'ruvon-sdk[rag]'"
            )

        inst = cls(db_path=db_path, model_name=model_name)
        base = project_root or _find_project_root()

        if source_roots is None:
            source_roots = _default_source_roots(base)

        manifest = inst._load_manifest()
        chunks_to_index: List[Chunk] = []

        if force:
            chunks_to_index = _load_and_chunk(source_roots)
            manifest = {}
        else:
            all_chunks = _load_and_chunk(source_roots)
            new_manifest: Dict[str, str] = {}
            for path in source_roots:
                paths = [path] if path.is_file() else list(path.rglob("*"))
                for p in paths:
                    if p.is_file() and p.suffix in (".md", ".yaml", ".yml"):
                        h = _file_hash(p)
                        new_manifest[str(p)] = h
                        if manifest.get(str(p)) != h:
                            # File changed — include its chunks
                            chunks_to_index.extend(
                                c for c in all_chunks if c.source == str(p)
                            )

            if not chunks_to_index:
                logger.info("[Indexer] Nothing changed; index is up to date.")
                return inst

            manifest = new_manifest

        logger.info("[Indexer] Embedding %d chunks with %s", len(chunks_to_index), inst.model_name)
        embeddings = inst._embed_chunks(chunks_to_index)
        inst._store(chunks_to_index, embeddings)
        inst._save_manifest(manifest)
        logger.info("[Indexer] Index built: %d chunks stored at %s", len(chunks_to_index), inst.db_path)
        return inst

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    async def retrieve(self, query: str, top_k: int = 5) -> List[Chunk]:
        """Hybrid search: vector ANN + BM25 keyword re-rank → top_k chunks."""
        if not _fastembed_available():
            logger.warning("[KnowledgeBase] fastembed not available; returning empty chunks")
            return []

        query_vec = self._embed_query(query)
        return self._hybrid_retrieve(query, list(query_vec), top_k)

    async def retrieve_fast(self, query: str, top_k: int = 10) -> List[Chunk]:
        """ANN-only search — used by the router for speed (no BM25 re-rank)."""
        if not _fastembed_available():
            return []
        query_vec = self._embed_query(query)
        return self._ann_retrieve(list(query_vec), top_k)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    @lru_cache(maxsize=512)
    def _embed_query(self, query: str) -> Tuple[float, ...]:
        """Embed a query string. Results are LRU-cached per query text."""
        model = self._get_model()
        vecs = list(model.embed([query]))
        return tuple(float(x) for x in vecs[0])

    def _embed_chunks(self, chunks: List[Chunk]) -> List[List[float]]:
        model = self._get_model()
        texts = [c.text for c in chunks]
        return [list(v) for v in model.embed(texts)]

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.model_name)
        return self._model

    # ------------------------------------------------------------------
    # Storage (LanceDB path)
    # ------------------------------------------------------------------

    def _store(self, chunks: List[Chunk], embeddings: List[List[float]]) -> None:
        if self._backend == "lancedb":
            self._store_lancedb(chunks, embeddings)
        else:
            self._store_sqlite_vec(chunks, embeddings)

    def _store_lancedb(self, chunks: List[Chunk], embeddings: List[List[float]]) -> None:
        import lancedb
        self.db_path.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(self.db_path))
        records = [
            {
                "id": c.id,
                "text": c.text,
                "source": c.source,
                "section": c.section,
                "chunk_type": c.chunk_type,
                "vector": emb,
            }
            for c, emb in zip(chunks, embeddings)
        ]
        if "ruvon_chunks" in db.table_names():
            tbl = db.open_table("ruvon_chunks")
            tbl.add(records)
        else:
            db.create_table("ruvon_chunks", data=records)
        self._table = None  # reset cached handle

    def _store_sqlite_vec(self, chunks: List[Chunk], embeddings: List[List[float]]) -> None:
        import sqlite3
        import struct
        try:
            import sqlite_vec
        except ImportError:
            raise RuntimeError(
                "sqlite-vec is required on this device. "
                "Install with: pip install sqlite-vec"
            )
        db_file = self.db_path.parent / "knowledge.sqlite"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(db_file))
        sqlite_vec.load(con)
        dim = len(embeddings[0]) if embeddings else 384
        con.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS ruvon_chunks "
            f"USING vec0(id TEXT, text TEXT, source TEXT, section TEXT, "
            f"chunk_type TEXT, embedding FLOAT[{dim}])"
        )
        for c, emb in zip(chunks, embeddings):
            blob = struct.pack(f"{len(emb)}f", *emb)
            con.execute(
                "INSERT OR REPLACE INTO ruvon_chunks VALUES (?, ?, ?, ?, ?, ?)",
                (c.id, c.text, c.source, c.section, c.chunk_type, blob),
            )
        con.commit()
        con.close()

    # ------------------------------------------------------------------
    # Retrieval internals
    # ------------------------------------------------------------------

    def _ann_retrieve(self, query_vec: List[float], top_k: int) -> List[Chunk]:
        if self._backend == "lancedb":
            return self._ann_lancedb(query_vec, top_k)
        return self._ann_sqlite_vec(query_vec, top_k)

    def _ann_lancedb(self, query_vec: List[float], top_k: int) -> List[Chunk]:
        tbl = self._get_table()
        if tbl is None:
            return []
        rows = tbl.search(query_vec).limit(top_k).to_list()
        return [
            Chunk(
                id=r["id"],
                text=r["text"],
                source=r["source"],
                section=r["section"],
                chunk_type=r["chunk_type"],
                score=float(r.get("_distance", 0.0)),
            )
            for r in rows
        ]

    def _ann_sqlite_vec(self, query_vec: List[float], top_k: int) -> List[Chunk]:
        import sqlite3
        import struct
        try:
            import sqlite_vec
        except ImportError:
            return []
        db_file = self.db_path.parent / "knowledge.sqlite"
        if not db_file.exists():
            return []
        con = sqlite3.connect(str(db_file))
        sqlite_vec.load(con)
        blob = struct.pack(f"{len(query_vec)}f", *query_vec)
        rows = con.execute(
            "SELECT id, text, source, section, chunk_type, distance "
            "FROM ruvon_chunks WHERE embedding MATCH ? "
            f"ORDER BY distance LIMIT {top_k}",
            (blob,),
        ).fetchall()
        con.close()
        return [
            Chunk(id=r[0], text=r[1], source=r[2], section=r[3], chunk_type=r[4], score=r[5])
            for r in rows
        ]

    def _hybrid_retrieve(self, query: str, query_vec: List[float], top_k: int) -> List[Chunk]:
        """ANN top-20 candidates → BM25 re-rank → top_k."""
        candidates = self._ann_retrieve(query_vec, top_k=20)
        if not candidates:
            return []

        try:
            from rank_bm25 import BM25Okapi
            tokenized_corpus = [c.text.lower().split() for c in candidates]
            bm25 = BM25Okapi(tokenized_corpus)
            bm25_scores = bm25.get_scores(query.lower().split())
            # Normalize BM25 scores to [0, 1]
            max_bm25 = max(bm25_scores) if max(bm25_scores) > 0 else 1.0
            bm25_norm = [s / max_bm25 for s in bm25_scores]
        except ImportError:
            # rank-bm25 not installed — fall back to ANN-only
            bm25_norm = [0.0] * len(candidates)

        # Combined score: 0.7 × vector_sim + 0.3 × bm25
        # Note: LanceDB returns _distance (lower = better); invert for scoring
        scored = []
        for i, chunk in enumerate(candidates):
            vec_score = 1.0 - min(chunk.score, 1.0)  # convert distance to similarity
            combined = 0.7 * vec_score + 0.3 * bm25_norm[i]
            scored.append((combined, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate by source+section
        seen = set()
        results = []
        for score, chunk in scored:
            key = (chunk.source, chunk.section)
            if key not in seen:
                seen.add(key)
                chunk.score = round(score, 4)
                results.append(chunk)
            if len(results) >= top_k:
                break

        return results

    def _get_table(self):
        if self._table is None and self._backend == "lancedb":
            try:
                import lancedb
                if not self.db_path.exists():
                    return None
                db = lancedb.connect(str(self.db_path))
                if "ruvon_chunks" not in db.table_names():
                    return None
                self._table = db.open_table("ruvon_chunks")
            except Exception as e:
                logger.warning("[KnowledgeBase] Failed to open LanceDB table: %s", e)
                return None
        return self._table

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        """Return statistics about the current index."""
        count = 0
        sources: set = set()
        try:
            if self._backend == "lancedb":
                tbl = self._get_table()
                if tbl is not None:
                    rows = tbl.to_pandas()
                    count = len(rows)
                    sources = set(rows["source"].tolist())
            else:
                import sqlite3
                db_file = self.db_path.parent / "knowledge.sqlite"
                if db_file.exists():
                    con = sqlite3.connect(str(db_file))
                    count = con.execute("SELECT COUNT(*) FROM ruvon_chunks").fetchone()[0]
                    sources = {r[0] for r in con.execute("SELECT DISTINCT source FROM ruvon_chunks")}
                    con.close()
        except Exception as e:
            logger.warning("[KnowledgeBase] stats error: %s", e)

        manifest = self._load_manifest()
        return {
            "chunk_count": count,
            "source_count": len(sources),
            "model": self.model_name,
            "backend": self._backend,
            "db_path": str(self.db_path),
            "files_indexed": len(manifest),
        }

    # ------------------------------------------------------------------
    # Manifest (incremental rebuild)
    # ------------------------------------------------------------------

    def _load_manifest(self) -> Dict[str, str]:
        if self.DEFAULT_MANIFEST_PATH.exists():
            try:
                return json.loads(self.DEFAULT_MANIFEST_PATH.read_text())
            except Exception:
                pass
        return {}

    def _save_manifest(self, manifest: Dict[str, str]) -> None:
        self.DEFAULT_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.DEFAULT_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    """Walk up from this file to find the project root (contains pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()
