"""
PagedBrowserInferenceProvider — shard-paged generative inference for Pyodide/browser.

Delegates all heavy lifting to the JS side via `globalThis.runPagedInference`.
The JS controller (OPFSShardCache + ShardScheduler + wllama) handles:
  - OPFS-backed shard caching
  - Double-buffer prefetch
  - Logic-gated fast path (shard-0 only for simple queries)
  - Token streaming via postMessage

This provider is a thin Pyodide ↔ JS FFI bridge. It requires `runPagedInference`
to be registered on `globalThis` in the Web Worker before any inference step runs.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from rufus.providers.inference import (
    InferenceProvider,
    InferenceResult,
    InferenceRuntime,
    ModelMetadata,
)
from rufus.models import AIInferenceConfig


class PagedBrowserInferenceProvider(InferenceProvider):
    """
    Shard-paged generative inference for Pyodide/browser environments.

    Memory budget: only `max_resident_shards` × shard_size_mb is held in WASM
    at any time. Remaining shards are cached in OPFS and paged in/out as needed.

    Usage::

        provider = PagedBrowserInferenceProvider(model_id="bitnet-2b")
        # The JS side must expose globalThis.runPagedInference before the step runs.

    Requires:
        - Pyodide runtime (``from js import runPagedInference`` must succeed)
        - ``globalThis.runPagedInference`` registered in the Web Worker
    """

    def __init__(self, model_id: str = "bitnet-2b"):
        self._model_id = model_id
        self._loaded: bool = False

    # ── InferenceProvider ABC ──────────────────────────────────────────────────

    @property
    def runtime(self) -> InferenceRuntime:
        return InferenceRuntime.CUSTOM

    async def initialize(self) -> None:
        """No-op: JS runtime initialises lazily on first inference call."""
        pass

    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        **kwargs,
    ) -> ModelMetadata:
        """Mark the model as available; actual shard loading happens in JS."""
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
            description="Shard-paged GGUF model (browser/OPFS)",
        )

    async def unload_model(self, model_name: str) -> bool:
        self._loaded = False
        return True

    def is_model_loaded(self, model_name: str) -> bool:
        return self._loaded

    def get_model_metadata(self, model_name: str) -> Optional[ModelMetadata]:
        if not self._loaded:
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
        return [self._model_id] if self._loaded else []

    async def close(self) -> None:
        self._loaded = False

    async def run_inference(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        **kwargs,
    ) -> InferenceResult:
        """
        Delegate inference to JS via Pyodide FFI.

        ``inputs`` is expected to contain a ``prompt`` key (str).
        The ``AIInferenceConfig`` is passed via kwargs as ``config``.
        """
        config: Optional[AIInferenceConfig] = kwargs.get("config")
        max_tokens = (config.max_tokens if config else None) or 128
        threshold = (config.logic_gate_threshold if config else None) or 0.5

        prompt = inputs if isinstance(inputs, str) else (
            inputs.get("prompt") or json.dumps(inputs)
        )

        t0 = time.monotonic()
        try:
            from js import runPagedInference  # type: ignore[import]
            payload = json.dumps({"prompt": prompt, "threshold": threshold})
            result = await runPagedInference(payload, max_tokens)
            latency_ms = (time.monotonic() - t0) * 1000

            return InferenceResult(
                outputs={
                    "text": str(result.text),
                    "tokens_generated": int(result.tokens_generated),
                    "shards_loaded": int(result.shards_loaded),
                    "latency_ms": float(result.latency_ms),
                    "complexity_score": float(result.complexity_score),
                    "path_taken": "fast_path" if result.shards_loaded <= 1 else "full_inference",
                },
                inference_time_ms=latency_ms,
                model_name=model_name,
                model_version="1.0.0",
                success=True,
            )
        except ImportError:
            # Not running in Pyodide — return a stub result so non-browser tests pass
            return InferenceResult(
                outputs={"text": "", "tokens_generated": 0, "shards_loaded": 0,
                         "latency_ms": 0.0, "complexity_score": 0.0, "path_taken": "unavailable"},
                inference_time_ms=0.0,
                model_name=model_name,
                model_version="1.0.0",
                success=False,
                error_message="runPagedInference not available outside Pyodide",
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
