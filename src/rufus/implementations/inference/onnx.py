"""
ONNX Runtime Inference Provider

Provides on-device ML inference using ONNX Runtime.
Supports models from PyTorch, TensorFlow, scikit-learn, and other frameworks.

Features:
- Cross-platform inference
- CPU and GPU execution providers
- Optimized for Intel, ARM, and NVIDIA hardware
- Support for quantized INT8 models
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional
import numpy as np

from rufus.providers.inference import (
    InferenceProvider,
    InferenceRuntime,
    InferenceResult,
    ModelMetadata,
)

logger = logging.getLogger(__name__)

# Try to import ONNX Runtime
_ONNX_AVAILABLE = False
_ort = None

try:
    import onnxruntime as ort
    _ort = ort
    _ONNX_AVAILABLE = True
    logger.info(f"ONNX Runtime available: {ort.__version__}")
except ImportError:
    logger.warning(
        "ONNX Runtime not available. Install with: pip install onnxruntime"
    )


class ONNXInferenceProvider(InferenceProvider):
    """
    ONNX Runtime inference provider for edge devices.

    ONNX Runtime provides optimized inference for models exported from
    PyTorch, TensorFlow, scikit-learn, and other ML frameworks.

    Features:
    - Automatic execution provider selection (CPU, CUDA, TensorRT, etc.)
    - Graph optimizations for faster inference
    - Support for quantized models
    - Memory-efficient execution

    Example:
        provider = ONNXInferenceProvider(providers=['CPUExecutionProvider'])
        await provider.initialize()
        await provider.load_model("models/detector.onnx", "detector")
        result = await provider.run_inference("detector", {"input": image_data})
    """

    def __init__(
        self,
        providers: Optional[List[str]] = None,
        graph_optimization_level: str = "all",
        intra_op_threads: int = 4,
        inter_op_threads: int = 1,
    ):
        """
        Initialize ONNX Runtime provider.

        Args:
            providers: List of execution providers in priority order.
                      Default: ['CPUExecutionProvider']
                      Options: 'CUDAExecutionProvider', 'TensorrtExecutionProvider',
                              'CoreMLExecutionProvider', 'CPUExecutionProvider'
            graph_optimization_level: Optimization level ('disabled', 'basic', 'extended', 'all')
            intra_op_threads: Threads for parallel execution within operators
            inter_op_threads: Threads for parallel execution across operators
        """
        if not _ONNX_AVAILABLE:
            raise RuntimeError(
                "ONNX Runtime not installed. Install with: pip install onnxruntime"
            )

        self.providers = providers or ['CPUExecutionProvider']
        self.graph_optimization_level = graph_optimization_level
        self.intra_op_threads = intra_op_threads
        self.inter_op_threads = inter_op_threads

        self._models: Dict[str, Dict[str, Any]] = {}
        self._session_options = None
        self._initialized = False

    @property
    def runtime(self) -> InferenceRuntime:
        return InferenceRuntime.ONNX

    def _create_session_options(self) -> 'ort.SessionOptions':
        """Create ONNX Runtime session options."""
        options = _ort.SessionOptions()

        # Set thread counts
        options.intra_op_num_threads = self.intra_op_threads
        options.inter_op_num_threads = self.inter_op_threads

        # Set optimization level
        opt_levels = {
            'disabled': _ort.GraphOptimizationLevel.ORT_DISABLE_ALL,
            'basic': _ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
            'extended': _ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
            'all': _ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
        }
        options.graph_optimization_level = opt_levels.get(
            self.graph_optimization_level,
            _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )

        return options

    async def initialize(self) -> None:
        """Initialize the ONNX Runtime."""
        if self._initialized:
            return

        logger.info(
            f"Initializing ONNX Runtime provider (providers={self.providers}, "
            f"threads={self.intra_op_threads})"
        )

        # Create session options
        self._session_options = self._create_session_options()

        # Log available providers
        available_providers = _ort.get_available_providers()
        logger.info(f"Available ONNX providers: {available_providers}")

        # Filter to only available providers
        self.providers = [p for p in self.providers if p in available_providers]
        if not self.providers:
            self.providers = ['CPUExecutionProvider']

        logger.info(f"Using ONNX providers: {self.providers}")
        self._initialized = True

    async def close(self) -> None:
        """Unload all models and clean up."""
        model_names = list(self._models.keys())
        for name in model_names:
            await self.unload_model(name)
        self._initialized = False
        logger.info("ONNX Runtime provider closed")

    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        **kwargs
    ) -> ModelMetadata:
        """
        Load an ONNX model from disk.

        Args:
            model_path: Path to .onnx file
            model_name: Unique name for this model
            model_version: Version string
            **kwargs: Additional session options

        Returns:
            ModelMetadata with model information
        """
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")

        if model_name in self._models:
            logger.warning(f"Model {model_name} already loaded, replacing")
            await self.unload_model(model_name)

        logger.info(f"Loading ONNX model: {model_name} from {model_path}")

        # Get file size
        size_bytes = os.path.getsize(model_path)

        # Create inference session
        session_options = kwargs.get("session_options") or self._session_options
        providers = kwargs.get("providers") or self.providers

        session = _ort.InferenceSession(
            model_path,
            sess_options=session_options,
            providers=providers,
        )

        # Get input/output details
        inputs = session.get_inputs()
        outputs = session.get_outputs()

        # Build metadata
        input_shapes = {}
        input_dtypes = {}
        for inp in inputs:
            # Handle dynamic dimensions
            shape = [d if isinstance(d, int) else -1 for d in inp.shape]
            input_shapes[inp.name] = shape
            input_dtypes[inp.name] = inp.type

        output_shapes = {}
        output_dtypes = {}
        for out in outputs:
            shape = [d if isinstance(d, int) else -1 for d in out.shape]
            output_shapes[out.name] = shape
            output_dtypes[out.name] = out.type

        # Check if quantized (look for INT8 types)
        quantized = any('int8' in str(inp.type).lower() for inp in inputs)

        metadata = ModelMetadata(
            name=model_name,
            version=model_version,
            runtime=InferenceRuntime.ONNX,
            input_shapes=input_shapes,
            output_shapes=output_shapes,
            input_dtypes=input_dtypes,
            output_dtypes=output_dtypes,
            size_bytes=size_bytes,
            quantized=quantized,
            description=f"ONNX model from {model_path}",
        )

        # Store model info
        self._models[model_name] = {
            "session": session,
            "inputs": inputs,
            "outputs": outputs,
            "metadata": metadata,
            "path": model_path,
        }

        logger.info(
            f"Model {model_name} loaded: {len(inputs)} inputs, "
            f"{len(outputs)} outputs, {size_bytes / 1024:.1f}KB"
        )

        return metadata

    async def unload_model(self, model_name: str) -> bool:
        """Unload a model from memory."""
        if model_name not in self._models:
            return False

        del self._models[model_name]
        logger.info(f"Model {model_name} unloaded")
        return True

    def _onnx_type_to_numpy(self, onnx_type: str) -> np.dtype:
        """Convert ONNX type string to numpy dtype."""
        type_map = {
            'tensor(float)': np.float32,
            'tensor(float16)': np.float16,
            'tensor(double)': np.float64,
            'tensor(int32)': np.int32,
            'tensor(int64)': np.int64,
            'tensor(int8)': np.int8,
            'tensor(uint8)': np.uint8,
            'tensor(bool)': np.bool_,
        }
        return type_map.get(onnx_type, np.float32)

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
            **kwargs: Additional options (e.g., output_names to select specific outputs)

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
        session = model_info["session"]
        model_inputs = model_info["inputs"]
        model_outputs = model_info["outputs"]
        metadata = model_info["metadata"]

        try:
            # Prepare input feed
            input_feed = {}
            for inp in model_inputs:
                inp_name = inp.name
                inp_type = inp.type

                # Find matching input data
                input_data = None
                if inp_name in inputs:
                    input_data = inputs[inp_name]
                elif len(inputs) == 1 and len(model_inputs) == 1:
                    # Single input model
                    input_data = next(iter(inputs.values()))
                else:
                    # Try common default keys
                    for key in ["input", "x", "data", "features"]:
                        if key in inputs:
                            input_data = inputs[key]
                            break

                if input_data is None:
                    raise ValueError(f"No input data provided for: {inp_name}")

                # Convert to numpy array with correct dtype
                np_dtype = self._onnx_type_to_numpy(inp_type)
                input_array = np.array(input_data, dtype=np_dtype)

                # Handle batch dimension
                expected_shape = inp.shape
                if expected_shape and len(input_array.shape) == len(expected_shape) - 1:
                    input_array = np.expand_dims(input_array, axis=0)

                input_feed[inp_name] = input_array

            # Select output names
            output_names = kwargs.get("output_names")
            if output_names is None:
                output_names = [out.name for out in model_outputs]

            # Run inference
            start_time = time.perf_counter()
            results = session.run(output_names, input_feed)
            inference_time_ms = (time.perf_counter() - start_time) * 1000

            # Package outputs
            outputs = {}
            for name, data in zip(output_names, results):
                outputs[name] = data.copy() if isinstance(data, np.ndarray) else data

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


def is_onnx_available() -> bool:
    """Check if ONNX Runtime is available."""
    return _ONNX_AVAILABLE


def get_available_providers() -> List[str]:
    """Get list of available ONNX execution providers."""
    if _ONNX_AVAILABLE:
        return _ort.get_available_providers()
    return []
