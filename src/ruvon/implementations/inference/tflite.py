"""
TensorFlow Lite Inference Provider

Provides on-device ML inference using TensorFlow Lite runtime.
Optimized for edge devices with support for:
- CPU execution with multi-threading
- GPU delegate (where available)
- Edge TPU delegate (Coral devices)
- Quantized models for low-memory devices
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional
import numpy as np

from ruvon.providers.inference import (
    InferenceProvider,
    InferenceRuntime,
    InferenceResult,
    ModelMetadata,
)

logger = logging.getLogger(__name__)

# Try to import TFLite runtime
_TFLITE_AVAILABLE = False
_tflite_interpreter = None

try:
    # Try the lightweight tflite-runtime first
    import tflite_runtime.interpreter as tflite
    _tflite_interpreter = tflite.Interpreter
    _TFLITE_AVAILABLE = True
    logger.info("Using tflite-runtime for inference")
except ImportError:
    try:
        # Fall back to full TensorFlow
        import tensorflow as tf
        _tflite_interpreter = tf.lite.Interpreter
        _TFLITE_AVAILABLE = True
        logger.info("Using tensorflow.lite for inference")
    except ImportError:
        logger.warning(
            "TensorFlow Lite not available. Install with: "
            "pip install tflite-runtime  (lightweight) or pip install tensorflow"
        )


class TFLiteInferenceProvider(InferenceProvider):
    """
    TensorFlow Lite inference provider for edge devices.

    Features:
    - Lazy model loading
    - Configurable thread count
    - Support for quantized models
    - Optional GPU/EdgeTPU delegates

    Example:
        provider = TFLiteInferenceProvider(num_threads=4)
        await provider.initialize()
        await provider.load_model("models/detector.tflite", "detector")
        result = await provider.run_inference("detector", {"input": image_data})
    """

    def __init__(
        self,
        num_threads: int = 4,
        use_gpu: bool = False,
        use_edgetpu: bool = False,
    ):
        """
        Initialize TFLite provider.

        Args:
            num_threads: Number of CPU threads for inference
            use_gpu: Enable GPU delegate if available
            use_edgetpu: Enable Edge TPU delegate if available
        """
        if not _TFLITE_AVAILABLE:
            raise RuntimeError(
                "TensorFlow Lite not installed. Install with: pip install tflite-runtime"
            )

        self.num_threads = num_threads
        self.use_gpu = use_gpu
        self.use_edgetpu = use_edgetpu

        self._models: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    @property
    def runtime(self) -> InferenceRuntime:
        return InferenceRuntime.TFLITE

    async def initialize(self) -> None:
        """Initialize the TFLite runtime."""
        if self._initialized:
            return

        logger.info(
            f"Initializing TFLite provider (threads={self.num_threads}, "
            f"gpu={self.use_gpu}, edgetpu={self.use_edgetpu})"
        )
        self._initialized = True

    async def close(self) -> None:
        """Unload all models and clean up."""
        model_names = list(self._models.keys())
        for name in model_names:
            await self.unload_model(name)
        self._initialized = False
        logger.info("TFLite provider closed")

    def _get_delegates(self) -> List:
        """Get hardware delegates based on configuration."""
        delegates = []

        if self.use_edgetpu:
            try:
                from tflite_runtime.interpreter import load_delegate
                delegates.append(load_delegate('libedgetpu.so.1'))
                logger.info("Edge TPU delegate loaded")
            except Exception as e:
                logger.warning(f"Edge TPU delegate not available: {e}")

        if self.use_gpu:
            try:
                # Try to load GPU delegate
                from tflite_runtime.interpreter import load_delegate
                delegates.append(load_delegate('libdelegate.so'))
                logger.info("GPU delegate loaded")
            except Exception as e:
                logger.debug(f"GPU delegate not available: {e}")

        return delegates

    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        **kwargs
    ) -> ModelMetadata:
        """
        Load a TFLite model from disk.

        Args:
            model_path: Path to .tflite file
            model_name: Unique name for this model
            model_version: Version string
            **kwargs: Additional options (e.g., custom delegates)

        Returns:
            ModelMetadata with model information
        """
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")

        if model_name in self._models:
            logger.warning(f"Model {model_name} already loaded, replacing")
            await self.unload_model(model_name)

        logger.info(f"Loading TFLite model: {model_name} from {model_path}")

        # Get file size
        size_bytes = os.path.getsize(model_path)

        # Create interpreter
        delegates = kwargs.get("delegates") or self._get_delegates()

        interpreter = _tflite_interpreter(
            model_path=model_path,
            num_threads=self.num_threads,
            experimental_delegates=delegates if delegates else None,
        )

        # Allocate tensors
        interpreter.allocate_tensors()

        # Get input/output details
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()

        # Build metadata
        input_shapes = {}
        input_dtypes = {}
        for inp in input_details:
            name = inp["name"]
            input_shapes[name] = list(inp["shape"])
            input_dtypes[name] = str(inp["dtype"])

        output_shapes = {}
        output_dtypes = {}
        for out in output_details:
            name = out["name"]
            output_shapes[name] = list(out["shape"])
            output_dtypes[name] = str(out["dtype"])

        # Check if quantized
        quantized = any(
            inp["dtype"] in (np.int8, np.uint8) for inp in input_details
        )

        metadata = ModelMetadata(
            name=model_name,
            version=model_version,
            runtime=InferenceRuntime.TFLITE,
            input_shapes=input_shapes,
            output_shapes=output_shapes,
            input_dtypes=input_dtypes,
            output_dtypes=output_dtypes,
            size_bytes=size_bytes,
            quantized=quantized,
            description=f"TFLite model from {model_path}",
        )

        # Store model info
        self._models[model_name] = {
            "interpreter": interpreter,
            "input_details": input_details,
            "output_details": output_details,
            "metadata": metadata,
            "path": model_path,
        }

        logger.info(
            f"Model {model_name} loaded: {len(input_details)} inputs, "
            f"{len(output_details)} outputs, {size_bytes / 1024:.1f}KB"
        )

        return metadata

    async def unload_model(self, model_name: str) -> bool:
        """Unload a model from memory."""
        if model_name not in self._models:
            return False

        del self._models[model_name]
        logger.info(f"Model {model_name} unloaded")
        return True

    async def run_inference(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        **kwargs
    ) -> InferenceResult:
        """
        Run inference on a loaded model.

        Args:
            model_name: Name of loaded model
            inputs: Dict mapping input names to numpy arrays or array-like data
            **kwargs: Additional options

        Returns:
            InferenceResult with outputs and timing
        """
        if model_name not in self._models:
            return InferenceResult(
                outputs={},
                inference_time_ms=0,
                model_name=model_name,
                model_version="unknown",
                success=False,
                error_message=f"Model {model_name} not loaded",
            )

        model_info = self._models[model_name]
        interpreter = model_info["interpreter"]
        input_details = model_info["input_details"]
        output_details = model_info["output_details"]
        metadata = model_info["metadata"]

        try:
            # Set input tensors
            for inp in input_details:
                inp_name = inp["name"]
                inp_index = inp["index"]
                inp_shape = inp["shape"]
                inp_dtype = inp["dtype"]

                # Find matching input data
                input_data = None
                if inp_name in inputs:
                    input_data = inputs[inp_name]
                elif len(inputs) == 1 and len(input_details) == 1:
                    # Single input model - use whatever key was provided
                    input_data = next(iter(inputs.values()))
                else:
                    # Try "input" as default key
                    input_data = inputs.get("input")

                if input_data is None:
                    raise ValueError(f"No input data provided for: {inp_name}")

                # Convert to numpy array with correct dtype
                input_array = np.array(input_data, dtype=inp_dtype)

                # Reshape if needed
                if input_array.shape != tuple(inp_shape):
                    # Try to add batch dimension
                    if len(input_array.shape) == len(inp_shape) - 1:
                        input_array = np.expand_dims(input_array, axis=0)
                    input_array = input_array.reshape(inp_shape)

                interpreter.set_tensor(inp_index, input_array)

            # Run inference
            start_time = time.perf_counter()
            interpreter.invoke()
            inference_time_ms = (time.perf_counter() - start_time) * 1000

            # Get outputs
            outputs = {}
            for out in output_details:
                out_name = out["name"]
                out_index = out["index"]
                output_data = interpreter.get_tensor(out_index)
                outputs[out_name] = output_data.copy()

            return InferenceResult(
                outputs=outputs,
                inference_time_ms=inference_time_ms,
                model_name=model_name,
                model_version=metadata.version,
                success=True,
            )

        except Exception as e:
            logger.error(f"Inference failed for {model_name}: {e}")
            return InferenceResult(
                outputs={},
                inference_time_ms=0,
                model_name=model_name,
                model_version=metadata.version,
                success=False,
                error_message=str(e),
            )

    def is_model_loaded(self, model_name: str) -> bool:
        """Check if a model is loaded."""
        return model_name in self._models

    def get_model_metadata(self, model_name: str) -> Optional[ModelMetadata]:
        """Get metadata for a loaded model."""
        if model_name in self._models:
            return self._models[model_name]["metadata"]
        return None

    def list_loaded_models(self) -> List[str]:
        """List all loaded model names."""
        return list(self._models.keys())


def is_tflite_available() -> bool:
    """Check if TFLite runtime is available."""
    return _TFLITE_AVAILABLE
