"""
ruvon build — AI-assisted workflow builder.

Converts natural language descriptions into validated, governance-checked
Ruvon workflow YAML definitions.

Supports three model backends:
  anthropic  — Claude via Anthropic API (requires ANTHROPIC_API_KEY)
  ollama     — any local model via Ollama REST API (no API key needed)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="build",
    help="AI-assisted workflow builder — natural language to Ruvon YAML",
    no_args_is_help=True,
)

# Colour constants for consistent output
_GREEN = typer.colors.GREEN
_YELLOW = typer.colors.YELLOW
_RED = typer.colors.RED
_CYAN = typer.colors.CYAN


def _echo_pipeline(msg: str) -> None:
    typer.secho(f"[Pipeline] {msg}", fg=_CYAN)


def _echo_workflow(msg: str) -> None:
    typer.secho(f"[Workflow] {msg}", fg=_GREEN, bold=True)


def _echo_warn(msg: str) -> None:
    typer.secho(f"[!] {msg}", fg=_YELLOW)


def _echo_error(msg: str) -> None:
    typer.secho(f"[✗] {msg}", fg=_RED, err=True)


def _print_lint_report(lint_report) -> None:
    """Print governance lint results with colours."""
    for result in lint_report.results:
        if result.passed:
            colour, symbol = _GREEN, "PASS"
        elif result.severity == "ERROR":
            colour, symbol = _RED, "FAIL"
        elif result.severity == "WARN":
            colour, symbol = _YELLOW, "WARN"
        else:
            colour, symbol = _CYAN, "INFO"
        typer.secho(f"  {result.rule_id:<10} {symbol:<5}  {result.message}", fg=colour)


def _get_builder(backend: str, model: Optional[str], ollama_url: str, api_key: Optional[str]):
    from ruvon.builder_ai import AIWorkflowBuilder
    return AIWorkflowBuilder(
        backend=backend,
        model=model or None,
        ollama_base_url=ollama_url,
        api_key=api_key,
    )


@app.command("generate")
def generate(
    prompt: str = typer.Argument(..., help="Natural language workflow description"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate and lint without saving to disk"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output file path (default: stdout)"),
    fmt: str = typer.Option("yaml", "--format", help="Output format: yaml | json"),
    no_lint: bool = typer.Option(False, "--no-lint", help="Skip governance linter (requires --force)"),
    force: bool = typer.Option(False, "--force", help="Allow skipping governance linter / suppress lint errors"),
    backend: str = typer.Option("anthropic", "--backend", help="LLM backend: anthropic | ollama"),
    model: Optional[str] = typer.Option(None, "--model", help="Model override, e.g. llama3 or claude-opus-4-6"),
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url", help="Ollama server URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY", help="Anthropic API key"),
    from_file: Optional[Path] = typer.Option(None, "--from-file", help="Modify an existing workflow YAML"),
):
    """
    Generate a Ruvon workflow from a natural language description.

    Examples:

        ruvon build generate "handle incoming bid submissions for Neelo UAE"

        ruvon build generate "handle bids" --backend ollama --model llama3

        ruvon build generate "handle bids" --dry-run --out bid-intake.yaml

        ruvon build generate --from-file existing.yaml "add anomaly detection"
    """
    asyncio.run(
        _run_single_shot(
            prompt=prompt,
            from_file=from_file,
            dry_run=dry_run,
            out=out,
            fmt=fmt,
            no_lint=no_lint,
            force=force,
            backend=backend,
            model=model,
            ollama_url=ollama_url,
            api_key=api_key,
        )
    )


@app.command("interactive")
def interactive_session(
    backend: str = typer.Option("anthropic", "--backend", help="LLM backend: anthropic | ollama"),
    model: Optional[str] = typer.Option(None, "--model", help="Model override"),
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Default save path"),
):
    """
    Open a multi-turn interactive REPL for workflow generation.

    Type your intent or modification. Commands: show | save [file] | exit

    Example:

        ruvon build interactive --backend ollama --model llama3
    """
    asyncio.run(_run_interactive(backend, model, ollama_url, api_key, out))


@app.command("explain")
def explain_workflow(
    workflow_file: Path = typer.Argument(..., help="Path to a Ruvon workflow YAML file"),
    backend: str = typer.Option("anthropic", "--backend", help="LLM backend: anthropic | ollama"),
    model: Optional[str] = typer.Option(None, "--model"),
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="ANTHROPIC_API_KEY"),
):
    """
    Explain an existing workflow YAML file in plain English.

    Example:

        ruvon build explain config/payment_workflow.yaml
    """
    asyncio.run(_run_explain(workflow_file, backend, model, ollama_url, api_key))


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------

async def _run_single_shot(
    prompt: str,
    from_file: Optional[Path],
    dry_run: bool,
    out: Optional[Path],
    fmt: str,
    no_lint: bool,
    force: bool,
    backend: str,
    model: Optional[str],
    ollama_url: str,
    api_key: Optional[str],
) -> None:
    # If --from-file, prepend existing YAML content to the prompt
    if from_file:
        if not from_file.exists():
            _echo_error(f"File not found: {from_file}")
            raise typer.Exit(1)
        existing_yaml = from_file.read_text()
        prompt = f"{prompt}\n\nExisting workflow to modify:\n{existing_yaml}"

    builder = _get_builder(backend, model, ollama_url, api_key)
    _echo_pipeline(f"Parsing intent... (backend={backend}, model={builder.model})")

    from ruvon.builder_ai.models import BuildResult
    result: BuildResult = await builder.build(
        prompt=prompt,
        skip_lint=no_lint,
        skip_lint_force=force,
    )

    # Handle clarification loop (max 3 attempts)
    attempts = 0
    while result.needs_clarification and attempts < 3:
        attempts += 1
        typer.echo("")
        typer.secho("> Ruvon needs a few clarifications before generating:", fg=_CYAN, bold=True)
        answers = {}
        for i, q in enumerate(result.questions, 1):
            answer = typer.prompt(f"  [{i}] {q}", default="")
            answers[q] = answer
        typer.echo("")
        _echo_pipeline("Resolving answers and generating...")
        result = await builder.build(
            prompt=prompt,
            clarification_answers=answers,
            skip_lint=no_lint,
            skip_lint_force=force,
        )

    if result.errors:
        _echo_error("Schema validation failed:")
        for err in result.errors:
            typer.secho(f"  • {err}", fg=_RED, err=True)
        raise typer.Exit(1)

    # Print lint results
    if result.lint_report:
        typer.echo("")
        typer.secho("[Pipeline] Governance lint results:", fg=_CYAN)
        _print_lint_report(result.lint_report)
        typer.echo("")
        if result.lint_report.has_errors and not force:
            _echo_error(
                f"Lint produced {result.lint_report.failed} error(s). "
                "Review and fix, or re-run with --force to suppress."
            )
            raise typer.Exit(1)

    # Determine output content
    if fmt == "json":
        content = json.dumps(result.workflow_dict, indent=2)
    else:
        content = result.yaml or ""

    # Show quality gate info if retries were needed
    if result.yaml_gate_attempts > 1:
        _echo_warn(f"YAML quality gate needed {result.yaml_gate_attempts} attempt(s) to pass")
    if result.stub_gate_attempts > 1:
        _echo_warn(f"Stub quality gate needed {result.stub_gate_attempts} attempt(s) to pass")
    if result.quality == "PARTIAL":
        _echo_warn("Stubs could not be fully validated — review before use")

    if dry_run:
        typer.echo(content)
        if result.stubs_py:
            typer.echo("")
            typer.secho("# --- Generated step stubs ---", fg=_CYAN)
            typer.echo(result.stubs_py)
        step_count = len((result.workflow_dict or {}).get("steps", []))
        _echo_workflow(f"Dry run complete — {step_count} steps generated (not saved)")
        return

    if out:
        out.write_text(content)
        step_count = len((result.workflow_dict or {}).get("steps", []))
        _echo_workflow(f"Saved to {out} — {step_count} steps")
        # Write stubs alongside YAML as <stem>_steps.py
        if result.stubs_py:
            stubs_path = out.with_name(out.stem + "_steps.py")
            stubs_path.write_text(result.stubs_py)
            _echo_workflow(f"Step stubs saved to {stubs_path}")
    else:
        typer.echo(content)
        if result.stubs_py:
            typer.echo("")
            typer.secho("# --- Generated step stubs (use --out to save alongside YAML) ---", fg=_CYAN)
            typer.echo(result.stubs_py)


async def _run_explain(
    workflow_file: Path,
    backend: str,
    model: Optional[str],
    ollama_url: str,
    api_key: Optional[str],
) -> None:
    if not workflow_file.exists():
        _echo_error(f"File not found: {workflow_file}")
        raise typer.Exit(1)
    workflow_yaml = workflow_file.read_text()
    builder = _get_builder(backend, model, ollama_url, api_key)
    _echo_pipeline(f"Explaining {workflow_file}...")
    explanation = await builder.explain(workflow_yaml)
    typer.echo("")
    typer.secho(str(workflow_file), fg=_CYAN, bold=True)
    typer.echo(explanation)
    typer.echo("")


async def _interactive_stub_fill(builder, result) -> Optional[str]:
    """Walk each STANDARD step stub and optionally fill via LLM description."""
    import re
    stubs_py = result.stubs_py
    if not stubs_py:
        return None

    # Extract function names that have TODO bodies
    todo_funcs = re.findall(r"^def (\w+)\(", stubs_py, re.MULTILINE)
    if not todo_funcs:
        return stubs_py

    typer.echo("")
    typer.secho(
        f"[Stubs] {len(todo_funcs)} step function(s) generated. "
        "Describe each one (press Enter to leave as TODO):",
        fg=_CYAN,
    )
    for func_name in todo_funcs:
        description = typer.prompt(f"  {func_name}", default="").strip()
        if not description:
            continue
        try:
            sig_match = re.search(r"(def " + re.escape(func_name) + r"\([^)]*\):)", stubs_py)
            signature = sig_match.group(1) if sig_match else f"def {func_name}(state, context):"
            stubs_py = await builder.stub_filler.fill_and_apply(
                stubs_py=stubs_py,
                func_name=func_name,
                signature=signature,
                description=description,
            )
            typer.secho(f"  ✓ {func_name} filled", fg=_GREEN)
        except Exception as e:  # noqa: BLE001
            _echo_warn(f"Could not fill '{func_name}': {e}")

    return stubs_py


async def _run_interactive(
    backend: str,
    model: Optional[str],
    ollama_url: str,
    api_key: Optional[str],
    out: Optional[Path],
) -> None:
    builder = _get_builder(backend, model, ollama_url, api_key)
    typer.secho(
        f"\nRuvon Workflow Builder (interactive) — backend={backend}, model={builder.model}",
        fg=_CYAN, bold=True,
    )
    typer.secho("Type your intent, or 'help' for commands. Ctrl+C to exit.\n", fg=_CYAN)

    current_yaml: Optional[str] = None
    current_stubs: Optional[str] = None

    while True:
        try:
            raw = typer.prompt(">", prompt_suffix=" ")
        except (KeyboardInterrupt, EOFError):
            typer.echo("\nExiting.")
            break

        raw = raw.strip()
        if not raw:
            continue

        if raw.lower() in ("exit", "quit", "q"):
            break

        if raw.lower() == "help":
            typer.echo("Commands: exit | save [file] | show | show-stubs")
            typer.echo("Or type your intent / modification request.")
            continue

        if raw.lower() == "show":
            if current_yaml:
                typer.echo(current_yaml)
            else:
                _echo_warn("No workflow generated yet.")
            continue

        if raw.lower() == "show-stubs":
            if current_stubs:
                typer.echo(current_stubs)
            else:
                _echo_warn("No stubs generated yet.")
            continue

        if raw.lower().startswith("save"):
            parts = raw.split(maxsplit=1)
            save_path = Path(parts[1]) if len(parts) > 1 else out or Path("workflow.yaml")
            if current_yaml:
                save_path.write_text(current_yaml)
                _echo_workflow(f"Saved to {save_path}")
                if current_stubs:
                    stubs_path = save_path.with_name(save_path.stem + "_steps.py")
                    stubs_path.write_text(current_stubs)
                    _echo_workflow(f"Step stubs saved to {stubs_path}")
            else:
                _echo_warn("No workflow to save yet.")
            continue

        # Build or modify
        prompt_for_build = raw
        if current_yaml:
            prompt_for_build = f"{raw}\n\nExisting workflow to modify:\n{current_yaml}"

        _echo_pipeline("Generating...")
        try:
            result = await builder.build(prompt=prompt_for_build)
        except Exception as e:
            _echo_error(f"Generation failed: {e}")
            continue

        if result.needs_clarification:
            typer.secho("> Ruvon needs clarifications:", fg=_CYAN)
            answers = {}
            for i, q in enumerate(result.questions, 1):
                answer = typer.prompt(f"  [{i}] {q}", default="")
                answers[q] = answer
            result = await builder.build(prompt=prompt_for_build, clarification_answers=answers)

        if result.errors:
            _echo_error("Validation errors: " + ", ".join(result.errors))
            continue

        if result.lint_report:
            typer.echo("")
            _print_lint_report(result.lint_report)
            typer.echo("")

        current_yaml = result.yaml
        step_count = len((result.workflow_dict or {}).get("steps", []))
        _echo_workflow(f"{step_count} steps generated")
        if current_yaml:
            typer.echo(current_yaml)

        # Stub fill-in phase: walk STANDARD steps and offer LLM body generation
        current_stubs = await _interactive_stub_fill(builder, result)
