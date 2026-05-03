"""
LlamaCppPagedProvider — native edge inference via llama.cpp with OS-level mmap paging.

On native Linux/macOS edge devices (Raspberry Pi, field terminals, etc.) the OS
memory manager pages individual transformer layers to/from flash automatically when
the model file is opened with ``--mmap``.  No custom layer scheduler is needed —
the OS handles eviction.

Memory footprint: only resident pages are held in RAM (~200 MB even for a 1.2 GB
model on a 512 MB device).

Requirements:
    - ``llama-cli`` binary (from llama.cpp release) on PATH or supplied as ``binary_path``
    - A GGUF model file on local storage
    - Python 3.9+ (asyncio.create_subprocess_exec)

Usage::

    provider = LlamaCppPagedProvider(
        binary_path="llama-cli",
        model_path="/opt/models/bitnet-2b-q4.gguf",
    )
    result = await provider.run_inference(
        model_name="bitnet-2b",
        inputs={"prompt": "Diagnose relay fault on circuit breaker CB-42"},
        config=ai_config,
    )
    print(result.outputs["text"])
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from ruvon.providers.inference import (
    InferenceProvider,
    InferenceResult,
    InferenceRuntime,
    ModelMetadata,
)
from ruvon.models import AIInferenceConfig


class LlamaCppPagedProvider(InferenceProvider):
    """
    Native edge: wraps llama.cpp CLI binary with ``--mmap`` for OS-level layer paging.

    The ``--mmap`` flag maps the GGUF file directly into the process address space.
    Only accessed pages (the active transformer layers) are loaded into physical RAM;
    cold layers remain on flash until needed.  The OS evicts the least-recently-used
    pages when memory pressure rises, giving automatic layer-level paging with zero
    custom scheduler code.

    Suitable for:
        - Raspberry Pi 4 / CM4 (512 MB – 8 GB RAM)
        - Field terminals with 256 MB+ flash and 512 MB+ RAM
        - Any POSIX system with a modern virtual memory manager

    Not suitable for:
        - Windows (mmap support in llama.cpp is limited on Win32)
        - Containers with ``--memory`` limits < model size (no swap available)
    """

    def __init__(
        self,
        binary_path: str = "llama-cli",
        model_path: Optional[str] = None,
        n_threads: int = 4,
        context_size: int = 2048,
    ):
        self._binary = binary_path
        self._model = model_path
        self._n_threads = n_threads
        self._context_size = context_size
        self._loaded: bool = False
        self._model_name: Optional[str] = None

    # ── InferenceProvider ABC ──────────────────────────────────────────────────

    @property
    def runtime(self) -> InferenceRuntime:
        return InferenceRuntime.CUSTOM

    async def initialize(self) -> None:
        """No-op: llama.cpp binary is exec'd fresh per inference call."""
        pass

    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        **kwargs,
    ) -> ModelMetadata:
        """Record model path; actual loading happens inside the subprocess."""
        path = model_path or self._model
        if not path:
            raise ValueError("model_path must be provided for LlamaCppPagedProvider")
        self._model = path
        self._model_name = model_name
        self._loaded = True
        return ModelMetadata(
            name=model_name,
            version=model_version,
            runtime=self.runtime,
            input_shapes={},
            output_shapes={},
            input_dtypes={},
            output_dtypes={},
            size_bytes=0,
            description=f"llama.cpp mmap model at {path}",
        )

    async def unload_model(self, model_name: str) -> bool:
        self._loaded = False
        self._model_name = None
        return True

    def is_model_loaded(self, model_name: str) -> bool:
        return self._loaded and self._model_name == model_name

    def get_model_metadata(self, model_name: str) -> Optional[ModelMetadata]:
        if not self.is_model_loaded(model_name):
            return None
        return ModelMetadata(
            name=model_name,
            version="1.0.0",
            runtime=self.runtime,
            input_shapes={},
            output_shapes={},
            input_dtypes={},
            output_dtypes={},
            size_bytes=0,
        )

    def list_loaded_models(self) -> List[str]:
        return [self._model_name] if self._loaded and self._model_name else []

    async def close(self) -> None:
        self._loaded = False

    async def run_inference(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        **kwargs,
    ) -> InferenceResult:
        """
        Run llama.cpp with ``--mmap`` in a subprocess.

        ``inputs`` should be a str prompt or a dict with a ``prompt`` key.
        """
        config: Optional[AIInferenceConfig] = kwargs.get("config")
        max_tokens = (config.max_tokens if config else None) or 128

        if self._model is None:
            raise RuntimeError(
                "LlamaCppPagedProvider: model_path not set. "
                "Call load_model() first or pass model_path= to __init__."
            )

        prompt = inputs if isinstance(inputs, str) else (
            inputs.get("prompt") or json.dumps(inputs)
        )

        cmd = [
            self._binary,
            "-m", self._model,
            "--mmap",
            "-p", prompt,
            "-n", str(max_tokens),
            "-t", str(self._n_threads),
            "-c", str(self._context_size),
            "--no-display-prompt",
            "--log-disable",
        ]

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            latency_ms = (time.monotonic() - t0) * 1000

            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()
                return InferenceResult(
                    outputs={},
                    inference_time_ms=latency_ms,
                    model_name=model_name,
                    model_version="1.0.0",
                    success=False,
                    error_message=f"llama.cpp exited {proc.returncode}: {err}",
                )

            text = stdout.decode(errors="replace").strip()
            tokens_est = len(text.split())
            return InferenceResult(
                outputs={
                    "text": text,
                    "tokens_generated": tokens_est,
                    "latency_ms": latency_ms,
                    "path_taken": "native_mmap",
                },
                inference_time_ms=latency_ms,
                model_name=model_name,
                model_version="1.0.0",
                success=True,
            )
        except FileNotFoundError:
            return InferenceResult(
                outputs={},
                inference_time_ms=(time.monotonic() - t0) * 1000,
                model_name=model_name,
                model_version="1.0.0",
                success=False,
                error_message=(
                    f"llama.cpp binary not found: '{self._binary}'. "
                    "Install from https://github.com/ggml-org/llama.cpp/releases"
                ),
            )
        except Exception as exc:
            return InferenceResult(
                outputs={},
                inference_time_ms=(time.monotonic() - t0) * 1000,
                model_name=model_name,
                model_version="1.0.0",
                success=False,
                error_message=str(exc),
            )
