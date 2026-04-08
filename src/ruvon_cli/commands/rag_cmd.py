"""CLI commands for managing the Rufus AI knowledge base (RAG + RAFT)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="rag",
    help="Manage the Rufus knowledge base for AI workflow builder (RAG + RAFT)",
    no_args_is_help=True,
)

logger = logging.getLogger(__name__)


def _require_knowledge():
    """Import knowledge module or exit with a helpful error."""
    try:
        from ruvon.builder_ai.knowledge import KnowledgeBase
        return KnowledgeBase
    except ImportError:
        typer.secho(
            "ERROR: Knowledge base dependencies not installed.\n"
            "Install with: pip install 'ruvon-sdk[rag]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)


@app.command("build")
def rag_build(
    source: Optional[Path] = typer.Option(
        None, "--source", "-s",
        help="Additional documentation directory to index",
    ),
    db_path: Optional[Path] = typer.Option(
        None, "--db",
        help="Vector store path (default: ~/.ruvon/knowledge.lance)",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Embedding model override (auto-selected by RAM if omitted)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Full rebuild even if nothing changed",
    ),
):
    """Index Rufus documentation into the local vector store.

    By default, indexes all docs found under the project root:
    docs/, config/, .claude/, and CLAUDE.md.

    Examples:
        ruvon rag build                      # Incremental rebuild
        ruvon rag build --force              # Full rebuild
        ruvon rag build --source ./my-docs   # Include extra docs
    """
    KnowledgeBase = _require_knowledge()

    source_roots = None
    if source:
        if not source.exists():
            typer.secho(f"ERROR: Source path not found: {source}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        source_roots = [source]

    typer.echo("Building knowledge index...")
    try:
        kb = KnowledgeBase.build(
            source_roots=source_roots,
            db_path=db_path,
            model_name=model,
            force=force,
        )
        stats = kb.stats()
        typer.secho(
            f"Index ready: {stats['chunk_count']} chunks from {stats['files_indexed']} files",
            fg=typer.colors.GREEN,
            bold=True,
        )
        typer.echo(f"  Backend:  {stats['backend']}")
        typer.echo(f"  Model:    {stats['model']}")
        typer.echo(f"  Location: {stats['db_path']}")
    except Exception as e:
        typer.secho(f"ERROR: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command("stats")
def rag_stats(
    db_path: Optional[Path] = typer.Option(None, "--db", help="Vector store path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show knowledge base statistics."""
    KnowledgeBase = _require_knowledge()
    try:
        kb = KnowledgeBase(db_path=db_path)
        stats = kb.stats()
        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            typer.echo("\nKnowledge Base Statistics")
            typer.echo("=" * 40)
            typer.echo(f"  Chunks indexed:  {stats['chunk_count']}")
            typer.echo(f"  Source files:    {stats['files_indexed']}")
            typer.echo(f"  Source count:    {stats['source_count']}")
            typer.echo(f"  Embedding model: {stats['model']}")
            typer.echo(f"  Backend:         {stats['backend']}")
            typer.echo(f"  Location:        {stats['db_path']}")
    except Exception as e:
        typer.secho(f"ERROR: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command("search")
def rag_search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
    db_path: Optional[Path] = typer.Option(None, "--db", help="Vector store path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Test retrieval: show top-K chunks matching a query.

    Examples:
        ruvon rag search "how to configure HUMAN_APPROVAL step"
        ruvon rag search "saga compensation pattern" --top-k 3
    """
    KnowledgeBase = _require_knowledge()

    async def _search():
        kb = KnowledgeBase(db_path=db_path)
        chunks = await kb.retrieve(query, top_k=top_k)
        if json_output:
            typer.echo(json.dumps(
                [c.model_dump() for c in chunks],
                indent=2,
                ensure_ascii=False,
            ))
        else:
            typer.echo(f"\nTop {len(chunks)} results for: {query!r}\n")
            for i, chunk in enumerate(chunks, 1):
                typer.secho(
                    f"[{i}] score={chunk.score:.3f}  type={chunk.chunk_type}",
                    fg=typer.colors.CYAN,
                )
                typer.echo(f"    Source:  {chunk.source}")
                typer.echo(f"    Section: {chunk.section}")
                preview = chunk.text[:200].replace("\n", " ")
                typer.echo(f"    Preview: {preview}...")
                typer.echo()

    try:
        asyncio.run(_search())
    except Exception as e:
        typer.secho(f"ERROR: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command("train-raft")
def rag_train_raft(
    base_model: str = typer.Option(
        "llama3", "--base-model", help="Ollama base model to fine-tune from"
    ),
    output_model: Optional[str] = typer.Option(
        None, "--output-model",
        help="Output model name (default: ruvon-expert-{hash})",
    ),
    samples: int = typer.Option(
        500, "--samples", help="Max training samples to generate"
    ),
    backend: str = typer.Option(
        "anthropic", "--backend",
        help="LLM backend for dataset generation: anthropic | ollama",
    ),
    db_path: Optional[Path] = typer.Option(None, "--db", help="Vector store path"),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", help="Where to write the JSONL dataset"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Generate dataset only; do not fine-tune Ollama",
    ),
):
    """Generate RAFT training data and optionally fine-tune a local Ollama model.

    Step 1: Generates Alpaca JSONL training samples from indexed docs using an LLM.
    Step 2: (unless --dry-run) Calls 'ollama create ruvon-expert' to fine-tune.

    The trained model is versioned by a hash of the training dataset. When you
    update the docs and rebuild the index, run this command again to re-train.

    Examples:
        ruvon rag train-raft --dry-run               # Generate dataset, inspect it
        ruvon rag train-raft                         # Train ruvon-expert from llama3
        ruvon rag train-raft --base-model mistral    # Train from a different base
    """
    KnowledgeBase = _require_knowledge()

    async def _train():
        from ruvon.builder_ai.knowledge.raft_dataset import RAFTDatasetGenerator
        from ruvon.builder_ai.knowledge.raft_trainer import RAFTTrainer
        from ruvon.builder_ai.stages.base import LLMStageMixin

        kb = KnowledgeBase(db_path=db_path)

        # Set up LLM for dataset generation
        mixin = LLMStageMixin(backend=backend)
        dataset_dir = output_dir or (Path.home() / ".ruvon")
        dataset_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = dataset_dir / "raft_dataset.jsonl"

        typer.echo(f"Generating RAFT training samples (max {samples})...")
        generator = RAFTDatasetGenerator(
            llm_call=mixin._call_llm,
            questions_per_chunk=3,
        )
        max_chunks = max(1, samples // 3)
        n = await generator.generate(kb, dataset_path, max_chunks=max_chunks)
        typer.secho(f"Generated {n} training samples → {dataset_path}", fg=typer.colors.GREEN)

        if dry_run:
            typer.echo("\nDry run complete. Inspect the dataset before training:")
            typer.echo(f"  {dataset_path}")
            typer.echo("\nSample entry:")
            first_line = dataset_path.read_text().split("\n")[0]
            sample = json.loads(first_line)
            typer.echo(f"  Question: {sample['instruction']}")
            typer.echo(f"  Answer:   {sample['output'][:120]}...")
            return

        trainer = RAFTTrainer()
        versioned_name = output_model or trainer.versioned_model_name(dataset_path)
        typer.echo(f"\nFine-tuning Ollama model '{versioned_name}' from '{base_model}'...")
        typer.echo("This may take several minutes...")
        try:
            final_name = trainer.create_model(
                dataset_path=dataset_path,
                base_model=base_model,
                output_model=versioned_name,
            )
            typer.secho(
                f"\nModel '{final_name}' created successfully.",
                fg=typer.colors.GREEN, bold=True,
            )
            typer.echo(
                f"\nUse it with: ruvon build generate ... --backend ollama --model {final_name}"
            )
        except FileNotFoundError:
            typer.secho(
                "ERROR: 'ollama' CLI not found. Install Ollama: https://ollama.ai",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1)

    try:
        asyncio.run(_train())
    except Exception as e:
        typer.secho(f"ERROR: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
