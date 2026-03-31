"""Tests for KnowledgeBase indexer — chunking, dedup, and file type handling."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Unit tests (no fastembed/lancedb required)
# ---------------------------------------------------------------------------

def test_split_text_respects_max_chars():
    from rufus.builder_ai.knowledge.indexer import _split_text

    long_text = ("word " * 300).strip()  # ~1500 chars
    chunks = _split_text(long_text, max_chars=500)
    for chunk in chunks:
        assert len(chunk) <= 600, f"Chunk too long: {len(chunk)} chars"
    assert len(chunks) > 1


def test_split_text_no_split_needed():
    from rufus.builder_ai.knowledge.indexer import _split_text

    short = "This is a short paragraph."
    result = _split_text(short, max_chars=500)
    assert result == [short]


def test_chunk_yaml_file(tmp_path):
    from rufus.builder_ai.knowledge.indexer import _chunk_yaml_file

    yaml_file = tmp_path / "test_workflow.yaml"
    yaml_file.write_text("workflow_type: TestWorkflow\nsteps:\n  - name: Step1\n")

    chunks = _chunk_yaml_file(yaml_file)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "yaml_example"
    assert "TestWorkflow" in chunks[0].text
    assert chunks[0].source == str(yaml_file)


def test_chunk_markdown_extracts_yaml_fences(tmp_path):
    from rufus.builder_ai.knowledge.indexer import _chunk_markdown

    md_file = tmp_path / "guide.md"
    md_file.write_text(
        "# How to configure\n\nSome prose here.\n\n"
        "```yaml\nworkflow_type: Example\nsteps: []\n```\n\n"
        "More prose after the block.\n"
    )

    chunks = _chunk_markdown(md_file, "explanation")
    yaml_chunks = [c for c in chunks if c.chunk_type == "yaml_example"]
    prose_chunks = [c for c in chunks if c.chunk_type == "explanation"]

    assert len(yaml_chunks) >= 1, "Should extract at least one YAML fence chunk"
    assert "workflow_type: Example" in yaml_chunks[0].text
    assert len(prose_chunks) >= 1, "Should also have prose chunks"


def test_chunk_markdown_dedup_by_id(tmp_path):
    from rufus.builder_ai.knowledge.indexer import _chunk_markdown

    md_file = tmp_path / "guide.md"
    md_file.write_text("# Section\n\nParagraph A.\n\nParagraph B.\n")

    chunks_1 = _chunk_markdown(md_file, "explanation")
    chunks_2 = _chunk_markdown(md_file, "explanation")

    ids_1 = {c.id for c in chunks_1}
    ids_2 = {c.id for c in chunks_2}
    assert ids_1 == ids_2, "Same file should produce same chunk IDs (deterministic)"


def test_file_hash_consistency(tmp_path):
    from rufus.builder_ai.knowledge.indexer import _file_hash

    f = tmp_path / "test.md"
    f.write_text("Hello world")
    h1 = _file_hash(f)
    h2 = _file_hash(f)
    assert h1 == h2
    assert len(h1) == 16


def test_file_hash_changes_on_content_change(tmp_path):
    from rufus.builder_ai.knowledge.indexer import _file_hash

    f = tmp_path / "test.md"
    f.write_text("content A")
    h1 = _file_hash(f)
    f.write_text("content B")
    h2 = _file_hash(f)
    assert h1 != h2


def test_load_and_chunk_skips_binary_files(tmp_path):
    from rufus.builder_ai.knowledge.indexer import _load_and_chunk

    (tmp_path / "doc.md").write_text("# Title\n\nText.")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "workflow.yaml").write_text("workflow_type: Test\nsteps: []\n")

    chunks = _load_and_chunk([tmp_path])
    sources = {c.source for c in chunks}
    assert not any(".png" in s for s in sources), "PNG should be skipped"
    assert any(".md" in s for s in sources), "Markdown should be indexed"
    assert any(".yaml" in s for s in sources), "YAML should be indexed"


def test_chunk_type_from_path():
    from rufus.builder_ai.knowledge.indexer import _chunk_type_from_path

    assert _chunk_type_from_path(Path("docs/lessons.md")) == "lesson"
    assert _chunk_type_from_path(Path("config/payment.yaml")) == "yaml_example"
    assert _chunk_type_from_path(Path("docs/step-types.md")) == "step_reference"
    assert _chunk_type_from_path(Path("docs/architecture.md")) == "explanation"


# ---------------------------------------------------------------------------
# Integration smoke test (skipped if fastembed/lancedb not installed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    pytest.importorskip("fastembed", reason="fastembed not installed") is None,
    reason="fastembed not installed",
)
def test_knowledge_base_build_and_retrieve(tmp_path):
    fastembed = pytest.importorskip("fastembed")
    lancedb = pytest.importorskip("lancedb")

    from rufus.builder_ai.knowledge.indexer import KnowledgeBase

    # Create minimal docs
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# HUMAN_APPROVAL Step\n\n"
        "Use HUMAN_APPROVAL to pause workflows for operator review.\n\n"
        "```yaml\ntype: HUMAN_APPROVAL\napproval_config:\n  timeout_hours: 24\n```\n"
    )

    kb = KnowledgeBase.build(
        source_roots=[docs],
        db_path=tmp_path / "test.lance",
        force=True,
    )

    import asyncio
    chunks = asyncio.run(kb.retrieve("how to configure human approval timeout"))
    assert len(chunks) > 0
    assert any("HUMAN_APPROVAL" in c.text or "approval_config" in c.text for c in chunks)
