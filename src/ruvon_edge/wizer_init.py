"""
Wizer pre-initialization hook for ruvon-edge WASM builds.

This module is invoked once at compile time by the Wizer snapshotting tool:

    wizer --init-func=ruvon_pre_init -o dist/ruvon_edge_snapshotted.wasm dist/ruvon_edge.wasm

Wizer executes ruvon_pre_init() inside the WASM linear memory, runs all the
top-level imports, and saves the resulting memory snapshot into the output
binary.  When the snapshotted binary is loaded at runtime, all of these modules
are already parsed and initialized — cold-start drops from 300ms–2s to <5ms.

Requirements:
    cargo install wizer --all-features
    (or: https://github.com/bytecodealliance/wizer/releases)

This file is NOT imported at normal runtime — it is only referenced by
build_wasi.sh as the --init-func target.
"""


def ruvon_pre_init() -> None:
    """Pre-load heavy dependencies into WASM linear memory via Wizer.

    Called once at build time.  All imported names are discarded; the side
    effect is that Python's import machinery has already parsed, compiled, and
    initialized these modules before the snapshot is taken.
    """
    # Standard library pre-loads (always available in py2wasm)
    import asyncio  # noqa: F401
    import json  # noqa: F401
    import logging  # noqa: F401
    import uuid  # noqa: F401

    # Heavy third-party deps
    import yaml  # noqa: F401
    import pydantic  # noqa: F401

    # Ruvon core models and builder (largest parse cost)
    from ruvon.models import WorkflowStep  # noqa: F401
    from ruvon.builder import WorkflowBuilder  # noqa: F401

    # Edge agent — the main entry point class
    from ruvon_edge.agent import RuvonEdgeAgent  # noqa: F401

    # orjson is optional (may not compile to WASM), so guard it
    try:
        import orjson  # noqa: F401
    except ImportError:
        pass
